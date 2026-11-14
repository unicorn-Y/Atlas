"""A service composition root with reversible registration.

`AppServices` is a 52-field dataclass that every router reads as
`services.<field>`. It works, but nothing owns a registration: a field is either
assigned in `server.lifespan` or left `None`, and there is no way to say "this
service came from this plugin, and unloading the plugin removes it".

This module is that missing seam, deliberately small. It does not replace the
dataclass — a migration that big would break 73 call sites for no user-visible
gain. It adds the two properties the dataclass cannot express:

* **ownership** — every registration names an owner, so a teardown can remove
  exactly what one contributor added;
* **reversibility** — ``register`` returns a disposer, and disposing a service
  makes it unresolvable again rather than leaving a stale instance behind.

The contract is fail-closed: resolving an unregistered name raises, and a
factory that raises is not cached, so a half-built service can never be served.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

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
    disposer: Callable[[], None] | None = None


class ServiceRegistry:
    """Ordered, owner-tagged, reversible service registrations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, ServiceEntry] = {}

    def register(self, name: str, factory: Callable[[], Any], *,
                 owner: str = "core",
                 disposer: Callable[[], None] | None = None) -> Callable[[], None]:
        """Register a lazily-built service and return its disposer.

        The factory is not called here: a service that is registered but never
        used must not cost anything at startup, which is the whole reason the
        composition root exists.
        """
        key = str(name or "").strip()
        if not key:
            raise ValueError("A service needs a name")
        if not callable(factory):
            raise TypeError(f"Service {key!r} factory is not callable")
        with self._lock:
            if key in self._entries:
                existing = self._entries[key]
                raise ValueError(
                    f"Service {key!r} is already registered by {existing.owner!r}"
                )
            self._entries[key] = ServiceEntry(
                name=key, owner=str(owner or "core"), factory=factory,
                disposer=disposer,
            )

        def dispose() -> None:
            self.unregister(key)

        return dispose

    def unregister(self, name: str) -> bool:
        with self._lock:
            entry = self._entries.pop(str(name or "").strip(), None)
        if entry is None:
            return False
        if entry.disposer is not None:
            try:
                entry.disposer()
            except Exception:  # noqa: BLE001 - teardown must not mask the unregister
                pass
        return True

    def unregister_owner(self, owner: str) -> int:
        """Drop everything one contributor registered; returns how many."""
        with self._lock:
            names = [n for n, e in self._entries.items() if e.owner == owner]
        return sum(1 for name in names if self.unregister(name))

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
            if entry.built:
                return entry.instance
            # Build inside the lock so two concurrent first-callers cannot each
            # construct a half-initialized singleton.
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
