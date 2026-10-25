"""Public read-only shared timelines and explicit local conversation import."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.sharing import ConversationShareStore, share_page_url, shared_page_html

router = APIRouter()


class ImportShareRequest(BaseModel):
    share_url: str
    password: str = ""


@router.get("/api/shared/{token}", response_class=HTMLResponse)
async def shared_timeline(token: str) -> HTMLResponse:
    share = ConversationShareStore().read(token, allow_locked=True)
    if share is None:
        raise HTTPException(404, "分享不存在、已撤销或已过期")
    share["token"] = token
    url = share_page_url(share["base_url"], token)
    return HTMLResponse(shared_page_html(url, share), headers={"Cache-Control": "no-store"})


@router.get("/api/shared/{token}/export")
async def public_share_export(token: str) -> JSONResponse:
    return _share_json(token, "")


@router.post("/api/shared/{token}/export")
async def protected_share_export(token: str, request: Request) -> JSONResponse:
    body = await request.json()
    password = str(body.get("password") or "") if isinstance(body, dict) else ""
    return _share_json(token, password)


def _share_json(token: str, password: str) -> JSONResponse:
    try:
        share = ConversationShareStore().read(token, password)
    except PermissionError:
        raise HTTPException(403, "口令不正确") from None
    if share is None:
        raise HTTPException(404, "分享不存在、已撤销或已过期")
    return JSONResponse({"title": share["title"], "messages": share["messages"], "expires_at": share["expires_at"]},
                        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})


@router.get("/api/shares")
async def list_shares(conversation_id: str | None = None) -> dict[str, Any]:
    return {"shares": ConversationShareStore().list(conversation_id=conversation_id)}


@router.delete("/api/shares/{share_id}")
async def revoke_share(share_id: str) -> dict[str, bool]:
    if not ConversationShareStore().revoke(share_id):
        raise HTTPException(404, "分享不存在或已经撤销")
    return {"revoked": True}


@router.post("/api/shared/import")
async def import_shared_conversation(
    body: ImportShareRequest, services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    parsed = urlsplit(body.share_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "分享链接必须是 HTTP(S) 地址")
    match = re.fullmatch(r"/api/shared/([A-Za-z0-9_-]{20,128})", parsed.path.rstrip("/"))
    if not match:
        raise HTTPException(422, "链接不是 Atlas 分享页地址")
    export_url = body.share_url.rstrip("/") + "/export"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(export_url, json={"password": body.password})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"分享服务连接失败：{type(exc).__name__}") from None
    if response.status_code == 403:
        raise HTTPException(403, "分享口令不正确")
    if response.status_code == 404:
        raise HTTPException(404, "分享不存在、已撤销或已过期")
    if response.status_code != 200:
        raise HTTPException(502, f"分享服务返回 HTTP {response.status_code}")
    try:
        data = response.json()
        messages = data["messages"]
        title = str(data.get("title") or "分享会话")
        if not isinstance(messages, list) or not messages:
            raise ValueError("empty transcript")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, "分享内容格式无效") from None
    memory = services.memory
    if memory is None:
        from atlas.server import memory as _memory
        memory = _memory
    conversation_id = await memory.create_conversation(f"分享：{title}"[:120])
    await memory.update_conversation(conversation_id, source="shared-import")
    transcript: list[dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "assistant")
        if role == "function":
            role = "tool"
        if role not in {"user", "assistant", "tool"}:
            continue
        content = str(item.get("content") or "")
        if not content:
            continue
        transcript.append({"role": role, "content": content, "display_metadata": {
            "imported_from_share": True, "source_created_at": str(item.get("created_at") or ""),
        }})
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import append_session_messages
    await asyncio.to_thread(append_session_messages, DATA_ROOT / "engine", conversation_id, transcript)
    return {"conversation_id": conversation_id, "title": f"分享：{title}"[:120], "messages": len(transcript)}
