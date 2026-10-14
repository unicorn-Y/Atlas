"""资料 surface (``/api/knowledge``): notes and references the user hands to Atlas.

Long-term memory has its own router (``memory_library_router``, ``/api/memlib``).
Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


class KnowledgeAddRequest(BaseModel):
    content: str
    source: str = ""
    category: str = "general"
    metadata: dict[str, Any] = {}


@router.get("/api/knowledge")
async def list_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List knowledge base entries."""
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge(category=category, limit=limit)


@router.post("/api/knowledge")
async def add_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: KnowledgeAddRequest,
) -> dict[str, Any]:
    """Add a knowledge entry."""
    memory = services.memory
    assert memory is not None
    entry_id = await memory.add_knowledge(
        content=req.content,
        source=req.source,
        category=req.category,
        metadata=req.metadata,
    )
    return {"id": entry_id, "content": req.content, "source": req.source}


@router.get("/api/knowledge/search")
async def search_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(..., min_length=1),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Search the knowledge base."""
    memory = services.memory
    assert memory is not None
    return await memory.search_knowledge(query=q, category=category, limit=limit)


@router.delete("/api/knowledge/{entry_id}")
async def delete_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    entry_id: str,
) -> dict[str, str]:
    """Delete a knowledge entry."""
    memory = services.memory
    assert memory is not None
    ok = await memory.delete_knowledge(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Knowledge entry not found: {entry_id}")
    return {"status": "ok", "id": entry_id}
