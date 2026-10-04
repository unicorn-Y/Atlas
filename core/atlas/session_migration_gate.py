"""Lightweight per-home barrier used while SessionDB history is migrating."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from contextlib import closing

_states_lock = threading.Lock()
_states: dict[str, tuple[threading.Event, str]] = {}


class SessionMigrationError(RuntimeError):
    """Transcript access stays closed when first-start migration fails."""


def _migration_key(home: str | Path) -> str:
    return str(Path(home).expanduser().resolve())


def begin_session_migration(home: str | Path) -> None:
    key = _migration_key(home)
    with _states_lock:
        current = _states.get(key)
        if current is not None and current[1] == "running":
            return
        event = threading.Event()
        _states[key] = (event, "running")


def has_legacy_transcripts(atlas_db: str | Path, session_db: str | Path) -> bool:
    """Check whether Atlas has transcript IDs absent from the canonical SessionDB."""
    import sqlite3

    atlas_path = Path(atlas_db).expanduser().resolve()
    state_path = Path(session_db).expanduser().resolve()
    if not atlas_path.is_file():
        return False
    try:
        with closing(sqlite3.connect(f"file:{atlas_path.as_posix()}?mode=ro", uri=True)) as conn:
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('conversations', 'messages')"
                )
            }
            if not tables:
                return False
            if tables != {"conversations", "messages"}:
                raise RuntimeError("Atlas transcript preflight found an incomplete schema")
            atlas_ids = {
                str(row[0]) for row in conn.execute(
                    "SELECT DISTINCT c.id FROM conversations c "
                    "JOIN messages m ON m.conversation_id=c.id"
                )
            }
        if not atlas_ids:
            return False
        if not state_path.is_file():
            return True
        with closing(sqlite3.connect(f"file:{state_path.as_posix()}?mode=ro", uri=True)) as conn:
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
                )
            }
            if "sessions" not in tables:
                raise RuntimeError("SessionDB transcript preflight found no sessions table")
            existing_ids = {str(row[0]) for row in conn.execute("SELECT id FROM sessions")}
        return bool(atlas_ids - existing_ids)
    except sqlite3.Error as exc:
        raise RuntimeError("Session migration preflight failed") from exc


def finish_session_migration(home: str | Path, status: str) -> None:
    key = _migration_key(home)
    with _states_lock:
        event, _previous = _states.get(key, (threading.Event(), "ready"))
        _states[key] = (event, status)
        event.set()


def require_migration_settled(home: str | Path) -> None:
    key = _migration_key(home)
    while True:
        with _states_lock:
            event, status = _states.get(key, (None, "ready"))
        if event is None:
            break
        event.wait()
        with _states_lock:
            current_event, status = _states.get(key, (event, status))
        if current_event is event:
            break
    if status == "failed":
        raise SessionMigrationError(
            "会话迁移未完成，历史记录已保护；请在健康状态提示中查看修复方式。"
        )


async def wait_for_session_migration(home: str | Path) -> None:
    await asyncio.to_thread(require_migration_settled, home)
