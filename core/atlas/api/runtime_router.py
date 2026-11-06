"""HTTP endpoints for the per-app run runtime."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()

@router.get("/api/runtime/runs")
async def list_runtime_runs(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, object]:
    """Read-only lifecycle index.

    The database restores run metadata after a backend restart. It does not
    restore the original model execution or full historical tool events.
    """
    manager = services.runtime_mgr
    rows = [
        run for run in reversed(list(manager.runs.values()))
        if conversation_id is None or run.conversation_id == conversation_id
    ]
    return {
        "total": len(rows),
        "runs": [
            {
                "run_id": run.run_id,
                "conversation_id": run.conversation_id,
                "model": run.model,
                "status": run.status,
                "sequence": run.sequence,
                "live": run.task is not None and not run.task.done(),
                "event_count": len(run.events),
                "interrupted_by_restart": any(
                    event.get("event") == "run.failed"
                    and event.get("data", {}).get("category") == "interrupted"
                    for event in run.events
                ),
            }
            for run in rows[:limit]
        ],
    }



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
