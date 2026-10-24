"""Integrations, notifications, telegram and hub surface (``/api/integrations, /api/notifications, /api/channels/telegram, /api/hub``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
import asyncio
import json

from pathlib import Path

from fastapi import Response

from atlas.config import get_config
from atlas.ssh import ssh_workspaces
from atlas.runtime import hub_control
from atlas.scheduler import ScheduledTask
router = APIRouter()


@router.get("/api/busy")
async def get_busy_status() -> dict[str, Any]:
    from atlas.notifications.busy import status
    return status()


@router.post("/api/busy")
async def update_busy_status(req: dict[str, Any]) -> dict[str, Any]:
    from atlas.notifications.busy import set_busy
    seconds = req.get("seconds")
    if seconds is not None and (not isinstance(seconds, (int, float)) or seconds < 0 or seconds > 30 * 86400):
        raise HTTPException(status_code=422, detail="seconds must be between 0 and 30 days, or null")
    return set_busy(float(seconds) if seconds else None)


def _idle_queue():
    from atlas.background_tasks import IdleTaskQueue
    return IdleTaskQueue(get_config().db_path.parent / "idle-tasks.db")


@router.get("/api/idle-tasks")
async def list_idle_tasks() -> dict[str, Any]:
    return {"tasks": _idle_queue().list()}


@router.post("/api/idle-tasks", status_code=201)
async def add_idle_task(req: dict[str, Any]) -> dict[str, Any]:
    import uuid
    try:
        return _idle_queue().add(str(req.get("id") or uuid.uuid4().hex), str(req.get("prompt") or ""), str(req.get("workspace") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/idle-tasks/order")
async def reorder_idle_tasks(req: dict[str, Any]) -> dict[str, Any]:
    try:
        _idle_queue().reorder(req.get("ids", []))
        return {"tasks": _idle_queue().list()}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/idle-tasks/{task_id}")
async def remove_idle_task(task_id: str) -> dict[str, Any]:
    _idle_queue().remove(task_id)
    return {"deleted": True}


@router.post("/api/idle-tasks/{task_id}/run-now")
async def run_idle_task_now(task_id: str) -> dict[str, Any]:
    if not _idle_queue().request_run_now(task_id):
        raise HTTPException(status_code=404, detail="queued task not found")
    return {"queued": True}


@router.get("/api/mail-trigger")
async def get_mail_trigger() -> dict[str, Any]:
    from atlas.background_tasks import mail_trigger_config
    return mail_trigger_config()


@router.put("/api/mail-trigger")
async def put_mail_trigger(req: dict[str, Any]) -> dict[str, Any]:
    from atlas.background_tasks import save_mail_trigger_config
    try:
        return save_mail_trigger_config(req, str(req.get("password")) if req.get("password") else None)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value



@router.get("/api/integrations")
async def list_integrations(
    services: Annotated[AppServices, Depends(get_app_services)],
    refresh: bool = Query(False),
) -> dict[str, Any]:
    capability_bus = _service("capability_bus", services)
    mcp_client = _service("mcp_client", services)
    agent_backend_host = _service("agent_backend_host", services)
    browser_use = _service("browser_use", services)
    """Return the shared upstream capability registry."""
    if capability_bus is None:
        return {"count": 0, "ready": 0, "degraded": 0, "capabilities": []}
    result = await asyncio.to_thread(capability_bus.status, refresh)
    runtime = mcp_client.get_runtime_status() if mcp_client else {"servers": []}
    server_states = {item["name"]: item for item in runtime.get("servers", [])}
    server_ids = {"playwright": "mcp.playwright", "chrome-devtools": "mcp.chrome_devtools"}
    for record in result["capabilities"]:
        server_name = next(
            (name for name, item_id in server_ids.items() if item_id == record["id"]), None,
        )
        if server_name and server_name in server_states:
            server = server_states[server_name]
            record["connected"] = bool(server.get("connected"))
            if not server.get("connected") and server.get("blocking_reason"):
                record["last_error"] = server["blocking_reason"]
        if record["id"].startswith("agent.") and agent_backend_host:
            backend_name = record["id"].split(".", 1)[1]
            record["connected"] = backend_name in agent_backend_host.connected_names()
            record["smoke_verified"] = backend_name in agent_backend_host.smoke_verified
            record["status"] = (
                "ready" if record["smoke_verified"] else
                "misconfigured"
                if record["authenticated"] is False or record["configured"] is False
                else "degraded"
            )
        if record["id"] == "browser.browser_use" and browser_use:
            record["connected"] = bool(browser_use._sessions)
            record["authenticated"] = browser_use.authenticated
            record["smoke_verified"] = browser_use.smoke_verified
            if browser_use.last_error:
                record["last_error"] = browser_use.last_error
            record["status"] = (
                "misconfigured" if browser_use.authenticated is False else
                "ready" if browser_use.smoke_verified else "degraded"
            )
    return result


@router.get("/api/notifications/status")
async def notification_status(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    notifications = services.notifications
    if notifications is None:
        from atlas import server as _atlas_server

        notifications = _atlas_server.notifications
    assert notifications is not None
    return notifications.status()


@router.get("/api/channels/telegram")
async def get_telegram_channel(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    telegram_service = _service("telegram_service", services)
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    return telegram_service.settings()


@router.put("/api/channels/telegram")
async def put_telegram_channel(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    telegram_service = _service("telegram_service", services)
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    workspace = req.get("default_workspace")
    if workspace:
        try:
            if workspace.startswith("ssh://"):
                ssh_workspaces.parse_workspace(workspace)
            elif not Path(workspace).is_absolute():
                raise ValueError("工作目录必须是绝对路径或 SSH 地址。")
        except (AttributeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return telegram_service.update_settings(req)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/channels/telegram/test")
async def test_telegram_channel(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    telegram_service = _service("telegram_service", services)
    if telegram_service is None:
        raise HTTPException(status_code=503, detail="Telegram 通道尚未就绪。")
    try:
        return await telegram_service.test_token()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/hub/status")
async def hub_status(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Report the background Hub's running state and scheduler summary."""
    return await hub_control.status()


