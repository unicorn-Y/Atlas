"""Runtime adapters between memory recall and delegated Atlas workers.

The memory library and SessionDB remain the authorities. This module only
builds bounded dispatch context and returns pointers to a retained child
SessionDB message; it never stores transcript text.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas.memory.library.source_ref import SourceRef

_MAX_CONTEXT_CHARS = 2400
_MAX_HITS = 4
_MAX_HIT_CHARS = 360


def prepare_delegation_context(
    *, goal: str, context: str | None, cwd: str | None, subtask_id: str,
    parent_conversation_id: str | None = None, library: Any | None = None,
) -> dict[str, Any]:
    """Append a small, task-relevant M5 recall block to a child task context."""
    original = str(context or "").strip()
    query = "\n".join(part for part in (str(goal or "").strip(), original) if part)
    result: dict[str, Any] = {
        "context": original,
        "claim_ids": [],
        "source_refs": [],
        "memory_available": False,
        "memory_error": None,
    }
    if not query:
        return result

    if library is None:
        try:
            from atlas.memory.library import get_library

            library = get_library()
        except Exception as exc:  # Memory is an optional enhancement to dispatch.
            result["memory_error"] = type(exc).__name__
            return result
    if library is None:
        return result

    invocation = f"delegation:{parent_conversation_id or 'unknown'}:{subtask_id}"
    try:
        hits = library.search(
            query, limit=_MAX_HITS, kinds=("fact", "dream", "episode", "diary"),
            invocation_id=invocation,
        )
    except Exception as exc:  # A recall outage must not block the delegated task.
        result["memory_error"] = type(exc).__name__
        return result

    lines: list[str] = []
    refs: list[str] = []
    claim_ids: list[str] = []
    for hit in hits[:_MAX_HITS]:
        if not isinstance(hit, dict):
            continue
        claim_id = str(hit.get("claim_id") or hit.get("id") or "").strip()
        text = " ".join(str(hit.get("text") or "").split())[:_MAX_HIT_CHARS]
        pointer: str | None = None
        source = hit.get("source_ref")
        try:
            if isinstance(source, dict):
                pointer = SourceRef(**source).to_ref()
            elif isinstance(hit.get("ref"), str) and str(hit["ref"]).startswith("atlas://source/"):
                pointer = SourceRef.from_ref(str(hit["ref"])).to_ref()
        except (TypeError, ValueError):
            pointer = None
        if not text or not pointer:
            continue
        level = str(hit.get("source_level") or "legacy_unknown")
        lines.append(f"- [{claim_id or 'memory'}; {level}] {text}\n  ref: {pointer}")
        refs.append(pointer)
        if claim_id:
            claim_ids.append(claim_id)

    result.update({
        "claim_ids": claim_ids,
        "source_refs": refs,
        "memory_available": True,
    })
    block_lines = [f"当前工作目录：{cwd}" if cwd else "当前工作目录：未提供"]
    block_lines.append("Atlas 记忆（按当前子任务检索；只作有来源的参考）：")
    block_lines.extend(lines or ["本次检索没有返回可引用的 Claim。"])
    block_lines.append(
        "需要更多上下文时可调用 memory_search 查询；用返回的 ref 通过 memory_search 的 open 参数按需展开。"
    )
    addition = "\n".join(block_lines)[:_MAX_CONTEXT_CHARS]
    result["context"] = f"{original}\n\n{addition}" if original else addition
    return result


def source_refs_for_result(
    *, child_conversation_id: str | None, terminal_message_uid: str | None,
    engine_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return an exact child SourceRef only while its SessionDB row still exists."""
    conversation_id = str(child_conversation_id or "").strip()
    message_uid = str(terminal_message_uid or "").strip()
    if not conversation_id or not message_uid:
        return []
    try:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import session_message_evidence

        home = Path(engine_root) if engine_root is not None else DATA_ROOT / "engine"
        evidence = session_message_evidence(home, conversation_id, message_uid)
        if not evidence:
            return []
        ref = SourceRef(
            conversation_id=conversation_id,
            message_uid=str(evidence.get("message_uid") or message_uid),
            observed_role=str(evidence.get("role") or "") or None,
            observed_at=str(evidence.get("timestamp") or "") or None,
        )
        return [ref.to_dict()]
    except Exception:  # A missing/unreadable source must never be replaced by a guess.
        return []


def capture_delegation_result(
    *, parent_conversation_id: str | None, child_conversation_id: str | None,
    terminal_message_uid: str | None, status: str, started_at: str,
    ended_at: str | None = None, tool_summaries: list[dict[str, Any]] | None = None,
    engine_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build lightweight, deduplicable result metadata without copying child text."""
    child_id = str(child_conversation_id or "").strip() or None
    terminal_id = str(terminal_message_uid or "").strip() or None
    parent_id = str(parent_conversation_id or "").strip() or None
    end = ended_at or datetime.now(timezone.utc).isoformat()
    refs = source_refs_for_result(
        child_conversation_id=child_id, terminal_message_uid=terminal_id,
        engine_root=engine_root,
    )
    identity = "\x1f".join((parent_id or "", child_id or "", terminal_id or ""))
    event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest() if all(
        (parent_id, child_id, terminal_id)
    ) else None
    return {
        "event_id": event_id,
        "parent_conversation_id": parent_id,
        "child_conversation_id": child_id,
        "terminal_message_uid": terminal_id,
        "started_at": started_at,
        "ended_at": end,
        "status": str(status or "failed"),
        "source_refs": refs,
        "source_available": bool(refs),
        "source_missing_reason": None if refs else (
            "child_session_not_retained_or_terminal_message_missing"
        ),
        "tool_summaries": [
            {key: item.get(key) for key in ("message_uid", "tool_name", "is_error")}
            for item in (tool_summaries or []) if isinstance(item, dict)
        ],
    }


__all__ = [
    "capture_delegation_result",
    "prepare_delegation_context",
    "source_refs_for_result",
]
