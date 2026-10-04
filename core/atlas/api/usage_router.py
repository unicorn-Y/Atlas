"""Hooks, commands, usage, safety and ASR surface (``/api/hooks, /api/commands, /api/usage, /api/safety, /api/asr``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from atlas.asr import ASRManager
from atlas.config import get_config
from atlas.safety.policy import (
    get_log as get_safety_log,
    get_settings as get_safety_settings,
    rule_catalog as get_safety_rules,
    update_settings as update_safety_settings,
)
from atlas.runtime.commands import list_user_commands, render_user_command, UserCommand
from atlas.runtime.hooks import HookStore

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


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


@router.get("/api/hooks")
async def list_hooks(
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace: str | None = None,
) -> dict[str, Any]:
    store = _server()._hook_store()
    return {"hooks": store.list_all(workspace), "logs": store.recent_logs()}


@router.post("/api/hooks/{hook_id}/enabled")
async def set_hook_enabled(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _server()._hook_store().set_hook_enabled(
            hook_id, bool(req.get("enabled", True)), req.get("workspace"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Hook 不存在") from exc


@router.post("/api/hooks", status_code=201)
async def create_hook(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    hooks = _server()._hook_store().list()
    hook = {"id": str(req.get("id", "")).strip(),
            "event": str(req.get("event", "")),
            "command": str(req.get("command", "")),
            "timeout_s": int(req.get("timeout_s", 30)),
            "enabled": bool(req.get("enabled", True))}
    if not hook["id"] or hook["event"] not in HookStore.EVENTS or not hook["command"]:
        raise HTTPException(status_code=422, detail="id, valid event, and command are required")
    if not 1 <= hook["timeout_s"] <= 300 or any(item["id"] == hook["id"] for item in hooks):
        raise HTTPException(status_code=409, detail="invalid timeout or duplicate hook id")
    hooks.append(hook)
    _server()._hook_store().save(hooks)
    return hook


@router.put("/api/hooks/{hook_id}")
async def update_hook(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    store = _server()._hook_store()
    hooks = store.list()
    for index, hook in enumerate(hooks):
        if hook["id"] != hook_id:
            continue
        updated = {**hook, **req, "id": hook_id}
        if updated.get("event") not in HookStore.EVENTS or not updated.get("command"):
            raise HTTPException(status_code=422, detail="valid event and command are required")
        updated["timeout_s"] = int(updated.get("timeout_s", 30))
        if not 1 <= updated["timeout_s"] <= 300:
            raise HTTPException(status_code=422, detail="timeout_s must be 1..300")
        hooks[index] = updated
        store.save(hooks)
        return updated
    raise HTTPException(status_code=404, detail="Hook not found")


@router.delete("/api/hooks/{hook_id}")
async def delete_hook(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str,
) -> dict[str, str]:
    store = _server()._hook_store()
    hooks = store.list()
    filtered = [item for item in hooks if item.get("id") != hook_id]
    if len(filtered) == len(hooks):
        raise HTTPException(status_code=404, detail="Hook not found")
    store.save(filtered)
    return {"status": "ok", "hook_id": hook_id}


@router.post("/api/hooks/{hook_id}/test")
async def test_hook(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str, workspace: str | None = None,
) -> dict[str, Any]:
    try:
        return await _server()._hook_store().test(hook_id, cwd=workspace)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Hook not found") from exc


# ---------------------------------------------------------------------------
# Custom commands (E5)
# ---------------------------------------------------------------------------

def _user_commands(workspace: str | None = None) -> list[UserCommand]:
    """Atlas, Claude, plugin, and Recipe commands through the shared listing."""
    return list_user_commands(
        workspace=Path(workspace).expanduser() if workspace else None,
        user_dir=get_config().db_path.parent,
        plugin_sources=_server()._plugin_command_sources(),
        recipes=_server()._task_store("recipes").list(),
    )


def _render_recipe_command(recipe: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """Map a Recipe onto the command renderer contract ({{param}} + defaults)."""
    prompt = str(recipe.get("prompt", ""))
    for param in recipe.get("params", []):
        name = str(param.get("name", ""))
        value = values.get(name, param.get("default"))
        if value is not None:
            prompt = prompt.replace("{{" + name + "}}", str(value))
    # Absent keys stay absent: the renderer distinguishes "unset" from None.
    rendered = {"prompt": prompt}
    for key in ("active_skills", "mode", "workspace", "profile_id"):
        if recipe.get(key) is not None:
            rendered[key] = recipe[key]
    return rendered


@router.get("/api/commands")
async def list_commands(
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace: str | None = None,
) -> dict[str, Any]:
    """List user-defined, plugin-contributed, and Recipe slash commands."""
    return {"commands": [item.to_dict() for item in _user_commands(workspace)]}


@router.post("/api/commands/render")
async def render_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    """Expand one selected command body into a runnable prompt."""
    command_id = str(req.get("id", ""))
    command = next(
        (item for item in _user_commands(req.get("workspace")) if item.id == command_id), None,
    )
    if command is None:
        raise HTTPException(status_code=404, detail=f"Command not found: {command_id}")
    rendered = render_user_command(
        command, str(req.get("arguments", "")),
        recipes=_server()._task_store("recipes").list(),
        recipe_renderer=_render_recipe_command,
    )
    return asdict(rendered)



# ---------------------------------------------------------------------------
# Runtime Protocol
# ---------------------------------------------------------------------------


@router.get("/api/runtime/protocol")
async def runtime_protocol(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    """Advertise Runtime Event Protocol version."""
    return {"version": "1.10"}


@router.get("/api/usage")
async def get_usage(
    services: Annotated[AppServices, Depends(get_app_services)],
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|conversation|model)$"),
) -> dict[str, Any]:
    usage_ledger = _service("usage_ledger", services)
    if usage_ledger is None:
        return {"rows": [], "totals": {"runs": 0, "input_tokens": 0,
                "output_tokens": 0, "cached_input_tokens": 0,
                "cache_hit_rate": None, "est_cost": 0}}
    return await usage_ledger.query(start=from_, end=to, group_by=group_by)


@router.get("/api/safety")
async def get_safety(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return {"settings": get_safety_settings(), "rules": get_safety_rules()}


@router.put("/api/safety")
async def put_safety(
    services: Annotated[AppServices, Depends(get_app_services)],
    body: dict[str, Any],
) -> dict[str, Any]:
    try:
        return {"settings": update_safety_settings(body), "rules": get_safety_rules()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/safety/log")
async def get_safety_review_log(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {"rows": get_safety_log(limit)}


@router.get("/api/asr/status")
async def get_asr_status(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    global asr_manager
    if asr_manager is None:
        asr_manager = ASRManager()
    return asr_manager.status()


@router.post("/api/asr/download")
async def download_asr_model(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    global asr_manager
    if asr_manager is None:
        asr_manager = ASRManager()
    try:
        await asr_manager.download()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return asr_manager.status()


@router.websocket("/ws/asr")
async def asr_websocket(
    services: Annotated[AppServices, Depends(get_app_services)],
    websocket: WebSocket,
) -> None:
    global asr_manager
    await websocket.accept()
    if asr_manager is None:
        asr_manager = ASRManager()
    if not asr_manager.status()["ready"]:
        await websocket.send_json({"type": "error", "detail": "请先下载本地语音模型。"})
        await websocket.close(code=1013)
        return
    try:
        while True:
            packet = await websocket.receive()
            if packet.get("bytes") is not None:
                data = packet["bytes"]
                if len(data) > 128 * 1024 or len(data) % 2:
                    await websocket.send_json({"type": "error", "detail": "音频帧大小或 PCM 格式无效。"})
                    continue
                partials, finals = await asyncio.to_thread(asr_manager.process_frame, data)
                for text in partials:
                    await websocket.send_json({"type": "partial", "text": text})
                for text in finals:
                    await websocket.send_json({"type": "final", "text": text})
            elif packet.get("text") is not None:
                try:
                    message = json.loads(packet["text"])
                except ValueError:
                    continue
                if message.get("type") == "end":
                    partials, finals = await asyncio.to_thread(asr_manager.process_frame, b"", final=True)
                    for text in finals:
                        await websocket.send_json({"type": "final", "text": text})
                    await websocket.send_json({"type": "ended"})
                    await websocket.close()
                    return
    except WebSocketDisconnect:
        return
    except Exception as exc:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1011)
