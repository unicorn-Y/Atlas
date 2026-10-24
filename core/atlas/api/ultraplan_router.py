"""API for Atlas's researched, editable ultraplan workflow."""
from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.ultraplan import discard, execute, get, save_edit, start

router = APIRouter(prefix="/api/ultraplan", tags=["ultraplan"])


def _orchestrator(services: AppServices) -> Any:
    if services.orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent orchestrator is unavailable")
    return services.orchestrator


@router.post("")
async def start_workflow(body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    try:
        return await start(_orchestrator(services), goal=str(body.get("goal") or ""),
                           workspace=str(body.get("workspace") or ""),
                           model=str(body.get("model") or _orchestrator(services)._model_mgr.current_model),
                           conversation_id=str(body.get("conversation_id") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{job_id}")
async def read_workflow(job_id: str) -> dict[str, Any]:
    try:
        return get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ultraplan not found") from exc


@router.put("/{job_id}")
async def edit_workflow(job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return save_edit(job_id, body.get("plan"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ultraplan not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{job_id}/approve")
async def approve_workflow(job_id: str, services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    orchestrator = _orchestrator(services)
    try:
        job = get(job_id)
        if job["status"] not in {"awaiting_approval", "failed_step"}:
            raise ValueError("plan is not awaiting approval")
        task = asyncio.create_task(execute(job_id, orchestrator), name=f"ultraplan-execute-{job_id}")
        return {**job, "status": "executing"} if task else job
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ultraplan not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{job_id}/discard")
async def discard_workflow(job_id: str) -> dict[str, Any]:
    try:
        return discard(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Ultraplan not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
