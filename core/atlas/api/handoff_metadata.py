"""Durable handoff lineage metadata, kept separate from the frozen MemoryStore schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute(
        "CREATE TABLE IF NOT EXISTS handoff_metadata ("
        "conversation_id TEXT PRIMARY KEY, handoff_from TEXT NOT NULL, handoff_goal TEXT NOT NULL)"
    )
    return db


def save_handoff_metadata(path: Path, conversation_id: str, parent_id: str, goal: str) -> None:
    """Atomically persist the two user-facing handoff fields for a child session."""
    with _connect(path) as db:
        db.execute(
            "INSERT INTO handoff_metadata(conversation_id,handoff_from,handoff_goal) VALUES(?,?,?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET handoff_from=excluded.handoff_from, "
            "handoff_goal=excluded.handoff_goal",
            (conversation_id, parent_id, goal),
        )


def load_handoff_metadata(path: Path, conversation_ids: list[str]) -> dict[str, dict[str, str]]:
    if not conversation_ids or not path.exists():
        return {}
    result: dict[str, dict[str, str]] = {}
    with _connect(path) as db:
        # Stay below SQLite's variable limit for unbounded conversation lists.
        for offset in range(0, len(conversation_ids), 900):
            batch = conversation_ids[offset : offset + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = db.execute(
                f"SELECT conversation_id,handoff_from,handoff_goal FROM handoff_metadata "
                f"WHERE conversation_id IN ({placeholders})",
                batch,
            ).fetchall()
            result.update(
                {
                    str(conversation_id): {
                        "handoff_from": str(parent_id),
                        "handoff_goal": str(goal),
                    }
                    for conversation_id, parent_id, goal in rows
                }
            )
    return result


def delete_handoff_metadata(path: Path, conversation_id: str) -> None:
    if not path.exists():
        return
    with _connect(path) as db:
        db.execute("DELETE FROM handoff_metadata WHERE conversation_id=?", (conversation_id,))
