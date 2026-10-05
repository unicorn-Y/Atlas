"""Single write path for the durable conversation transcript (Hermes SessionDB).

DATA-OWNERS.md (H2.1): the conversation record (messages, tool calls/results,
rewinds, forks) has ONE owner — Hermes ``SessionDB`` — and this module is the
only place outside the engine turn loop that writes to it. Truncate, rewind,
fork, delete and import/export operate DIRECTLY on ``SessionDB``: targets are
SessionDB-native (user-turn ordinals), no Atlas message state is read to decide
what gets written. Callers that still address turns by Atlas message id resolve
the ordinal themselves with :func:`atlas_turn_ordinal` and pass it to
:func:`rewind_user_turn` / :func:`fork_session_through_turn`.

Hermes source: ``hermes_state.py::SessionDB``, ``hermes_state_rewind.py`` and
``hermes_state_portability.py`` at unicorn-Y/hermes-agent@562ad75 (MIT).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import time
import tempfile
import shutil
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.session_migration_gate import (
    SessionMigrationError,
    begin_session_migration,
    finish_session_migration,
    require_migration_settled as _require_migration_settled,
    wait_for_session_migration,
)


def _open_db(home: str | Path):
    _require_migration_settled(home)
    root = Path(home).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    from hermes_state import SessionDB

    return SessionDB(db_path=root / "state.db")


def _message_for_atlas(message: dict[str, Any]) -> dict[str, Any]:
    """Keep the existing Atlas message wire shape while sourcing its body from SessionDB."""
    metadata = dict(message.get("display_metadata") or {})
    for key in ("tool_name", "tool_call_id", "tool_calls", "reasoning", "reasoning_content",
                "reasoning_details", "codex_reasoning_items", "codex_message_items",
                "_compressed_summary", "finish_reason", "token_count", "display_kind"):
        if key in message:
            metadata[key] = message[key]
    timestamp = message.get("timestamp") or message.get("created_at") or ""
    if isinstance(timestamp, (int, float)):
        timestamp = datetime.fromtimestamp(timestamp, UTC).isoformat()
    return {
        "id": str(message.get("message_uid") or message.get("id") or ""),
        "role": str(message.get("role") or "unknown"),
        "content": message.get("content") if message.get("content") is not None else "",
        "metadata": metadata,
        "created_at": timestamp,
    }


def read_session_messages(
    home: str | Path, conversation_id: str, *, limit: int = 100,
    before_id: str | None = None, include_compacted: bool = True,
) -> list[dict[str, Any]]:
    """Read an Atlas-shaped chronological page from the canonical SessionDB transcript."""
    with _open_db(home) as db:
        payload = db.export_session(conversation_id, include_compacted=include_compacted)
    if not payload:
        return []
    messages = [_message_for_atlas(item) for item in payload.get("messages", [])]
    if before_id:
        anchor = next((i for i, item in enumerate(messages) if item["id"] == before_id), None)
        if anchor is None:
            return []
        messages = messages[:anchor]
    return messages[-limit:]


def read_session_all_messages(home: str | Path, conversation_id: str) -> list[dict[str, Any]]:
    with _open_db(home) as db:
        payload = db.export_session(conversation_id, include_compacted=True)
    if not payload:
        return []
    return [_message_for_atlas(item) for item in payload.get("messages", [])]


def latest_session_message_id(
    home: str | Path, conversation_id: str, *, role: str | None = None,
) -> str | None:
    with _open_db(home) as db:
        messages = db.get_messages(conversation_id, limit=20, latest=True, include_compacted=True)
    for message in reversed(messages):
        if role is None or message.get("role") == role:
            message_id = message.get("message_uid") or message.get("id")
            if message_id is not None:
                return str(message_id)
    return None


def session_message_evidence(
    home: str | Path, conversation_id: str | None, message_id: str,
) -> dict[str, Any] | None:
    """Return canonical role/time evidence for a stable SessionDB message UID."""
    with _open_db(home) as db:
        if conversation_id:
            row = db._read_one(
                "SELECT message_uid, role, timestamp FROM messages "
                "WHERE session_id=? AND (message_uid=? OR id=?) LIMIT 1",
                (conversation_id, message_id, message_id),
            )
        else:
            row = db._read_one(
                "SELECT message_uid, role, timestamp FROM messages "
                "WHERE message_uid=? OR id=? LIMIT 1", (message_id, message_id),
            )
    return dict(row) if row is not None else None


def append_session_message(
    home: str | Path, conversation_id: str, role: str, content: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Append an auxiliary visible message (for example a hook denial) to SessionDB."""
    with _open_db(home) as db:
        if db.get_session(conversation_id) is None:
            db.ensure_session(conversation_id, "api_server")
        message_id = db.append_message(
            conversation_id, role, content=content,
            display_metadata=metadata or None,
        )
        messages = db.get_messages(conversation_id, limit=1, latest=True)
        latest = messages[-1] if messages else {}
        return str(latest.get("message_uid") or message_id)


