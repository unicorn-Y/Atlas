"""User-local policy for sessions hosted by the WSL runtime."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["wsl-policy"])


class WslPolicyRequest(BaseModel):
    enabled: bool = True
    require_isolation: bool = False


def is_wsl_runtime() -> bool:
    """Detect the current Linux process environment without confusing WSL timeouts with policy."""
    import os
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in open("/proc/version", encoding="utf-8", errors="replace").read().lower()
    except OSError:
        return False


def get_wsl_policy() -> dict[str, bool]:
    settings = load_user_settings()
    value = settings.get("wsl_session_policy", {})
    if not isinstance(value, dict):
        value = {}
    return {
        "enabled": value.get("enabled", True) is True,
        "require_isolation": value.get("require_isolation", False) is True,
    }


def apply_wsl_session_policy(sandbox: dict[str, Any] | None, *, runtime_is_wsl: bool | None = None) -> dict[str, Any] | None:
    """Apply the local policy to a run and fail explicitly when WSL is disabled."""
    active = is_wsl_runtime() if runtime_is_wsl is None else runtime_is_wsl
    if not active:
        return sandbox
    policy = get_wsl_policy()
    if not policy["enabled"]:
        raise PermissionError("本机策略已禁用 WSL 会话")
    if policy["require_isolation"] and sandbox is None:
        return {"type": "docker", "network": False}
    return sandbox


@router.get("/api/settings/wsl-policy")
async def read_wsl_policy(services: AppServices = Depends(get_app_services)) -> dict[str, Any]:
    return {**get_wsl_policy(), "runtime_is_wsl": is_wsl_runtime(), "runtime": "wsl" if is_wsl_runtime() else "native"}


@router.put("/api/settings/wsl-policy")
async def write_wsl_policy(req: WslPolicyRequest, services: AppServices = Depends(get_app_services)) -> dict[str, Any]:
    settings = load_user_settings()
    settings["wsl_session_policy"] = req.model_dump()
    try:
        save_user_settings(settings)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法保存 WSL 会话策略") from exc
    return {**get_wsl_policy(), "runtime_is_wsl": is_wsl_runtime(), "runtime": "wsl" if is_wsl_runtime() else "native"}
