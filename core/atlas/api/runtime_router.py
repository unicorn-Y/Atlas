"""HTTP endpoints for the per-app run runtime."""

from __future__ import annotations

import asyncio
from typing import Any
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


@router.get("/api/subtasks/online")
async def list_online_subtasks(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """List live child agents across all parent runs, not just the open session."""
    return {"items": await services.runtime_mgr.list_online_subtasks()}


@router.get("/api/runs/{run_id}/subtasks")
async def list_subtasks(
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return {"items": await services.runtime_mgr.list_subtasks(run_id)}


@router.post("/api/runs/{run_id}/subtasks/{subtask_id}/close")
async def close_subtask(
    run_id: str,
    subtask_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    manager = services.runtime_mgr
    item = await manager.get_subtask(run_id, subtask_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if item.get("backend") != "atlas":
        raise HTTPException(status_code=409, detail="Only native Atlas child sessions support lifecycle control")
    if item.get("status") == "completed":
        raise HTTPException(status_code=409, detail="已完成的子会话已关闭；transcript 保留，可打开查看。")
    run = manager.runs.get(run_id)
    active = run.subtasks.get(subtask_id) if run else None
    if active and active.get("status") in {"running", "closing"}:
        cancel_event = active.get("cancel_event")
        if cancel_event is not None:
            cancel_event.set()
    await manager.save_subtask({**item, "status": "closed"})
    if active and active.get("status") in {"running", "closing"}:
        # Let the native worker persist its SessionEnd recovery point after the
        # cancellation signal, while keeping close responsive if a tool blocks.
        for _ in range(40):
            await asyncio.sleep(0.1)
            latest = await manager.get_subtask(run_id, subtask_id)
            if latest and latest.get("session_id"):
                item = latest
                break
        await manager.save_subtask({**item, "status": "completed" if item.get("status") == "completed" else "closed"})
    return {"status": "closed", "subtask_id": subtask_id}


@router.post("/api/runs/{run_id}/subtasks/{subtask_id}/resume")
async def resume_subtask(
    run_id: str,
    subtask_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    manager = services.runtime_mgr
    item = await manager.get_subtask(run_id, subtask_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if item.get("backend") != "atlas":
        raise HTTPException(status_code=409, detail="Only native Atlas child sessions can be resumed")
    if item.get("status") == "completed":
        raise HTTPException(status_code=409, detail="已完成的终态不支持恢复；子会话 transcript 仍可打开查看。")
    if item.get("status") not in {"closed", "cancelled", "failed"}:
        raise HTTPException(status_code=409, detail=f"当前状态 {item.get('status')} 不支持恢复")
    session_id = str(item.get("session_id") or "")
    if not session_id:
        raise HTTPException(status_code=409, detail="恢复点尚未生成子会话 ID；请稍后重试或打开父会话。")
    orchestrator = services.orchestrator
    if orchestrator is None or not callable(getattr(orchestrator, "_run_atlas_subtask", None)):
        raise HTTPException(status_code=503, detail="原生子 Agent 执行器未就绪")
    recovery = item.get("recovery_point") or {}
    memory = services.memory
    if memory is None or await memory.get_conversation(session_id) is None:
        raise HTTPException(status_code=409, detail="子会话 transcript 不存在，无法恢复。")
    resume_count = int(recovery.get("resume_count") or 0) + 1
    recovery["resume_count"] = resume_count
    item["status"] = "running"
    item["recovery_point"] = recovery
    await manager.save_subtask(item)

    async def continue_child() -> None:
        status = "failed"
        try:
            result = await orchestrator._run_atlas_subtask(
                goal=str(item.get("goal") or "继续完成此前的子任务"),
                context=(
                    "继续此前未完成的子任务。先根据本子会话已有上下文恢复进度，"
                    "不要重复已经完成的副作用；完成剩余工作后汇报结果。"
                ),
                cwd=str(item.get("workspace") or "") or None,
                subtask_id=f"{subtask_id}-resume-{resume_count}",
                atlas_options={
                    "model": str(item.get("model") or "") or None,
                    "permission_mode": "full_access", "agent_role": "leaf",
                    "depth": 1, "resume_session_id": session_id,
                },
                on_progress=lambda _text: None,
            )
            status = str(result.get("status") or "failed")
            if status == "cancelled":
                status = "cancelled"
        except Exception:
            status = "failed"
        finally:
            latest = await manager.get_subtask(run_id, subtask_id) or item
            await manager.save_subtask({
                **latest, "status": status, "session_id": session_id,
                "recovery_point": recovery,
            })

    task = asyncio.create_task(continue_child(), name=f"subtask-resume:{subtask_id}:{resume_count}")
    manager.subtask_tasks = getattr(manager, "subtask_tasks", {})
    manager.subtask_tasks[(run_id, subtask_id)] = task
    task.add_done_callback(lambda _task: manager.subtask_tasks.pop((run_id, subtask_id), None))
    return {"status": "running", "subtask_id": subtask_id, "session_id": session_id}


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
