"""Permission presets and the standing-grant registry.

The approval dialog can hand the agent a standing capability
(``allow_always``). Until now that capability could only be created: nothing
listed it, nothing revoked it, and there was no way to say "for this run, ask me
about writes" without editing config by hand. This router is the missing read
and undo half, plus the preset table the UI offers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas import approval_policy

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class RevokeRequest(BaseModel):
    request_fingerprint: str | None = None
    tool: str | None = None
    workspace: str | None = None


class PresetRequest(BaseModel):
    preset: str = Field(..., description="observe | ask | trusted | free")


def _summary() -> dict[str, Any]:
    grants = approval_policy.grants()
    by_tool: dict[str, int] = {}
    for item in grants:
        key = str(item.get("tool") or "?")
        by_tool[key] = by_tool.get(key, 0) + 1
    return {
        "count": len(grants),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1])),
        "grants": grants,
        "presets": [
            {"name": name, **body} for name, body in approval_policy.PERMISSION_PRESETS.items()
        ],
        "default_preset": approval_policy.DEFAULT_PRESET,
    }


@router.get("")
async def list_permissions() -> dict[str, Any]:
    """Every standing grant, grouped, plus the preset table."""
    return _summary()


@router.post("/revoke")
async def revoke_permissions(req: RevokeRequest) -> dict[str, Any]:
    """Revoke grants by fingerprint, tool, or workspace.

    A request with no filter is rejected rather than treated as "all": wiping
    every permission the user ever granted should be an explicit choice.
    """
    if not any((req.request_fingerprint, req.tool, req.workspace)):
        raise HTTPException(
            status_code=400,
            detail="需要 request_fingerprint、tool 或 workspace 之一；要清空请用 POST /api/permissions/clear",
        )
    try:
        removed = approval_policy.revoke(
            request_fingerprint=req.request_fingerprint,
            tool=req.tool,
            workspace=req.workspace,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"撤销失败：{exc}") from exc
    return {"removed": removed, **_summary()}


@router.post("/clear")
async def clear_permissions() -> dict[str, Any]:
    """Revoke everything. The response says how much was actually there."""
    try:
        removed = approval_policy.clear()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"清空失败：{exc}") from exc
    return {"removed": removed, **_summary()}


@router.get("/presets")
async def list_presets() -> dict[str, Any]:
    """The named permission bundles, without touching stored grants."""
    return {
        "default": approval_policy.DEFAULT_PRESET,
        "presets": [
            {"name": name, **body} for name, body in approval_policy.PERMISSION_PRESETS.items()
        ],
    }


@router.get("/presets/{name}")
async def show_preset(name: str) -> dict[str, Any]:
    """Resolve one preset. Unknown names resolve to the default, like ``preset()``."""
    resolved = approval_policy.preset(name)
    return {"requested": name, "resolved": resolved,
            "exact": resolved["name"] == str(name).strip().lower()}


@router.post("/presets/resolve")
async def resolve_preset(req: PresetRequest) -> dict[str, Any]:
    """Ask what a preset name means before applying it to a run."""
    return {"requested": req.preset, "resolved": approval_policy.preset(req.preset)}
