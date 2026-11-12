"""Read-only health snapshot, backoff queue and honest dream failures."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from atlas.api import diagnostics_router
from atlas.memory.library import dream as dream_mod
from atlas.memory.library.health import DREAM_LAG_LIMIT_SECONDS, memory_health
from atlas.memory.library.queue import (
    BASE_DELAY_SECONDS,
    MAX_DELAY_SECONDS,
    TurnQueue,
    backoff_delay_seconds,
)

#: Schema of the shipped database before backoff existed: no next_attempt_at.
LEGACY_SCHEMA = """CREATE TABLE pending(
    id INTEGER PRIMARY KEY, created TEXT, session TEXT, mode TEXT,
    user_text TEXT, assistant_text TEXT,
    workspace TEXT, steps TEXT NOT NULL DEFAULT '[]', verified INTEGER NOT NULL DEFAULT 0,
    turn_started TEXT,
    stage TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT)"""


@pytest.fixture
def memory_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    root.mkdir()
    monkeypatch.setenv("ATLAS_TEST_MEMORY_ROOT", str(root))
    return root


def _legacy_queue(root: Path, *, attempts: int = 3, created: str = "2026-10-17T13:25:27+08:00",
                  error: str = "401 Authorization Required") -> Path:
    path = root / ".queue.sqlite"
    db = sqlite3.connect(path)
    try:
        db.execute(LEGACY_SCHEMA)
        db.execute(
            "INSERT INTO pending(created,session,mode,user_text,assistant_text,"
            "stage,attempts,last_error) VALUES(?,?,?,?,?,?,?,?)",
            (created, "s-1", "expert", "记住我喜欢深色主题", "好的", "diary_done", attempts, error),
        )
        db.commit()
    finally:
        db.close()
    return path


def test_health_on_an_empty_root_is_ok_and_does_not_create_files(memory_root: Path) -> None:
    before = sorted(p.name for p in memory_root.iterdir())

    result = memory_health()

    assert result["ok"] is True
    assert result["enabled"] is True
    assert result["queue_exists"] is False
    assert result["queue_pending"] == 0
    assert result["queue_exhausted"] == 0
    assert result["oldest_pending_age_seconds"] is None
    assert result["dream_checkpoint"] is None
    assert result["dream_lag_seconds"] is None
    assert result["problems"] == []
    assert json.dumps(result, ensure_ascii=False)  # JSON-serialisable for the API
    # A probe must never migrate, create or otherwise write into the library.
    assert sorted(p.name for p in memory_root.iterdir()) == before


def test_health_reports_a_stuck_legacy_row_and_leaves_the_schema_alone(memory_root: Path) -> None:
    path = _legacy_queue(memory_root)

    result = memory_health()

    assert result["ok"] is False
    assert result["queue_exists"] is True
    assert result["queue_total"] == 1
    assert result["queue_pending"] == 1
    assert result["queue_exhausted"] == 1
    assert result["oldest_pending_at"] == "2026-10-17T13:25:27+08:00"
    assert result["oldest_pending_age_seconds"] > 3600
    assert "401" in str(result["last_error"])
    assert result["last_error_at"] == "2026-10-17T13:25:27+08:00"
    assert [item["probe"] for item in result["problems"]] == ["queue", "queue"]

    db = sqlite3.connect(path)
    try:
        columns = {row[1] for row in db.execute("PRAGMA table_info(pending)")}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()
    assert "next_attempt_at" not in columns, "health opened the queue read-write"
    assert "meta" not in tables


def test_health_reports_dream_lag_from_the_checkpoint(memory_root: Path) -> None:
    stale = (datetime.now(UTC) - timedelta(days=5)).isoformat(timespec="seconds")
    (memory_root / ".dream-state.json").write_text(
        json.dumps({"checkpoint": stale}), encoding="utf-8")

    result = memory_health()

    assert result["dream_checkpoint"] == stale
    assert result["dream_lag_seconds"] > DREAM_LAG_LIMIT_SECONDS
    assert result["ok"] is False
    assert [item["probe"] for item in result["problems"]] == ["dream"]


def test_health_survives_a_corrupt_queue_file(memory_root: Path) -> None:
    (memory_root / ".queue.sqlite").write_bytes(b"this is not a database")

    result = memory_health()

    assert result["ok"] is False
    assert result["queue_exists"] is True
    assert result["problems"] and result["problems"][0]["probe"] == "queue"
    assert result["problems"][0]["error"]


def test_backoff_grows_exponentially_and_is_capped() -> None:
    assert backoff_delay_seconds(0) == BASE_DELAY_SECONDS
    assert backoff_delay_seconds(1) == BASE_DELAY_SECONDS * 2
    assert backoff_delay_seconds(2) == BASE_DELAY_SECONDS * 4
    assert backoff_delay_seconds(3) == BASE_DELAY_SECONDS * 8
    assert backoff_delay_seconds(50) == MAX_DELAY_SECONDS == 6 * 60 * 60
    delays = [backoff_delay_seconds(n) for n in range(12)]
    assert delays == sorted(delays)


def test_failed_rows_are_retried_later_instead_of_being_dropped(tmp_path: Path) -> None:
    queue = TurnQueue(tmp_path)
    row_id = queue.insert(created="2026-10-17T13:25:27+08:00", session="s-1", mode="expert",
                          user_text="记住我喜欢深色主题", assistant_text="好的")

    for _ in range(5):  # older code stopped selecting rows after three tries
        queue.fail(row_id, "401 Authorization Required")

    rows = queue.pending()
    assert rows == [], "a backing-off row must not be retried immediately"
    assert queue.count() == 1, "a failing row must never be deleted"
    assert queue.due_count() == 0
    assert queue.exhausted_count() == 1
    assert queue.failed_count() == 1

    db = sqlite3.connect(queue.path)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT * FROM pending WHERE id=?", (row_id,)).fetchone()
    finally:
        db.close()
    assert row["attempts"] == 5
    assert row["last_error_at"] and row["next_attempt_at"]
    assert datetime.fromisoformat(row["next_attempt_at"]) > datetime.now(UTC)
    assert row["user_text"] == "记住我喜欢深色主题"


def test_reset_endpoint_makes_rows_due_again_and_keeps_their_content(memory_root: Path) -> None:
    queue = TurnQueue(memory_root)
    row_id = queue.insert(created="2026-10-17T13:25:27+08:00", session="s-1", mode="expert",
                          user_text="记住我喜欢深色主题", assistant_text="好的")
    queue.stage_diary_done(row_id)
    for _ in range(3):
        queue.fail(row_id, "401 Authorization Required")

    assert memory_health()["queue_exhausted"] == 1

    reset = asyncio.run(diagnostics_router.retry_memory_diagnostics())

    assert reset == {"reset": 1}
    health = asyncio.run(diagnostics_router.get_memory_diagnostics())
    assert health["queue_pending"] == 1
    assert health["queue_exhausted"] == 0
    assert health["last_error"] is None
    rows = queue.pending()
    assert [row["id"] for row in rows] == [row_id]
    assert rows[0]["attempts"] == 0
    assert rows[0]["stage"] == "diary_done"
    assert rows[0]["user_text"] == "记住我喜欢深色主题"
    assert rows[0]["assistant_text"] == "好的"


def test_retry_endpoint_without_a_queue_writes_nothing(memory_root: Path) -> None:
    assert asyncio.run(diagnostics_router.retry_memory_diagnostics()) == {"reset": 0}
    assert not (memory_root / ".queue.sqlite").exists()


class _Entry:
    def __init__(self, at: str, text: str) -> None:
        self.id = f"e-{at}"
        self.at = at
        self.text = text
        self.trigger: list[str] = ["atlas"]
        self.files: list[str] = []
        self.outcome = ""
        self.decisions: list[str] = []
        self.commands: list[str] = []
        self.facts: list[str] = []
        self.open_items: list[str] = []
        self.steps: list[str] = []
        self.verified = False


class _Page:
    def __init__(self, entries: list[_Entry]) -> None:
        self.current = entries


class _Store:
    def __init__(self, root: Path, pages: dict[str, _Page]) -> None:
        self.root = root
        self._pages = pages

    def pages(self) -> list[str]:
        return list(self._pages)

    def read(self, rel: str) -> _Page:
        return self._pages[rel]


class _Library:
    """Minimal stand-in: enough for dream grouping to run, no model at all."""

    def __init__(self, root: Path) -> None:
        entries = [_Entry(f"2026-01-0{day}", "atlas 项目进展") for day in (1, 2, 3)]
        self.store = _Store(root, {"经历/项目.md": _Page(entries)})
        self.config: dict[str, Any] = {}

    def ready(self) -> None:
        return None

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def _model_id(self, model_mgr: Any) -> str:
        return "unused"


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def exception(self, event: str, **kwargs: Any) -> None:
        self.calls.append((event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append((event, kwargs))


def test_dream_failure_is_logged_with_a_traceback_and_never_moves_the_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    checkpoint = {"checkpoint": "2025-12-31T00:00:00+00:00"}
    state = root / ".dream-state.json"
    state.write_text(json.dumps(checkpoint), encoding="utf-8")
    recorder = _Recorder()
    monkeypatch.setattr(dream_mod, "log", recorder)

    result = asyncio.run(dream_mod.run_dream(_Library(root), None))

    assert result["ok"] is False
    assert result["error"] and result["error_type"] == "RuntimeError"
    assert result["projects"] == [] and result["added"] == 0
    assert [call[0] for call in recorder.calls] == ["memory.library.dream_failed"]
    event, kwargs = recorder.calls[0]
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["error"]
    assert json.loads(state.read_text(encoding="utf-8")) == checkpoint, (
        "checkpoint advanced on failure")
    assert not (root / "事").exists()
