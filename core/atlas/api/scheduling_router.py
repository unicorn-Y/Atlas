"""Schedules and standing goals surface (``/api/schedules, /api/goals``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.scheduler import ScheduledTask, TaskStatus, TriggerType

router = APIRouter()


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch
    and the scheduler-callback helpers keep living beside their callers."""
    import atlas.server

    return atlas.server


class ScheduleCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    trigger_type: str = "cron"  # cron | interval | date
    trigger_args: dict[str, Any] = {}
    action: str  # "agent:<message>"
    tags: list[str] = []


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_args: dict[str, Any] | None = None
    action: str | None = None
    status: str | None = None  # "active" | "paused"
    tags: list[str] | None = None


class GoalCreateRequest(BaseModel):
    id: str
    name: str
    goal: str
    description: str = ""
    trigger_type: str = "cron"
    trigger_args: dict[str, Any] = {}
    tags: list[str] = []


async def _goal_payload(task: ScheduledTask) -> dict[str, Any]:
    await _server()._ensure_goal_migrated(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_state

    state = await asyncio.to_thread(
        goal_state, DATA_ROOT / "engine", _server()._goal_session_id(task.id),
    )
    result = task.to_dict()
    result["goal"] = str((state or {}).get("goal") or "")
    result["goal_session_id"] = _server()._goal_session_id(task.id)
    result["goal_status"] = (state or {}).get("status", "cleared")
    progress = {}
    if state:
        from atlas.engine.goals import MAX_PLAN_ATTEMPTS, GoalState

        subgoals = state.get("subgoals", [])
        completed = [i for i in state.get("completed_subgoals", []) if isinstance(i, int)]
        plan_attempts = int(state.get("plan_attempts", 0) or 0)
        # Reuse GoalState.needs_plan so the gate cannot drift between the engine
        # and the UI. A malformed row must degrade to "no gate", never raise.
        try:
            needs_plan = GoalState.from_json(json.dumps(state)).needs_plan()
        except Exception:  # noqa: BLE001 - a corrupt row must not break /api/schedules
            needs_plan = False
        progress = {
            "turns_used": state.get("turns_used", 0),
            "max_turns": state.get("max_turns", 20),
            "subgoals": subgoals,
            "completed_subgoals": completed,
            "completed_count": len([i for i in completed if 0 < i <= len(subgoals)]),
            # Plan-gate surface: the UI needs to tell "still planning" apart from
            # "executing", which the old payload could not express.
            "decomposition_required": bool(state.get("decomposition_required", True)),
            "needs_plan": needs_plan,
            "plan_attempts": plan_attempts,
            "max_plan_attempts": MAX_PLAN_ATTEMPTS,
            "last_verdict": state.get("last_verdict"),
            "last_reason": state.get("last_reason"),
            "paused_reason": state.get("paused_reason"),
            "last_evaluation": {
                "verdict": state.get("last_verdict"),
                "reason": state.get("last_reason"),
            },
        }
    result["goal_progress"] = progress
    return result


@router.get("/api/schedules")
async def list_schedules(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
    tag: str | None = Query(None),
) -> dict[str, Any]:
    """Return all scheduled tasks."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    filter_status = TaskStatus(status) if status else None
    tasks = scheduler.list_tasks(status=filter_status, tag=tag)
    return {
        "count": len(tasks),
        "active_count": scheduler.active_count,
        "tasks": [t.to_dict() for t in tasks],
    }


@router.get("/api/schedules/{task_id}")
async def get_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str,
) -> dict[str, Any]:
    """Return a single scheduled task."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@router.post("/api/schedules/{task_id}/pause")
async def pause_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = await scheduler.update_task(task_id, status=TaskStatus.PAUSED)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@router.post("/api/schedules/{task_id}/resume")
async def resume_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = await scheduler.update_task(task_id, status=TaskStatus.ACTIVE)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return task.to_dict()


@router.post("/api/schedules")
async def create_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ScheduleCreateRequest,
) -> dict[str, Any]:
    """Create a new scheduled task."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = ScheduledTask(
        id=req.id,
        name=req.name,
        description=req.description,
        trigger_type=TriggerType(req.trigger_type),
        trigger_args=req.trigger_args,
        action=req.action,
        tags=req.tags,
    )
    try:
        result = await scheduler.add_task(task)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result.to_dict()


@router.put("/api/schedules/{task_id}")
async def update_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str, req: ScheduleUpdateRequest,
) -> dict[str, Any]:
    """Update an existing scheduled task."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    kwargs: dict[str, Any] = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.description is not None:
        kwargs["description"] = req.description
    if req.trigger_type is not None:
        kwargs["trigger_type"] = TriggerType(req.trigger_type)
    if req.trigger_args is not None:
        kwargs["trigger_args"] = req.trigger_args
    if req.action is not None:
        kwargs["action"] = req.action
    if req.status is not None:
        kwargs["status"] = TaskStatus(req.status)
    if req.tags is not None:
        kwargs["tags"] = req.tags

    result = await scheduler.update_task(task_id, **kwargs)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return result.to_dict()


