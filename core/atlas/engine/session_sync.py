"""Single write path for the durable conversation transcript (Atlas SessionDB).

DATA-OWNERS.md (H2.1): the conversation record (messages, tool calls/results,
rewinds, forks) has ONE owner — Hermes ``SessionDB`` — and this module is the
only place outside the engine turn loop that writes to it. Truncate, rewind,
fork, delete and import/export operate DIRECTLY on ``SessionDB``: targets are
SessionDB-native (user-turn ordinals), no Atlas message state is read to decide
what gets written. Callers that still address turns by Atlas message id resolve
the ordinal themselves with :func:`atlas_turn_ordinal` and pass it to
:func:`rewind_user_turn` / :func:`fork_session_through_turn`.

Hermes source: ``atlas_state.py::SessionDB``, ``atlas_state_rewind.py`` and
``atlas_state_portability.py`` at unicorn-Y/hermes-agent@562ad75 (MIT).

SessionDB 以 ``conversation_id`` 为会话身份；本模块不持有 task_id 映射，
会话记录保持纯转录权威（H2.1 单一所有者）。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import shutil
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.engine.kernel.repair import ToolHistoryError

from atlas.session_migration_gate import (
    begin_session_migration,
    finish_session_migration,
    require_migration_settled as _require_migration_settled,
    wait_for_session_migration as _wait_for_session_migration,
)


_SESSION_SNAPSHOT_KEY = "_atlas_session_snapshot"
_SESSION_SNAPSHOT_SCHEMA = 1
_TRANSCRIPT_ROLES = frozenset({"system", "user", "assistant", "tool"})
_SESSION_SNAPSHOT_FIELDS = frozenset({
    "schema_version", "kind", "created_at", "method", "boundary_watermark",
    "source_message_count", "source_first_message_id", "source_last_message_id",
    "summary_sha256", "summary_chars", "state",
})
_SESSION_SNAPSHOT_STATE_FIELDS = frozenset({"plan", "todo", "open_tool_call_ids"})


def _valid_session_snapshot_manifest(manifest: Any, summary: str) -> bool:
    """Reject incomplete, mistyped, or extended snapshot state at the restore boundary."""
    if not isinstance(manifest, dict) or set(manifest) != _SESSION_SNAPSHOT_FIELDS:
        return False
    if (type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != _SESSION_SNAPSHOT_SCHEMA
            or manifest.get("kind") != "context_compaction"
            or manifest.get("method") != "summary"):
        return False
    if not isinstance(manifest.get("created_at"), str):
        return False
    try:
        datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    for field in ("boundary_watermark", "source_message_count", "summary_chars"):
        value = manifest.get(field)
        if type(value) is not int or value < 0:
            return False
    first_id, last_id = (manifest.get("source_first_message_id"),
                         manifest.get("source_last_message_id"))
    if any(value is not None and (not isinstance(value, str) or not value)
           for value in (first_id, last_id)):
        return False
    source_count = manifest["source_message_count"]
    if (source_count == 0 and (first_id is not None or last_id is not None)) or (
            source_count > 0 and (first_id is None or last_id is None)):
        return False
    digest = manifest.get("summary_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
        return False
    if manifest["summary_chars"] != len(summary):
        return False
    import hashlib

    if digest != hashlib.sha256(summary.encode("utf-8")).hexdigest():
        return False
    state = manifest.get("state")
    if not isinstance(state, dict) or not set(state).issubset(_SESSION_SNAPSHOT_STATE_FIELDS):
        return False
    for field in ("plan", "todo"):
        if field in state and state[field] is not None and not isinstance(state[field], dict):
            return False
    open_calls = state.get("open_tool_call_ids")
    if open_calls is not None and (
            not isinstance(open_calls, list)
            or any(not isinstance(item, str) or not item for item in open_calls)
            or len(set(open_calls)) != len(open_calls)):
        return False
    return True


async def wait_for_session_migration(home: str | Path) -> None:
    """Public compatibility wrapper for callers awaiting legacy migration state."""
    await _wait_for_session_migration(home)


def _open_db(home: str | Path):
    _require_migration_settled(home)
    root = Path(home).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    from atlas.engine.state.atlas_state import SessionDB

    return SessionDB(db_path=root / "state.db")


def _message_for_atlas(message: dict[str, Any]) -> dict[str, Any]:
    """Keep the existing Atlas message wire shape while sourcing its body from SessionDB."""
    metadata = dict(message.get("display_metadata") or {})
    for key in ("tool_name", "tool_call_id", "tool_calls", "reasoning", "reasoning_content",
                "reasoning_details", "codex_reasoning_items", "codex_message_items",
                "_compressed_summary", "finish_reason", "token_count", "display_kind",
                "tool_snapshot"):
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


def read_session_model_messages(home: str | Path, conversation_id: str) -> list[dict[str, Any]]:
    """Read the canonical active model history with SessionDB row identities intact."""
    with _open_db(home) as db:
        cached = db.read_projection_cache(conversation_id, "model_history", 1)
        if cached is not None:
            return resolve_session_attachments(home, conversation_id, cached)
        revision = db.projection_revision(conversation_id)
        rows = db._fetch_conversation_rows(
            [conversation_id], db._active_clause(False, False), with_session_id=False,
        )
        model_history = db._rows_to_conversation(
            rows, session_id=conversation_id, include_ancestors=False,
            repair_alternation=False, include_row_ids=True, include_summary_markers=True,
        )
    # Older Atlas writes put tool pairing fields in display_metadata. Promote them
    # before alternation repair so valid tool results are not mistaken for stray rows.
    for message in model_history:
        metadata = message.get("display_metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("tool_calls", "tool_call_id", "tool_name", "finish_reason",
                    "reasoning", "reasoning_content", "reasoning_details",
                    "codex_reasoning_items", "codex_message_items", "_compressed_summary",
                    "tool_snapshot", "output_ref", "microcompacted", "masked_content"):
            if key in metadata and key not in message:
                message[key] = metadata[key]
    model_history = [
        message for message in model_history
        if message.get("display_kind") not in {"structured_component", "agent_canvas", "subtask_activity"}
        and (message.get("display_metadata") or {}).get("display_kind") not in {"structured_component", "agent_canvas", "subtask_activity"}
    ]
    from atlas.engine.kernel.repair import normalize_tool_results

    # Corrupt orphan/duplicate receipts are excluded from the model projection;
    # the kernel's recovery pass then pairs unresolved assistant calls with an
    # explicit unknown-outcome receipt before the next request.
    model_history = normalize_tool_results(
        model_history, require_complete=False, drop_orphan_results=True,
    )
    with _open_db(home) as db:
        db.write_projection_cache(conversation_id, "model_history", 1, revision, model_history)
    return resolve_session_attachments(home, conversation_id, model_history)


_ATTACHMENT_REF_KEY = "_atlas_attachment_ref"
_ACTIVE_SESSION_TURNS: set[tuple[str, str]] = set()


class SessionAttachmentIntegrityError(ToolHistoryError):
    """A durable attachment ref cannot be safely restored into model history."""


def mark_session_turn_active(conversation_id: str, turn_id: str, active: bool) -> None:
    """Track turns in this process so readers never repair a live in-process run."""
    key = (str(conversation_id), str(turn_id))
    if active:
        _ACTIVE_SESSION_TURNS.add(key)
    else:
        _ACTIVE_SESSION_TURNS.discard(key)


def ensure_session_workspace(home: str | Path, conversation_id: str, workspace: Any) -> None:
    """Record the run's local workspace on the engine session row when absent.

    Durable session queries admit a session by matching its stored ``cwd``
    metadata against the current run's workspace. Kernel runs created bare
    session rows without cwd, so that admission gate could never pass. This
    fills the NULL once per session; an existing cwd is never overwritten
    (``_UPSERT_KEEP_EXISTING_SQL`` COALESCE semantics). SSH workspaces are
    skipped: session queries fail closed for them anyway.
    """
    conversation_id = str(conversation_id or "").strip()
    workspace = str(workspace or "").strip()
    if not conversation_id or not workspace or workspace.startswith("ssh://"):
        return
    with _open_db(home) as db:
        db.ensure_session(conversation_id, "api_server", cwd=workspace)


def persist_session_attachments(
    home: str | Path, conversation_id: str, content: Any,
) -> Any:
    """Persist image data URLs before a user transcript row can reference them."""
    if not isinstance(content, list):
        return content
    root = Path(home).expanduser().resolve() / "attachments"
    result = []
    for block in content:
        item = dict(block) if isinstance(block, dict) else block
        image = item.get("image_url") if isinstance(item, dict) else None
        url = image.get("url") if isinstance(image, dict) else None
        if not isinstance(url, str) or not url.startswith("data:image/"):
            result.append(item)
            continue
        try:
            header, encoded = url.split(",", 1)
            media_type = header[5:].split(";", 1)[0]
            if not media_type.startswith("image/") or ";base64" not in header:
                raise ValueError("unsupported attachment encoding")
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid image attachment") from exc
        digest = hashlib.sha256(payload).hexdigest()
        destination = root / digest[:2] / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError("existing durable image attachment failed integrity verification")
        else:
            fd, temporary = tempfile.mkstemp(prefix=".attachment-", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if destination.exists():
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        raise ValueError("existing durable image attachment failed integrity verification")
                else:
                    os.replace(temporary, destination)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary)
        item["image_url"] = {
            "url": f"atlas-attachment://{digest}", "media_type": media_type,
            _ATTACHMENT_REF_KEY: True,
        }
        result.append(item)
    return result


def resolve_session_attachments(
    home: str | Path, conversation_id: str, messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve and SHA-256 verify immutable image refs whenever model history is read."""
    root = Path(home).expanduser().resolve() / "attachments"
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            image = block.get("image_url") if isinstance(block, dict) else None
            ref = image.get("url") if isinstance(image, dict) else None
            if not isinstance(ref, str) or not ref.startswith("atlas-attachment://"):
                continue
            digest = ref.removeprefix("atlas-attachment://")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise SessionAttachmentIntegrityError("invalid durable image attachment reference")
            try:
                payload = (root / digest[:2] / digest).read_bytes()
            except OSError as exc:
                raise SessionAttachmentIntegrityError(
                    "durable image attachment is missing or unreadable"
                ) from exc
            if hashlib.sha256(payload).hexdigest() != digest:
                raise SessionAttachmentIntegrityError(
                    "durable image attachment failed integrity verification"
                )
            media_type = str(image.get("media_type") or "image/png")
            image["url"] = f"data:{media_type};base64,{base64.b64encode(payload).decode('ascii')}"
            image.pop("media_type", None)
            image.pop(_ATTACHMENT_REF_KEY, None)
    return messages


