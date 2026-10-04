"""HTTP endpoints for the per-app run runtime."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


@router.post("/api/runs/{run_id}/subtasks/{subtask_id}/cancel")
async def cancel_subtask(
    run_id: str,
    subtask_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    run = services.runtime_mgr.runs.get(run_id)
    subtask = run.subtasks.get(subtask_id) if run else None
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if subtask.get("status") in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Subtask is already finished")
    subtask["cancel_event"].set()
    return {"status": "cancelling", "subtask_id": subtask_id}
