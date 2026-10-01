"""Atlas title provenance synchronization for Hermes sessions."""

from __future__ import annotations

from pathlib import Path


def set_user_title(home: str | Path, conversation_id: str, title: str) -> bool:
    """Mirror an explicit Atlas rename into Hermes with user-level provenance."""
    from atlas.engine.session_sync import _open_db

    with _open_db(home) as db:
        return db.set_session_title(conversation_id, title)
