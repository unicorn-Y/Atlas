"""Registrable, invalidation-aware derived views over session state.

Every feature that wants "a cheaper shape of a session" today rebuilds it on each
request: a summary list, a per-channel view, a lineage tree. Each one re-reads the
same rows and re-derives the same dicts, and none of them can tell when the thing
it derived from has moved on.

This module is the single seam for that. A projection is a named, pure function
over session state plus a declared set of *dependencies* (the event names that
must invalidate it). The cache holds the derived value and drops it the moment one
of its dependencies fires, so a caller never has to remember to invalidate by hand.

Design notes:

* **Registered, not hard-coded.** ``register`` takes a name, a function, and the
  events it depends on. Adding the fifth projection does not touch this file.
* **Invalidation is event-driven.** ``invalidate_on(event_name)`` is what the
  event bus calls. A projection with no dependencies is never cached — deriving
  it once and freezing it would serve stale data forever.
* **Keyed caches.** A projection over *all* sessions and a projection over *one*
  session are both expressible: the key is part of the call, and the cache is
  keyed by it.
* **Bounded.** The cache refuses to grow past ``max_entries`` per projection and
  evicts the least-recently-used key instead of leaking. An unbounded derived-view
  cache is a memory leak with extra steps.
* **Failures are not cached.** An exception propagates and leaves no entry, so a
  transient DB error cannot pin an error value in place until some unrelated event
  happens to fire.

Typical wiring::

    projections = SessionProjections()
    projections.register("session.summary",
                         fn=lambda key, store: store.summary(key),
                         depends_on=("session.updated", "session.deleted"))
    ...
    value = projections.get("session.summary", key, store)   # cached
    projections.invalidate_on("session.updated")             # called by the bus
"""

from __future__ import annotations

import threading
import copy
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["SessionProjections", "ProjectionStats", "Projection"]


@dataclass
class Projection:
    """One registered derived view."""

    name: str
    fn: Callable[[Any, Any], Any] | Callable[..., Any]
    depends_on: tuple[str, ...] = ()
    view_schema: dict[str, Any] | None = None
    #: ``name -> derived value``, oldest use first so the front is the eviction
    #: candidate. ``OrderedDict`` because LRU needs cheap reordering.
    cache: OrderedDict[Any, Any] = field(default_factory=OrderedDict)
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def cacheable(self) -> bool:
        """A projection with no dependencies cannot know when it went stale."""
        return bool(self.depends_on)


@dataclass
class ProjectionStats:
    name: str
    entries: int
    capacity: int
    hits: int
    misses: int
    evictions: int
    depends_on: tuple[str, ...]
    cacheable: bool
    schema: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entries": self.entries,
            "capacity": self.capacity,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "depends_on": list(self.depends_on),
            "cacheable": self.cacheable,
            "schema": copy.deepcopy(self.schema),
        }