def record_file_observation(
    home: str | Path, conversation_id: str, path: str, token: dict[str, Any],
) -> None:
    """Persist the last provider version token under its owning session and path."""
    key = "fs-observation:" + hashlib.sha256(
        f"{conversation_id}\0{path}".encode("utf-8")
    ).hexdigest()
    with _open_db(home) as db:
        db.set_meta(key, json.dumps({"session_id": conversation_id, "path": path, "token": token}))


def get_file_observation(
    home: str | Path, conversation_id: str, path: str,
) -> dict[str, Any] | None:
    key = "fs-observation:" + hashlib.sha256(
        f"{conversation_id}\0{path}".encode("utf-8")
    ).hexdigest()
    with _open_db(home) as db:
        raw = db.get_meta(key)
    if not raw:
        return None
    value = json.loads(raw)
    return value.get("token") if value.get("session_id") == conversation_id and value.get("path") == path else None


def begin_session_compaction(
    home: str | Path, conversation_id: str, holder: str, *, ttl_seconds: float = 300.0,
) -> int:
    """Acquire the canonical SessionDB compaction lease and capture its start watermark."""
    with _open_db(home) as db:
        if not db.try_acquire_compression_lock(conversation_id, holder, ttl_seconds):
            raise RuntimeError("SessionDB compaction is already active for this conversation")
        try:
            watermark = int(db.get_active_message_watermark(conversation_id))
            db.append_session_event(conversation_id, "compaction/start", {
                "holder": holder, "watermark": watermark,
            })
            return watermark
        except BaseException:
            db.release_compression_lock(conversation_id, holder)
            raise


