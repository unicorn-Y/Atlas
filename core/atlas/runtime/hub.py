"""Atlas Background Hub — detached host for long-lived agent work.

The Hub is a separate localhost-only process that owns:

- a scheduler over its own task store (``data/hub-schedules.toml``), so
  scheduled agent tasks fire even when the Electron desktop app is closed;
- the DBOS durable backend, so those tasks survive hub/desktop restarts;
- a real local AgentOrchestrator (model + memory + local execution), which is
  what actually executes the scheduled agent messages.

The desktop server stays the interactive plane; the Hub is the background
plane. Control surface (127.0.0.1 only): ``GET /health``, ``GET /status``,
``GET/POST/DELETE /tasks``, ``POST /tasks/{id}/run``, ``POST /shutdown``.

Run directly with ``python -m atlas.runtime.hub`` or via ``atlas hub start``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from atlas.config import get_config

DEFAULT_PORT = 8791


def _hub_port() -> int:
    try:
        return int(os.environ.get("ATLAS_HUB_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def create_hub_app(scheduler: Any = None) -> Any:
    """Build the Hub control app around a scheduler instance."""
    from fastapi import FastAPI, HTTPException

    from atlas.origin_guard import OriginGuard

    app = FastAPI(title="Atlas Hub", version="0.1.0")
    # Only the desktop backend (server-side, no Origin) and the CLI talk to the Hub; web pages
    # must not be able to run tasks or shut it down with a bare cross-site POST.
    app.add_middleware(OriginGuard)
    state: dict[str, Any] = {"scheduler": scheduler, "started_at": ""}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "role": "hub"}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        scheduler = state["scheduler"]
        return {
            "status": "ok",
            "scheduler_running": bool(scheduler and scheduler._started),
            "task_count": scheduler.task_count if scheduler else 0,
            "observability": scheduler.observability_snapshot() if scheduler else {},
        }

    @app.get("/tasks")
    async def list_tasks() -> dict[str, Any]:
        scheduler = state["scheduler"]
        return {"tasks": [t.to_dict() for t in scheduler.list_tasks()] if scheduler else []}

    @app.post("/tasks")
    async def create_task(req: dict[str, Any]) -> dict[str, Any]:
        from atlas.scheduler import ScheduledTask

        scheduler = state["scheduler"]
        if scheduler is None:
            raise HTTPException(status_code=503, detail="Hub scheduler unavailable")
        message = str(req.get("message", "")).strip()
        task_id = str(req.get("id") or "").strip()
        if not task_id:
            raise HTTPException(status_code=400, detail="id is required")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        try:
            task = ScheduledTask.from_dict({
                "id": task_id,
                "name": str(req.get("name", task_id)),
                "description": str(req.get("description", "")),
                "trigger_type": str(req.get("trigger_type", "interval")),
                "trigger_args": dict(req.get("trigger_args", {}) or {}),
                "action": f"agent:{message}",
                "goal": str(req.get("goal", "")),
            })
            created = await scheduler.add_task(task)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return created.to_dict()

    @app.delete("/tasks/{task_id}")
    async def delete_task(task_id: str) -> dict[str, str]:
        scheduler = state["scheduler"]
        if scheduler is None or not await scheduler.delete_task(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "ok", "task_id": task_id}

    @app.post("/tasks/{task_id}/run")
    async def run_task(task_id: str) -> dict[str, Any]:
        scheduler = state["scheduler"]
        if scheduler is None or not await scheduler.run_now(task_id):
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "triggered", "task_id": task_id}

    @app.post("/shutdown")
    async def shutdown() -> dict[str, str]:
        state["shutdown"] = True
        return {"status": "shutting_down"}

    app.state.hub_state = state
    return app


async def hub_main() -> None:
    """Run the Hub process: scheduler + durable + a real local agent loop."""
    import asyncio
    import uuid

    import uvicorn

    from atlas.capabilities.durable.dbos_backend import DurableBackend
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager
    from atlas.scheduler import AtlasScheduler
    from atlas.notifications import NotificationBus
    from atlas.tools.local_execution import LocalExecutionRuntime

    cfg = get_config()
    memory = MemoryStore()
    await memory.init()
    manager = ModelManager()
    local = LocalExecutionRuntime()

    from atlas.agent import AgentOrchestrator

    orchestrator = AgentOrchestrator(manager, memory, local_execution=local)

    notifier = NotificationBus()

    async def agent_callback(task_id: str, message: str) -> None:
        run_id = uuid.uuid4().hex[:8]
        print(f"[hub] task {task_id} run {run_id}: {message}", flush=True)
        events = orchestrator.run(message, f"hub-{task_id}-{run_id}")
        async for _event in events:
            pass
        await notifier.notify(
            f"Atlas Hub task {task_id} finished",
            f"Background task completed. Message: {message[:200]}",
        )

    scheduler = AtlasScheduler(
        agent_callback=agent_callback,
        schedules_path=cfg.db_path.parent / "hub-schedules.toml",
    )
    await scheduler.start()

    durable = DurableBackend(cfg.db_path.parent / "dbos.sqlite")
    durable.set_dispatcher(
        lambda payload: agent_callback(
            str(payload.get("task_id", "adhoc")), str(payload.get("message", "")),
        ),
        asyncio.get_running_loop(),
    )
    durable.start()

    app = create_hub_app(scheduler)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=_hub_port(), log_level="warning",
    )
    server = uvicorn.Server(config)

    serve_task = asyncio.create_task(server.serve())
    print(f"[hub] listening on 127.0.0.1:{_hub_port()}", flush=True)
    while not serve_task.done():
        if app.state.hub_state.get("shutdown"):
            server.should_exit = True
            break
        await asyncio.sleep(0.5)
    await serve_task

    await scheduler.stop()
    durable.stop()
    await local.shutdown()
    await memory.close()
    print("[hub] stopped", flush=True)


def schedules_path() -> Path:
    return get_config().db_path.parent / "hub-schedules.toml"


if __name__ == "__main__":
    import asyncio

    asyncio.run(hub_main())
