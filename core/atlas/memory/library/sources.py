"""Read and search the canonical conversation transcript by provenance pointer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from atlas.memory.library.source_ref import SourceRef

RAW_SNIPPET_MAX_CHARS = 320


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text") or item) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _at(message: dict[str, Any]) -> str:
    return str(message.get("created_at") or message.get("timestamp") or message.get("at") or "")


def open_ref(
    ref: SourceRef | str | Mapping[str, Any],
    window: int = 1,
    *,
    engine_root: str | Path | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    try:
        exact: SourceRef | None = (
            ref if isinstance(ref, SourceRef)
            else SourceRef(**dict(ref)) if isinstance(ref, Mapping)
            else None
        )
    except (TypeError, ValueError):
        return {"ok": False, "reason": "出处格式无效", "precision": "exact"}
    raw_ref = exact.to_ref() if exact is not None else str(ref or "")
    if exact is None and raw_ref.startswith("atlas://"):
        try:
            exact = SourceRef.from_ref(raw_ref)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "出处格式无效", "precision": "exact"}
    if exact is not None:
        session, stamp = exact.conversation_id, ""
    else:
        session, sep, stamp = raw_ref.rpartition("@")
        if not sep or not session:
            try:
                from atlas.memory.library import get_library

                library = get_library()
                found = library.store.find_entry(raw_ref.split(",", 1)[0]) if library else None
                if found and found[1].source_ref:
                    exact = SourceRef(**found[1].source_ref)
                    return open_ref(exact, window, engine_root=engine_root, root=root)
                if found and found[1].ref:
                    return open_ref(found[1].ref, window, engine_root=engine_root, root=root)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
            return {"ok": False, "reason": "出处格式无效"}
    if engine_root is None:
        engine_root = Path(root) if root else None
    if engine_root is None:
        from atlas.config import DATA_ROOT

        engine_root = DATA_ROOT / "engine"
    from atlas.engine.session_sync import list_session_previews, read_session_all_messages

    try:
        messages = read_session_all_messages(engine_root, session)
    except (FileNotFoundError, KeyError, ValueError, OSError):
        messages = []
    if not messages:
        return {"ok": False, "reason": "原对话已删除"}
    if exact is not None:
        anchor = next((i for i, message in enumerate(messages)
                       if str(message.get("id") or "") == exact.message_uid), None)
        if anchor is None and exact.tool_call_id:
            def has_tool_call(message: dict[str, Any]) -> bool:
                metadata = message.get("metadata")
                if not isinstance(metadata, dict):
                    return False
                if str(metadata.get("tool_call_id") or "") == exact.tool_call_id:
                    return True
                calls = metadata.get("tool_calls")
                return isinstance(calls, list) and any(
                    isinstance(call, dict) and str(call.get("id") or "") == exact.tool_call_id
                    for call in calls
                )

            anchor = next((i for i, message in enumerate(messages) if has_tool_call(message)), None)
        if anchor is None:
            return {"ok": False, "reason": "原消息已删除或不存在", "precision": "exact",
                    "source_ref": exact.to_ref(), "conversation_id": session,
                    "message_uid": exact.message_uid}
        precision = "exact"
        selected = anchor
    else:
        users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
        if not users:
            return {"ok": False, "reason": "原对话已删除", "precision": "approximate"}
        precision = "approximate"
        try:
            target = datetime.fromisoformat(stamp)
            def distance(index: int) -> float:
                message_time = _parse_at(messages[index])
                if message_time is None:
                    return float("inf")
                if message_time.tzinfo is None and target.tzinfo is not None:
                    message_time = message_time.replace(tzinfo=target.tzinfo)
                elif target.tzinfo is None and message_time.tzinfo is not None:
                    message_time = message_time.replace(tzinfo=None)
                return abs((message_time - target).total_seconds())

            selected = min(users, key=distance)
        except (TypeError, ValueError):
            selected = users[-1]
    users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if not users:
        if exact is None:
            return {"ok": False, "reason": "原对话已删除", "precision": precision}
        start, end = selected, selected + 1
    else:
        user_pos = max((pos for pos, idx in enumerate(users) if idx <= selected), default=0)
        radius = 1 if window >= 2 else 0
        start = users[max(0, user_pos - radius)]
        end = (
            users[min(len(users) - 1, user_pos + 1 + radius)]
            if user_pos + 1 + radius < len(users)
            else len(messages)
        )
    if end < len(messages) and messages[end].get("role") == "user":
        pass
    selected_messages = messages[start:end]
    total = 0
    truncated = False
    result = []
    target_full_text = ""
    span_applied = False
    for row in selected_messages:
        role = str(row.get("role") or "unknown")
        text = _text(row.get("content", row.get("text")))
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        is_target = bool(exact and (
            str(row.get("id") or "") == exact.message_uid
            or (exact.tool_call_id and (
                str(metadata.get("tool_call_id") or "") == exact.tool_call_id
                or any(isinstance(call, dict) and str(call.get("id") or "") == exact.tool_call_id
                       for call in (metadata.get("tool_calls") or []))
            ))
        ))
        full_text = text
        if is_target:
            target_full_text = full_text
            if (exact.span_start is not None and exact.span_end is not None
                    and exact.span_end <= len(full_text)):
                text = full_text[exact.span_start:exact.span_end]
                span_applied = True
        tool = None
        if role == "tool" or metadata.get("tool_name"):
            tool = {
                "name": metadata.get("tool_name", "tool"),
                "ok": not bool(metadata.get("is_error")),
                "args": metadata.get("tool_arguments"),
                "output": text[:2000],
            }
            text = text[:2000]
            if len(_text(row.get("content", row.get("text")))) > 2000:
                truncated = True
        remaining = 12000 - total
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        total += len(text)
        result.append(
            {"role": role, "text": text, "at": _at(row),
             "message_uid": str(row.get("id") or ""), "target": is_target,
             **({"tool": tool} if tool else {})}
        )
        calls = metadata.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else call
                name = str(function.get("name") or call.get("name") or "tool")
                args = function.get("arguments", call.get("arguments"))
                result.append(
                    {
                        "role": "tool_call",
                        "text": "",
                        "at": _at(row),
                        "tool": {"name": name, "ok": None, "args": args, "output": ""},
                    }
                )
    try:
        title = list_session_previews(engine_root, limit=10000).get(session, "")
    except Exception:  # noqa: BLE001 - title is optional; transcript availability is authoritative.
        title = ""
    return {
        "ok": True,
        "session": session,
        "conversation_id": session,
        **({"message_uid": exact.message_uid, "source_ref": exact.to_ref()}
           if exact is not None else {}),
        "precision": precision,
        **({"span_applied": span_applied} if exact is not None and exact.span_start is not None else {}),
        **({"content_hash_ok": (not exact.content_hash or hashlib.sha256(
            target_full_text.encode("utf-8")).hexdigest() == exact.content_hash)} if exact is not None else {}),
        "title": title,
        "messages": result,
        "truncated": truncated,
    }


def memory_open(
    ref: SourceRef | str | Mapping[str, Any],
    window: int = 1,
    *,
    engine_root: str | Path | None = None,
) -> dict[str, Any]:
    """Public read-only open API; legacy references remain visibly approximate."""
    return open_ref(ref, window, engine_root=engine_root)


def _parse_at(message: dict[str, Any]) -> datetime | None:
    stamp = _at(message)
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def search_raw(query: str, limit: int = 10) -> list[dict[str, Any]]:
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import search_session_messages

    try:
        found = search_session_messages(DATA_ROOT / "engine", query, limit=max(1, min(50, limit)))
    except (OSError, RuntimeError, ValueError):
        return []
    results = []
    for row in found:
        conversation_id = str(row.get("conversation_id") or "")
        message_uid = str(row.get("id") or "")
        # Session search returns a bounded match excerpt. Never substitute the
        # transcript/content field here: full messages are opened only by SourceRef.
        snippet = " ".join(str(row.get("snippet") or "").split())[:RAW_SNIPPET_MAX_CHARS]
        if not snippet:
            continue
        try:
            ref = SourceRef(conversation_id, message_uid).to_ref()
        except ValueError:
            continue
        results.append({
            "id": str(row.get("id") or ""),
            "kind": "raw",
            "path": "原对话",
            "title": conversation_id,
            "text": snippet,
            "snippet": snippet,
            "src": "原对话",
            "at": str(row.get("created_at") or ""),
            "ref": ref,
            "source_ref": SourceRef(conversation_id, message_uid).to_dict(),
            "score": 1.0,
            "project": "",
            "summary_kind": "matched_excerpt",
        })
    return results


__all__ = ["memory_open", "open_ref", "search_raw"]
