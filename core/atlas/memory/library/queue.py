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
            workspace TEXT, steps TEXT NOT NULL DEFAULT '[]', verified INTEGER NOT NULL DEFAULT 0,
            turn_started TEXT,
            source_ref TEXT NOT NULL DEFAULT '', source_precision TEXT NOT NULL DEFAULT 'approximate',
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
        if "source_ref" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN source_ref TEXT NOT NULL DEFAULT ''")
        if "source_precision" not in columns:
            db.execute("ALTER TABLE pending ADD COLUMN source_precision TEXT NOT NULL DEFAULT 'approximate'")
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
               steps: str = "[]", verified: bool = False, turn_started: str = "",
               source_ref: str = "", source_precision: str = "missing") -> int:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO pending(created,session,mode,user_text,assistant_text,workspace,steps,verified,"
                "turn_started,source_ref,source_precision) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (created, session, mode, user_text, assistant_text, workspace, steps, int(verified),
                 turn_started, source_ref, source_precision),
            )
            return int(cursor.lastrowid)

    def pending(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM pending WHERE attempts < 3 ORDER BY id LIMIT ?",
                              (max(1, min(500, limit)),)).fetchall()
            return [dict(row) for row in rows]

    def failed(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id, created, session, stage, attempts, last_error FROM pending "
                "WHERE attempts >= 3 ORDER BY id LIMIT ?", (max(1, min(500, limit)),)
            ).fetchall()
            return [dict(row) for row in rows]

    def retry_failed(self, row_id: int | None = None) -> int:
        with self._connection() as db:
            if row_id is None:
                cursor = db.execute("UPDATE pending SET attempts=0,last_error=NULL WHERE attempts>=3")
            else:
                cursor = db.execute(
                    "UPDATE pending SET attempts=0,last_error=NULL WHERE id=? AND attempts>=3",
                    (row_id,),
                )
            return int(cursor.rowcount)

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

