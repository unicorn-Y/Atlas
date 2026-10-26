"""Hooks, commands, usage, safety and ASR surface (``/api/hooks, /api/commands, /api/usage, /api/safety, /api/asr``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
import structlog
import yaml

from atlas.asr import ASRManager
from atlas.config import get_config
from atlas.safety.policy import (
    get_log as get_safety_log,
    get_settings as get_safety_settings,
    rule_catalog as get_safety_rules,
    update_settings as update_safety_settings,
)
from atlas.runtime.commands import _frontmatter, list_user_commands, render_user_command, UserCommand
from atlas.runtime.hooks import HookStore

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()
log = structlog.get_logger(__name__)


def _get_asr_manager(services: AppServices) -> ASRManager:
    """Create the one lazy ASR service owned by this application container."""
    if services.asr_manager is None:
        services.asr_manager = ASRManager()
    return services.asr_manager


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

class AtlasUserCommandPayload(BaseModel):
    name: str | None = Field(default=None, max_length=63)
    description: str = Field(default="", max_length=500)
    argument_hint: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=100_000)


_ATLAS_COMMAND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}\Z")


def _atlas_command_path(name: str, *, create_root: bool = False) -> Path:
    """Resolve a flat Atlas-user command path without permitting traversal or symlinks."""
    if not _ATLAS_COMMAND_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="name must be a 1-63 character command slug")
    root = Path(get_config().db_path).expanduser().parent / "commands"
    if root.is_symlink():
        raise HTTPException(status_code=409, detail="Atlas commands directory cannot be a symbolic link")
    if not root.exists() and create_root:
        root.mkdir(parents=True, exist_ok=True)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Atlas user commands directory does not exist")
    if not root.is_dir():
        raise HTTPException(status_code=409, detail="Atlas commands path is not a directory")
    target = root / f"{name}.md"
    if target.is_symlink():
        raise HTTPException(status_code=409, detail="Symbolic-link command files are not managed")
    try:
        if target.resolve(strict=False).parent != root.resolve(strict=True):
            raise HTTPException(status_code=422, detail="Command path escapes the Atlas user directory")
    except OSError as exc:
        raise HTTPException(status_code=409, detail="Cannot safely resolve Atlas command path") from exc
    return target


def _ensure_no_casefold_collision(root: Path, name: str) -> None:
    for item in root.iterdir():
        if item.suffix == ".md" and item.stem.casefold() == name.casefold():
            raise HTTPException(status_code=409, detail="An Atlas command already uses this name")


def _read_atlas_command(name: str) -> tuple[dict[str, Any], str]:
    target = _atlas_command_path(name)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Atlas user command not found")
    try:
        metadata, body = _frontmatter(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=422, detail="Existing command frontmatter cannot be safely edited") from exc
    return metadata, body


def _command_document(metadata: dict[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{frontmatter}---\n\n{body}" + ("" if body.endswith("\n") else "\n")


def _atomic_write_command(target: Path, document: str, *, create_only: bool = False) -> None:
    temp_path: Path | None = None
    try:
        descriptor, raw_temp = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".tmp", dir=target.parent)
        temp_path = Path(raw_temp)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            # Windows ACL inheritance is the available protection on Windows.
            pass
        if create_only:
            # A hard-link create is atomic and refuses to clobber a file that appeared
            # after the earlier collision check. Both paths are in the same directory.
            os.link(temp_path, target)
            temp_path.unlink()
        else:
            os.replace(temp_path, target)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="An Atlas command already uses this name") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save Atlas command: {exc}") from exc
    finally:
        if temp_path is not None:
            with suppress(OSError):
                temp_path.unlink()


def _command_response(name: str, metadata: dict[str, Any], body: str) -> dict[str, Any]:
    hint = metadata.get("argument-hint") or ""
    if isinstance(hint, list):
        hint = " ".join(str(item) for item in hint)
    return {
        "id": f"atlas:{name}", "name": name,
        "description": str(metadata.get("description") or "").strip(),
        "argument_hint": str(hint).strip(), "body": body, "source": "atlas",
    }


@router.get("/api/commands/atlas-user/{name}")
async def get_atlas_user_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    metadata, body = _read_atlas_command(name)
    return _command_response(name, metadata, body)


@router.post("/api/commands/atlas-user", status_code=201)
async def create_atlas_user_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    payload: AtlasUserCommandPayload,
) -> dict[str, Any]:
    name = str(payload.name or "")
    target = _atlas_command_path(name, create_root=True)
    _ensure_no_casefold_collision(target.parent, name)
    if any(item.name.casefold() == name.casefold() for item in _user_commands()):
        raise HTTPException(status_code=409, detail="A command with this name is already available")
    metadata: dict[str, Any] = {}
    if payload.description.strip():
        metadata["description"] = payload.description.strip()
    if payload.argument_hint.strip():
        metadata["argument-hint"] = payload.argument_hint.strip()
    _atomic_write_command(target, _command_document(metadata, payload.body), create_only=True)
    return _command_response(name, metadata, payload.body)


@router.put("/api/commands/atlas-user/{name}")
async def update_atlas_user_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
    payload: AtlasUserCommandPayload,
) -> dict[str, Any]:
    if payload.name and payload.name != name:
        raise HTTPException(status_code=422, detail="Command names are immutable during editing")
    target = _atlas_command_path(name)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Atlas user command not found")
    metadata, _old_body = _read_atlas_command(name)
    # Keep unrelated Claude-compatible frontmatter (tool restrictions, model, mode, etc.)
    # intact when the Atlas editor changes only the visible summary and command body.
    for key, value in (("description", payload.description.strip()), ("argument-hint", payload.argument_hint.strip())):
        if value:
            metadata[key] = value
        else:
            metadata.pop(key, None)
    _atomic_write_command(target, _command_document(metadata, payload.body))
    return _command_response(name, metadata, payload.body)


@router.delete("/api/commands/atlas-user/{name}")
async def delete_atlas_user_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    name: str,
) -> dict[str, Any]:
    target = _atlas_command_path(name)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Atlas user command not found")
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not remove Atlas command: {exc}") from exc
    return {"id": f"atlas:{name}", "deleted": True}

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
    model: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    usage_ledger = _service("usage_ledger", services)
    if usage_ledger is None:
        return {"rows": [], "totals": {"runs": 0, "input_tokens": 0,
                "output_tokens": 0, "cached_input_tokens": 0,
                "cache_hit_rate": None, "est_cost": 0}}
    report = await usage_ledger.query(start=from_, end=to, group_by=group_by, model=model)
    model_rows = await usage_ledger.query(start=from_, end=to, group_by="model")
    return {**report, "models": [row["key"] for row in model_rows.get("rows", [])]}


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
    asr_manager = _get_asr_manager(services)
    return asr_manager.status()


@router.post("/api/asr/download")
async def download_asr_model(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    asr_manager = _get_asr_manager(services)
    try:
        await asr_manager.download()
    except Exception as exc:  # noqa: BLE001 — downloader libraries use transport-specific errors
        log.exception("asr.model_download_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return asr_manager.status()


@router.websocket("/ws/asr")
async def asr_websocket(
    services: Annotated[AppServices, Depends(get_app_services)],
    websocket: WebSocket,
) -> None:
    await websocket.accept()
    asr_manager = _get_asr_manager(services)
    if not asr_manager.status()["ready"]:
        await websocket.send_json({"type": "preparing", "detail": "首次使用正在自动下载并准备本地 SenseVoice 语音模型。"})
        preparation = asyncio.create_task(asr_manager.download())
        while not preparation.done():
            await websocket.send_json({"type": "progress", **asr_manager.status()})
            await asyncio.sleep(0.5)
        try:
            await preparation
        except Exception as exc:  # noqa: BLE001 — preserve transport detail for a recoverable user error
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1013)
            return
        await websocket.send_json({"type": "ready", **asr_manager.status()})
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
    except Exception as exc:  # noqa: BLE001 — decoder and VAD providers expose native exceptions
        log.exception("asr.websocket_failed")
        with suppress(Exception):
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1011)
