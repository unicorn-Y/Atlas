"""Read-only, locally hosted capability portal with per-entry visibility."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from atlas.config import get_config, load_user_settings, save_user_settings

router = APIRouter(tags=["portal"])

_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "agent.atlas", "kind": "agent", "name": "Atlas Agent", "description": "在本机 Atlas 会话中运行任务。", "call_entry": "Atlas 桌面聊天"},
    {"id": "capability.chat", "kind": "capability", "name": "会话对话", "description": "在 Atlas 客户端开始或继续本机会话。", "call_entry": "Atlas 桌面聊天"},
    {"id": "capability.mobile", "kind": "capability", "name": "移动 Web 会话", "description": "由本机用户开启短时移动会话后，用手机浏览器继续任务。", "call_entry": "Atlas 设置 → 移动入口"},
    {"id": "capability.health", "kind": "capability", "name": "服务健康检查", "description": "读取 Atlas API 服务健康状态。", "call_entry": "/api/health"},
)
_IDS = {entry["id"] for entry in _CATALOG}


def _config() -> dict[str, Any]:
    raw = load_user_settings().get("capability_portal")
    raw = raw if isinstance(raw, dict) else {}
    visible = raw.get("visible_entries")
    visible = visible if isinstance(visible, list) else []
    return {
        "enabled": raw.get("enabled") is True,
        "private_network": raw.get("private_network") is True,
        "visible_entries": sorted({item for item in visible if isinstance(item, str) and item in _IDS}),
        "catalog": [dict(item) for item in _CATALOG],
        "bind_host": get_config().server_host,
        "port": get_config().server_port,
    }


def _request_is_loopback(request: Request) -> bool:
    try:
        return ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        return False


def _ensure_visible(request: Request) -> dict[str, Any]:
    config = _config()
    if not config["enabled"]:
        raise HTTPException(status_code=404, detail="门户未启用。")
    if not _request_is_loopback(request) and not config["private_network"]:
        raise HTTPException(status_code=404, detail="门户仅在本机开放。")
    if not _request_is_loopback(request):
        try:
            remote = ipaddress.ip_address(request.client.host if request.client else "")
        except ValueError:
            raise HTTPException(status_code=404, detail="门户仅在私有网络开放。") from None
        if not remote.is_private:
            raise HTTPException(status_code=404, detail="门户仅在私有网络开放。")
    return config


@router.get("/api/portal/config")
async def get_portal_config() -> dict[str, Any]:
    return _config()


@router.put("/api/portal/config")
async def put_portal_config(payload: dict[str, Any]) -> dict[str, Any]:
    enabled = payload.get("enabled", False)
    private_network = payload.get("private_network", False)
    visible_entries = payload.get("visible_entries", [])
    if not isinstance(enabled, bool) or not isinstance(private_network, bool):
        raise HTTPException(status_code=422, detail="门户开关值必须为布尔值。")
    if not isinstance(visible_entries, list) or any(not isinstance(item, str) or item not in _IDS for item in visible_entries):
        raise HTTPException(status_code=422, detail="公开条目包含未知能力 ID。")
    settings = load_user_settings()
    settings["capability_portal"] = {
        "enabled": enabled,
        "private_network": private_network,
        "visible_entries": sorted(set(visible_entries)),
    }
    save_user_settings(settings)
    return _config()


@router.get("/api/portal/manifest")
async def portal_manifest(request: Request) -> dict[str, Any]:
    config = _ensure_visible(request)
    visible = set(config["visible_entries"])
    entries = [dict(item) for item in _CATALOG if item["id"] in visible]
    return {"name": "Atlas Capability Portal", "read_only": True, "generated_at": datetime.now(timezone.utc).isoformat(), "entries": entries,
            "health_endpoint": "/api/health", "network_scope": "private_network" if config["private_network"] else "loopback"}


@router.get("/portal", response_class=HTMLResponse)
async def capability_portal(request: Request) -> HTMLResponse:
    _ensure_visible(request)
    # Portal content is loaded as JSON and inserted with textContent, never HTML interpolation.
    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"><title>Atlas 能力门户</title><style>body{margin:0;background:#f6f5f1;color:#25251f;font:15px/1.6 system-ui,sans-serif}main{max-width:850px;margin:7vh auto;padding:24px}h1{font-size:25px}article{margin:12px 0;padding:18px;border:1px solid #d9d7ce;border-radius:14px;background:white}small{color:#69695f}.tag{font-size:12px;border-radius:12px;background:#eef3ed;padding:3px 9px}a{color:#315b50}</style></head><body><main><h1>Atlas 能力门户</h1><p id="health"><span class="tag">正在读取服务状态…</span></p><section id="entries" aria-live="polite"></section><script>async function load(){const root=document.getElementById('entries'),health=document.getElementById('health');try{const [manifest,status]=await Promise.all([fetch('/api/portal/manifest').then(r=>{if(!r.ok)throw Error('门户不可用');return r.json()}),fetch('/api/health').then(r=>({ok:r.ok}))]);health.textContent=status.ok?'Atlas 服务在线':'Atlas 服务需要检查';for(const item of manifest.entries){const card=document.createElement('article'),title=document.createElement('h2'),description=document.createElement('p'),entry=document.createElement('small'),state=document.createElement('span');title.textContent=item.name;description.textContent=item.description;entry.textContent='调用入口：'+item.call_entry;state.textContent=' · 健康：'+(status.ok?'在线':'需要检查');card.append(title,description,entry,state);root.append(card)}if(!manifest.entries.length)root.textContent='管理员尚未选择公开能力。'}catch(e){health.textContent=String(e);root.textContent='无法加载门户内容。'}}</script><script>load()</script></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
