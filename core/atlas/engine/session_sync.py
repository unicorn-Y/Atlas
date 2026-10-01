"""Bridge Atlas history mutations to the Hermes SessionDB transcript.

Hermes source: ``hermes_state.py::SessionDB``, ``hermes_state_rewind.py`` and
``hermes_state_portability.py`` at unicorn-Y/hermes-agent@562ad75 (MIT).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _open_db(home: str | Path):
    root = Path(home).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(root)
    from hermes_state import SessionDB

    return SessionDB(db_path=root / "state.db")


def capture_session(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    with _open_db(home) as db:
        return db.export_session(conversation_id, include_inactive=True)


def restore_session(home: str | Path, payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    with _open_db(home) as db:
        session_id = str(payload.get("id") or "")
        if session_id:
            db.delete_session(session_id)
        result = db.import_sessions([payload])
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Hermes session restore failed: {result.get('errors', result)}")


def delete_session(home: str | Path, conversation_id: str) -> bool:
    with _open_db(home) as db:
        return db.delete_session(conversation_id)


def rewind_to_atlas_message(
    home: str | Path, conversation_id: str, atlas_messages: list[dict[str, Any]], message_id: str,
) -> dict[str, Any] | None:
    """Rewind Hermes at the same user turn Atlas is removing; return a redo snapshot."""
    target = next((index for index, item in enumerate(atlas_messages)
                   if str(item.get("id")) == message_id), None)
    if target is None:
        return None
    user_ordinal = sum(1 for item in atlas_messages[:target] if item.get("role") == "user")
    with _open_db(home) as db:
        snapshot = db.export_session(conversation_id, include_inactive=True)
        if snapshot is None:
            return None
        db.rewind_user_turn(conversation_id, user_ordinal)
        return snapshot


def fork_session(
    home: str | Path, source_id: str, fork_id: str,
    atlas_messages: list[dict[str, Any]], through_message_id: str,
) -> None:
    """Copy the durable Hermes transcript through the selected Atlas turn."""
    target = next((index for index, item in enumerate(atlas_messages)
                   if str(item.get("id")) == through_message_id), None)
    if target is None:
        return
    users_through = sum(1 for item in atlas_messages[:target + 1] if item.get("role") == "user")
    with _open_db(home) as db:
        payload = db.export_session(source_id, include_inactive=True)
        if payload is None:
            return
        transcript = payload.get("messages", [])
        seen_users = 0
        stop = len(transcript)
        for index, item in enumerate(transcript):
            if item.get("role") == "user":
                if seen_users >= users_through:
                    stop = index
                    break
                seen_users += 1
        cloned = {**payload, "id": fork_id, "parent_session_id": None,
                  "messages": transcript[:stop]}
        result = db.import_sessions([cloned])
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Hermes session fork failed: {result.get('errors', result)}")
