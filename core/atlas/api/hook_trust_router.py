"""Per-hook review endpoints backed by HookStore's independent trust registry."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


def _server() -> Any:
    import atlas.server

    return atlas.server


class HookTrustRequest(BaseModel):
    trusted: bool
    fingerprint: str = Field(min_length=64, max_length=64)
    workspace: str | None = None


@router.get("/api/hooks/trust")
async def list_hook_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace: str | None = None,
) -> dict[str, Any]:
    del services
    return {"hooks": _server()._hook_store().list_all(workspace)}


@router.put("/api/hooks/{hook_id}/trust")
async def set_hook_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    hook_id: str,
    request: HookTrustRequest,
) -> dict[str, Any]:
    del services
    try:
        return _server()._hook_store().set_hook_trust(
            hook_id,
            request.trusted,
            fingerprint=request.fingerprint,
            cwd=request.workspace,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Hook 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
