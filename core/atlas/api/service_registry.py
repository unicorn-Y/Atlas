"""A service composition root with reversible registration.

`AppServices` is a 52-field dataclass that every router reads as
`services.<field>`. It works, but nothing owns a registration: a field is either
assigned in `server.lifespan` or left `None`, and there is no way to say "this
service came from this plugin, and unloading the plugin removes it".

This module is that missing seam, deliberately small. It does not replace the
dataclass — a migration that big would break 73 call sites for no user-visible
gain. It adds the three properties the dataclass cannot express:

* **ownership** — every registration names an owner, so a teardown can remove
  exactly what one contributor added;
* **reversibility** — ``register`` returns a disposer, and disposing a service
  makes it unresolvable again rather than leaving a stale instance behind;
* **ordering** — ``depends_on`` declares what must exist first, so builds happen
  in dependency order and teardown happens in reverse. A component never sees
  its dependency torn out from under it.

The contract is fail-closed: resolving an unregistered name raises, a factory
that raises is not cached, so a half-built service can never be served, and a
dependency cycle is refused instead of recursing forever.
"""

from __future__ import annotations

import inspect
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

__all__ = ["ServiceRegistry", "ServiceEntry", "ServiceNotRegistered"]


class ServiceNotRegistered(LookupError):
    """Resolving a name nobody registered.

    A subclass of ``LookupError`` so existing ``except LookupError`` handlers
    keep working, with a message that names the owner list — the difference
    between "typo" and "the plugin that provides this never loaded" is exactly
    what a caller needs at that moment.
    """


@dataclass
class ServiceEntry:
    name: str
    owner: str
    factory: Callable[[], Any]
    instance: Any = None
    built: bool = False
    disposer: Callable[[], Any] | None = None
    #: Names that must be built before this one. Declared, not inferred: a
    #: factory that happens to call ``resolve`` on something else would
    #: otherwise make teardown order depend on call order.
    depends_on: tuple[str, ...] = ()