def list_session_previews(home: str | Path, *, limit: int = 1000) -> dict[str, str]:
    with _open_db(home) as db:
        sessions = db.list_sessions_rich(
            limit=limit, include_children=True, include_archived=True, include_hidden=True,
            project_compression_tips=False,
        )
    return {str(item["id"]): str(item.get("preview") or "") for item in sessions}


def search_session_messages(
    home: str | Path, query: str, *, limit: int = 20,
) -> list[dict[str, Any]]:
    with _open_db(home) as db:
        matches = db.search_messages(query, limit=limit)
        output = []
        for item in matches:
            row = db._read_one(
                "SELECT message_uid FROM messages WHERE id=? AND session_id=?",
                (item.get("id"), item.get("session_id")),
            )
            mapped = _message_for_atlas({
                "id": (row[0] if row else None) or item.get("id"),
                "role": item.get("role"), "timestamp": item.get("timestamp"),
            })
            output.append({
                "id": mapped["id"],
                "conversation_id": str(item.get("session_id") or ""),
                "role": str(item.get("role") or "unknown"),
                "created_at": mapped["created_at"],
                "content": str(item.get("snippet") or ""),
                "snippet": str(item.get("snippet") or ""),
            })
    return output


@dataclass(frozen=True)
class MigrationReport:
    status: str
    imported_sessions: int = 0
    imported_messages: int = 0
    ignored_existing_sessions: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "imported_sessions": self.imported_sessions,
            "imported_messages": self.imported_messages,
            "ignored_existing_sessions": self.ignored_existing_sessions,
            "error": self.error,
        }


class _SessionImportValidationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _copy_sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        sqlite3.connect(target).close()
        return
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)


def _existing_session_ids(state_db: Path) -> set[str]:
    if not state_db.is_file():
        return set()
    with closing(sqlite3.connect(f"file:{state_db.as_posix()}?mode=ro", uri=True)) as conn:
        tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
            )
        }
        if "sessions" not in tables:
            raise RuntimeError("SessionDB transcript preflight found no sessions table")
        return {str(row[0]) for row in conn.execute("SELECT id FROM sessions")}


