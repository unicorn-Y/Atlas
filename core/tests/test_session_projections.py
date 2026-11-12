"""Projection cache: cached derived reads invalidated by the write generation.

The point of this cache is the invalidation rule, so these tests are mostly about
when an entry must *stop* being served. A cache that is merely fast is worthless
here: the session list is what the user sees after a turn, and serving the
pre-turn page would look like the turn did nothing.

``PRAGMA data_version`` moves for *another* connection's commit but not for your
own, so the local counter exists. Both halves are asserted separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.engine.state.projections import (
    ProjectionCache,
    forget_shared,
    shared_for,
)


@pytest.fixture
def cache() -> ProjectionCache:
    return ProjectionCache(capacity=4)


def test_a_miss_then_a_hit(cache: ProjectionCache) -> None:
    calls = []

    def compute() -> str:
        calls.append(1)
        return "page"

    assert cache.get_or_compute("list", (1,), None, compute) == "page"
    assert cache.get_or_compute("list", (1,), None, compute) == "page"
    assert len(calls) == 1
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1


def test_different_arguments_are_different_entries(cache: ProjectionCache) -> None:
    assert cache.get_or_compute("list", (1,), None, lambda: "a") == "a"
    assert cache.get_or_compute("list", (2,), None, lambda: "b") == "b"
    assert cache.stats()["entries"] == 2


def test_different_names_are_different_entries(cache: ProjectionCache) -> None:
    assert cache.get_or_compute("list", (1,), None, lambda: "a") == "a"
    assert cache.get_or_compute("other", (1,), None, lambda: "b") == "b"
    assert cache.stats()["entries"] == 2


def test_a_list_and_a_tuple_argument_share_an_entry(cache: ProjectionCache) -> None:
    """``[1, 2]`` and ``(1, 2)`` mean the same thing to SQL, so they must not split."""
    assert cache.get_or_compute("list", ([1, 2],), None, lambda: "a") == "a"
    assert cache.get_or_compute("list", ((1, 2),), None, lambda: "b") == "a"


def test_a_local_write_invalidates_everything(cache: ProjectionCache) -> None:
    cache.get_or_compute("list", (1,), None, lambda: "stale")
    cache.touch()
    assert cache.get_or_compute("list", (1,), None, lambda: "fresh") == "fresh"


def test_touch_reports_how_many_entries_it_dropped(cache: ProjectionCache) -> None:
    cache.get_or_compute("a", (), None, lambda: 1)
    cache.get_or_compute("b", (), None, lambda: 2)
    assert cache.touch() == 2
    assert cache.touch() == 0


def test_a_foreign_commit_invalidates(cache: ProjectionCache) -> None:
    class Connection:
        def __init__(self) -> None:
            self.version = 1

        def execute(self, sql: str):
            assert "data_version" in sql

            class Cursor:
                def __init__(self, value: int) -> None:
                    self.value = value

                def fetchone(self):
                    return (self.value,)

            return Cursor(self.version)

    conn = Connection()
    assert cache.get_or_compute("list", (1,), conn, lambda: "old") == "old"
    conn.version = 2  # another connection committed
    assert cache.get_or_compute("list", (1,), conn, lambda: "new") == "new"


def test_an_own_commit_does_not_invalidate_without_touch(cache: ProjectionCache) -> None:
    """Documents the asymmetry that makes ``touch`` necessary.

    ``data_version`` deliberately does not move for writes on the same connection,
    so a cache keyed on it alone would serve a page generated before this
    connection's own write. That is why every committed write calls ``touch``.
    """

    class Connection:
        def execute(self, sql: str):
            class Cursor:
                def fetchone(self):
                    return (7,)

            return Cursor()

    conn = Connection()
    assert cache.get_or_compute("list", (1,), conn, lambda: "before") == "before"
    # Same version -> still cached. The write path must call touch() for this.
    assert cache.get_or_compute("list", (1,), conn, lambda: "after") == "before"
    cache.touch()
    assert cache.get_or_compute("list", (1,), conn, lambda: "after") == "after"


def test_a_raising_compute_is_never_cached(cache: ProjectionCache) -> None:
    """A transient SQLite busy error must not become the remembered answer."""
    calls = []

    def boom() -> str:
        calls.append(1)
        raise RuntimeError("SQLITE_BUSY")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            cache.get_or_compute("list", (), None, boom)
    assert len(calls) == 2
    assert cache.stats()["entries"] == 0
    assert cache.get_or_compute("list", (), None, lambda: "ok") == "ok"


def test_the_lru_is_bounded_and_evicts_the_oldest(cache: ProjectionCache) -> None:
    for index in range(4):
        cache.get_or_compute("k", (index,), None, lambda: index)
    assert cache.stats()["entries"] == 4
    cache.get_or_compute("k", (99,), None, lambda: 99)
    assert cache.stats()["entries"] == 4
    # The oldest key was evicted: recomputing it is a miss, not a hit.
    before = cache.stats()["misses"]
    cache.get_or_compute("k", (0,), None, lambda: "recomputed")
    assert cache.stats()["misses"] == before + 1


def test_a_connection_that_cannot_answer_degrades_instead_of_raising(
    cache: ProjectionCache,
) -> None:
    class Broken:
        def execute(self, sql: str):
            raise RuntimeError("database is closed")

    assert cache.get_or_compute("list", (), Broken(), lambda: "works") == "works"


def test_two_instances_on_one_path_share_a_cache(tmp_path: Path) -> None:
    """The sidebar opens and closes a SessionDB per refresh; a per-instance cache
    would always be cold and would look implemented while doing nothing."""
    forget_shared(tmp_path / "state.db")
    first = shared_for(tmp_path / "state.db")
    second = shared_for(tmp_path / "state.db")
    assert first is second
    first.get_or_compute("list", (), None, lambda: "warm")
    assert second.get_or_compute("list", (), None, lambda: "cold") == "warm"
    forget_shared(tmp_path / "state.db")


def test_forget_shared_starts_a_new_cache(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    before = shared_for(path)
    forget_shared(path)
    assert shared_for(path) is not before
    forget_shared(path)


def test_stats_expose_a_hit_rate_once_there_are_reads(cache: ProjectionCache) -> None:
    assert cache.stats()["hit_rate"] is None
    cache.get_or_compute("a", (), None, lambda: 1)
    cache.get_or_compute("a", (), None, lambda: 1)
    assert cache.stats()["hit_rate"] == 0.5


# --------------------------------------------------------------------------
# SessionDB wiring: the cache must be attached to real reads, and a real
# committed write must be visible through it. Testing the cache class alone
# would pass while the sidebar kept paying 180 ms per refresh.
# --------------------------------------------------------------------------


def test_session_db_serves_the_second_read_from_cache(tmp_path: Path) -> None:
    from atlas.engine.state.atlas_state import SessionDB
    from atlas.engine.state.projections import forget_shared

    db = SessionDB(tmp_path / "state.db")
    try:
        db.ensure_session("s1", "probe")
        calls = []

        def read() -> int:
            calls.append(1)
            return len(db.list_sessions_rich(limit=10))

        assert db.cached_read("previews", (), read) == 1
        assert db.cached_read("previews", (), read) == 1
        assert len(calls) == 1
    finally:
        db.close()
        forget_shared(tmp_path / "state.db")


def test_a_real_committed_write_is_visible_through_the_cache(tmp_path: Path) -> None:
    """The one staleness that must never happen: a new session missing from the
    list because the page it belongs to was cached before it existed."""
    from atlas.engine.state.atlas_state import SessionDB
    from atlas.engine.state.projections import forget_shared

    db = SessionDB(tmp_path / "state.db")
    try:
        db.ensure_session("s1", "probe")
        assert db.cached_read(
            "previews", (), lambda: len(db.list_sessions_rich(limit=10))
        ) == 1
        db.ensure_session("s2", "probe")
        assert db.cached_read(
            "previews", (), lambda: len(db.list_sessions_rich(limit=10))
        ) == 2
    finally:
        db.close()
        forget_shared(tmp_path / "state.db")


def test_two_session_db_instances_on_one_path_share_and_invalidate(tmp_path: Path) -> None:
    """The HTTP layer opens a SessionDB per request; both must see each other's
    writes, which ``PRAGMA data_version`` provides for foreign commits."""
    from atlas.engine.state.atlas_state import SessionDB
    from atlas.engine.state.projections import forget_shared

    first = SessionDB(tmp_path / "state.db")
    second = SessionDB(tmp_path / "state.db")
    try:
        first.ensure_session("s1", "probe")
        assert second.cached_read(
            "previews", (), lambda: len(second.list_sessions_rich(limit=10))
        ) == 1
        first.ensure_session("s2", "probe")
        assert second.cached_read(
            "previews", (), lambda: len(second.list_sessions_rich(limit=10))
        ) == 2
    finally:
        first.close()
        second.close()
        forget_shared(tmp_path / "state.db")

