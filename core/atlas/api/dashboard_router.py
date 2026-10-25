"""Loopback-only browser console for local run, session, channel, and device status."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from typing import Annotated, Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.dashboard_access import read_control, token_valid
from atlas.config import PROJECT_ROOT

router = APIRouter()


@router.post("/api/dashboard/access")
async def create_dashboard_access(request: Request) -> dict[str, Any]:
    """Create a browser token in the running backend's own data directory.

    The CLI can attach to an already-running Atlas process whose DATA_ROOT differs
    from the CLI's environment. Creating the token here keeps the read path and
    write path in the same service process.
    """
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Dashboard is available only from loopback")
    from atlas.dashboard_access import create_access

    host = request.url.hostname or "127.0.0.1"
    port = request.url.port or 8765
    shutdown_token = os.environ.get("ATLAS_SHUTDOWN_TOKEN", "")
    token, info = create_access(
        port=port, pid=os.getpid(), owns_server=bool(shutdown_token),
        shutdown_token=shutdown_token,
    )
    return {
        "url": f"http://{host}:{port}/dashboard#{token}",
        "pid": info["pid"], "expires_at": info["expires_at"],
    }


def _require_dashboard_access(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Dashboard is available only from loopback")
    if not token_valid(request.headers.get("x-atlas-dashboard-token")):
        raise HTTPException(status_code=401, detail="Dashboard session is missing or expired; run atlas dashboard start")


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Dashboard is available only from loopback")
    if not read_control():
        raise HTTPException(status_code=404, detail="Run `atlas dashboard start` to enable the local console")
    page = _dashboard_dist_dir() / "dashboard.html"
    if page.is_file():
        html = page.read_text(encoding="utf-8", errors="replace")
        html = html.replace("<head>", '<head><base href="/dashboard/">', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    html = _DASHBOARD_HTML.replace(
        '<html lang="zh-CN">', '<html lang="zh-CN"><head><base href="/dashboard/"></head>', 1,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _dashboard_dist_dir() -> Path:
    candidates = (
        PROJECT_ROOT / "dashboard",
        PROJECT_ROOT / "frontend" / "dist",
        Path(__file__).resolve().parents[3] / "frontend" / "dist",
    )
    return next((path for path in candidates if (path / "dashboard.html").is_file()), candidates[0])


@router.get("/dashboard/assets/{asset_path:path}")
async def dashboard_asset(asset_path: str, request: Request) -> FileResponse:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Dashboard is available only from loopback")
    root = (_dashboard_dist_dir() / "assets").resolve()
    candidate = (root / asset_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Dashboard asset was not found")
    return FileResponse(candidate, headers={"Cache-Control": "no-cache", "Referrer-Policy": "no-referrer"})


@router.get("/api/dashboard/status", dependencies=[Depends(_require_dashboard_access)])
async def dashboard_status(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    runs = list(getattr(services.runtime_mgr, "runs", {}).values()) if services.runtime_mgr else []
    channels = services.channel_manager.status() if services.channel_manager else {"channels": []}
    startup = services.startup.snapshot() if services.startup else {}
    return {
        "status": "ready", "components": startup, "active_runs": sum(run.status == "running" for run in runs),
        "waiting_runs": sum(bool(run.waiting_for) for run in runs),
        "channels": len(channels.get("channels", [])),
        "devices": len(await asyncio.to_thread(services.device_registry.list_devices)) if services.device_registry else 0,
    }


@router.get("/api/dashboard/sessions", dependencies=[Depends(_require_dashboard_access)])
async def dashboard_sessions(services: Annotated[AppServices, Depends(get_app_services)]) -> list[dict[str, Any]]:
    if services.memory is None:
        raise HTTPException(status_code=503, detail="Conversation store is not ready")
    rows = await services.memory.list_conversations(limit=100)
    return [{key: row.get(key) for key in ("id", "title", "workspace", "preview", "updated_at")}
            for row in rows]


@router.get("/api/dashboard/channels", dependencies=[Depends(_require_dashboard_access)])
async def dashboard_channels(services: Annotated[AppServices, Depends(get_app_services)]) -> list[dict[str, Any]]:
    if services.channel_manager is None:
        return []
    return services.channel_manager.status().get("channels", [])


@router.get("/api/dashboard/devices", dependencies=[Depends(_require_dashboard_access)])
async def dashboard_devices(services: Annotated[AppServices, Depends(get_app_services)]) -> list[dict[str, Any]]:
    if services.device_registry is None:
        return []
    rows = await asyncio.to_thread(services.device_registry.list_devices)
    allowed = ("device_id", "display_name", "kind", "os", "trusted", "status", "last_seen", "capabilities")
    return [{key: row.get(key) for key in allowed if key in row} for row in rows]


_DASHBOARD_HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Atlas 本地控制台</title><style>
:root{color-scheme:dark;font:15px system-ui,Segoe UI,sans-serif;background:#10141c;color:#e5e7eb}body{margin:0}main{max-width:1050px;margin:0 auto;padding:24px 18px}header,.tabs,.row{display:flex;align-items:center;gap:10px}header{justify-content:space-between}h1{font-size:23px;margin:0}button{border:1px solid #344052;background:#202938;color:inherit;border-radius:9px;padding:9px 13px;cursor:pointer}.tabs{margin:22px 0 12px}.tabs button[aria-selected=true]{background:#315fe8;border-color:#315fe8}.muted{color:#a4afbd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card,article{background:#181f2b;border:1px solid #2a3545;border-radius:12px;padding:14px}.card strong{font-size:22px;display:block;margin-top:5px}.list{display:grid;gap:9px}article{overflow-wrap:anywhere}article b{display:block;margin-bottom:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0;color:#c4ceda;font:12px ui-monospace,Consolas,monospace}#error{color:#ff9999;margin:12px 0}@media(max-width:550px){main{padding:17px 12px}.tabs{overflow:auto}.tabs button{white-space:nowrap}}
</style><main><header><h1>Atlas · 本地控制台</h1><button id="refresh">刷新</button></header><p class="muted" id="status">正在连接本机 Atlas…</p><div id="error"></div><nav class="tabs" aria-label="控制台页面"><button data-tab="overview" aria-selected="true">运行状态</button><button data-tab="sessions" aria-selected="false">会话</button><button data-tab="channels" aria-selected="false">渠道</button><button data-tab="devices" aria-selected="false">设备</button></nav><section id="content"></section></main><script>
let token='';const tokenKey='atlas.dashboard.token';const headers={'X-Atlas-Dashboard-Token':''};function adoptToken(value){const fresh=String(value||'').replace(/^#/,'').trim();if(fresh){token=fresh;sessionStorage.setItem(tokenKey,fresh);headers['X-Atlas-Dashboard-Token']=fresh;history.replaceState(null,'',location.pathname+location.search)}else if(!token){token=sessionStorage.getItem(tokenKey)||'';headers['X-Atlas-Dashboard-Token']=token}}adoptToken(location.hash.slice(1));window.addEventListener('hashchange',()=>{if(location.hash.length>1){adoptToken(location.hash.slice(1));void show()}});let tab='overview';const $=id=>document.getElementById(id);async function api(path){const r=await fetch(path,{headers});if(!r.ok){const detail=(await r.json().catch(()=>({}))).detail||`HTTP ${r.status}`;if(r.status===401){sessionStorage.removeItem(tokenKey);throw Error('控制台令牌已失效。请从 Atlas 设置→诊断中重新点击“打开本地控制台”。')}throw Error(detail)}return r.json()}function node(tag,text,cls=''){const el=document.createElement(tag);el.textContent=text??'';if(cls)el.className=cls;return el}function card(label,value){const el=node('div','','card');el.append(node('span',label,'muted'),node('strong',String(value??'—')));return el}async function show(){try{if(!token)throw Error('缺少控制台访问令牌，请运行 atlas dashboard start 并使用命令输出的网址');const body=$('content');body.replaceChildren();if(tab==='overview'){const d=await api('/api/dashboard/status');const grid=node('div','','grid');grid.append(card('服务状态',d.status),card('运行中任务',d.active_runs),card('等待中任务',d.waiting_runs),card('已注册渠道',d.channels),card('配对设备',d.devices));body.append(grid);const c=node('pre',JSON.stringify(d.components,null,2),'card');c.setAttribute('aria-label','组件启动状态');body.append(c)}else{const path={sessions:'/api/dashboard/sessions',channels:'/api/dashboard/channels',devices:'/api/dashboard/devices'}[tab];const items=await api(path);const list=node('div','','list');for(const item of items){const article=node('article');const title=item.title||item.display_name||item.name||item.device_id||item.id||'Atlas';article.append(node('b',String(title)));article.append(node('pre',JSON.stringify(item,null,2)));list.append(article)}if(!items.length)list.append(node('article','暂无记录'));body.append(list)}$('status').textContent='已连接本机 Atlas · '+new Date().toLocaleTimeString();$('error').textContent=''}catch(e){$('error').textContent=String(e.message||e);$('status').textContent='控制台暂不可用'}}document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>x.setAttribute('aria-selected',String(x===b)));void show()});$('refresh').onclick=()=>void show();void show();setInterval(()=>void show(),15000);
</script></html>'''
