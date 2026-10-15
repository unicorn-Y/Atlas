# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/subagents/registry/subagent-registry-helpers.ts (MIT)
"""Durable registry of linked (independent) sessions.

One row per side session: who started it (parent conversation), the real
conversation it lives in, how it was started (proposal card, user request,
the model's own initiative) and what it last reported. The conversation
itself stays the single owner of transcript, worktree and permissions; this
table only records the link and the lifecycle, like OpenClaw's subagent
registry keeps requester/child keys next to the child session store.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ACTIVE = {"starting", "running", "waiting"}
OPEN = ACTIVE | {"proposed", "idle"}
TERMINAL = {"failed", "stopped", "dismissed", "expired"}
PROPOSAL_TTL = timedelta(days=7)

_COLUMNS = (
    "session_id", "name", "title", "prompt", "background", "context", "initiation",
    "status", "parent_conversation_id", "parent_run_id", "conversation_id",
    "use_worktree", "worktree_path", "worktree_branch", "notify_parent",
    "last_run_id", "last_report", "last_status", "stats", "error",
    "created_at", "updated_at", "expires_at", "hub_runs", "unseen_report",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def slugify(text: str, fallback: str = "session") -> str:
    """CCD-style short handle: ``[a-z0-9-]``, at most 24 characters."""
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].strip("-")
    # Chinese titles have no ASCII to keep: use a short random handle instead.
    return value if len(value) >= 3 else f"{fallback[:15]}-{uuid.uuid4().hex[:4]}"


class SessionStore:
    """Small synchronous SQLite store; every call is a single short statement."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS linked_sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    background TEXT NOT NULL DEFAULT '',
                    context TEXT NOT NULL DEFAULT 'fresh',
                    initiation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parent_conversation_id TEXT,
                    parent_run_id TEXT,
                    conversation_id TEXT,
                    use_worktree INTEGER NOT NULL DEFAULT 0,
                    worktree_path TEXT,
                    worktree_branch TEXT,
                    notify_parent INTEGER NOT NULL DEFAULT 1,
                    last_run_id TEXT,
                    last_report TEXT NOT NULL DEFAULT '',
                    last_status TEXT,
                    stats TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    hub_runs TEXT NOT NULL DEFAULT '[]',
                    unseen_report INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS linked_sessions_parent ON linked_sessions(parent_conversation_id)")
            db.execute("CREATE INDEX IF NOT EXISTS linked_sessions_child ON linked_sessions(conversation_id)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["use_worktree"] = bool(item["use_worktree"])
        item["notify_parent"] = bool(item["notify_parent"])
        item["unseen_report"] = bool(item["unseen_report"])
        item["stats"] = json.loads(item.get("stats") or "{}")
        item["hub_runs"] = json.loads(item.get("hub_runs") or "[]")
        return item

    def create(self, **fields: Any) -> dict[str, Any]:
        now = _now()
        session_id = "s_" + uuid.uuid4().hex[:10]
        record = {
            "session_id": session_id, "name": slugify(str(fields.get("name") or fields.get("title") or "")),
            "title": str(fields.get("title") or "独立会话")[:120], "prompt": str(fields.get("prompt") or ""),
            "background": str(fields.get("background") or ""), "context": fields.get("context") or "fresh",
            "initiation": fields.get("initiation") or "user_asked", "status": fields.get("status") or "proposed",
            "parent_conversation_id": fields.get("parent_conversation_id"),
            "parent_run_id": fields.get("parent_run_id"), "conversation_id": fields.get("conversation_id"),
            "use_worktree": int(bool(fields.get("use_worktree"))), "worktree_path": None, "worktree_branch": None,
            "notify_parent": int(fields.get("notify_parent", True) is not False), "last_run_id": None,
            "last_report": "", "last_status": None, "stats": "{}", "error": None,
            "created_at": now, "updated_at": now,
            "expires_at": (datetime.now(UTC) + PROPOSAL_TTL).isoformat()
            if (fields.get("status") or "proposed") == "proposed" else None,
            "hub_runs": "[]", "unseen_report": 0,
        }
        # Handles are unique among the parent's sessions so "send to <name>" resolves.
        siblings = {item["name"] for item in self.list(parent=record["parent_conversation_id"])}
        base, suffix = record["name"], 2
        while record["name"] in siblings:
            record["name"] = f"{base[:21]}-{suffix}"
            suffix += 1
        with self._lock, self._connect() as db:
            db.execute(
                f"INSERT INTO linked_sessions ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                tuple(record[key] for key in _COLUMNS),
            )
        return self.get(session_id) or {}

    def update(self, session_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get(session_id)
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in _COLUMNS or key == "session_id":
                raise KeyError(key)
            if key in {"stats", "hub_runs"}:
                value = json.dumps(value, ensure_ascii=False)
            elif key in {"use_worktree", "notify_parent", "unseen_report"}:
                value = int(bool(value))
            values[key] = value
        values["updated_at"] = _now()
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE linked_sessions SET {', '.join(f'{key}=?' for key in values)} WHERE session_id=?",
                (*values.values(), session_id),
            )
        return self.get(session_id)

    def add_hub_run(self, session_id: str, run_id: str) -> None:
        record = self.get(session_id)
        if record is not None:
            runs = [*record["hub_runs"], run_id][-50:]
            self.update(session_id, hub_runs=runs, last_run_id=run_id)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute(
                "SELECT * FROM linked_sessions WHERE session_id=?", (session_id,),
            ).fetchone())

    def by_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute(
                "SELECT * FROM linked_sessions WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone())

    def list(self, parent: str | None = None, *, include_closed: bool = True,
             limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM linked_sessions"
        args: list[Any] = []
        if parent is not None:
            sql += " WHERE parent_conversation_id=?"
            args.append(parent)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._connect() as db:
            rows = [self._row(row) for row in db.execute(sql, args).fetchall()]
        items = [row for row in rows if row is not None]
        self._expire(items)
        if not include_closed:
            items = [item for item in items if item["status"] not in {"dismissed", "expired"}]
        return items

    def _expire(self, items: list[dict[str, Any]]) -> None:
        now = datetime.now(UTC)
        for item in items:
            if item["status"] == "proposed" and item.get("expires_at"):
                try:
                    expired = datetime.fromisoformat(item["expires_at"]) < now
                except ValueError:
                    expired = False
                if expired:
                    self.update(item["session_id"], status="expired")
                    item["status"] = "expired"