def abort_session_compaction(home: str | Path, conversation_id: str, holder: str) -> None:
    """Release an acquired compaction lease when preparation or publication fails."""
    with _open_db(home) as db:
        try:
            db.append_session_event(conversation_id, "compaction/end", {
                "holder": holder, "reason": "aborted",
            })
        finally:
            db.release_compression_lock(conversation_id, holder)


def compact_session_messages(
    home: str | Path, conversation_id: str, holder: str, watermark: int,
    held_messages: list[dict[str, Any]], compacted_messages: list[dict[str, Any]], *,
    tail_count: int = 0, carried_messages: list[dict[str, Any]] | None = None,
    snapshot_state: dict[str, Any] | None = None,
) -> int:
    """Publish model compaction and its recoverable snapshot atomically.

    ``snapshot_state`` carries runtime boundary fields that are not part of the
    user-facing transcript (for example plan/todo state and pending tool-call IDs).
    The generated snapshot manifest is stored in display metadata on the summary
    message, in the same SessionDB transaction that archives the old transcript.
    """
    from atlas.engine.agent.conversation_compression_archive import coverage_for_commit
    from atlas.engine.agent.context_compressor import stamp_db_persisted_markers

    import hashlib

    summary = next((item for item in compacted_messages
                    if item.get("_compressed_summary") or (
                        item.get("role") == "user" and isinstance(item.get("content"), str)
                        and item["content"].startswith("[Conversation continuation summary]"))), None)
    if summary is not None:
        summary_text = str(summary.get("content") or "")
        source_ids = [str(item.get("message_uid") or item.get("id") or item.get("_row_id"))
                      for item in held_messages
                      if item.get("message_uid") or item.get("id") or item.get("_row_id") is not None]
        manifest = {
            "schema_version": _SESSION_SNAPSHOT_SCHEMA,
            "kind": "context_compaction",
            "created_at": datetime.now(UTC).isoformat(),
            "method": "summary",
            "boundary_watermark": int(watermark),
            "source_message_count": len(source_ids),
            "source_first_message_id": source_ids[0] if source_ids else None,
            "source_last_message_id": source_ids[-1] if source_ids else None,
            "summary_sha256": hashlib.sha256(summary_text.encode("utf-8")).hexdigest(),
            "summary_chars": len(summary_text),
            "state": dict(snapshot_state or {}),
        }
        display_metadata = dict(summary.get("display_metadata") or {})
        display_metadata[_SESSION_SNAPSHOT_KEY] = manifest
        summary["display_metadata"] = display_metadata

    with _open_db(home) as db:
        try:
            if not db.refresh_compression_lock(conversation_id, holder):
                raise RuntimeError("SessionDB compaction lease expired before publication")
            covered_ids, unresolved_held = coverage_for_commit(
                db, conversation_id, held_messages,
            )
            count = db.archive_and_compact(
                conversation_id, compacted_messages, watermark=watermark,
                lock_holder=holder, tail_count=tail_count,
                carried_messages=carried_messages,
                covered_ids=covered_ids, unresolved_held=unresolved_held,
            )
            stamp_db_persisted_markers(compacted_messages)
            return int(count)
        except BaseException:
            with suppress(Exception):
                db.append_session_event(conversation_id, "compaction/end", {
                    "holder": holder, "reason": "aborted",
                })
            raise
        finally:
            db.release_compression_lock(conversation_id, holder)


