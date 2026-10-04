"""Small durable inbox for detached process and watch notifications."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_lock = threading.Lock()

# H3 event bridge: conversation_id -> {(loop, event)} registered by in-flight
# turns. ``publish_notification`` wakes these waiters so a running turn consumes
# its notifications immediately instead of polling the inbox on a timer.
_waiters_lock = threading.Lock()
_waiters: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}


def subscribe_notifications(
    conversation_id: str,
) -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
    """Register an asyncio.Event woken by new notifications for this conversation."""
    loop = asyncio.get_running_loop()
    event = asyncio.Event()
    with _waiters_lock:
        _waiters.setdefault(conversation_id, set()).add((loop, event))
    return loop, event


def unsubscribe_notifications(
    conversation_id: str,
    handle: tuple[asyncio.AbstractEventLoop, asyncio.Event],
) -> None:
    """Remove a subscription created by :func:`subscribe_notifications`."""
    with _waiters_lock:
        waiters = _waiters.get(conversation_id)
        if waiters:
            waiters.discard(handle)
            if not waiters:
                _waiters.pop(conversation_id, None)


def _wake_notification_waiters(conversation_id: str) -> None:
    with _waiters_lock:
        waiters = list(_waiters.get(conversation_id, ()))
    for loop, event in waiters:
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:  # loop already closed: the waiter is gone
            continue


def _database_path() -> Path:
    from atlas.config import get_config

    return Path(get_config().db_path)


def publish_notification(
    conversation_id: str,
    *,
    kind: str,
    content: str,
    source_id: str | None = None,
) -> str:
    """Persist one notification in its conversation inbox and return its id."""
    if not conversation_id:
        raise ValueError("conversation_id is required")
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    notification_id = uuid.uuid4().hex
    created_at = datetime.now(UTC).isoformat()
    with _lock, sqlite3.connect(path, timeout=5) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS notification_inbox (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                source_id TEXT,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(conversation_id, source_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS notification_dedupe (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                UNIQUE(conversation_id, source_id)
            )
        """)
        db.execute("BEGIN IMMEDIATE")
        if source_id:
            prior = db.execute(
                "SELECT id FROM notification_dedupe WHERE conversation_id=? AND source_id=?",
                (conversation_id, source_id),
            ).fetchone()
            if prior:
                db.commit()
                return str(prior[0])
            db.execute(
                "INSERT INTO notification_dedupe (id, conversation_id, source_id) VALUES (?, ?, ?)",
                (notification_id, conversation_id, source_id),
            )
        db.execute(
            "INSERT OR IGNORE INTO notification_inbox "
            "(id, conversation_id, source_id, kind, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (notification_id, conversation_id, source_id, kind, content, created_at),
        )
        db.commit()
    _wake_notification_waiters(conversation_id)
    return notification_id


def _consume(conversation_id: str, limit: int) -> list[dict[str, Any]]:
    path = _database_path()
    if not path.exists() or limit <= 0:
        return []
    with _lock, sqlite3.connect(path, timeout=5) as db:
        db.row_factory = sqlite3.Row
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notification_inbox'"
        ).fetchone()
        if table is None:
            return []
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT id, kind, content, created_at FROM notification_inbox "
            "WHERE conversation_id=? ORDER BY created_at, id LIMIT ?",
            (conversation_id, min(limit, 100)),
        ).fetchall()
        if rows:
            db.executemany(
                "DELETE FROM notification_inbox WHERE id=?", [(row["id"],) for row in rows]
            )
        db.commit()
    return [dict(row) for row in rows]


async def consume_notifications(
    conversation_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Atomically consume pending notifications without blocking the event loop."""
    if not conversation_id:
        return []
    if limit <= 0:
        return []
    return await asyncio.to_thread(_consume, conversation_id, limit)
