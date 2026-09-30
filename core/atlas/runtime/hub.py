"""Atlas Background Hub — detached host for long-lived agent work.

The Hub is a separate localhost-only process that can own:

- the canonical scheduler store (``data/schedules.toml``), so scheduled agent
  tasks survive when the Electron desktop app is closed;
- the DBOS durable backend, so those tasks survive hub/desktop restarts;
- a real local AgentOrchestrator (model + memory + local execution), which is
  what actually executes the scheduled agent messages.

The desktop server stays the interactive plane; the Hub is the background
plane. Control surface (127.0.0.1 only): ``GET /health``, ``GET /status``,
``GET/POST/DELETE /tasks``, ``POST /tasks/{id}/run``, ``POST /shutdown``.

Run directly with ``python -m atlas.runtime.hub`` or via ``atlas hub start``.
"""

from __future__ import annotations

import json
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
    from atlas.telegram import TelegramService

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
        conversation_id = f"hub-{task_id}-{run_id}"
        print(f"[hub] task {task_id} run {run_id}: {message}", flush=True)
        events = orchestrator.run(message, conversation_id)
        failed = False
        async for _event in events:
            if isinstance(_event, dict) and _event.get("type") == "error":
                failed = True
        await scheduler.dispatch_event(
            "run.failed" if failed else "run.completed",
            {"run_id": run_id, "conversation_id": conversation_id, "task_id": task_id},
        )
        await notifier.notify(
            f"Atlas Hub task {task_id} finished",
            f"Background task completed. Message: {message[:200]}",
        )

    scheduler = AtlasScheduler(
        agent_callback=agent_callback,
        schedules_path=cfg.db_path.parent / "schedules.toml", role="hub",
    )
    await scheduler.start()

    telegram_active: dict[int, tuple[str, str, asyncio.Event]] = {}

    def hub_owns_lease() -> bool:
        try:
            lease = json.loads(scheduler._lease_path.read_text(encoding="utf-8"))
            return lease.get("token") == scheduler._lease_token
        except (OSError, ValueError, TypeError):
            return False

    async def telegram_task(text: str, user_id: int, channel: Any) -> dict[str, str]:
        config = channel.settings()
        title = text.strip()[:30] or "手机任务"
        conversation_id = await memory.create_conversation(title)
        await memory.update_conversation(
            conversation_id, workspace=config["default_workspace"] or None,
            permission_mode="ask_writes", source="telegram",
        )
        run_id = uuid.uuid4().hex
        cancel_event = asyncio.Event()
        telegram_active[user_id] = (conversation_id, title, cancel_event)

        async def approve(event_id: str, tool_name: str, _arguments: dict[str, Any]) -> str:
            future = await channel.request_approval(
                user_id, run_id, event_id, f"需要确认执行 {tool_name}。",
            )
            cancel_waiter = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {future, cancel_waiter}, timeout=600,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                return future.result() if future in done else "deny"
            finally:
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)

        await memory.save_message(
            conversation_id, "user", text, {"run_id": run_id, "source": "telegram"},
        )
        response: list[str] = []
        failed = None
        try:
            async for event in orchestrator.run(
                text, conversation_id=conversation_id, run_id=run_id,
                workspace=config["default_workspace"] or None,
                permission_mode="ask_writes", cancel_event=cancel_event,
                approval_callback=approve,
            ):
                if event.get("type") == "chunk":
                    response.append(str(event.get("content", "")))
                elif event.get("type") == "error":
                    failed = str(event.get("detail", "任务执行失败。"))
                    break
            if failed:
                raise RuntimeError(failed)
            changed = {file["path"] for item in orchestrator.checkpoints.list_checkpoints(run_id=run_id)
                       for file in item.get("files", [])}
            answer = "".join(response)[:1500]
            return {"conversation_id": conversation_id, "run_id": run_id,
                    "summary": f"{answer}\n\n改动文件数：{len(changed)}"}
        finally:
            telegram_active.pop(user_id, None)

    async def telegram_command(command: str, user_id: int) -> str:
        name = command.split(maxsplit=1)[0].split("@", 1)[0].casefold()
        if name == "/status":
            active = telegram_active.get(user_id)
            return f"正在运行：{active[1]}" if active else "目前没有运行中的任务。"
        if name == "/stop":
            active = telegram_active.get(user_id)
            if not active:
                return "目前没有可停止的任务。"
            active[2].set()
            return f"已请求停止：{active[1]}"
        conversations = [item for item in await memory.list_conversations(limit=100)
                         if item.get("source") == "telegram"]
        if name == "/list":
            return "\n".join(item["title"] for item in conversations[:5]) or "还没有手机任务。"
        return "可用命令：/list、/stop、/status"

    telegram_service = TelegramService(
        cfg.db_path.parent / "telegram.json", owns_lease=hub_owns_lease,
        submit_task=telegram_task, command_handler=telegram_command,
    )
    telegram_service.start()

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

    await telegram_service.stop()
    await scheduler.stop()
    durable.stop()
    await local.shutdown()
    await memory.close()
    print("[hub] stopped", flush=True)


def schedules_path() -> Path:
    return get_config().db_path.parent / "schedules.toml"


if __name__ == "__main__":
    import asyncio

    asyncio.run(hub_main())