def detect_orphaned_compactions(home: str | Path, conversation_id: str) -> list[dict[str, Any]]:
    """Return durable ``compaction/start`` brackets with no matching ``compaction/end``.

    Read-only projection over the session event log. A start without an end for
    the same holder means the run died between lease acquisition and publication
    (crash, kill, power loss) — the lease TTL will expire on its own, but the
    orphan is detectable from the transcript instead of inferred from lock rows.
    """
    with _open_db(home) as db:
        events = db.list_session_events(conversation_id, after_seq=0, limit=10_000)
    open_brackets: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = str(event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        holder = str(payload.get("holder") or "")
        if kind == "compaction/start" and holder:
            open_brackets[holder] = {
                "holder": holder,
                "watermark": payload.get("watermark"),
                "start_seq": event.get("seq"),
            }
        elif kind == "compaction/end" and holder:
            open_brackets.pop(holder, None)
    return list(open_brackets.values())


def restore_session_snapshot(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    """Restore from the newest durable summary snapshot plus following active rows.

    SessionDB compaction leaves one active continuation-summary row and the
    post-boundary tail. This projection starts at that row rather than replaying
    archived transcript generations. Legacy summaries without a manifest remain
    resumable and are surfaced with ``legacy=True``.
    """
    messages = read_session_model_messages(home, conversation_id)
    anchor = None
    manifest: dict[str, Any] | None = None
    legacy = False
    for index, message in enumerate(messages):
        metadata = message.get("display_metadata")
        candidate = metadata.get(_SESSION_SNAPSHOT_KEY) if isinstance(metadata, dict) else None
        if isinstance(candidate, dict):
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("Invalid session snapshot: summary content is not text")
            if not _valid_session_snapshot_manifest(candidate, content):
                raise ValueError("Invalid session snapshot: manifest integrity check failed")
            anchor, manifest, legacy = index, dict(candidate), False
        elif message.get("_compressed_summary"):
            anchor, manifest, legacy = index, None, True
    if anchor is None:
        return None
    return {
        "snapshot": manifest,
        "snapshot_message": dict(messages[anchor]),
        "messages": [dict(item) for item in messages[anchor:]],
        "post_snapshot_count": max(0, len(messages) - anchor - 1),
        "legacy": legacy,
    }


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


def append_session_event(
    home: str | Path, conversation_id: str, event_type: str, payload: dict[str, Any],
) -> int:
    """Append one durable lifecycle event without changing transcript messages."""
    with _open_db(home) as db:
        return db.append_session_event(conversation_id, event_type, payload)


def read_session_events(
    home: str | Path, conversation_id: str, *, after_seq: int = 0, limit: int = 1000,
) -> list[dict[str, Any]]:
    """Close stale turns on read, then return lifecycle events without transcript rewrites."""
    with _open_db(home) as db:
        events = db.list_session_events(conversation_id, after_seq=0, limit=10_000)
    open_turns: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload") or {}
        turn_id = str(payload.get("turn_id") or "")
        if not turn_id:
            continue
        if event.get("event_type") == "turn/start":
            open_turns[turn_id] = event
        elif event.get("event_type") == "turn/end":
            open_turns.pop(turn_id, None)
    stale_turns = {
        turn_id for turn_id, opened in open_turns.items()
        if (conversation_id, turn_id) not in _ACTIVE_SESSION_TURNS
        and not _turn_process_is_alive(opened.get("payload") or {})
    }
    if stale_turns:
        with _open_db(home) as db:
            db.repair_interrupted_turns(conversation_id, stale_turns)
    with _open_db(home) as db:
        return db.list_session_events(conversation_id, after_seq=after_seq, limit=limit)


def _turn_process_is_alive(payload: dict[str, Any]) -> bool:
    """Avoid repairing a live turn; PID reuse is rejected by its process creation token."""
    pid = payload.get("process_id")
    started = payload.get("process_started_at")
    if type(pid) is not int or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if not isinstance(started, (int, float)):
        return False
    try:
        import psutil

        return abs(psutil.Process(pid).create_time() - float(started)) < 0.01
    except Exception as exc:
        # Access denied is not evidence that the owner died; missing and reused PIDs are.
        if type(exc).__name__ == "AccessDenied":
            return True
        return False


def latest_session_message(
    home: str | Path, conversation_id: str, *, role: str | None = None,
) -> dict[str, Any] | None:
    """Latest message (Atlas shape) of one session, optionally filtered by role.

    同一套稳定 ID 体系：返回的 ``id`` 是 SessionDB ``message_uid``（legacy 行
    回落 row id），与 :func:`latest_session_message_id` / run_drive 的
    ``done.message_id`` 同源 —— UM02/T02.2 真实捕获（memory.capture）用它在
    消息持久化之后取稳定 ID + 原文 + 发生时间，不另造第二套 ID。

    压缩摘要行（``_compressed_summary``）不是真实发言，显式跳过：只有 summary
    时不得伪装成有原话（原消息行保留在 SessionDB 中，原始捕获在原消息层早已
    完成，不受压缩影响）。
    """
    with _open_db(home) as db:
        messages = db.get_messages(conversation_id, limit=50, latest=True, include_compacted=True)
    for message in reversed(messages):
        if message.get("_compressed_summary"):
            continue
        if role is None or message.get("role") == role:
            return _message_for_atlas(message)
    return None


def update_session_assistant_message(
    home: str | Path, conversation_id: str, message_id: str, *,
    content: str, metadata_patch: dict[str, Any],
) -> bool:
    """Attach presentation metadata to a persisted assistant message without changing model history."""
    with _open_db(home) as db:
        return bool(db.update_message_content_and_metadata(
            conversation_id, message_id, content=content, metadata_patch=metadata_patch,
        ))


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
    role = str(role or "").strip()
    if role not in _TRANSCRIPT_ROLES:
        raise ValueError(f"Unsupported transcript role: {role or '(empty)'}")
    if not str(conversation_id or "").strip():
        raise ValueError("conversation_id must not be empty")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("message metadata must be an object")
    with _open_db(home) as db:
        if db.get_session(conversation_id) is None:
            db.ensure_session(conversation_id, "api_server")
        values = dict(metadata or {})
        formal_fields = (
            "tool_name", "tool_calls", "tool_call_id", "token_count", "finish_reason",
            "reasoning", "reasoning_content", "reasoning_details", "codex_reasoning_items",
            "codex_message_items", "platform_message_id", "observed", "effect_disposition",
            "_compressed_summary", "timestamp", "api_content", "display_kind",
        )
        append_fields = {key: values.pop(key) for key in formal_fields if key in values}
        message_id = db.append_message(
            conversation_id, role, content=content, display_metadata=values or None,
            **append_fields,
        )
        messages = db.get_messages(conversation_id, limit=1, latest=True)
        latest = messages[-1] if messages else {}
        return str(latest.get("message_uid") or message_id)


def append_user_message_before_model(
    home: str | Path, conversation_id: str, content: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Synchronously commit a user turn before its first model request.

    ``append_session_message`` returns only after the SessionDB write transaction
    commits. Keep this deliberately synchronous: callers must await/finish it before
    starting a model request, so a killed process remains resumable from the prompt.
    """
    return append_session_message(home, conversation_id, "user", content, metadata)


def append_session_messages(
    home: str | Path, conversation_id: str, messages: list[dict[str, Any]],
) -> list[str]:
    """Append an ordered assistant/tool event batch in one durable transaction.

    This is intended for the assistant tool-call message and its tool results when
    they are already available together. For streaming events use
    :func:`append_session_message` in event order; each call commits before returning.
    The returned IDs follow input order and are the DB row IDs assigned by SessionDB.
    """
    if not messages:
        return []
    if not str(conversation_id or "").strip():
        raise ValueError("conversation_id must not be empty")
    for index, source in enumerate(messages):
        if not isinstance(source, dict):
            raise ValueError(f"session transcript event {index} must be an object")
        role = str(source.get("role") or "").strip()
        if role not in _TRANSCRIPT_ROLES:
            raise ValueError(f"Unsupported transcript role at event {index}: {role or '(empty)'}")
        if "content" not in source:
            raise ValueError(f"session transcript event {index} requires content")
    with _open_db(home) as db:
        if db.get_session(conversation_id) is None:
            db.ensure_session(conversation_id, "api_server")
        rows: list[dict[str, Any]] = []
        for source in messages:
            item = dict(source)
            role = str(item.pop("role", "")).strip()
            item["role"] = role
            item["display_metadata"] = dict(item.pop("display_metadata", {}) or {})
            item["display_metadata"].update(dict(item.pop("metadata", {}) or {}))
            rows.append(item)
        db.append_messages_batch(conversation_id, rows)
        return [str(item.get("message_uid") or item.get("_row_id") or "") for item in rows]


def list_session_previews(home: str | Path, *, limit: int = 1000) -> dict[str, str]:
    with _open_db(home) as db:
        sessions = db.cached_read(
            "session_previews",
            (limit,),
            lambda: [
                {"id": str(item["id"]), "preview": str(item.get("preview") or "")}
                for item in db.list_sessions_rich(
                    limit=limit, include_children=True, include_archived=True, include_hidden=True,
                    project_compression_tips=False,
                )
            ],
        )
    return {item["id"]: item["preview"] for item in sessions}


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
    is replaced. Existing Atlas session IDs remain authoritative and are counted as ignored.
    The caller owns startup health state and user-facing failure notification.
    """
    from atlas.config import get_config

    atlas_path = Path(get_config().db_path)
    atlas_path = Path(home).expanduser().resolve() / "state.db"
    begin_session_migration(atlas_path.parent)
    stage_dir: Path | None = None
    settled = False
    phase = "preflight"
    try:
        # T01.3：经 MemoryStore 公开只读方法取 DISTINCT 会话清单
        # （authority-map 1.0，不再直摸 memory_store._db）。
        atlas_ids = {str(cid) for cid in await memory_store.list_conversation_ids()}
        original_session_ids = _existing_session_ids(atlas_path)
        pending_ids = atlas_ids - original_session_ids
        ignored_existing = len(atlas_ids & original_session_ids)
        if not pending_ids:
            finish_session_migration(atlas_path.parent, "ready")
            settled = True
            return MigrationReport("ready", ignored_existing_sessions=ignored_existing)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backups = Path(backup_root) if backup_root else atlas_path.parent / "backup" / timestamp
        phase = "backup"
        atlas_path.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=".session-migration-", dir=atlas_path.parent))
        stage_db = stage_dir / "state.db"
        backups = backups / timestamp if backup_root else backups
        backups.mkdir(parents=True, exist_ok=False)
        _copy_sqlite_backup(atlas_path, backups / "atlas.sqlite3")
        _copy_sqlite_backup(atlas_path, backups / "state.db")
        _copy_sqlite_backup(atlas_path, stage_db)
        phase = "import"
        conversations = await memory_store.list_conversations(limit=None)
        from atlas.engine.state.atlas_state import SessionDB

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
                finish_session_migration(atlas_path.parent, "ready")
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
        _publish_staged_database(stage_db, atlas_path, stage_dir)
        finish_session_migration(atlas_path.parent, "ready")
        settled = True
        return MigrationReport(
            "ready", imported, imported_messages,
            ignored_existing_sessions=staged_ignored_existing,
        )
    except asyncio.CancelledError:
        finish_session_migration(atlas_path.parent, "failed")
        settled = True
        raise
    except (OSError, sqlite3.Error, RuntimeError, ValueError, TypeError, KeyError) as exc:
        finish_session_migration(atlas_path.parent, "failed")
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
            finish_session_migration(atlas_path.parent, "failed")
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
            raise RuntimeError(f"Atlas session restore failed: {result.get('errors', result)}")


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
        prefix = transcript[:stop]
        if prefix and _has_open_turn(prefix):
            raise ValueError("Cannot fork a session through an open turn")
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
            "messages": ([preamble] if preamble else []) + prefix,
        }
        result = db.import_sessions(
            [cloned],
            session_events=[{
                "session_id": fork_id,
                "event_type": "session/end-seed",
                "payload": {
                    "inherited": True,
                    "source_session_id": source_id,
                    "source_message_count": len(prefix),
                },
            }],
        )
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Atlas session fork failed: {result.get('errors', result)}")


