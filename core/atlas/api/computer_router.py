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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from atlas.origin_guard import TOKEN_HEADER, is_trusted

router = APIRouter(prefix="/api/computer", tags=["computer"])


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


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


__all__ = ["router"]
