"""Conversation-scoped background run and process controls.

The runtime and LocalExecutionRuntime remain the authorities for run/process
lifecycle. This router adds the explicit background marker and a safe,
conversation-scoped view over those live records.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


async def _background_table(manager: Any) -> None:
    if manager is None or manager._db is None:
        raise HTTPException(status_code=503, detail="Runtime persistence is unavailable")
    async with manager._persist_lock:
        await manager._db.execute("""
            CREATE TABLE IF NOT EXISTS atlas_background_runs (
                run_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                backgrounded_at TEXT NOT NULL
            )
        """)
        await manager._db.commit()


def _conversation_run(manager: Any, conversation_id: str, run_id: str) -> Any:
    run = manager.runs.get(run_id) if manager is not None else None
    if run is None or run.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Run not found in this conversation")
    return run


@router.get("/api/conversations/{conversation_id}/background-jobs")
async def list_background_jobs(
    conversation_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    manager = services.runtime_mgr
    await _background_table(manager)
    async with manager._persist_lock:
        async with manager._db.execute(
            "SELECT run_id, backgrounded_at FROM atlas_background_runs WHERE conversation_id = ?",
            (conversation_id,),
        ) as cursor:
            marked = {row["run_id"]: row["backgrounded_at"] for row in await cursor.fetchall()}

    runs = []
    subtasks = []
    for run_id, run in manager.runs.items():
        if run.conversation_id != conversation_id:
            continue
        for subtask_id, task in run.subtasks.items():
            subtasks.append({
                "id": subtask_id,
                "run_id": run_id,
                "kind": "subtask",
                "status": task.get("status", "unknown"),
                "title": task.get("goal") or task.get("description") or task.get("agent") or "子 Agent",
                "detail": task.get("progress") or task.get("summary") or task.get("result") or "",
            })
        if run.status not in {"running", "paused", "waiting"} and run_id not in marked:
            continue
        runs.append({
            "id": run_id,
            "kind": "run",
            "status": run.status,
            "started_at": run.started_at,
            "updated_at": run.updated_at,
            "waiting_for": run.waiting_for,
            "backgrounded_at": marked.get(run_id),
        })

    processes = []
    runtime = services.local_execution
    if runtime is not None:
        for process in runtime._processes.values():
            if process.conversation_id != conversation_id or not process.detached:
                continue
            processes.append({
                "id": process.execution_id,
                "kind": "process",
                "status": process.state,
                "command": process.command,
                "cwd": process.cwd,
                "run_id": process.owner_run_id,
                "started_at": process.started_at,
                "exit_code": process.exit_code,
            })
    runs.sort(key=lambda item: item["updated_at"], reverse=True)
    processes.sort(key=lambda item: item["started_at"], reverse=True)
    return {"conversation_id": conversation_id, "runs": runs, "subtasks": subtasks, "processes": processes}


@router.post("/api/conversations/{conversation_id}/background-jobs/runs/{run_id}/background")
async def background_run(
    conversation_id: str,
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    manager = services.runtime_mgr
    run = _conversation_run(manager, conversation_id, run_id)
    if run.status not in {"running", "paused", "waiting"}:
        raise HTTPException(status_code=409, detail="Run is no longer active")
    await _background_table(manager)
    async with manager._persist_lock:
        await manager._db.execute(
            "INSERT INTO atlas_background_runs(run_id, conversation_id, backgrounded_at) "
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
            "ON CONFLICT(run_id) DO UPDATE SET conversation_id=excluded.conversation_id, "
            "backgrounded_at=excluded.backgrounded_at",
            (run_id, conversation_id),
        )
        await manager._db.commit()
    return {"run_id": run_id, "status": run.status, "backgrounded": "true"}


@router.post("/api/conversations/{conversation_id}/background-jobs/runs/{run_id}/foreground")
async def foreground_run(
    conversation_id: str,
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    manager = services.runtime_mgr
    _conversation_run(manager, conversation_id, run_id)
    await _background_table(manager)
    async with manager._persist_lock:
        await manager._db.execute(
            "DELETE FROM atlas_background_runs WHERE run_id = ? AND conversation_id = ?",
            (run_id, conversation_id),
        )
        await manager._db.commit()
    return {"run_id": run_id, "backgrounded": "false"}


@router.post("/api/conversations/{conversation_id}/background-jobs/runs/{run_id}/stop")
async def stop_background_run(
    conversation_id: str,
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    run = _conversation_run(services.runtime_mgr, conversation_id, run_id)
    if run.status in {"running", "paused", "waiting"}:
        run.cancel_event.set()
    return {"run_id": run_id, "status": "cancelling" if run.status in {"running", "paused", "waiting"} else run.status}


@router.post("/api/conversations/{conversation_id}/background-jobs/runs/{run_id}/subtasks/{subtask_id}/stop")
async def stop_background_subtask(
    conversation_id: str,
    run_id: str,
    subtask_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    run = _conversation_run(services.runtime_mgr, conversation_id, run_id)
    subtask = run.subtasks.get(subtask_id)
    if not subtask:
        raise HTTPException(status_code=404, detail="Task not found in this conversation")
    if subtask.get("status") in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Task is already finished")
    cancel_event = subtask.get("cancel_event")
    if cancel_event is None:
        raise HTTPException(status_code=409, detail="Task cannot be stopped by this runtime")
    cancel_event.set()
    return {"run_id": run_id, "subtask_id": subtask_id, "status": "cancelling"}


@router.get("/api/conversations/{conversation_id}/background-jobs/processes/{execution_id}/output")
async def background_process_output(
    conversation_id: str,
    execution_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
    stream: str = Query("stdout", pattern="^(stdout|stderr)$"),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    runtime = services.local_execution
    process = runtime._processes.get(execution_id) if runtime is not None else None
    if process is None or process.conversation_id != conversation_id or not process.detached:
        raise HTTPException(status_code=404, detail="Background process not found in this conversation")
    path = process.stdout_path if stream == "stdout" else process.stderr_path
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(65536)
    return {"output": chunk.decode("utf-8", errors="replace"), "next_offset": offset + len(chunk),
            "status": process.state}


@router.post("/api/conversations/{conversation_id}/background-jobs/processes/{execution_id}/stop")
async def stop_background_process(
    conversation_id: str,
    execution_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    runtime = services.local_execution
    process = runtime._processes.get(execution_id) if runtime is not None else None
    if process is None or process.conversation_id != conversation_id or not process.detached:
        raise HTTPException(status_code=404, detail="Background process not found in this conversation")
    await runtime._cancel_process(process)
    return {"id": execution_id, "status": process.state, "exit_code": process.exit_code}