def _has_open_turn(messages: list[dict[str, Any]]) -> bool:
    """Whether a transcript prefix ends before its assistant turn is complete.

    Tool calls are paired by call id because multiple calls can be outstanding in
    one assistant message and their results can arrive in any order. A completed
    turn also needs an assistant response after the last user/tool result.
    """
    pending: set[str] = set()
    last_role: str | None = None
    for message in messages:
        role = str(message.get("role") or "")
        if role == "assistant":
            raw_calls = message.get("tool_calls") or []
            if isinstance(raw_calls, str):
                try:
                    raw_calls = json.loads(raw_calls)
                except (TypeError, ValueError):
                    raw_calls = []
            if isinstance(raw_calls, list):
                for call in raw_calls:
                    if isinstance(call, dict) and call.get("id"):
                        pending.add(str(call["id"]))
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if call_id:
                pending.discard(call_id)
        if role not in {"system", "developer"}:
            last_role = role
    return bool(pending) or last_role != "assistant"


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


def goal_command(
    home: str | Path, conversation_id: str, command: str, *,
    expected_goal_id: str | None = None, expected_revision: int | None = None,
) -> dict[str, Any]:
    """Apply Atlas per-session /goal command and return its continuation prompt."""
    from atlas.engine.goal_command import GoalCommandResult, dispatch_goal_command, is_goal_control
    from atlas.engine.goals import GoalManager, GoalRevisionConflict

    manager = GoalManager(conversation_id, home=home)
    previous = manager.state
    try:
        if expected_goal_id is not None or expected_revision is not None:
            manager.check_revision(expected_goal_id, expected_revision)
        result = dispatch_goal_command(
            manager, command, authorize_gate=lambda: "Goal gates require explicit approval.")
    except GoalRevisionConflict as exc:
        result = GoalCommandResult(str(exc), error=True)
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
                  "max_turns": state.max_turns, "subgoals": state.subgoals,
                  "completed_subgoals": state.completed_subgoals,
                  "goal_id": state.goal_id, "revision": state.revision}
                 if state is not None else None),
    }