@router.post("/api/hub/start")
async def hub_start(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Start the detached background Hub (no-op when already running)."""
    return await hub_control.start()


@router.post("/api/hub/stop")
async def hub_stop(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Gracefully stop the background Hub."""
    return await hub_control.stop()


@router.get("/api/hub/tasks")
async def hub_tasks(
    services: Annotated[AppServices, Depends(get_app_services)],
    response: Response,
) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    return {"tasks": [task.to_dict() for task in scheduler.list_tasks()]}


@router.post("/api/hub/tasks")
async def hub_create_task(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any], response: Response,
) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    message = str(req.get("message", "")).strip()
    if not message or not str(req.get("id", "")).strip():
        raise HTTPException(status_code=400, detail="id and message are required")
    try:
        task = ScheduledTask.from_dict({
            "id": str(req["id"]), "name": str(req.get("name", req["id"])),
            "description": str(req.get("description", "")),
            "trigger_type": str(req.get("trigger_type", "interval")),
            "trigger_args": dict(req.get("trigger_args", {}) or {}),
            "action": f"agent:{message}", "goal": str(req.get("goal", "")),
        })
        return (await scheduler.add_task(task)).to_dict()
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/hub/tasks/{task_id}/run")
async def hub_run_task(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str, response: Response,
) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    if not await scheduler.run_now(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "triggered", "task_id": task_id}


@router.delete("/api/hub/tasks/{task_id}")
async def hub_delete_task(
    services: Annotated[AppServices, Depends(get_app_services)],
    task_id: str, response: Response,
) -> dict[str, Any]:
    response.headers["Deprecation"] = "true"
    scheduler = services.scheduler
    if scheduler is None:
        from atlas import server as _atlas_server

        scheduler = _atlas_server.scheduler
    assert scheduler is not None
    if not await scheduler.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task_id": task_id}


@router.post("/api/notifications/test")
async def notification_test(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Send a test notification to every configured target."""
    notifications = services.notifications
    if notifications is None:
        from atlas import server as _atlas_server

        notifications = _atlas_server.notifications
    assert notifications is not None
    return await notifications.notify(
        "Atlas notification test", "If you can read this, notifications work.",
    )


@router.get("/api/notifications/urls")
async def get_notification_urls(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    notifications = services.notifications
    if notifications is None:
        from atlas import server as _atlas_server

        notifications = _atlas_server.notifications
    assert notifications is not None
    return {"urls": notifications.urls}


@router.put("/api/notifications/urls")
async def set_notification_urls(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    """Persist notification target URLs (Apprise) and apply them immediately."""
    notifications = services.notifications
    if notifications is None:
        from atlas import server as _atlas_server

        notifications = _atlas_server.notifications
    assert notifications is not None
    urls = req.get("urls")
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise HTTPException(status_code=400, detail="urls must be a list of strings")
    notifications.set_urls([u.strip() for u in urls if u.strip()])
    path = get_config().db_path.parent / "notification-urls.json"
    path.write_text(json.dumps({"urls": notifications.urls}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


class IntegrationToggleRequest(BaseModel):
    enabled: bool


@router.patch("/api/integrations/{capability_id}/enabled")
async def set_integration_enabled(
    services: Annotated[AppServices, Depends(get_app_services)],
    capability_id: str, req: IntegrationToggleRequest,
) -> dict[str, Any]:
    """Enable or disable an optional integration for this runtime."""
    capability_bus = _service("capability_bus", services)
    mcp_client = _service("mcp_client", services)
    if capability_bus is None or not await asyncio.to_thread(
        capability_bus.set_enabled, capability_id, req.enabled,
    ):
        raise HTTPException(status_code=404, detail=f"Integration not found: {capability_id}")
    server_names = {"mcp.playwright": "playwright", "mcp.chrome_devtools": "chrome-devtools"}
    server_name = server_names.get(capability_id)
    if server_name and mcp_client:
        configured = mcp_client.get_server_config(server_name)
        if configured is not None:
            if req.enabled:
                await mcp_client.restart_server(server_name)
            else:
                await mcp_client.disconnect_server(server_name)
    return next(
        item for item in (await list_integrations())["capabilities"]
        if item["id"] == capability_id
    )


# ---------------------------------------------------------------------------
# MCP Server Management
# ---------------------------------------------------------------------------
