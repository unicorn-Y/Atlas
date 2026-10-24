"""Durable peer messages exchanged between Atlas conversations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _path() -> Path:
    from atlas.config import DATA_ROOT
    return DATA_ROOT / "data" / "peer-inbox.sqlite3"


def send_peer_message(
    sender_id: str, recipient_id: str, sender_title: str, content: str,
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not sender_id or not recipient_id or sender_id == recipient_id or not text:
        raise ValueError("peer message requires distinct sender/recipient sessions and non-empty text")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {"id": uuid.uuid4().hex, "sender_conversation_id": sender_id,
            "recipient_conversation_id": recipient_id, "sender_title": sender_title[:200],
            "content": text[:16_000], "created_at": datetime.now(UTC).isoformat(), "read_at": None}
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS peer_messages (
            id TEXT PRIMARY KEY, sender_conversation_id TEXT NOT NULL,
            recipient_conversation_id TEXT NOT NULL, sender_title TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT)""")
        db.execute("INSERT INTO peer_messages VALUES (?, ?, ?, ?, ?, ?, NULL)",
                   tuple(item[key] for key in ("id", "sender_conversation_id", "recipient_conversation_id", "sender_title", "content", "created_at")))
    return item


def list_peer_messages(recipient_id: str, *, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    query = "SELECT id,sender_conversation_id,recipient_conversation_id,sender_title,content,created_at,read_at FROM peer_messages WHERE recipient_conversation_id=?"
    args: list[Any] = [recipient_id]
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(max(1, min(500, int(limit))))
    with sqlite3.connect(path, timeout=5) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, args).fetchall()]


def mark_peer_messages_read(recipient_id: str, message_ids: list[str] | None = None) -> int:
    path = _path()
    if not path.exists():
        return 0
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path, timeout=5) as db:
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            cursor = db.execute(
                f"UPDATE peer_messages SET read_at=? WHERE recipient_conversation_id=? AND read_at IS NULL AND id IN ({placeholders})",
                [now, recipient_id, *message_ids[:500]],
            )
        else:
            cursor = db.execute("UPDATE peer_messages SET read_at=? WHERE recipient_conversation_id=? AND read_at IS NULL", (now, recipient_id))
        return cursor.rowcount


__all__ = ["send_peer_message", "list_peer_messages", "mark_peer_messages_read"]
