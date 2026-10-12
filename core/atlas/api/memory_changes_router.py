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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atlas.config import DATA_ROOT
from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.unified_memory_router import _http_error
from atlas.memory import desktop_views
from atlas.memory.unified_client import UnifiedMemoryError
from atlas.memory import memos_changes, memos_service

router = APIRouter(prefix="/api/memory", tags=["memory-changes"])

MEMOS_VIEWER = "http://127.0.0.1:18800"
PAUSE_FLAG = DATA_ROOT / "data" / "memory_paused"  # same path HermesRuntime checks


def _unified(services: AppServices) -> Any:
    facade = services.unified_memory
    if facade is not None and facade.enabled:
        return facade
    if services.config is not None and services.config.get("memory.unified.enabled", False):
        raise HTTPException(503, "统一记忆尚未就绪。")
    return None


@router.get("/changes")
async def get_changes(services: Annotated[AppServices, Depends(get_app_services)],
                      limit: int = 100, before: int | None = None, entity: str = "",
                      op: str = "") -> dict[str, Any]:
    if _unified(services) is not None:
        raise HTTPException(501, "统一记忆变动记录尚未接入此页面；关于你和经验与技能读取统一记忆。")
    memos_changes.ensure_watcher()
    await asyncio.to_thread(memos_changes.scan)  # always show the latest state on open/refresh
    return await asyncio.to_thread(memos_changes.list_changes, limit=limit, before_id=before,
                                   entity=entity, op=op)


@router.get("/state")
async def get_state(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    if _unified(services) is not None:
        return {"paused": False, "viewer_url": "", "source": "unified-memory", "can_pause": False}
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
async def get_facts(services: Annotated[AppServices, Depends(get_app_services)],
                    history: bool = False, limit: int = 500) -> Any:
    facade = _unified(services)
    if facade is not None:
        try:
            return desktop_views.facts(await desktop_views.records(
                facade, max(1, min(limit, 5000)), facets=("FACT", "PREFERENCE", "STATE", "HABIT", "RELATION")), history)
        except UnifiedMemoryError as exc:
            raise _http_error(exc) from exc
    return await _memos_get(f"/api/v1/facts?history={1 if history else 0}&limit={limit}")


@router.get("/library/{kind}")
async def get_library(kind: str, services: Annotated[AppServices, Depends(get_app_services)],
                      limit: int = 100) -> Any:
    if kind not in _LIBRARY_PATHS:
        raise HTTPException(404, f"没有这类记忆：{kind}")
    facade = _unified(services)
    if facade is not None:
        if kind == "policies":
            raise HTTPException(501, "统一记忆服务尚未提供策略列表投影；此页面不会读取旧 MemOS 策略。")
        try:
            return desktop_views.library(await desktop_views.records(
                facade, max(1, min(limit, 5000)), facets=("SKILL" if kind == "skills" else "KNOWLEDGE",)), kind)
        except UnifiedMemoryError as exc:
            raise _http_error(exc) from exc
    return await _memos_get(f"{_LIBRARY_PATHS[kind]}?limit={limit}")


class PauseBody(BaseModel):
    paused: bool


@router.post("/pause")
async def set_pause(body: PauseBody, services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    if _unified(services) is not None:
        raise HTTPException(501, "统一记忆的暂停尚未接入此页面。")
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
async def delete_memory(body: DeleteBody, services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    facade = _unified(services)
    if facade is not None:
        raise HTTPException(501, "统一记忆的删除需要遗忘预览和所有者授权；此入口尚未接入该流程，不会修改旧 MemOS 数据。")
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
