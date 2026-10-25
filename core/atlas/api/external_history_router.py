"""Read-only discovery and explicit import of Claude Code / Codex / OpenClaw transcripts."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import DATA_ROOT

router = APIRouter()
_history_import_lock = asyncio.Lock()


def _memory_service(services: AppServices) -> Any:
    memory = services.memory
    if memory is None:
        from atlas import server as atlas_server

        memory = atlas_server.memory
    if memory is None:
        raise HTTPException(status_code=503, detail="会话服务尚未就绪")
    return memory


@router.get("/api/import/external/history")
async def scan_external_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    source: str,
    days: int | None = None,
) -> dict[str, Any]:
    """List recent text-bearing sessions under the recognized local history roots."""
    del services  # The scan reads only the current user's recognized local roots.
    if source not in {"claude", "codex", "openclaw"}:
        raise HTTPException(status_code=422, detail="source must be claude, codex, or openclaw")
    from atlas.runtime.external_import import list_external_history

    try:
        return await asyncio.to_thread(list_external_history, source, days)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"扫描外部会话失败：{exc}") from exc


@router.post("/api/import/external/history/import")
async def import_external_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Import explicitly selected text turns through Memory + canonical SessionDB."""
    source = str(request.get("source") or "")
    if source not in {"claude", "codex", "openclaw"}:
        raise HTTPException(status_code=422, detail="source must be claude, codex, or openclaw")
    raw_keys = request.get("session_keys")
    if not isinstance(raw_keys, list) or any(not isinstance(key, str) for key in raw_keys):
        raise HTTPException(status_code=422, detail="session_keys must be an array of session keys")
    keys = list(dict.fromkeys(key for key in raw_keys if key))
    if len(keys) > 100 or any(len(key) != 64 or any(char not in "0123456789abcdef" for char in key) for key in keys):
        raise HTTPException(status_code=422, detail="每次最多导入 100 条有效会话")
    if not keys:
        raise HTTPException(status_code=422, detail="请至少选择一条会话")

    memory = _memory_service(services)
    from atlas.engine.session_sync import append_session_message, read_session_all_messages
    from atlas.runtime.external_import import (
        _history_index,
        _save_history_index,
        load_external_history,
    )

    try:
        scan = await asyncio.to_thread(load_external_history, source)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"读取外部会话失败：{exc}") from exc
    available = {session["key"]: session for session in scan["sessions"]}

    results: list[dict[str, Any]] = []
    imported_sessions = 0
    imported_messages = 0
    skipped = 0
    async with _history_import_lock:
        index = await asyncio.to_thread(_history_index)
        receipts = index["sessions"]
        for key in keys:
            session = available.get(key)
            if session is None:
                skipped += 1
                results.append({"key": key, "status": "unavailable", "messages_imported": 0})
                continue
            receipt = receipts.get(key)
            if isinstance(receipt, dict) and receipt.get("completed"):
                existing_conversation = await memory.get_conversation(str(receipt.get("conversation_id") or ""))
                if existing_conversation is not None:
                    skipped += 1
                    results.append({
                        "key": key, "status": "already_imported",
                        "conversation_id": receipt.get("conversation_id"), "messages_imported": 0,
                    })
                    continue
                receipts.pop(key, None)

            added = 0
            conversation_id = ""
            try:
                conversation_id = str(receipt.get("conversation_id") or "") if isinstance(receipt, dict) else ""
                if not conversation_id or await memory.get_conversation(conversation_id) is None:
                    provider = {"claude": "Claude Code", "codex": "Codex", "openclaw": "OpenClaw"}[source]
                    conversation_id = await memory.create_conversation(f"{provider} · {session['title']}")
                    receipts[key] = {"conversation_id": conversation_id, "completed": False}
                    await asyncio.to_thread(_save_history_index, index)

                existing = await asyncio.to_thread(
                    read_session_all_messages, DATA_ROOT / "engine", conversation_id,
                )
                imported_keys = {
                    str((message.get("metadata") or {}).get("external_message_key") or "")
                    for message in existing
                }
                for message in session["messages"]:
                    message_key = message["external_message_key"]
                    if message_key in imported_keys:
                        continue
                    metadata: dict[str, Any] = {
                        "external_source": source,
                        "external_session_key": key,
                        "external_message_key": message_key,
                    }
                    if message.get("timestamp"):
                        metadata["timestamp"] = message["timestamp"]
                    await asyncio.to_thread(
                        append_session_message,
                        DATA_ROOT / "engine", conversation_id,
                        message["role"], message["content"], metadata,
                    )
                    imported_keys.add(message_key)
                    added += 1

                receipts[key] = {"conversation_id": conversation_id, "completed": True}
                await asyncio.to_thread(_save_history_index, index)
                imported_messages += added
                if added:
                    imported_sessions += 1
                    status = "imported"
                else:
                    skipped += 1
                    status = "already_imported"
                results.append({
                    "key": key, "status": status,
                    "conversation_id": conversation_id, "messages_imported": added,
                })
            except Exception as exc:
                skipped += 1
                imported_messages += added
                results.append({
                    "key": key, "status": "partial" if added else "failed",
                    "conversation_id": conversation_id or None, "messages_imported": added,
                    "error": str(exc)[:300],
                })

    return {
        "imported": imported_sessions,
        "messages_imported": imported_messages,
        "skipped": skipped,
        "results": results,
    }


