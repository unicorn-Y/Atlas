"""Read and search the canonical conversation transcript by provenance pointer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


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
    ref: str,
    window: int = 1,
    *,
    engine_root: str | Path | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    from .source_ref import SourceRef

    exact = None
    raw_ref = str(ref or "")
    if raw_ref.startswith("atlas://"):
        try:
            exact = SourceRef.from_ref(raw_ref)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "出处格式无效", "precision": "exact"}
        session, stamp = exact.conversation_id, ""
        sep = "@"
    else:
        session, sep, stamp = raw_ref.rpartition("@")
    if not sep or not session:
        try:
            from atlas.memory.library import get_library

            library = get_library()
            found = library.store.find_entry(str(ref).split(",", 1)[0]) if library else None
            if found and found[1].ref:
                return open_ref(found[1].ref, window, engine_root=engine_root, root=root)
        except (OSError, RuntimeError, ValueError):
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
    users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if not users:
        return {"ok": False, "reason": "原对话已删除"}
    if exact is not None:
        selected = next((i for i, message in enumerate(messages)
                         if str(message.get("id") or "") == exact.message_uid), None)
        if selected is None:
            return {"ok": False, "reason": "原消息已删除或不存在", "precision": "exact",
                    "conversation_id": session, "message_uid": exact.message_uid}
        user_pos = max((position for position, message_index in enumerate(users)
                        if message_index <= selected), default=-1)
        if user_pos < 0:
            return {"ok": False, "reason": "出处消息之前没有用户轮次", "precision": "exact",
                    "conversation_id": session, "message_uid": exact.message_uid}
    else:
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
        user_pos = users.index(selected)
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
    for row in selected_messages:
        role = str(row.get("role") or "unknown")
        text = _text(row.get("content", row.get("text")))
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
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
            {"role": role, "text": text, "at": _at(row), **({"tool": tool} if tool else {})}
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
        "precision": "exact" if exact is not None else "approximate",
        **({"conversation_id": session, "message_uid": exact.message_uid} if exact else {}),
        "title": title,
        "messages": result,
        "truncated": truncated,
    }


def _parse_at(message: dict[str, Any]) -> datetime | None:
    stamp = _at(message)
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def iter_search_raw(query: str):
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import search_session_messages

    page_size = 50
    offset = 0
    while True:
        try:
            batch = search_session_messages(DATA_ROOT / "engine", query, limit=page_size, offset=offset)
        except (OSError, RuntimeError, ValueError):
            return
        yield from batch
        offset += len(batch)
        if len(batch) < page_size:
            break


def _raw_result(row: dict[str, Any]) -> dict[str, Any] | None:
    from .source_ref import SourceRef

    try:
        ref = SourceRef(str(row.get("conversation_id") or ""), str(row.get("id") or "")).to_ref()
    except ValueError:
        return None
    return {
        "id": str(row.get("id") or ""), "kind": "raw", "path": "原对话",
        "title": str(row.get("conversation_id") or ""),
        "text": str(row.get("content") or ""),
        "snippet": str(row.get("snippet") or row.get("content") or ""),
        "src": "原对话", "at": str(row.get("created_at") or ""), "ref": ref,
        "precision": "exact", "score": 1.0, "project": "",
    }


def search_raw(query: str, limit: int = 10) -> list[dict[str, Any]]:
    from . import get_library

    library = get_library()
    results = []
    for row in iter_search_raw(query):
        result = _raw_result(row)
        if result is not None and not (library and library.store.source_tombstoned(result["ref"])):
            results.append(result)
            if len(results) >= max(1, limit):
                break
    return results


__all__ = ["open_ref", "search_raw", "iter_search_raw", "_raw_result"]
