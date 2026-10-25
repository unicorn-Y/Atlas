"""Local control surface for self-hosted SSH jobs and returned Git patches."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from atlas.remote_tasks import RemoteTaskStore

router = APIRouter(prefix="/api/remote-tasks", tags=["remote-tasks"])
_store = RemoteTaskStore()


def start_remote_tasks() -> None:
    _store.start()


async def stop_remote_tasks() -> None:
    await _store.close()


@router.get("/environments")
async def environments(q: str = "") -> dict[str, Any]:
    return {"environments": await _store.environments(q)}


@router.put("/environments")
async def save_environment(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"environment": await _store.save_environment(body)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/environments/{alias}/test")
async def test_environment(alias: str) -> dict[str, Any]:
    if alias not in {item["alias"] for item in await _store.environments()}:
        raise HTTPException(status_code=404, detail="SSH Host 别名不存在")
    return await _store.ssh.test(alias)


@router.post("")
async def create_task(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"task": await _store.create_task(body)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_tasks(environment: str = "") -> dict[str, Any]:
    return {"tasks": await _store.list_tasks(environment)}


@router.get("/snapshots")
async def list_snapshots() -> dict[str, Any]:
    return {"snapshots": await _store.list_snapshots()}


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    task = await _store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="远端任务不存在")
    return {"task": task}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, Any]:
    task = await _store.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="远端任务不存在")
    return {"task": task}


@router.post("/{task_id}/retry")
async def retry_task(task_id: str) -> dict[str, Any]:
    task = await _store.retry(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="远端任务不存在")
    return {"task": task}


@router.post("/{task_id}/attempts/{attempt_id}/apply")
async def apply_attempt(task_id: str, attempt_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _store.apply_attempt(task_id, attempt_id, str(body.get("workspace", "")))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/snapshots")
async def create_snapshot(body: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return {"snapshot": await _store.snapshot(body, request.app.state.services)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