class SessionProjections:
    """Registry + LRU cache for derived session views."""

    def __init__(self, *, max_entries: int = 64) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = max_entries
        self._projections: dict[str, Projection] = {}
        # event name -> projection names that must be dropped when it fires.
        self._by_event: dict[str, set[str]] = {}
        # ``get``/``invalidate`` touch shared dicts; FastAPI handlers are threaded.
        self._lock = threading.RLock()
        self._state_version = 0
        self.register(
            "session.summary",
            _session_summary_projection,
            depends_on=("run.started", "run.completed", "run.failed", "run.cancelled"),
            schema=_SESSION_SUMMARY_SCHEMA,
        )

    # -- registration ----------------------------------------------------

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        depends_on: Iterable[str] = (),
        replace: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> Projection:
        """Register ``fn`` under ``name``.

        ``replace=False`` makes a duplicate registration an error: two features
        silently fighting over one name is exactly the kind of thing that shows up
        as "the summary is sometimes wrong" and never gets diagnosed.
        """
        if not name:
            raise ValueError("projection name must not be empty")
        if not callable(fn):
            raise TypeError("projection fn must be callable")
        deps = tuple(dict.fromkeys(str(d) for d in depends_on if str(d)))
        with self._lock:
            if name in self._projections and not replace:
                raise ValueError(f"projection already registered: {name}")
            self._unindex(self._projections.get(name))
            projection = Projection(
                name=name, fn=fn, depends_on=deps,
                view_schema=copy.deepcopy(schema) if schema is not None else None,
            )
            self._projections[name] = projection
            for event in deps:
                self._by_event.setdefault(event, set()).add(name)
            return projection

    def unregister(self, name: str) -> bool:
        """Drop a projection and its cache. Returns whether it existed."""
        with self._lock:
            projection = self._projections.pop(name, None)
            if projection is None:
                return False
            self._unindex(projection)
            return True

    def _unindex(self, projection: Projection | None) -> None:
        if projection is None:
            return
        for event in projection.depends_on:
            owners = self._by_event.get(event)
            if owners is not None:
                owners.discard(projection.name)
                if not owners:
                    self._by_event.pop(event, None)

    # -- reads -----------------------------------------------------------

    def get(self, name: str, key: Any, *args: Any, **kwargs: Any) -> Any:
        """Return the cached value for ``(name, key)`` or derive it.

        ``fn`` is called as ``fn(key, *args, **kwargs)``. Exceptions propagate and
        leave no cache entry, so an error can never be served as a value.
        """
        projection = self._require(name)
        if not projection.cacheable:
            projection.misses += 1
            return projection.fn(key, *args, **kwargs)

        with self._lock:
            if key in projection.cache:
                projection.cache.move_to_end(key)
                projection.hits += 1
                return projection.cache[key]

        # Derive outside the lock: a projection that reads the DB must not block
        # every other projection's cache hit behind it.
        projection.misses += 1
        value = projection.fn(key, *args, **kwargs)

        with self._lock:
            # Re-check: another thread may have filled this key while we derived.
            if key in projection.cache:
                projection.cache.move_to_end(key)
                return projection.cache[key]
            projection.cache[key] = value
            while len(projection.cache) > self._max_entries:
                projection.cache.popitem(last=False)
                projection.evictions += 1
        return value

    def invalidate(self, name: str, key: Any | None = None) -> int:
        """Drop one key (``key`` given) or every key of ``name``. Returns count."""
        projection = self._require(name)
        with self._lock:
            if key is None:
                removed = len(projection.cache)
                projection.cache.clear()
                self._state_version += 1
                return removed
            removed = 1 if projection.cache.pop(key, _MISSING) is not _MISSING else 0
            self._state_version += 1
            return removed

    def invalidate_on(self, event_name: str) -> int:
        """Drop every projection that declared ``event_name`` as a dependency.

        This is the method an event bus calls. Unknown events are a no-op rather
        than an error: the bus forwards everything and most events interest no
        projection.
        """
        with self._lock:
            names = tuple(self._by_event.get(str(event_name), ()))
            removed = 0
            for name in names:
                projection = self._projections.get(name)
                if projection is None:
                    continue
                removed += len(projection.cache)
                projection.cache.clear()
            if names:
                self._state_version += 1
            return removed

    def invalidate_all(self) -> int:
        with self._lock:
            removed = 0
            for projection in self._projections.values():
                removed += len(projection.cache)
                projection.cache.clear()
            if self._projections:
                self._state_version += 1
            return removed

    def get_snapshot(
        self, name: str, key: Any, *args: Any, as_of_seq: int | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Return a typed projection view with its invalidation generation and sequence watermark.

        A projection may return a private ``_asOfSeq`` value when it can derive
        the exact durable cursor itself. Otherwise the caller must supply the
        cursor explicitly. The private key is never exposed in the view payload.
        """
        projection = self._require(name)
        if projection.view_schema is None:
            raise ValueError(f"projection {name!r} has no view schema")
        if as_of_seq is not None and (type(as_of_seq) is not int or as_of_seq < 0):
            raise ValueError("as_of_seq must be a non-negative integer")
        value = self.get(name, key, *args, **kwargs)
        if isinstance(value, dict) and as_of_seq is None:
            as_of_seq = value.get("_asOfSeq")
        elif value is None and as_of_seq is None:
            as_of_seq = 0
        if type(as_of_seq) is not int or as_of_seq < 0:
            raise ValueError(f"projection {name!r} requires a non-negative as_of_seq")
        data = dict(value) if isinstance(value, dict) else value
        if isinstance(data, dict):
            data.pop("_asOfSeq", None)
        with self._lock:
            state_version = self._state_version
        return {
            "stateVersion": state_version,
            "asOfSeq": as_of_seq,
            "schema": copy.deepcopy(projection.view_schema),
            "data": data,
        }

    @staticmethod
    def invalidate_for(services: Any, event_name: str) -> int:
        """Invalidate on ``services.session_projections`` if it is bound.

        Call sites live in hot paths (the run-event funnel) and must not each
        repeat ``getattr(services, "session_projections", None)`` plus a None
        check. A container without the field, or with it left ``None``, is a
        no-op rather than an error: the cache is an optimisation, not a
        precondition for emitting an event.
        """
        registry = getattr(services, "session_projections", None)
        if registry is None:
            return 0
        return registry.invalidate_on(event_name)

    # -- introspection ---------------------------------------------------

    def _require(self, name: str) -> Projection:
        with self._lock:
            projection = self._projections.get(name)
        if projection is None:
            raise KeyError(f"unknown projection: {name}")
        return projection

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._projections)

    def stats(self) -> list[ProjectionStats]:
        with self._lock:
            return [
                ProjectionStats(
                    name=p.name,
                    entries=len(p.cache),
                    capacity=self._max_entries,
                    hits=p.hits,
                    misses=p.misses,
                    evictions=p.evictions,
                    depends_on=p.depends_on,
                    cacheable=p.cacheable,
                    schema=copy.deepcopy(p.view_schema),
                )
                for p in sorted(self._projections.values(), key=lambda p: p.name)
            ]

    def describe(self) -> dict[str, Any]:
        """JSON-friendly snapshot for the introspection surface."""
        stats = self.stats()
        return {
            "projections": len(stats),
            "stateVersion": self._state_version,
            "entries": sum(s.entries for s in stats),
            "max_entries_per_projection": self._max_entries,
            "hits": sum(s.hits for s in stats),
            "misses": sum(s.misses for s in stats),
            "evictions": sum(s.evictions for s in stats),
            "events": sorted(self._by_event),
            "detail": [s.as_dict() for s in stats],
        }


_MISSING = object()


_SESSION_SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["sessionId", "messageCount", "lastMessage"],
    "properties": {
        "sessionId": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "messageCount": {"type": "integer", "minimum": 0},
        "lastMessage": {"type": ["object", "null"]},
    },
}


def _session_summary_projection(session_id: str, store: Any) -> dict[str, Any] | None:
    """Purely derive a compact session preview from the SessionDB read surface."""
    session = store.get_session(session_id)
    if session is None:
        return None
    messages = store.get_messages(
        session_id, limit=1, latest=True, include_compacted=True,
    )
    latest = messages[-1] if messages else None
    last_message = None
    as_of_seq = 0
    if latest is not None:
        raw_seq = latest.get("id", latest.get("_row_id", 0))
        as_of_seq = int(raw_seq) if str(raw_seq).isdigit() else 0
        last_message = {
            "seq": as_of_seq,
            "role": latest.get("role"),
            "content": latest.get("content"),
        }
    return {
        "sessionId": str(session_id),
        "title": session.get("title"),
        "messageCount": max(0, int(session.get("message_count") or 0)),
        "lastMessage": last_message,
        "_asOfSeq": as_of_seq,
    }
