"""Durable, rebuildable queue of SessionDB lifecycle pointers.

Queue rows deliberately contain message identities and processing state only.
The conversation transcript remains exclusively in SessionDB.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
            stage TEXT NOT NULL DEFAULT 'new', attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            conversation_id TEXT, message_uids TEXT NOT NULL DEFAULT '[]',
            event_kind TEXT, occurred_at TEXT, scope TEXT NOT NULL DEFAULT 'messages',
            run_id TEXT, tool_call_id TEXT, event_key TEXT,
            next_attempt_at TEXT, lease_until TEXT)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(pending)")}
        additions = {
            "workspace": "TEXT", "steps": "TEXT NOT NULL DEFAULT '[]'",
            "verified": "INTEGER NOT NULL DEFAULT 0", "turn_started": "TEXT",
            "conversation_id": "TEXT", "message_uids": "TEXT NOT NULL DEFAULT '[]'",
            "event_kind": "TEXT", "occurred_at": "TEXT",
            "scope": "TEXT NOT NULL DEFAULT 'messages'", "run_id": "TEXT",
            "tool_call_id": "TEXT", "event_key": "TEXT",
            "next_attempt_at": "TEXT", "lease_until": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f"ALTER TABLE pending ADD COLUMN {name} {declaration}")
        self._migrate_legacy_rows(db)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pending_event_key ON pending(event_key)")
        db.commit()
        return db

    @staticmethod
    def _time_key(value: Any) -> str | None:
        try:
            stamp = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.astimezone(UTC).isoformat()

    def _migrate_legacy_rows(self, db: sqlite3.Connection) -> None:
        """Convert old body rows to exact UID refs or visibly broad legacy tasks."""
        rows = db.execute("""SELECT id,session,created,turn_started FROM pending
            WHERE event_kind IS NULL""").fetchall()
        if not rows:
            return
        by_session: dict[str, list[dict[str, Any]]] = {}
        try:
            from atlas.config import DATA_ROOT
            from atlas.engine.session_sync import read_session_all_messages

            for session in {str(row["session"] or "") for row in rows if row["session"]}:
                by_session[session] = read_session_all_messages(DATA_ROOT / "engine", session)
        except Exception:
            # Keep the pointer explicitly unanchored when canonical evidence is
            # unavailable; never infer a UID from nearest timestamps.
            by_session = {}
        for row in rows:
            conversation_id = str(row["session"] or "")
            exact_time = self._time_key(row["turn_started"] or row["created"])
            candidates = []
            if exact_time and conversation_id:
                candidates = [message for message in by_session.get(conversation_id, [])
                              if self._time_key(message.get("created_at")) == exact_time
                              and message.get("id")]
            unique_uid = str(candidates[0]["id"]) if len(candidates) == 1 else ""
            uids = [unique_uid] if unique_uid else []
            event_kind = "turn_end" if unique_uid else "legacy_unanchored"
            scope = "messages" if unique_uid else "session"
            occurred_at = str(row["turn_started"] or row["created"] or "")
            db.execute("""UPDATE pending SET conversation_id=?,message_uids=?,event_kind=?,
                occurred_at=?,scope=?,stage='new',user_text='',assistant_text='',steps='[]'
                WHERE id=?""",
                       (conversation_id, json.dumps(uids), event_kind, occurred_at,
                        scope, int(row["id"])))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def insert(self, *, conversation_id: str, message_uids: list[str], event_kind: str,
               occurred_at: str, scope: str = "messages", run_id: str | None = None,
               tool_call_id: str | None = None) -> int:
        uids = list(dict.fromkeys(str(uid) for uid in message_uids if str(uid)))
        # The last UID is the lifecycle watermark. Different adapters may send
        # the same boundary with a narrower or fuller ordered UID list.
        identity = json.dumps([conversation_id, uids[-1] if uids else scope, event_kind], ensure_ascii=False,
                              separators=(",", ":"))
        event_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._connection() as db:
            if event_kind != "session_idle":
                db.execute("DELETE FROM pending WHERE conversation_id=? AND event_kind='session_idle'",
                           (conversation_id,))
            db.execute("""INSERT OR IGNORE INTO pending(
                created, session, conversation_id, message_uids, event_kind, occurred_at,
                scope, run_id, tool_call_id, event_key, stage)
                VALUES(?,?,?,?,?,?,?,?,?,?, 'new')""",
                       (occurred_at, conversation_id, conversation_id,
                        json.dumps(uids, ensure_ascii=False), event_kind, occurred_at,
                        scope, run_id, tool_call_id, event_key))
            row = db.execute("SELECT id FROM pending WHERE event_key=?", (event_key,)).fetchone()
            if row is None:
                raise RuntimeError("lifecycle event enqueue failed")
            return int(row["id"])

    def pending(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        lease = (now + timedelta(minutes=10)).isoformat()
        with self._connection() as db:
            rows = db.execute("SELECT * FROM pending ORDER BY id").fetchall()
            now_key = now.isoformat()
            def due(value: Any) -> bool:
                if not value:
                    return True
                key = self._time_key(value)
                return key is None or key <= now_key

            eligible = [row for row in rows if due(row["next_attempt_at"])
                        and due(row["occurred_at"]) and due(row["lease_until"])]
            ids = [int(row["id"]) for row in eligible]
            if not ids:
                return []
            db.executemany("UPDATE pending SET lease_until=? WHERE id=?",
                           [(lease, row_id) for row_id in ids])
            placeholders = ",".join("?" for _ in ids)
            claimed = db.execute(
                f"SELECT * FROM pending WHERE id IN ({placeholders}) ORDER BY id", ids,
            ).fetchall()
            result = [dict(row) for row in claimed]
            for row in result:
                try:
                    row["message_uids"] = json.loads(row.get("message_uids") or "[]")
                except (TypeError, ValueError):
                    row["message_uids"] = []
            return result

    def stage_diary_done(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("UPDATE pending SET stage='diary_done' WHERE id=?", (row_id,))

    def remove(self, row_id: int) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM pending WHERE id=?", (row_id,))

    def failed_count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM pending WHERE attempts > 0").fetchone()[0])

    def fail(self, row_id: int, error: str) -> None:
        with self._connection() as db:
            row = db.execute("SELECT attempts FROM pending WHERE id=?", (row_id,)).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"] or 0) + 1
            delay = min(3600, 5 * (2 ** min(attempts - 1, 10)))
            retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
            # Keep diagnostics bounded and avoid copying a potentially sensitive
            # exception payload into the derived queue.
            candidate = str(error).split(":", 1)[0].replace("\n", " ").strip()
            error_type = (candidate[:80] if candidate.isidentifier()
                          else "processing_error")
            db.execute("""UPDATE pending SET attempts=?,last_error=?,next_attempt_at=?,
                lease_until=NULL WHERE id=?""", (attempts, error_type, retry_at, row_id))

    def retry_delay_seconds(self, row_id: int) -> float | None:
        """Return seconds until a failed row is eligible again, if it still exists."""
        with self._connection() as db:
            row = db.execute("SELECT next_attempt_at FROM pending WHERE id=?", (row_id,)).fetchone()
        if row is None or not row["next_attempt_at"]:
            return None
        try:
            due = datetime.fromisoformat(str(row["next_attempt_at"]))
        except ValueError:
            return 0.0
        return max(0.0, (due - datetime.now(UTC)).total_seconds())

    def next_wake_delay(self) -> float | None:
        """Seconds until the next row can be claimed, or None when empty."""
        now = datetime.now(UTC)
        with self._connection() as db:
            rows = db.execute(
                "SELECT occurred_at,next_attempt_at,lease_until FROM pending",
            ).fetchall()
        due_times: list[datetime] = []
        for row in rows:
            values = [row["occurred_at"], row["next_attempt_at"], row["lease_until"]]
            parsed = []
            for value in values:
                if not value:
                    continue
                try:
                    parsed.append(datetime.fromisoformat(str(value)))
                except ValueError:
                    continue
            if parsed:
                due_times.append(max(parsed))
        if not due_times:
            return 0.0 if rows else None
        return max(0.0, (min(due_times) - now).total_seconds())

    def count(self) -> int:
        with self._connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM pending").fetchone()[0])
