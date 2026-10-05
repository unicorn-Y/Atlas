"""Explicit SessionDB transcript setup for tests with Atlas MemoryStore metadata."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from hermes_state import SessionDB


async def seed_session_messages(
    conversation_id: str,
    messages: list[
        tuple[str, str]
        | tuple[str, str, dict[str, Any]]
        | tuple[str, str, dict[str, Any], str]
    ],
) -> list[str]:
    """Write transcript rows to the configured canonical SessionDB test home."""
    from atlas.config import DATA_ROOT

    home = DATA_ROOT / "engine"
    message_ids: list[str] = []

    def append(item: tuple[Any, ...]) -> str:
        role, content, *extras = item
        metadata = extras[0] if extras and isinstance(extras[0], dict) else None
        message_uid = extras[1] if len(extras) > 1 else None
        with SessionDB(db_path=home / "state.db") as db:
            if db.get_session(conversation_id) is None:
                db.ensure_session(conversation_id, "atlas_test_fixture")
            db.append_message(
                conversation_id, role, content=content,
                display_metadata=metadata, message_uid=message_uid,
            )
            latest = db.get_messages(conversation_id, limit=1, latest=True)
            return str(latest[-1].get("message_uid") or latest[-1]["id"])

    for item in messages:
        message_ids.append(await asyncio.to_thread(append, item))
    return message_ids


async def save_memory_fixture_message(
    memory: Any,
    conversation_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Set up legacy Atlas metadata/body plus its explicit canonical transcript row."""
    legacy_id = await memory.save_message(conversation_id, role, content, metadata)
    return (await seed_session_messages(
        conversation_id, [(role, content, metadata or {}, legacy_id)],
    ))[0]


def set_session_message_timestamp(
    conversation_id: str, message_uid: str, timestamp: str,
) -> None:
    """Set a canonical test row's UTC epoch timestamp for ordering regressions."""
    from atlas.config import DATA_ROOT

    parsed = datetime.fromisoformat(timestamp).replace(tzinfo=UTC).timestamp()
    db_path = DATA_ROOT / "engine" / "state.db"
    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            connection.execute(
                "UPDATE messages SET timestamp = ? WHERE session_id = ? AND message_uid = ?",
                (parsed, conversation_id, message_uid),
            )
