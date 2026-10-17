"""Knowledge base (docs/knowledge/DESIGN.md).

- GET  /api/knowledge/stats              各层数量
- GET  /api/knowledge/search?q=&kind=    搜提炼层
- POST /api/knowledge/import             {"source": "claude-code"|"codex"|"atlas", "path"?} 原样存档
- POST /api/knowledge/item               {"kind", "title", "body", "source"?, "tags"?, "model"?} 手动加一条
- POST /api/knowledge/reindex            重建索引
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from atlas.knowledge import CuratedItem, KnowledgeBase, get_knowledge_base

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _kb() -> KnowledgeBase:
    kb = get_knowledge_base()
    if kb is None:
        raise HTTPException(503, "知识库已在配置中关闭（[knowledge] enabled = false）。")
    return kb


class ImportBody(BaseModel):
    source: str
    path: str | None = None


class ItemBody(BaseModel):
    kind: str
    title: str
    body: str
    source: str = ""
    tags: list[str] = []
    model: str = ""


@router.get("/stats")
async def stats() -> dict[str, Any]:
    return await asyncio.to_thread(_kb().stats)


@router.get("/search")
async def search(q: str = Query(...), kind: str | None = None, limit: int = 8) -> dict[str, Any]:
    return {"results": await asyncio.to_thread(_kb().search, q, kind, limit)}


@router.post("/import")
async def import_source(body: ImportBody) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(_kb().import_source, body.source, body.path)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(result)


@router.post("/item")
async def add_item(body: ItemBody) -> dict[str, Any]:
    try:
        path = await asyncio.to_thread(_kb().add, CuratedItem(**body.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"path": str(path)}


@router.post("/reindex")
async def reindex() -> dict[str, Any]:
    return {"items": await asyncio.to_thread(_kb().store.reindex)}