class ServiceRegistry:
    """Ordered, owner-tagged, reversible service registrations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, ServiceEntry] = {}

    def register(self, name: str, factory: Callable[[], Any], *,
                 owner: str = "core",
                 disposer: Callable[[], Any] | None = None,
                 depends_on: Iterable[str] = ()) -> Callable[[], None]:
        """Register a lazily-built service and return its disposer.

        The factory is not called here: a service that is registered but never
        used must not cost anything at startup, which is the whole reason the
        composition root exists.

        ``depends_on`` names services that must be constructed first. Declaring
        them makes two things possible that the dataclass could not express:
        `resolve` can build a dependency tree in the right order, and teardown
        can proceed in reverse order so a component never sees its dependency
        disappear underneath it.
        """
        key = str(name or "").strip()
        if not key:
            raise ValueError("A service needs a name")
        if not callable(factory):
            raise TypeError(f"Service {key!r} factory is not callable")
        deps = tuple(str(d).strip() for d in depends_on if str(d or "").strip())
        if key in deps:
            raise ValueError(f"Service {key!r} cannot depend on itself")
        with self._lock:
            if key in self._entries:
                existing = self._entries[key]
                raise ValueError(
                    f"Service {key!r} is already registered by {existing.owner!r}"
                )
            missing = [dep for dep in deps if dep not in self._entries]
            if missing:
                # Fail at registration rather than at first resolve: a typo in a
                # dependency name is a wiring mistake, and it should surface where
                # the wiring happens.
                raise ServiceNotRegistered(
                    f"Service {key!r} depends on unregistered {missing}"
                )
            self._entries[key] = ServiceEntry(
                name=key, owner=str(owner or "core"), factory=factory,
                disposer=disposer, depends_on=deps,
            )

        def dispose() -> None:
            self.unregister(key)

        return dispose

    def _teardown_order(self, names: Iterable[str]) -> list[str]:
        """Order ``names`` so a service is disposed after everything that needs it.

        A dependency must outlive its dependents. Without this, unloading in
        insertion order could dispose a shared service while a component built
        on it is still registered — the component would then hold a dead object
        and only fail on next use, far from the unload that caused it.
        """
        wanted = list(dict.fromkeys(names))
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            entry = self._entries.get(name)
            if entry is None:
                # Shutdown callers may have actions for lifecycle resources
                # that are created after registry population (or are not
                # AppServices entries at all). The graph can constrain known
                # entries, but must never erase a real cleanup action.
                ordered.append(name)
                return
            # Dependents before dependencies: recurse into whoever needs me.
            for other in wanted:
                other_entry = self._entries.get(other)
                if other_entry is not None and name in other_entry.depends_on:
                    visit(other)
            ordered.append(name)

        for name in wanted:
            visit(name)
        return ordered

    def teardown_order(self, names: Iterable[str]) -> list[str]:
        """Return names in dependent-before-dependency shutdown order.

        Unrelated entries retain their caller order, so lifecycle cleanup can
        preserve its established sequencing while honoring declared edges.
        """
        with self._lock:
            return self._teardown_order(names)

    def unregister(self, name: str) -> bool:
        key = str(name or "").strip()
        with self._lock:
            if key not in self._entries:
                return False
            # Anything that depends on this must go first.
            affected = {key}
            changed = True
            while changed:
                changed = False
                for name, entry in self._entries.items():
                    if name not in affected and any(dep in affected for dep in entry.depends_on):
                        affected.add(name)
                        changed = True
            dependents = [n for n in affected if n != key]
            async_disposers = [
                n for n in affected
                if (entry := self._entries.get(n)) is not None
                and entry.disposer is not None
                and inspect.iscoroutinefunction(entry.disposer)
            ]
            if async_disposers:
                raise RuntimeError(
                    f"Async service disposers require unregister_owner_async: {async_disposers}"
                )
        for dependent in dependents:
            self.unregister(dependent)
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return False
        if entry.disposer is not None:
            try:
                entry.disposer()
            except Exception:  # noqa: BLE001 - teardown must not mask the unregister
                pass
        return True

    def unregister_owner(self, owner: str) -> int:
        """Drop everything one contributor registered; returns how many.

        Ordered so dependents are disposed before the services they use, which
        matters when an owner registers both.
        """
        with self._lock:
            names = [n for n, e in self._entries.items() if e.owner == owner]
        return sum(1 for name in self._teardown_order(names) if self.unregister(name))

    async def unregister_owner_async(self, owner: str) -> list[str]:
        """Dispose an owner and every dependent in reverse dependency order.

        Disposers may be sync or async. All entries are removed and every
        disposer is attempted even if one raises; failures are re-raised as a
        group after cleanup finishes.
        """
        with self._lock:
            roots = {name for name, entry in self._entries.items() if entry.owner == owner}
            closure = set(roots)
            changed = True
            while changed:
                changed = False
                for name, entry in self._entries.items():
                    if name not in closure and any(dep in closure for dep in entry.depends_on):
                        closure.add(name)
                        changed = True
            order = self._teardown_order(name for name in self._entries if name in closure)

        removed: list[str] = []
        errors: list[Exception] = []
        for name in order:
            with self._lock:
                entry = self._entries.pop(name, None)
            if entry is None:
                continue
            removed.append(name)
            if entry.disposer is None:
                continue
            try:
                result = entry.disposer()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # finish releasing siblings before surfacing failures
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                f"Service teardown for owner {owner!r} had {len(errors)} failure(s)", errors,
            )
        return removed

    def owner_for(self, name: str) -> str | None:
        """Return the provider owner without exposing its instance."""
        with self._lock:
            entry = self._entries.get(str(name or "").strip())
            return entry.owner if entry is not None else None

    def has_disposer(self, name: str) -> bool:
        """Whether a registration owns a concrete teardown callback."""
        with self._lock:
            entry = self._entries.get(str(name or "").strip())
            return bool(entry is not None and entry.disposer is not None)

    def resolve(self, name: str) -> Any:
        key = str(name or "").strip()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                owners = sorted({e.owner for e in self._entries.values()})
                raise ServiceNotRegistered(
                    f"Service {key!r} is not registered. "
                    f"Registered owners: {owners or 'none'}"
                )
            return self._build(entry, seen=())

    def _build(self, entry: ServiceEntry, *, seen: tuple[str, ...]) -> Any:
        """Construct ``entry`` after its declared dependencies, once each.

        Called with the registry lock held. ``seen`` is the path taken to get
        here; a name appearing twice on it would be a dependency cycle, which
        ``register`` cannot reject on its own because the second edge may be
        declared before the first node exists.
        """
        if entry.built:
            return entry.instance
        if entry.name in seen:
            cycle = " -> ".join((*seen, entry.name))
            raise ValueError(f"Service dependency cycle: {cycle}")
        for dependency in entry.depends_on:
            target = self._entries.get(dependency)
            if target is None:
                raise ServiceNotRegistered(
                    f"Service {entry.name!r} depends on {dependency!r}, which went away"
                )
            self._build(target, seen=(*seen, entry.name))
        instance = entry.factory()
        entry.instance = instance
        entry.built = True
        return instance

    def has(self, name: str) -> bool:
        with self._lock:
            return str(name or "").strip() in self._entries

    def snapshot(self) -> dict[str, str]:
        """``name -> owner`` for introspection. Never returns instances."""
        with self._lock:
            return {name: entry.owner for name, entry in self._entries.items()}

    def owners(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock:
            for entry in self._entries.values():
                counts[entry.owner] = counts.get(entry.owner, 0) + 1
        return counts

    def dependencies(self) -> dict[str, list[str]]:
        """``name -> declared dependencies`` for introspection."""
        with self._lock:
            return {
                name: list(entry.depends_on)
                for name, entry in self._entries.items()
                if entry.depends_on
            }

    def bind_into(self, target: Any) -> list[str]:
        """Fill same-named attributes on ``target``; returns the names bound.

        Used to project the registry onto `AppServices` without changing how any
        existing router reads a field. A name the target has no slot for is
        skipped rather than creating a new attribute, so a typo cannot silently
        add surface area.
        """
        bound: list[str] = []
        with self._lock:
            names = list(self._entries)
        for name in names:
            if not hasattr(target, name):
                continue
            setattr(target, name, self.resolve(name))
            bound.append(name)
        return bound