@router.post("/api/import/external/jsonl/preview")
async def preview_jsonl_history(request: dict[str, Any]) -> dict[str, Any]:
    """Inspect one user-selected JSONL transcript without persisting its source."""
    content = request.get("content")
    fmt = str(request.get("format") or "auto")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content 必须是 UTF-8 文本")
    from atlas.runtime.history_adapters import inspect_jsonl, normalize_jsonl_messages

    try:
        inspected = inspect_jsonl(content, fmt)
        mapping = request.get("mapping") if isinstance(request.get("mapping"), dict) else None
        messages = normalize_jsonl_messages(content, inspected["format"], mapping)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    excerpts = [{"role": item["role"], "content": item["content"][:500], "timestamp": item.get("timestamp", "")}
                for item in messages[:8]]
    return {
        "format": inspected["format"], "detected_format": inspected["detected_format"],
        "available_fields": inspected["available_fields"], "mapping": inspected["mapping"],
        "record_count": inspected["record_count"], "invalid_lines": inspected["invalid_lines"],
        "file_key": inspected["file_key"], "message_count": len(messages), "preview": excerpts,
    }


@router.post("/api/import/external/jsonl/import")
async def import_jsonl_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Import a mapped Pi, Hermes, or Atlas CLI JSONL export as a new transcript."""
    content = request.get("content")
    fmt = str(request.get("format") or "auto")
    if not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content 必须是 UTF-8 文本")
    from atlas.runtime.history_adapters import inspect_jsonl, normalize_jsonl_messages

    try:
        inspected = inspect_jsonl(content, fmt)
        mapping = request.get("mapping") if isinstance(request.get("mapping"), dict) else None
        messages = normalize_jsonl_messages(content, inspected["format"], mapping)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not messages:
        raise HTTPException(status_code=422, detail="映射后没有 user/assistant 文本消息；请检查字段映射")
    file_key = inspected["file_key"]
    filename = str(request.get("filename") or "会话导入").replace("\\", "/").split("/")[-1][:160]
    memory = _memory_service(services)
    from atlas.engine.session_sync import append_session_message, read_session_all_messages
    from atlas.runtime.external_import import _history_index, _save_history_index

    async with _history_import_lock:
        index = await asyncio.to_thread(_history_index)
        receipt = index["jsonl"].get(file_key)
        if isinstance(receipt, dict) and receipt.get("completed"):
            conversation_id = str(receipt.get("conversation_id") or "")
            if conversation_id and await memory.get_conversation(conversation_id) is not None:
                return {"status": "already_imported", "conversation_id": conversation_id, "messages_imported": 0}
        conversation_id = str(receipt.get("conversation_id") or "") if isinstance(receipt, dict) else ""
        if not conversation_id or await memory.get_conversation(conversation_id) is None:
            conversation_id = await memory.create_conversation(f"{inspected['format']} · {filename}")
            index["jsonl"][file_key] = {
                "conversation_id": conversation_id, "completed": False,
                "format": inspected["format"], "filename": filename,
                "mapping": dict(mapping or inspected["mapping"]),
            }
            await asyncio.to_thread(_save_history_index, index)
        existing = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)
        imported_keys = {
            str((message.get("metadata") or {}).get("external_message_key") or "")
            for message in existing
        }
        added = 0
        try:
            for item in messages:
                message_key = item["external_message_key"]
                if message_key in imported_keys:
                    continue
                metadata = {
                    "external_source": inspected["format"], "external_file_key": file_key,
                    "external_message_key": message_key,
                }
                if item.get("timestamp"):
                    metadata["timestamp"] = item["timestamp"]
                await asyncio.to_thread(
                    append_session_message, DATA_ROOT / "engine", conversation_id,
                    item["role"], item["content"], metadata,
                )
                imported_keys.add(message_key)
                added += 1
            index["jsonl"][file_key] = {
                **index["jsonl"].get(file_key, {}), "conversation_id": conversation_id,
                "completed": True, "message_count": len(messages),
            }
            await asyncio.to_thread(_save_history_index, index)
        except Exception as exc:
            index["jsonl"][file_key] = {
                **index["jsonl"].get(file_key, {}), "conversation_id": conversation_id,
                "completed": False, "message_count": len(imported_keys),
            }
            await asyncio.to_thread(_save_history_index, index)
            raise HTTPException(status_code=500, detail=f"会话部分导入失败，可重试续传：{exc}") from exc
    return {
        "status": "imported" if added else "already_imported", "conversation_id": conversation_id,
        "messages_imported": added, "message_count": len(messages),
        "source_format": inspected["format"], "source_filename": filename,
    }
