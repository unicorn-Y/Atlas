"""Kanban, recipe and profile records surface (``/api/kanban, /api/recipes, /api/profiles``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch
    (``_task_store`` is monkeypatched by route tests) and the TOML store
    builders keep living beside their remaining server-side callers."""
    import atlas.server

    return atlas.server


@router.get("/api/kanban/boards")
async def list_kanban_boards(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return {"boards": _server()._kanban_store().boards()}


@router.post("/api/kanban/boards", status_code=201)
async def create_kanban_board(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    try:
        board = _server()._kanban_store().create_board(str(req.get("name", "")), req.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return board


@router.get("/api/kanban/boards/{board_id}/tasks")
async def list_kanban_tasks(
    services: Annotated[AppServices, Depends(get_app_services)],
    board_id: str,
) -> dict[str, Any]:
    return {"tasks": _server()._kanban_store().tasks(board_id)}


@router.post("/api/kanban/boards/{board_id}/tasks", status_code=201)
async def create_kanban_task(
    services: Annotated[AppServices, Depends(get_app_services)],
    board_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _server()._kanban_store().create_task(board_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/api/kanban/boards/{board_id}/tasks/{task_id}")
async def update_kanban_task(
    services: Annotated[AppServices, Depends(get_app_services)],
    board_id: str, task_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _server()._kanban_store().update_task(board_id, task_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/recipes")
async def list_recipes(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return {"recipes": _server()._task_store("recipes").list()}


@router.post("/api/recipes", status_code=201)
async def create_recipe(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _server()._task_store("recipes").put(_validate_recipe(req))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/recipes/{recipe_id}")
async def update_recipe(
    services: Annotated[AppServices, Depends(get_app_services)],
    recipe_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    store = _server()._task_store("recipes")
    old = store.get(recipe_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    try:
        return store.put(_validate_recipe({**old, **req, "id": recipe_id, "created_at": old["created_at"]}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/recipes/{recipe_id}")
async def delete_recipe(
    services: Annotated[AppServices, Depends(get_app_services)],
    recipe_id: str,
) -> dict[str, str]:
    if not _server()._task_store("recipes").delete(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"status": "deleted"}


@router.post("/api/recipes/{recipe_id}/render")
async def render_recipe(
    services: Annotated[AppServices, Depends(get_app_services)],
    recipe_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    recipe = _server()._task_store("recipes").get(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    supplied = req.get("params", {})
    if not isinstance(supplied, dict):
        raise HTTPException(status_code=422, detail="params must be an object")
    missing = []
    rendered = recipe["prompt"]
    for param in recipe.get("params", []):
        name = param["name"]
        value = supplied.get(name, param.get("default"))
        if value is None:
            missing.append(name)
        else:
            rendered = rendered.replace("{{" + name + "}}", str(value))
    if missing:
        raise HTTPException(status_code=422, detail={"missing": missing})
    return {key: recipe.get(key) for key in ("active_skills", "mode", "workspace", "profile_id")} | {"prompt": rendered}


@router.post("/api/recipes/from-run", status_code=201)
async def recipe_from_run(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    runtime_mgr = services.runtime_mgr
    if runtime_mgr is None:
        runtime_mgr = _server().runtime_mgr
    assert runtime_mgr is not None
    run = runtime_mgr.runs.get(str(req.get("run_id", "")))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    conv = await memory.get_conversation(run.conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Run conversation not found")
    messages = await memory.get_conversation_messages(conv["id"], limit=1000)
    user_message = run.user_input or next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)
    if not user_message:
        raise HTTPException(status_code=422, detail="Run has no user message")
    try:
        return _server()._task_store("recipes").put(_validate_recipe({
            "name": req.get("name", "Saved run"), "description": "从一次任务生成",
            "prompt": user_message, "params": [], "active_skills": run.active_skills,
            "mode": run.mode, "workspace": conv.get("workspace") or run.workspace,
            "profile_id": run.profile_id,
        }))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/profiles")
async def list_profiles(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    profiles = _server()._profile_store().list()
    for profile in profiles:
        profile.setdefault("tools", {}).setdefault("allow", None)
        profile["tools"].setdefault("deny", [])
        profile.setdefault("model", None)
        profile.setdefault("reasoning_effort", None)
    return {"profiles": profiles}


@router.post("/api/profiles", status_code=201)
async def create_profile(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _server()._profile_store().put(_validate_profile(req))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_profile(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "name", "description", "model", "reasoning_effort", "instructions",
               "active_skills", "tools", "mode", "created_at", "updated_at"}
    if set(value) - allowed:
        raise ValueError("profile contains unsupported fields")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ValueError("name is required")
    if value.get("mode", "act") not in {"act", "plan"}:
        raise ValueError("mode must be 'act' or 'plan'")
    if value.get("reasoning_effort") not in {None, "minimal", "low", "medium", "high"}:
        raise ValueError("invalid reasoning_effort")
    tools = value.get("tools", {"allow": None, "deny": []})
    if not isinstance(tools, dict) or (tools.get("allow") is not None and not isinstance(tools.get("allow"), list)):
        raise ValueError("tools.allow must be a list or null")
    if not isinstance(tools.get("deny", []), list):
        raise ValueError("tools.deny must be a list")
    tools = {"allow": tools.get("allow"), "deny": tools.get("deny", [])}
    if any(not isinstance(item, str) for item in (tools["allow"] or []) + tools["deny"]):
        raise ValueError("tool names must be strings")
    if not isinstance(value.get("active_skills", []), list):
        raise ValueError("active_skills must be a list")
    if any(not isinstance(item, str) for item in value.get("active_skills", [])):
        raise ValueError("active_skills must contain strings")
    if value.get("model") is not None and not isinstance(value.get("model"), str):
        raise ValueError("model must be a string")
    if not isinstance(value.get("description", ""), str) or not isinstance(value.get("instructions", ""), str):
        raise ValueError("description and instructions must be strings")
    return {**value, "description": value.get("description", ""), "instructions": value.get("instructions", ""),
            "active_skills": value.get("active_skills", []), "tools": tools, "mode": value.get("mode", "act")}


@router.put("/api/profiles/{profile_id}")
async def update_profile(
    services: Annotated[AppServices, Depends(get_app_services)],
    profile_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    store = _server()._profile_store()
    old = store.get(profile_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        return store.put(_validate_profile({**old, **req, "id": profile_id, "created_at": old["created_at"]}))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/profiles/{profile_id}")
async def delete_profile(
    services: Annotated[AppServices, Depends(get_app_services)],
    profile_id: str,
) -> dict[str, str]:
    if profile_id in {"default", "architect", "reviewer"}:
        raise HTTPException(status_code=409, detail="Built-in profiles cannot be deleted")
    if not _server()._profile_store().delete(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "deleted"}


def _validate_recipe(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"id", "name", "description", "prompt", "params", "active_skills", "mode",
               "workspace", "profile_id", "created_at", "updated_at"}
    if set(value) - allowed:
        raise ValueError("recipe contains unsupported fields")
    required = ("name", "description", "prompt")
    if any(not isinstance(value.get(key), str) for key in required):
        raise ValueError("name, description, and prompt must be strings")
    if value.get("mode", "act") not in {"act", "plan"}:
        raise ValueError("mode must be 'act' or 'plan'")
    params = value.get("params", [])
    if (not isinstance(params, list) or any(
        not isinstance(item, dict) or set(item) - {"name", "label", "default"}
        or not isinstance(item.get("name"), str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["name"])
        for item in params
    )):
        raise ValueError("params must be a list of named parameter objects")
    names = [item["name"] for item in params]
    if len(names) != len(set(names)):
        raise ValueError("parameter names must be unique")
    if not isinstance(value.get("active_skills", []), list):
        raise ValueError("active_skills must be a list")
    if any(not isinstance(item, str) for item in value.get("active_skills", [])):
        raise ValueError("active_skills must contain strings")
    for key in ("workspace", "profile_id"):
        if value.get(key) is not None and not isinstance(value.get(key), str):
            raise ValueError(f"{key} must be a string")
    return {**value, "params": params, "active_skills": value.get("active_skills", []),
            "mode": value.get("mode", "act")}
