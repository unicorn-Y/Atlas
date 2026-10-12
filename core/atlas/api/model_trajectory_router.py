"""Conversation-scoped model call trajectory query API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter(tags=["model-trajectory"])


@router.get("/api/conversations/{conversation_id}/model-trajectory")
async def search_model_trajectory(
    conversation_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(default="", max_length=200),
    source: str = Query(default="", max_length=80),
    call_type: str = Query(default="", max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = getattr(services, "model_trajectory", None)
    if store is None:
        raise HTTPException(status_code=503, detail="model trajectory is unavailable")
    try:
        return await store.search(
            conversation_id, query=q, source=source, call_type=call_type,
            limit=limit, offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
