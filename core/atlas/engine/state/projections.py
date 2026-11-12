"""Cached projections of expensive session reads, invalidated by write generation.

``list_sessions_rich(order_by_last_active=True)`` is the Web UI's session list. It
costs 544 ms on a real library (1497 sessions / 515k messages) because the
compression-chain CTE seeds from every admitted session and walks children
forward before the page can be cut. The same page is requested again on every
rail refresh, every window focus, and every "load more" — the *answer* changes only
when a message is appended.

So the fix is a cache, not a faster query, and the whole difficulty is deciding
when it is stale. Timers are wrong (a TTL either serves a stale list after a turn
finishes or throws the cache away between turns). Hashing the tables is wrong (it
costs as much as the query). The database already knows: ``PRAGMA data_version``
changes when *another* connection commits and stays put for your own writes, so it
is exactly the "did the committed state move" counter, for free.

That asymmetry is the design constraint. A write on *this* connection does not
bump ``data_version``, so every write path calls :meth:`ProjectionCache.touch`
to bump a local counter as well. Both counters go into the key. A cache entry
therefore survives until either someone else commits or we ourselves write.

Nothing here caches prompts, transcripts or tool output — only the row dicts a
listing already had to build, and only while their key holds.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Callable, Hashable

log = logging.getLogger(__name__)

#: How many projected pages to keep. A page is ~20 rows of session metadata; the
#: bound exists so a caller that pages through thousands of sessions cannot turn
#: the cache into a second copy of the database.
DEFAULT_CAPACITY = 96

#: Caches are shared per DATABASE PATH, not per instance. `SessionDB` is opened
#: and closed per request in several call sites (the sidebar preview path opens
#: one per refresh), and a per-instance cache would be cold on every call — it
#: would look implemented and do nothing. Same reasoning as the read budget in
#: atlas_state_readpool: the resource being shared belongs to the file.
_SHARED: dict[str, ProjectionCache] = {}
_SHARED_LOCK = threading.Lock()


def shared_for(db_path: Any, capacity: int = DEFAULT_CAPACITY) -> ProjectionCache:
    """The one cache for ``db_path``, creating it on first use."""
    key = str(db_path)
    with _SHARED_LOCK:
        cache = _SHARED.get(key)
        if cache is None:
            cache = ProjectionCache(capacity=capacity)
            _SHARED[key] = cache
        return cache


def forget_shared(db_path: Any) -> None:
    """Drop the shared cache for one path (test isolation, and after a DB replace)."""
    with _SHARED_LOCK:
        _SHARED.pop(str(db_path), None)


def _freeze(value: Any) -> Hashable:
    """Make an argument tuple hashable without silently dropping its identity.

    Lists become tuples and dicts become sorted item tuples, so ``[1,2]`` and
    ``(1,2)`` share an entry (they mean the same thing to SQL) but two different
    dicts never collide.
    """
    if isinstance(value, dict):
        return ("dict", tuple(sorted((key, _freeze(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return ("seq", tuple(_freeze(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted(_freeze(item) for item in value)))
    try:
        hash(value)
    except TypeError:
        return ("repr", repr(value))
    return value


class ProjectionCache:
    """Bounded LRU of derived read results, keyed by (name, args, write generation).

    Thread-safe: the session database is read from the event loop and from worker
    threads (export, portability, tests), and a cache that loses an entry under
    contention is fine but one that corrupts the LRU is not.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._capacity = max(1, int(capacity))
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._local_generation = 0
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    # -- generation -------------------------------------------------------
    def touch(self) -> int:
        """Record a write on this connection and drop every cached projection.

        Called from the state layer's write paths. It must be cheap and must never
        raise: it runs inside transactions whose failure modes are already handled.
        """
        with self._lock:
            self._local_generation += 1
            dropped = len(self._entries)
            self._entries.clear()
            self.invalidations += 1
        return dropped

    def generation(self, connection: Any) -> tuple[int, int]:
        """The key component that makes an entry stale: (local writes, foreign commits).

        ``data_version`` is read straight off the connection. A connection that
        cannot answer (closed, or a stub in a test) degrades to the local counter
        alone rather than raising — a cache must never be the reason a read fails.
        """
        foreign = 0
        if connection is not None:
            try:
                row = connection.execute("PRAGMA data_version").fetchone()
                foreign = int(row[0]) if row else 0
            except Exception:  # noqa: BLE001 - see docstring
                foreign = 0
        return (self._local_generation, foreign)

    # -- reads ------------------------------------------------------------
    def get_or_compute(
        self,
        name: str,
        args: tuple[Any, ...],
        connection: Any,
        compute: Callable[[], Any],
        *,
        generation: tuple[int, int] | None = None,
    ) -> Any:
        """Return the cached projection, or compute, store and return it.

        ``generation`` may be supplied when the caller already had to read it (for
        example on a pooled connection it must return before the query runs); when
        omitted it is derived from ``connection``.

        A raised exception is never cached: a transient SQLite busy error must not
        be remembered as the answer.
        """
        stamp = generation if generation is not None else self.generation(connection)
        key = (name, _freeze(args), stamp)
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return self._entries[key]
        value = compute()
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
            self.misses += 1
        return value

    def clear(self) -> int:
        with self._lock:
            dropped = len(self._entries)
            self._entries.clear()
        return dropped

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "capacity": self._capacity,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else None,
                "invalidations": self.invalidations,
                "local_generation": self._local_generation,
            }
