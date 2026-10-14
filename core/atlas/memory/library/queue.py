"""Durable pending-turn queue for background memory writes."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


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
            stage TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT)""")
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
               user_text: str, assistant_text: str) -> int:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO pending(created,session,mode,user_text,assistant_text) VALUES(?,?,?,?,?)",
                (created, session, mode, user_text, assistant_text),
            )
            return int(cursor.lastrowid)

    def pending(self) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM pending WHERE attempts < 3 ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def stage_diary_done(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("UPDATE pending SET stage='diary_done' WHERE id=?", (row_id,))

    def remove(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM pending WHERE id=?", (row_id,))

    def failed_count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM pending WHERE attempts >= 3").fetchone()[0])

    def fail(self, row_id: int, error: str) -> None:
        with self._connection() as db:
            db.execute("UPDATE pending SET attempts=attempts+1,last_error=? WHERE id=?",
                       (error[:1000], row_id))

    def count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM pending").fetchone()[0])

