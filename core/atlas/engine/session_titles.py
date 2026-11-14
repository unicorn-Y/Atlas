"""Atlas title provenance synchronization for Atlas sessions."""

from __future__ import annotations

from pathlib import Path


def set_user_title(home: str | Path, conversation_id: str, title: str) -> bool:
    """Mirror an explicit Atlas rename into Hermes with user-level provenance."""
    from atlas.engine.session_sync import _open_db

    with _open_db(home) as db:
        return db.set_session_title(conversation_id, title)


def refresh_user_title(home: str | Path, conversation_id: str) -> bool:
    """Unpin a user rename (S28 ``refresh()``) so automatic titles re-compete."""
    from atlas.engine.session_sync import _open_db

    with _open_db(home) as db:
        return db.refresh_session_title(conversation_id)