def _legacy_timestamp(value: Any) -> Any:
    """Convert Atlas SQLite UTC timestamps to Hermes' accepted datetime value."""
    if value is None or value == "":
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("Atlas transcript timestamp is invalid")
        return value
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            numeric = None
        if numeric is not None:
            if not math.isfinite(numeric):
                raise ValueError("Atlas transcript timestamp is invalid")
            return numeric
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Atlas transcript timestamp is invalid") from exc
    else:
        raise ValueError("Atlas transcript timestamp is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()


def _timestamp_epoch(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return parsed.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _timestamp_epoch(_legacy_timestamp(value))
    return None


def _publish_staged_database(stage_db: Path, target: Path, stage_dir: Path) -> None:
    """Replace main/WAL/SHM as one quiesced set, restoring exact originals on failure."""
    originals: dict[Path, Path] = {}
    published = False
    try:
        for suffix in ("", "-wal", "-shm"):
            current = Path(f"{target}{suffix}")
            if current.exists():
                saved = stage_dir / f"original{suffix or '.db'}"
                os.replace(current, saved)
                originals[current] = saved
        os.replace(stage_db, target)
        published = True
    except Exception:
        if published:
            Path(target).unlink(missing_ok=True)
        for current, saved in originals.items():
            if saved.exists():
                os.replace(saved, current)
        raise
    # The old WAL/SHM must never be visible beside the new main database.
    for saved in originals.values():
        with suppress(OSError):
            saved.unlink(missing_ok=True)


def _decoded(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _verify_imported_session(db: Any, expected: dict[str, Any]) -> None:
    session_id = str(expected["id"])
    actual = db.export_session(session_id, include_inactive=True)
    if actual is None:
        raise _SessionImportValidationError("session_missing")
    expected_messages = expected.get("messages") or []
    actual_messages = actual.get("messages") or []
    if len(actual_messages) != len(expected_messages):
        raise _SessionImportValidationError("message_count")
    expected_started_at = _timestamp_epoch(expected.get("started_at"))
    actual_started_at = _timestamp_epoch(actual.get("started_at"))
    if expected_started_at is not None and (
        actual_started_at is None or abs(expected_started_at - actual_started_at) > 1e-6
    ):
        raise _SessionImportValidationError("session_started_at")
    for expected_message, actual_message in zip(expected_messages, actual_messages, strict=True):
        for field in ("role", "content", "tool_name", "tool_call_id", "tool_calls",
                      "display_metadata"):
            expected_value = _decoded(expected_message.get(field))
            actual_value = _decoded(actual_message.get(field))
            if field == "display_metadata":
                expected_value = expected_value or {}
                actual_value = actual_value or {}
            if expected_value != actual_value:
                raise _SessionImportValidationError(f"message_{field}")
        expected_uid = expected_message.get("message_uid")
        actual_uid = actual_message.get("message_uid")
        if expected_uid and str(actual_uid or "") != str(expected_uid):
            raise _SessionImportValidationError("message_uid")
        expected_timestamp = _timestamp_epoch(expected_message.get("timestamp"))
        actual_timestamp = _timestamp_epoch(actual_message.get("timestamp"))
        if expected_timestamp is not None and (
            actual_timestamp is None or abs(expected_timestamp - actual_timestamp) > 1e-6
        ):
            raise _SessionImportValidationError("message_timestamp")
    if expected.get("parent_session_id") and str(actual.get("parent_session_id") or "") != str(
        expected["parent_session_id"]
    ):
        raise _SessionImportValidationError("branch_parent")
    expected_config = _decoded(expected.get("model_config")) or {}
    actual_config = _decoded(actual.get("model_config")) or {}
    if not isinstance(expected_config, dict):
        expected_config = {}
    if not isinstance(actual_config, dict):
        actual_config = {}
    anchor = expected_config.get("_branch_message_id")
    if anchor:
        parent_id = str(expected.get("parent_session_id") or expected_config.get("_branched_from") or "")
        parent = db.export_session(parent_id, include_inactive=True) if parent_id else None
        parent_messages = (parent or {}).get("messages") or []
        parent_uids = {
            str(item.get("message_uid") or item.get("id") or "") for item in parent_messages
        }
        if str(anchor) not in parent_uids:
            raise _SessionImportValidationError("branch_anchor_missing")
        if str(actual_config.get("_branch_message_id") or "") != str(anchor):
            raise _SessionImportValidationError("branch_anchor_mismatch")


async def migrate_legacy_sessions(home: str | Path, memory_store: Any, *,
                                  backup_root: str | Path | None = None) -> MigrationReport:
    """Back up both stores, stage missing Atlas transcripts, verify, then publish SessionDB.

    Any imported content is validated in the staged database before the canonical state file
    is replaced. Existing Hermes session IDs remain authoritative and are counted as ignored.
    The caller owns startup health state and user-facing failure notification.
    """
    from atlas.config import get_config

    atlas_path = Path(get_config().db_path)
    hermes_path = Path(home).expanduser().resolve() / "state.db"
    begin_session_migration(hermes_path.parent)
    stage_dir: Path | None = None
    settled = False
    phase = "preflight"
    try:
        assert memory_store._db is not None
        cursor = await memory_store._db.execute(
            "SELECT DISTINCT c.id FROM conversations c "
            "JOIN messages m ON m.conversation_id=c.id"
        )
        atlas_ids = {str(row[0]) for row in await cursor.fetchall()}
        original_session_ids = _existing_session_ids(hermes_path)
        pending_ids = atlas_ids - original_session_ids
        ignored_existing = len(atlas_ids & original_session_ids)
        if not pending_ids:
            finish_session_migration(hermes_path.parent, "ready")
            settled = True
            return MigrationReport("ready", ignored_existing_sessions=ignored_existing)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backups = Path(backup_root) if backup_root else atlas_path.parent / "backup" / timestamp
        phase = "backup"
        hermes_path.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=".session-migration-", dir=hermes_path.parent))
        stage_db = stage_dir / "state.db"
        backups = backups / timestamp if backup_root else backups
        backups.mkdir(parents=True, exist_ok=False)
        _copy_sqlite_backup(atlas_path, backups / "atlas.sqlite3")
        _copy_sqlite_backup(hermes_path, backups / "state.db")
        _copy_sqlite_backup(hermes_path, stage_db)
        phase = "import"
        conversations = await memory_store.list_conversations(limit=None)
        from hermes_state import SessionDB

        with SessionDB(db_path=stage_db) as db:
            existing_rows = db._read_all("SELECT id, title FROM sessions")
            existing = {str(row[0]) for row in existing_rows}
            used_titles = {str(row[1]) for row in existing_rows if row[1] is not None}
            payloads: list[dict[str, Any]] = []
            staged_ignored_existing = 0
            for conversation in conversations:
                conversation_id = str(conversation.get("id") or "")
                if not conversation_id:
                    continue
                legacy = await memory_store.get_messages_with_rowid(conversation_id)
                if not legacy:
                    continue
                if conversation_id in existing:
                    staged_ignored_existing += 1
                    continue
                title = str(conversation.get("title") or "对话")
                if title in used_titles:
                    suffix = f" · Atlas {conversation_id[:8]}"
                    unique_title = f"{title}{suffix}"
                    if unique_title in used_titles:
                        unique_title = f"{title} · Atlas {conversation_id}"
                    sequence = 2
                    while unique_title in used_titles:
                        unique_title = f"{title} · Atlas {conversation_id} ({sequence})"
                        sequence += 1
                    title = unique_title
                used_titles.add(title)
                messages = []
                for row in legacy:
                    try:
                        metadata = row.get("metadata") or "{}"
                        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
                    except (TypeError, ValueError):
                        metadata = {}
                    metadata = metadata if isinstance(metadata, dict) else {}
                    messages.append({
                        "role": str(row.get("role") or "unknown"),
                        "content": row.get("content") or "",
                        "message_uid": str(row.get("id") or "") or None,
                        "timestamp": _legacy_timestamp(row.get("created_at")),
                        "tool_name": metadata.get("tool_name"),
                        "tool_call_id": metadata.get("tool_call_id"),
                        "tool_calls": metadata.get("tool_calls"),
                        "display_metadata": metadata,
                    })
                payloads.append({
                    "id": conversation_id, "title": title,
                    "source": conversation.get("source") or "atlas_import",
                    "parent_session_id": conversation.get("parent_conversation_id"),
                    "started_at": _legacy_timestamp(conversation.get("created_at")),
                    "model_config": {
                        "atlas_import": True,
                        **({"_branched_from": conversation["parent_conversation_id"]}
                           if conversation.get("parent_conversation_id") else {}),
                        **({"_branch_message_id": conversation["fork_message_id"]}
                           if conversation.get("fork_message_id") else {}),
                    },
                    "messages": messages,
                })
            if not payloads:
                finish_session_migration(hermes_path.parent, "ready")
                settled = True
                return MigrationReport(
                    "ready", ignored_existing_sessions=staged_ignored_existing,
                )
            result = db.import_sessions(payloads)
            if not result.get("ok") or result.get("imported") != len(payloads):
                raise RuntimeError(f"SessionDB import rejected: {result.get('errors', result)}")
            phase = "verify"
            for payload in payloads:
                _verify_imported_session(db, payload)
            imported = int(result["imported"])
            imported_messages = sum(len(payload["messages"]) for payload in payloads)
        with closing(sqlite3.connect(stage_db)) as staged:
            staged.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for sidecar in (Path(f"{stage_db}-wal"), Path(f"{stage_db}-shm")):
            sidecar.unlink(missing_ok=True)
        phase = "publish"
        _publish_staged_database(stage_db, hermes_path, stage_dir)
        finish_session_migration(hermes_path.parent, "ready")
        settled = True
        return MigrationReport(
            "ready", imported, imported_messages,
            ignored_existing_sessions=staged_ignored_existing,
        )
    except asyncio.CancelledError:
        finish_session_migration(hermes_path.parent, "failed")
        settled = True
        raise
    except (OSError, sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError) as exc:
        finish_session_migration(hermes_path.parent, "failed")
        settled = True
        return MigrationReport(
            "failed", error=(
                f"会话迁移失败（{phase}）：{exc.code}"
                if isinstance(exc, _SessionImportValidationError)
                else f"会话迁移失败（{phase}）：{type(exc).__name__}"
            ),
        )
    finally:
        if not settled:
            finish_session_migration(hermes_path.parent, "failed")
        if stage_dir is not None:
            shutil.rmtree(stage_dir, ignore_errors=True)


def capture_session(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    """Direct SessionDB read/export of one full session payload (导出)."""
    with _open_db(home) as db:
        return db.export_session(conversation_id, include_inactive=True)


def restore_session(home: str | Path, payload: dict[str, Any] | None) -> None:
    """Direct SessionDB write: replace a session with an exported payload (导入)."""
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
    """Direct SessionDB write: remove one session and its transcript (删除)."""
    with _open_db(home) as db:
        return db.delete_session(conversation_id)


def atlas_turn_ordinal(
    messages: list[dict[str, Any]], message_id: str, *, through_target: bool,
) -> int | None:
    """Resolve a message id inside a caller-supplied message list to the
    SessionDB user-turn ordinal it addresses.

    Pure adapter math for the transition period (DATA-OWNERS step 2): counts
    user messages before ``message_id`` (``through_target=False`` — rewind
    starts AT that turn) or through it (``through_target=True`` — fork keeps
    that turn). Returns None when the id is not in the list.
    """
    target = next((index for index, item in enumerate(messages)
                   if str(item.get("id")) == message_id), None)
    if target is None:
        return None
    span = messages[:target + 1] if through_target else messages[:target]
    return sum(1 for item in span if item.get("role") == "user")


def rewind_user_turn(
    home: str | Path, conversation_id: str, user_ordinal: int,
) -> dict[str, Any] | None:
    """Direct SessionDB write: export a redo snapshot, then rewind the durable
    transcript to just before user turn ``user_ordinal`` (0 = oldest)."""
    with _open_db(home) as db:
        snapshot = db.export_session(conversation_id, include_inactive=True)
        if snapshot is None:
            return None
        db.rewind_user_turn(conversation_id, user_ordinal)
        return snapshot


def fork_session_through_turn(
    home: str | Path, source_id: str, fork_id: str, user_turns: int, *,
    branch_message_id: str | None = None,
    preamble: dict[str, Any] | None = None,
) -> None:
    """Direct SessionDB write: clone the durable transcript through the first
    ``user_turns`` user turns. The cut point is computed from the SessionDB
    transcript itself, never from Atlas state.

    ``preamble`` (an optional raw SessionDB message dict) is imported as the
    clone's FIRST message — the fork's context summary must sit ahead of the
    carried-over transcript, before the next user message.
    """
    with _open_db(home) as db:
        payload = db.export_session(source_id, include_inactive=True)
        if payload is None:
            return
        transcript = payload.get("messages", [])
        seen_users = 0
        stop = len(transcript)
        for index, item in enumerate(transcript):
            if item.get("role") == "user":
                if seen_users >= user_turns:
                    stop = index
                    break
                seen_users += 1
        model_config = payload.get("model_config") or {}
        if isinstance(model_config, str):
            try:
                model_config = json.loads(model_config)
            except ValueError:
                model_config = {}
        cloned = {
            **payload, "id": fork_id, "parent_session_id": source_id,
            "title": f"{str(payload.get('title') or '对话')[:80]} · 分支 {fork_id[:6]}",
            "model_config": {**model_config, "_branched_from": source_id,
                             "_branch_message_id": branch_message_id},
            "messages": ([preamble] if preamble else []) + transcript[:stop],
        }
        result = db.import_sessions([cloned])
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Hermes session fork failed: {result.get('errors', result)}")


def list_branch_tree(home: str | Path, conversation_id: str) -> list[dict[str, Any]]:
    """Return the explicit Hermes branch lineage around one session."""
    with _open_db(home) as db:
        session = db.get_session(conversation_id)
        if session is None:
            return []
        sessions = []
        offset = 0
        while True:
            page = db.list_sessions_rich(
                include_children=True, include_archived=True, include_hidden=True,
                limit=1000, offset=offset, project_compression_tips=False,
            )
            sessions.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
    by_id = {str(item.get("id")): item for item in sessions}
    by_id[conversation_id] = {**by_id.get(conversation_id, {}), **session}
    for item in by_id.values():
        config = item.get("model_config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = {}
        item["_branch_config"] = config if isinstance(config, dict) else {}
    branched = {
        key: value for key, value in by_id.items()
        if value["_branch_config"].get("_branched_from")
    }
    root = conversation_id
    ancestors: set[str] = set()
    while root not in ancestors:
        ancestors.add(root)
        parent = str(by_id.get(root, {}).get("parent_session_id") or "")
        if parent not in by_id or root not in branched:
            break
        root = parent
    output: list[dict[str, Any]] = []
    pending = [root]
    seen: set[str] = set()
    while pending:
        current = pending.pop(0)
        if current in seen and current != root:
            continue
        seen.add(current)
        item = by_id.get(current)
        if item is None:
            continue
        output.append({
            "id": current, "parent_session_id": item.get("parent_session_id"),
            "title": item.get("title") or "未命名对话",
            "branch_message_id": item["_branch_config"].get("_branch_message_id"),
        })
        pending.extend(sorted(
            key for key, child in branched.items()
            if child.get("parent_session_id") == current and key not in seen
        ))
    return output


def goal_command(home: str | Path, conversation_id: str, command: str) -> dict[str, Any]:
    """Apply Hermes' canonical per-session /goal command and return its continuation prompt."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goal_command import dispatch_goal_command, is_goal_control
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    previous = manager.state
    result = dispatch_goal_command(
        manager, command, authorize_gate=lambda: "Goal gates require explicit approval.")
    state = manager.state
    normalized = command.strip().split(maxsplit=1)[0].casefold() if command.strip() else ""
    event = None
    if normalized in {"pause", "resume", "clear", "stop", "done"}:
        event = "goal.paused" if normalized == "pause" else (
            "goal.resumed" if normalized == "resume" else "goal.cleared"
        )
    elif not is_goal_control(command) and state and (
            previous is None or previous.status == "cleared"):
        event = "goal.created"
    elif not is_goal_control(command) and state and previous and previous.goal != state.goal:
        event = "goal.replaced"
    if event and not result.error:
        record_goal_event(home, conversation_id, event, {"goal": state.goal if state else ""})
    return {
        "output": result.output, "prompt": result.prompt, "kickoff": result.kickoff,
        "error": result.error,
        "goal": ({"text": state.goal, "status": state.status, "turns_used": state.turns_used,
                  "max_turns": state.max_turns, "subgoals": state.subgoals}
                 if state is not None else None),
    }


def evaluate_goal_after_turn(
    home: str | Path, conversation_id: str, response: str,
) -> dict[str, Any]:
    """Use Hermes' per-session GoalManager as the authority after an assistant turn."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    if not manager.is_active():
        return {"status": manager.state.status if manager.state else None,
                "should_continue": False, "continuation_prompt": None,
                "verdict": "inactive", "message": ""}
    return manager.evaluate_after_turn(response or "")


def goal_state(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    """Return the canonical Hermes GoalState for a conversation or automation session."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    state = GoalManager(conversation_id).state
    return json.loads(state.to_json()) if state is not None else None


def set_goal(home: str | Path, conversation_id: str, goal: str) -> dict[str, Any]:
    """Create or replace a goal through Hermes' per-session manager."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    state = manager.set(goal)
    return json.loads(state.to_json())


def mutate_goal(
    home: str | Path, conversation_id: str, action: str, reason: str = "user-paused",
) -> dict[str, Any] | None:
    """Apply a canonical Hermes done, pause, resume, or clear action."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    if action == "pause":
        state = manager.pause(reason)
    elif action == "resume":
        state = manager.resume()
    elif action == "done":
        manager.mark_done(reason)
        state = manager.state
    elif action == "clear":
        manager.clear()
        state = None
    else:
        raise ValueError(f"unsupported goal action: {action}")
    return json.loads(state.to_json()) if state is not None else None


def record_goal_event(
    home: str | Path, conversation_id: str, event: str,
    data: dict[str, Any] | None = None, run_id: str | None = None,
) -> dict[str, Any]:
    """Append audit-only goal history in Hermes SessionDB state metadata."""
    with _open_db(home) as db:
        key = f"goal-events:{conversation_id}"
        events = json.loads(db.get_meta(key) or "[]")
        if not isinstance(events, list):
            events = []
        sequence = max(
            (int(item.get("sequence", -1)) for item in events if isinstance(item, dict)),
            default=-1,
        ) + 1
        record = {
            "event_id": f"{conversation_id}:{sequence}",
            "sequence": sequence,
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data or {},
        }
        if run_id:
            record["run_id"] = run_id
        events.append(record)
        db.set_meta(key, json.dumps(events[-200:], ensure_ascii=False))
        return record


def goal_events(
    home: str | Path, conversation_id: str, run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read audit-only goal events from the same Hermes SessionDB as GoalManager."""
    with _open_db(home) as db:
        events = json.loads(db.get_meta(f"goal-events:{conversation_id}") or "[]")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)
            and (run_id is None or event.get("run_id") == run_id)]


def append_branch_summary(
    home: str | Path, parent_id: str, child_id: str, fork_message_id: str, content: str,
) -> None:
    """Mirror the Atlas branch note into Hermes' authoritative parent transcript."""
    with _open_db(home) as db:
        if db.get_session(parent_id) is None:
            return
        existing = db.get_messages_as_conversation(parent_id)
        if any(item.get("display_kind") == "branch_summary"
               and (item.get("display_metadata") or {}).get("child_conversation_id") == child_id
               for item in existing):
            return
        db.append_message(parent_id, "assistant", content, display_kind="branch_summary",
                          display_metadata={"child_conversation_id": child_id,
                                            "fork_message_id": fork_message_id})