def evaluate_goal_after_turn(
    home: str | Path, conversation_id: str, response: str, judge=None,
) -> dict[str, Any]:
    """Evaluate the persisted per-session goal after an assistant turn."""
    from atlas.engine.goals import GoalManager

    manager = GoalManager(conversation_id, home=home)
    if not manager.is_active():
        return {"status": manager.state.status if manager.state else None,
                "should_continue": False, "continuation_prompt": None,
                "verdict": "inactive", "message": ""}
    return manager.evaluate_after_turn(response or "", judge=judge)


def goal_state(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    """Return the persisted goal state for a conversation or automation session."""
    from atlas.engine.goals import GoalManager

    state = GoalManager(conversation_id, home=home).state
    return json.loads(state.to_json()) if state is not None else None


def set_goal(home: str | Path, conversation_id: str, goal: str) -> dict[str, Any]:
    """Create or replace a goal in the per-session state store."""
    from atlas.engine.goals import GoalManager

    manager = GoalManager(conversation_id, home=home)
    state = manager.set(goal)
    return json.loads(state.to_json())


def mutate_goal(
    home: str | Path, conversation_id: str, action: str, reason: str = "user-paused",
) -> dict[str, Any] | None:
    """Apply a per-session done, pause, resume, or clear action."""
    from atlas.engine.goals import GoalManager

    manager = GoalManager(conversation_id, home=home)
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
    """Append audit-only goal history in SessionDB state metadata."""
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
    """Read audit-only goal events from SessionDB state metadata."""
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
