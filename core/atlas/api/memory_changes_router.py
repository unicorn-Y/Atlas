"""GET /api/memory/changes —— MemOS 记忆变动记录（新增 / 删除 / 修改 / 淡忘 / 归档 / 评分变化）。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from atlas.memory import memos_changes

router = APIRouter(prefix="/api/memory", tags=["memory-changes"])


@router.get("/changes")
async def get_changes(limit: int = 100, before: int | None = None, entity: str = "",
                      op: str = "") -> dict[str, Any]:
    memos_changes.ensure_watcher()
    await asyncio.to_thread(memos_changes.scan)  # always show the latest state on open/refresh
    return await asyncio.to_thread(memos_changes.list_changes, limit=limit, before_id=before,
                                   entity=entity, op=op)
