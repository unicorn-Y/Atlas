"""Mobile browser entry and session control API for local Atlas runs."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.remote_access import create_remote_session, local_network_address, remote_access_status, revoke_remote_session

router = APIRouter()


@router.get("/remote", response_class=HTMLResponse)
async def remote_page() -> HTMLResponse:
    return HTMLResponse(_MOBILE_HTML, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/api/remote/access")
async def start_remote_access(request: Request, req: dict[str, Any] | None = None) -> dict[str, Any]:
    ttl = int((req or {}).get("ttl_seconds", 8 * 60 * 60))
    host = str((req or {}).get("host") or local_network_address()).strip()
    if any(char in host for char in "/?#@ ") or len(host) > 253:
        raise HTTPException(status_code=400, detail="远程访问地址无效")
    port = request.url.port or 8765
    try:
        grant = create_remote_session(ttl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    url = f"http://{host}:{port}/remote/#{grant['token']}"
    return {"session_id": grant["session_id"], "url": url, "expires_at": grant["expires_at"], "host": host}


@router.get("/api/remote/status")
async def remote_status() -> dict[str, Any]:
    return {**remote_access_status(), "host": local_network_address()}


@router.post("/api/remote/stop")
async def stop_remote_access(req: dict[str, Any] | None = None) -> dict[str, int]:
    return {"revoked": revoke_remote_session((req or {}).get("session_id"))}


@router.get("/api/remote/tasks")
async def remote_tasks(services: Annotated[AppServices, Depends(get_app_services)]) -> list[dict[str, Any]]:
    if services.memory is None or services.runtime_mgr is None:
        raise HTTPException(status_code=503, detail="Atlas 运行时尚未就绪")
    conversations = await services.memory.list_conversations(limit=None)
    runs = {run.conversation_id: run for run in services.runtime_mgr.runs.values()}
    return [{"id": str(item["id"]), "title": str(item.get("title") or "无标题"),
             "workspace": str(item.get("workspace") or ""), "preview": str(item.get("preview") or ""),
             "run_id": runs[item["id"]].run_id if item["id"] in runs else None,
             "status": runs[item["id"]].status if item["id"] in runs else "idle",
             "waiting_for": runs[item["id"]].waiting_for if item["id"] in runs else None,
             "pending_approvals": [event["data"] for event in runs[item["id"]].events if event.get("event") == "approval.required"] if item["id"] in runs else []}
            for item in conversations]


_MOBILE_HTML = r'''<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#111827"><title>Atlas Remote</title><style>
*{box-sizing:border-box}body{margin:0;background:#10141c;color:#e5e7eb;font:16px system-ui,-apple-system,sans-serif}main{max-width:680px;margin:auto;padding:18px 14px 36px}.top{display:flex;align-items:center;justify-content:space-between}h1{font-size:22px;margin:5px 0}button,input,textarea{font:inherit;border-radius:10px;border:1px solid #374151;background:#1d2430;color:#f9fafb;padding:11px}button{cursor:pointer;background:#315fe8;border:0;margin:3px}button.secondary{background:#293241}button.danger{background:#8b3040}.muted{color:#9ca3af;font-size:13px}.card{background:#181e28;border:1px solid #293241;border-radius:14px;padding:14px;margin:12px 0}.row{display:flex;gap:8px;align-items:center}.row input{flex:1;min-width:0}.items{display:grid;gap:8px}.task{display:flex;justify-content:space-between;gap:10px;text-align:left;width:100%;background:#1d2430;border:1px solid #293241}.task small{display:block;color:#9ca3af}.detail{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}.message{padding:9px 0;border-bottom:1px solid #293241}.message b{color:#8fb0ff}.approval{border:1px solid #a06a27;background:#312719}.err{color:#ff9b9b}.hidden{display:none}textarea{width:100%;min-height:80px}.foot{padding-bottom:env(safe-area-inset-bottom)}
</style><main><header class="top"><h1>Atlas · Remote</h1><button id="reload" class="secondary">刷新</button></header><div id="status" class="muted">正在连接本机 Atlas…</div><div id="error" class="err"></div><section id="listView"><div class="card"><div class="items" id="tasks"></div></div><div class="card"><h3>新建任务</h3><input id="title" placeholder="任务名称" style="width:100%"><textarea id="prompt" placeholder="要继续处理的内容"></textarea><button id="create">开始任务</button></div></section><section id="detailView" class="hidden"><button id="back" class="secondary">← 所有任务</button><div class="card"><h2 id="taskTitle"></h2><div id="controls"></div><div id="transcript"></div></div><div id="approval"></div><div class="card"><textarea id="reply" placeholder="继续对话"></textarea><button id="send">发送到此会话</button></div></section></main><script>
const token=location.hash.slice(1)||sessionStorage.getItem('atlas.remote.token')||'';if(token)sessionStorage.setItem('atlas.remote.token',token);history.replaceState(null,'',location.pathname);const auth={'X-Atlas-Api-Token':token};let ws=null,current=null,items=[];const $=id=>document.getElementById(id);function err(e){$('error').textContent=String(e.message||e);$('status').textContent='连接失败 · 可点“刷新”重试'}async function api(path,opt={}){const r=await fetch(path,{...opt,headers:{...auth,'Content-Type':'application/json',...(opt.headers||{})}});if(!r.ok)throw Error((await r.json().catch(()=>({}))).detail||`HTTP ${r.status}`);return r.json()}function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}async function refresh(){try{items=await api('/api/remote/tasks');$('tasks').innerHTML=items.map(x=>`<button class="task" data-id="${esc(x.id)}"><span>${esc(x.title)}<small>${esc(x.workspace)} · ${esc(x.preview)}</small></span><small>${esc(x.status)}${x.waiting_for?' · 等待'+esc(x.waiting_for):''}</small></button>`).join('')||'<p class="muted">还没有会话任务。可在下方创建。</p>';document.querySelectorAll('.task').forEach(b=>b.onclick=()=>open(b.dataset.id));$('status').textContent='已连接 · '+items.length+' 个会话';$('error').textContent=''}catch(e){err(e)}}async function open(id){current=items.find(x=>x.id===id)||{id,title:id};$('listView').classList.add('hidden');$('detailView').classList.remove('hidden');$('taskTitle').textContent=current.title;await messages();controls();connect()}async function messages(){try{const ms=await api(`/api/conversations/${encodeURIComponent(current.id)}/messages?limit=100`);$('transcript').innerHTML=ms.map(m=>`<div class="message"><b>${esc(m.role)}</b><div class="detail">${esc(m.content)}</div></div>`).join('');$('transcript').scrollTop=$('transcript').scrollHeight}catch(e){err(e)}}function controls(){const run=items.find(x=>x.id===current.id);$('controls').innerHTML=run&&run.run_id?`<span class="muted">状态：${esc(run.status)}</span> <button class="secondary" id="pause">暂停 / 继续</button> <button class="danger" id="cancel">停止</button>`:'';if($('pause'))$('pause').onclick=()=>wsSend({type:run.status==='paused'?'run.resume':'run.pause',run_id:run.run_id});if($('cancel'))$('cancel').onclick=()=>wsSend({type:'run.cancel',run_id:run.run_id})}function connect(){if(ws)ws.close();const proto=location.protocol==='https:'?'wss:':'ws:';ws=new WebSocket(`${proto}//${location.host}/ws/chat`,['atlas',token]);ws.onopen=()=>{if(current.run_id)wsSend({type:'resume',run_id:current.run_id,after_sequence:0})};ws.onmessage=e=>{let x;try{x=JSON.parse(e.data)}catch{return}if(x.event==='approval.required')approval(x);if(x.event==='approval.responded')$('approval').innerHTML='';if(x.event==='message.delta')$('transcript').insertAdjacentHTML('beforeend',`<div class="message"><b>assistant</b><div>${esc(x.data?.content||'')}</div></div>`);if(['run.completed','run.failed','run.cancelled','run.paused','run.resumed','run.started'].includes(x.event)){void refresh();void messages()}};ws.onerror=()=>{$('status').textContent='实时连接中断 · 刷新重试'}}function wsSend(x){if(ws&&ws.readyState===1)ws.send(JSON.stringify(x));else err(Error('实时连接尚未建立'))}function approval(x){const d=x.data||{};$('approval').innerHTML=`<div class="card approval"><b>等待操作审批</b><p>${esc(d.description||d.tool||'此操作需要确认')}</p><button id="allow">允许一次</button><button class="danger" id="deny">拒绝</button></div>`;$('allow').onclick=()=>wsSend({type:'approval.response',event_id:d.approval_id||d.event_id,choice:'allow_once'});$('deny').onclick=()=>wsSend({type:'approval.response',event_id:d.approval_id||d.event_id,choice:'deny'})}$('reload').onclick=()=>void refresh();$('back').onclick=()=>{$('detailView').classList.add('hidden');$('listView').classList.remove('hidden');if(ws)ws.close();void refresh()};$('create').onclick=async()=>{try{const title=$('title').value.trim()||'手机任务',content=$('prompt').value.trim();if(!content)throw Error('请输入任务内容');const c=await api('/api/conversations',{method:'POST',body:JSON.stringify({title})});current={id:c.id,title:c.title};await refresh();open(c.id);ws.addEventListener('open',()=>wsSend({type:'run.start',run_id:crypto.randomUUID(),conversation_id:c.id,content}),{once:true})}catch(e){err(e)}};$('send').onclick=()=>{const content=$('reply').value.trim();if(!content||!current)return;const run=items.find(x=>x.id===current.id);wsSend({type:'run.start',run_id:crypto.randomUUID(),conversation_id:current.id,content});$('reply').value=''};if(!token){$('status').textContent='缺少临时会话凭据';$('error').textContent='请从桌面或 atlas remote start 重新打开二维码链接'}else void refresh();
</script></html>'''
