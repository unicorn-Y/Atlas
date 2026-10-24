"""REST surface for the X2 computer runtime (``/api/computer/*``).

The router mirrors the Hermes computer-use doctor output (readiness, driver
version, diagnostics) and never raises: the handler funnels every failure into
an ``{"ok": false, "error": ...}`` payload with a 200 status so the frontend
card can render a degraded state instead of an error page.

``POST /foreground`` resolves a pending foreground-confirmation card
(``computer.foreground_required``) through the pending registry — the single
resolution channel shared with ``POST /api/browser/handoff``.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/computer", tags=["computer"])

def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(request.headers.get("origin"), request.headers.get(TOKEN_HEADER), fetch_site=request.headers.get("sec-fetch-site"))
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")

@router.get("/teach")
async def teach_status() -> dict[str, Any]:
    from atlas.computer_teach import snapshot
    return snapshot()

@router.post("/teach/start", dependencies=[Depends(_require_trusted_origin)])
async def teach_start() -> dict[str, Any]:
    from atlas.computer_teach import start
    try: return await asyncio.to_thread(start)
    except (ValueError, RuntimeError) as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/teach/stop", dependencies=[Depends(_require_trusted_origin)])
async def teach_stop() -> dict[str, Any]:
    from atlas.computer_teach import stop
    try: return await asyncio.to_thread(stop)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc

@router.put("/teach/steps", dependencies=[Depends(_require_trusted_origin)])
async def teach_correct(req: dict[str, Any]) -> dict[str, Any]:
    from atlas.computer_teach import correct
    try: return correct(req.get("steps", []))
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc

@router.post("/teach/replay", dependencies=[Depends(_require_trusted_origin)])
async def teach_replay() -> dict[str, Any]:
    from atlas.computer_teach import replay
    try: return await asyncio.to_thread(replay)
    except Exception as exc: raise HTTPException(400, str(exc)) from exc

@router.post("/teach/export", dependencies=[Depends(_require_trusted_origin)])
async def teach_export(req: dict[str, Any], request: Request) -> dict[str, Any]:
    from atlas.computer_teach import export_skill
    try:
        from atlas import server
        app_services = getattr(request.app.state, "services", None)
        model_mgr = getattr(app_services, "model_mgr", None) or getattr(server, "model_mgr", None)
        if model_mgr is None: raise HTTPException(503, "技能整理模型暂不可用。")
        from atlas.computer_teach import snapshot
        state = snapshot()
        prompt = [{"role":"system","content":"你把桌面演示步骤整理成可复用 Atlas 技能。只返回完整 SKILL.md（含 YAML frontmatter、用途、参数、逐步操作及每步定位策略）。优先窗口/控件定位，其次锚点截图匹配，最后坐标。保留目标窗口信息；敏感输入只要求用户运行时提供，不得推断或生成任何凭据。"},
                  {"role":"user","content":json.dumps({"name":req.get("name"),"purpose":req.get("purpose"),"parameters":req.get("parameters",[]),"steps":[{key:value for key,value in step.items() if key!="anchor"} for step in state.get("steps",[])]},ensure_ascii=False)}]
        result = await model_mgr.model_router.complete_for(model_mgr.current_model,"conversation",prompt,max_tokens=2400,temperature=.2)
        draft = str(getattr(result,"text","") or "")
        exported = await asyncio.to_thread(export_skill,str(req.get("name","")),str(req.get("purpose","")),req.get("parameters",[]),draft)
        skill_mgr = getattr(app_services, "skill_mgr", None)
        if skill_mgr is not None:
            await asyncio.to_thread(skill_mgr.scan_skills_sync)
        return exported
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/status")
async def computer_status() -> dict[str, Any]:
    """Desktop-control readiness: Hermes doctor report + Atlas permission state."""
    from atlas.tools.x2.computer import status_snapshot

    return await asyncio.to_thread(status_snapshot)


class ForegroundResolution(BaseModel):
    run_id: str
    approve: bool


@router.post("/foreground", dependencies=[Depends(_require_trusted_origin)])
async def resolve_foreground_endpoint(req: ForegroundResolution) -> dict[str, Any]:
    """Resolve a pending foreground confirmation (computer.foreground_required)."""
    from atlas.tools.x2 import pending as x2pending

    run_id = req.run_id.strip()
    if not run_id:
        raise HTTPException(status_code=422, detail="run_id 不能为空")
    if not x2pending.resolve(run_id, "allow" if req.approve else "deny"):
        raise HTTPException(status_code=404, detail="该运行没有等待中的前台确认")
    return {"status": "ok", "run_id": run_id, "approved": req.approve}


class PauseRequest(BaseModel):
    run_id: str
    pause: bool = True


@router.post("/pause", dependencies=[Depends(_require_trusted_origin)])
async def pause_computer_endpoint(req: PauseRequest) -> dict[str, Any]:
    """User moved the mouse during a foreground sequence — pause (or resume)."""
    from atlas.tools.x2.computer import set_paused

    ok = set_paused(req.run_id, req.pause)
    if not ok:
        raise HTTPException(status_code=404, detail="没有可暂停的电脑操作任务")
    return {"status": "ok", "run_id": req.run_id, "paused": req.pause}


@router.get("/runs/{run_id}/steps", dependencies=[Depends(_require_trusted_origin)])
async def computer_run_steps(run_id: str) -> dict[str, Any]:
    """Recorded step trail for the operation replay panel (thumbnails capped)."""
    from atlas.tools.x2.computer import run_steps

    return {"run_id": run_id, "steps": run_steps(run_id)}


@router.get("/access-requests", dependencies=[Depends(_require_trusted_origin)])
async def computer_access_requests(request: Request) -> dict[str, Any]:
    """Pending Computer Use approvals for the desktop permission surface."""
    runtime = getattr(getattr(request.app.state, "services", None), "computer_use", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Computer Use runtime is unavailable")
    return {"requests": runtime.access_requests(pending_only=True)}


class ComputerAccessResolution(BaseModel):
    approve: bool


@router.post("/access-requests/{request_id}/resolve", dependencies=[Depends(_require_trusted_origin)])
async def resolve_computer_access(request_id: str, req: ComputerAccessResolution, request: Request) -> dict[str, Any]:
    """Resolve an explicit access prompt; grants are issued by the waiting run only."""
    runtime = getattr(getattr(request.app.state, "services", None), "computer_use", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Computer Use runtime is unavailable")
    resolved = runtime.resolve_access_request(request_id, req.approve)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No pending Computer Use request exists")
    return resolved


@router.post("/runs/{run_id}/stop", dependencies=[Depends(_require_trusted_origin)])
async def stop_computer_run(run_id: str, request: Request) -> dict[str, Any]:
    """Latch stop, revoke the run grant, and cancel its active Computer Use call."""
    runtime = getattr(getattr(request.app.state, "services", None), "computer_use", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Computer Use runtime is unavailable")
    return {"status": "stopped", **await runtime.stop_run(run_id)}


__all__ = ["router"]
