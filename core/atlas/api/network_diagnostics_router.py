"""Conversation-owned, read-only access to model HTTP transport diagnostics."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.models.http_diagnostics import read_network_diagnostics

router = APIRouter()


async def _run_conversation_id(manager: Any, run_id: str) -> str:
    if manager is None or manager._db is None:
        raise HTTPException(status_code=503, detail="Runtime persistence is unavailable")

    active_run = manager.runs.get(run_id)
    if active_run is not None:
        return str(active_run.conversation_id)

    try:
        async with manager._persist_lock:
            async with manager._db.execute(
                "SELECT conversation_id FROM runtime_runs WHERE run_id = ?", (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Runtime ownership lookup failed") from exc
    if row is None or not row["conversation_id"]:
        raise HTTPException(status_code=404, detail="Run not found")
    return str(row["conversation_id"])


@router.get("/api/runs/{run_id}/network-diagnostics")
async def get_run_network_diagnostics(
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """Return metadata only when the caller's conversation matches runtime ownership."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    manager = services.runtime_mgr
    owned_conversation_id = await _run_conversation_id(manager, run_id)
    if owned_conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Run not found in this conversation")
    memory = services.memory
    if memory is None:
        raise HTTPException(status_code=503, detail="Conversation ownership is unavailable")
    try:
        conversation = await memory.get_conversation(owned_conversation_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Conversation ownership lookup failed") from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="Run not found")

    items = read_network_diagnostics(run_id, limit=limit)
    return {"run_id": run_id, "conversation_id": owned_conversation_id, "items": items}


@router.get("/api/conversations/{conversation_id}/network-diagnostics")
async def get_conversation_network_diagnostics(
    conversation_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """Return recent HTTP metadata events for runs belonging to this conversation."""
    memory = services.memory
    if memory is None:
        raise HTTPException(status_code=503, detail="Conversation ownership is unavailable")
    try:
        conversation = await memory.get_conversation(conversation_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Conversation ownership lookup failed") from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    manager = services.runtime_mgr
    if manager is None or manager._db is None:
        raise HTTPException(status_code=503, detail="Runtime persistence is unavailable")
    try:
        async with manager._persist_lock:
            async with manager._db.execute(
                "SELECT run_id FROM runtime_runs WHERE conversation_id = ? "
                "ORDER BY COALESCE(updated_at, started_at) DESC, rowid DESC LIMIT 30",
                (conversation_id,),
            ) as cursor:
                run_ids = [str(row["run_id"]) for row in await cursor.fetchall()]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Runtime history lookup failed") from exc

    items: list[dict[str, Any]] = []
    for run_id in run_ids:
        items.extend(
            {**event, "run_id": run_id}
            for event in read_network_diagnostics(run_id, limit=limit)
        )
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {"items": items[:limit]}
