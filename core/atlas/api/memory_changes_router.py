"""MemOS 记忆的 Atlas 内置入口：变动记录、暂停 / 恢复、删除对话记录、归档技能。

- GET  /api/memory/changes   变动记录（新增 / 删除 / 修改 / 淡忘 / 归档 / 评分变化）
- GET  /api/memory/state     是否暂停、MemOS 面板地址
- POST /api/memory/pause     {"paused": bool} 暂停后 Atlas 既不召回也不写入记忆（下一轮即生效）
- GET  /api/memory/facts     「关于你」：当前事实（history=1 含历史版本）
- GET  /api/memory/library/{kind}  技能 / 策略 / 世界模型列表
- POST /api/memory/delete    {"entity": "traces", "ids": [...]} 删除对话记录 / 关于你 / 策略 / 世界模型；skills → 归档
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.config import DATA_ROOT
from atlas.memory import memos_changes, memos_service

router = APIRouter(prefix="/api/memory", tags=["memory-changes"])

MEMOS_VIEWER = "http://127.0.0.1:18800"
PAUSE_FLAG = DATA_ROOT / "data" / "memory_paused"  # same path HermesRuntime checks


@router.get("/changes")
async def get_changes(limit: int = 100, before: int | None = None, entity: str = "",
                      op: str = "") -> dict[str, Any]:
    memos_changes.ensure_watcher()
    await asyncio.to_thread(memos_changes.scan)  # always show the latest state on open/refresh
    return await asyncio.to_thread(memos_changes.list_changes, limit=limit, before_id=before,
                                   entity=entity, op=op)


@router.get("/state")
async def get_state() -> dict[str, Any]:
    return {"paused": PAUSE_FLAG.exists(), "viewer_url": MEMOS_VIEWER}


# Lists the 记忆 page shows straight from MemOS (server/routes/{skill,policies}.ts).
_LIBRARY_PATHS = {"skills": "/api/v1/skills", "policies": "/api/v1/policies",
                  "world_model": "/api/v1/world-models"}


async def _memos_get(path: str) -> Any:
    try:
        return await asyncio.to_thread(memos_service.request, "GET", path)
    except Exception as exc:  # MemOS could not be started / rejected
        raise HTTPException(502, f"MemOS 没有响应：{exc}") from exc


@router.get("/facts")
async def get_facts(history: bool = False, limit: int = 500) -> Any:
    return await _memos_get(f"/api/v1/facts?history={1 if history else 0}&limit={limit}")


@router.get("/library/{kind}")
async def get_library(kind: str, limit: int = 100) -> Any:
    if kind not in _LIBRARY_PATHS:
        raise HTTPException(404, f"没有这类记忆：{kind}")
    return await _memos_get(f"{_LIBRARY_PATHS[kind]}?limit={limit}")


class PauseBody(BaseModel):
    paused: bool


@router.post("/pause")
async def set_pause(body: PauseBody) -> dict[str, Any]:
    if body.paused:
        PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FLAG.write_text("paused by user\n", encoding="utf-8")
    else:
        PAUSE_FLAG.unlink(missing_ok=True)
    return {"paused": PAUSE_FLAG.exists()}


class DeleteBody(BaseModel):
    entity: str
    ids: list[str]


def _memos_post(path: str, payload: dict[str, Any] | None, method: str = "POST") -> Any:
    return memos_service.request(method, path, payload)


# MemOS hard-delete routes (server/routes/policies.ts)
_DELETE_PATHS = {"policies": "/api/v1/policies", "world_model": "/api/v1/world-models",
                 "user_facts": "/api/v1/facts"}


@router.post("/delete")
async def delete_memory(body: DeleteBody) -> dict[str, Any]:
    ids = [i for i in body.ids if i]
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    try:
        if body.entity == "traces":
            result = await asyncio.to_thread(_memos_post, "/api/v1/traces/delete", {"ids": ids})
        elif body.entity == "skills":
            result = [await asyncio.to_thread(_memos_post, "/api/v1/skills/archive", {"id": i}) for i in ids]
        elif body.entity in _DELETE_PATHS:
            result = [await asyncio.to_thread(_memos_post, f"{_DELETE_PATHS[body.entity]}/{quote(i, safe='')}",
                                              None, "DELETE") for i in ids]
        else:
            raise HTTPException(400, f"暂不支持删除这类记忆：{body.entity}")
    except HTTPException:
        raise
    except Exception as exc:  # MemOS offline / rejected
        raise HTTPException(502, f"MemOS 没有响应：{exc}") from exc
    await asyncio.to_thread(memos_changes.scan)  # record the deletion right away
    return {"ok": True, "result": result}
