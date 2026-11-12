"""Durable pending-turn queue for background memory writes.

Retries use exponential backoff instead of a hard attempt cap: a memory turn is
never dropped because a provider was rate limited or unauthorised for a while.
A row becomes eligible again when ``next_attempt_at`` has passed; the delay
grows from :data:`BASE_DELAY_SECONDS` and is capped at :data:`MAX_DELAY_SECONDS`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

#: First retry waits this long.
BASE_DELAY_SECONDS = 30.0
#: Backoff ceiling (6 hours) so a long outage settles into a slow probe.
MAX_DELAY_SECONDS = 6 * 60 * 60.0


def backoff_delay_seconds(attempts: int) -> float:
    """Delay before the next try after ``attempts`` failures (30s, 1m, 2m, … 6h)."""
    try:
        retries = max(0, int(attempts))
    except (TypeError, ValueError):
        retries = 0
    return min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * float(2 ** min(retries, 16)))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class TurnQueue:
    def __init__(self, root: Path) -> None:
        self.path = Path(root) / ".queue.sqlite"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS pending(
            id INTEGER PRIMARY KEY, created TEXT, session TEXT, mode TEXT,
            user_text TEXT, assistant_text TEXT,
            workspace TEXT, steps TEXT NOT NULL DEFAULT '[]', verified INTEGER NOT NULL DEFAULT 0,
            turn_started TEXT,
            stage TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(pending)")}
        if "workspace" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN workspace TEXT")
        if "steps" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN steps TEXT NOT NULL DEFAULT '[]'")
        if "verified" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        if "turn_started" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN turn_started TEXT")
        # Backoff state; NULL means "due now", which is also how pre-existing
        # rows behave, so an old database needs no data migration.
        if "next_attempt_at" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN next_attempt_at TEXT")
        if "last_error_at" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN last_error_at TEXT")
        db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE INDEX IF NOT EXISTS pending_due ON pending(next_attempt_at)")
        db.commit()
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def insert(self, *, created: str, session: str, mode: str,
               user_text: str, assistant_text: str, workspace: str = "",
               steps: str = "[]", verified: bool = False, turn_started: str = "") -> int:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO pending(created,session,mode,user_text,assistant_text,"
                "workspace,steps,verified,turn_started,next_attempt_at,last_error_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (created, session, mode, user_text, assistant_text, workspace, steps, int(verified),
                 turn_started),
            )
            return int(cursor.lastrowid)

    def pending(self) -> list[dict[str, Any]]:
        """Rows that are due now, oldest first; attempts never exclude a row."""
        now = _now_iso()
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM pending "
                "WHERE next_attempt_at IS NULL OR next_attempt_at <= ? ORDER BY id",
                (now,),
            ).fetchall()
            return [dict(row) for row in rows]

    def due_count(self) -> int:
        now = _now_iso()
        with self._connection() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM pending "
                "WHERE next_attempt_at IS NULL OR next_attempt_at <= ?",
                (now,),
            ).fetchone()[0])

    def exhausted_count(self) -> int:
        """Rows waiting out a backoff delay (retrying, but not due yet)."""
        now = _now_iso()
        with self._connection() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM pending "
                "WHERE next_attempt_at IS NOT NULL AND next_attempt_at > ?",
                (now,),
            ).fetchone()[0])

    def stage_diary_done(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("UPDATE pending SET stage='diary_done' WHERE id=?", (row_id,))

    def remove(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM pending WHERE id=?", (row_id,))
            db.execute("INSERT INTO meta(key,value) VALUES('last_success_at',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_now_iso(),))

    def failed_count(self) -> int:
        """Rows that have failed at least once (kept for the existing dashboard field)."""
        with self._connection() as db:
            return int(db.execute(
                "SELECT COUNT(*) FROM pending WHERE attempts > 0",
            ).fetchone()[0])

    def fail(self, row_id: int, error: str) -> int:
        """Record a failure and schedule the next try; returns the new attempt count."""
        with self._connection() as db:
            row = db.execute("SELECT attempts FROM pending WHERE id=?", (row_id,)).fetchone()
            attempts = int(row["attempts"] or 0) if row is not None else 0
            delay = backoff_delay_seconds(attempts)
            next_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(
                timespec="seconds")
            db.execute(
                "UPDATE pending SET attempts=attempts+1,last_error=?,last_error_at=?,"
                "next_attempt_at=? WHERE id=?",
                (str(error)[:1000], _now_iso(), next_at, row_id),
            )
            return attempts + 1

    def reset_attempts(self) -> int:
        """Make every failed row due again, keeping its content and stage."""
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE pending SET attempts=0,last_error=NULL,last_error_at=NULL,"
                "next_attempt_at=NULL "
                "WHERE attempts > 0 OR last_error IS NOT NULL OR next_attempt_at IS NOT NULL"
            )
            return int(cursor.rowcount or 0)

    def count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM pending").fetchone()[0])

    def last_success_at(self) -> str | None:
        with self._connection() as db:
            row = db.execute("SELECT value FROM meta WHERE key='last_success_at'").fetchone()
            return str(row["value"]) if row is not None else None


__all__ = ["TurnQueue", "backoff_delay_seconds", "BASE_DELAY_SECONDS", "MAX_DELAY_SECONDS"]
