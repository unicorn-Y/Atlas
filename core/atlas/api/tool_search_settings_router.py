"""Persistent user default for full or on-demand tool schema loading."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.config import load_user_settings, save_user_settings

router = APIRouter()
MODES = {"all", "on-demand"}


class ToolSearchModeBody(BaseModel):
    mode: str


def _mode_from_settings(settings: dict[str, Any]) -> tuple[str, str]:
    saved = str(settings.get("tool_search_mode") or "").strip().lower()
    if saved in MODES:
        return saved, "user-settings.json"
    from atlas.config import get_config

    configured = get_config().get("library.tool_search_mode")
    if str(configured or "").lower() in MODES:
        return str(configured).lower(), "atlas.toml"
    deferred = get_config().get("library.defer_tools", True)
    return ("on-demand" if deferred else "all"), "atlas.toml"


@router.get("/api/settings/tool-search-mode")
async def get_tool_search_mode() -> dict[str, str]:
    mode, source = _mode_from_settings(load_user_settings())
    return {"mode": mode, "source": source}


@router.put("/api/settings/tool-search-mode")
async def set_tool_search_mode(body: ToolSearchModeBody) -> dict[str, str]:
    mode = body.mode.strip().lower()
    if mode not in MODES:
        raise HTTPException(status_code=422, detail="mode must be 'all' or 'on-demand'")
    settings = load_user_settings()
    settings["tool_search_mode"] = mode
    save_user_settings(settings)
    return {"mode": mode, "source": "user-settings.json"}


@router.delete("/api/settings/tool-search-mode")
async def reset_tool_search_mode() -> dict[str, str]:
    settings = load_user_settings()
    settings.pop("tool_search_mode", None)
    save_user_settings(settings)
    mode, source = _mode_from_settings(settings)
    return {"mode": mode, "source": source}