@router.delete("/api/schedules/{task_id}")
async def delete_schedule(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str,
) -> dict[str, str]:
    """Delete a scheduled task."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    ok = await scheduler.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return {"status": "ok", "task_id": task_id}


@router.post("/api/schedules/{task_id}/run")
async def run_schedule_now(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str,
) -> dict[str, str]:
    """Manually trigger a scheduled task immediately."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    ok = await scheduler.run_now(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task not found: {task_id}")
    return {"status": "ok", "task_id": task_id}


@router.get("/api/goals")
async def list_goals(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    goals = [task for task in scheduler.list_tasks()
             if task.action == "goal" or task.legacy_goal]
    payload = [await _goal_payload(task) for task in goals]
    return {"count": len(payload), "goals": payload}


@router.post("/api/goals", status_code=201)
async def create_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: GoalCreateRequest,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    goal = req.goal.strip()
    if not goal:
        raise HTTPException(status_code=422, detail="Goal must not be empty")
    try:
        trigger_type = TriggerType(req.trigger_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid trigger_type") from exc
    task = ScheduledTask(
        id=req.id,
        name=req.name,
        description=req.description,
        trigger_type=trigger_type,
        trigger_args=req.trigger_args,
        action="goal",
        tags=req.tags,
    )
    try:
        await scheduler.add_task(task)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import record_goal_event, set_goal
    try:
        await asyncio.to_thread(set_goal, DATA_ROOT / "engine", _server()._goal_session_id(task.id), goal)
        await asyncio.to_thread(record_goal_event, DATA_ROOT / "engine", _server()._goal_session_id(task.id),
                                "goal.created", {"goal": goal})
    except Exception:
        await scheduler.delete_task(task.id)
        raise
    return await _goal_payload(task)


@router.get("/api/goals/{goal_id}")
async def get_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    return await _goal_payload(task)


@router.put("/api/goals/{goal_id}")
async def update_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    allowed = {key: req[key] for key in ("name", "description", "trigger_args", "tags") if key in req}
    if "trigger_type" in req:
        try:
            allowed["trigger_type"] = TriggerType(req["trigger_type"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid trigger_type") from exc
    await _server()._ensure_goal_migrated(task)
    if "goal" in req:
        value = req["goal"]
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=422, detail="goal must not be empty")
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import record_goal_event, set_goal
        await asyncio.to_thread(set_goal, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), value)
        await asyncio.to_thread(record_goal_event, DATA_ROOT / "engine", _server()._goal_session_id(goal_id),
                                "goal.replaced", {"goal": value})
    updated = await scheduler.update_task(goal_id, **allowed)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    return await _goal_payload(updated)


@router.post("/api/goals/{goal_id}/pause")
async def pause_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    await _server()._ensure_goal_migrated(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import mutate_goal, record_goal_event
    await asyncio.to_thread(mutate_goal, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "pause")
    await asyncio.to_thread(record_goal_event, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "goal.paused")
    return await _goal_payload(task)


@router.post("/api/goals/{goal_id}/resume")
async def resume_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str,
) -> dict[str, Any]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    await _server()._ensure_goal_migrated(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import mutate_goal, record_goal_event
    await asyncio.to_thread(mutate_goal, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "resume")
    await asyncio.to_thread(record_goal_event, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "goal.resumed")
    return await _goal_payload(task)


@router.delete("/api/goals/{goal_id}")
async def clear_goal_route(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str,
) -> dict[str, str]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail="Scheduled goal not found")
    await _server()._ensure_goal_migrated(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import mutate_goal, record_goal_event
    await asyncio.to_thread(mutate_goal, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "clear")
    await asyncio.to_thread(record_goal_event, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "goal.cleared")
    await scheduler.delete_task(goal_id)
    return {"status": "cleared", "goal_id": goal_id}


@router.get("/api/goals/{goal_id}/trace")
async def get_goal_trace(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str, run_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return canonical engine state; Atlas no longer stores a second goal event trace."""
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if task is None or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    payload = await _goal_payload(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_events
    events = await asyncio.to_thread(
        goal_events, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), run_id,
    )
    return {"goal_id": goal_id, "status": payload["goal_status"],
            "state": payload["goal_progress"], "events": events}


@router.post("/api/goals/{goal_id}/run")
async def run_goal_now(
    services: Annotated[AppServices, Depends(get_app_services)],
    goal_id: str,
) -> dict[str, str]:
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    task = scheduler.get_task(goal_id)
    if not task or not (task.action == "goal" or task.legacy_goal):
        raise HTTPException(status_code=404, detail=f"Scheduled goal not found: {goal_id}")
    await _server()._ensure_goal_migrated(task)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_state, mutate_goal
    state = await asyncio.to_thread(
        goal_state, DATA_ROOT / "engine", _server()._goal_session_id(goal_id),
    )
    if state and state.get("status") == "paused":
        await asyncio.to_thread(
            mutate_goal, DATA_ROOT / "engine", _server()._goal_session_id(goal_id), "resume",
        )
    await scheduler.run_now(goal_id)
    return {"status": "ok", "goal_id": goal_id}
