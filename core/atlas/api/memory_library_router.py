"""Memory library (docs/memory/PLAN-V1.md) for the memory page and for other devices.

- GET  /api/memlib/today              今日变动、现状、今天聊了几轮
- GET  /api/memlib/overview           所有页面（我 / 现状 / 它自己 / 人 / 事）
- GET  /api/memlib/page?path=人/老王.md  一页的当前与历史
- GET  /api/memlib/changes?limit=60   变动记录（每次 git 提交一条，附增删）
- GET  /api/memlib/search?q=...       搜索（和 memory_search 工具同一套）
- POST /api/memlib/entry              {"id", "text"} 改一条 → 标成「你改的」
- POST /api/memlib/add                {"path", "text"} 在某页加一条
- POST /api/memlib/forget             {"id"} 忘掉一条（留墓碑，日记原文一并抹掉）
- POST /api/memlib/aliases            {"path", "aliases": [...]}
- POST /api/memlib/revert             {"sha"} 撤销某次变动
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.memory.library import MemoryLibrary, get_library

router = APIRouter(prefix="/api/memlib", tags=["memory-library"])


def _lib() -> MemoryLibrary:
    library = get_library()
    if library is None:
        raise HTTPException(503, "记忆库已在配置中关闭（[memory.library] enabled = false）。")
    return library


async def _run(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except KeyError as exc:
        raise HTTPException(404, "找不到这条记忆，可能已经被改过。") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


class EntryEdit(BaseModel):
    id: str
    text: str


class EntryAdd(BaseModel):
    path: str
    text: str


class EntryRef(BaseModel):
    id: str


class Aliases(BaseModel):
    path: str
    aliases: list[str]


class Revert(BaseModel):
    sha: str


@router.get("/today")
async def today() -> dict[str, Any]:
    return await _run(_lib().today)


@router.get("/overview")
async def overview() -> dict[str, Any]:
    return await _run(_lib().overview)


@router.get("/page")
async def page(path: str) -> dict[str, Any]:
    return await _run(_lib().page_view, path)


@router.get("/changes")
async def changes(limit: int = 60, diary: bool = False) -> dict[str, Any]:
    rows = await _run(_lib().changes, max(1, min(300, limit)), diary)
    return {"changes": rows}


@router.get("/search")
async def search(q: str, limit: int = 10, history: bool = False) -> dict[str, Any]:
    return {"results": await _run(_lib().search, q, max(1, min(50, limit)), history)}


@router.post("/entry")
async def edit_entry(body: EntryEdit) -> dict[str, Any]:
    return await _run(_lib().edit_entry, body.id, body.text)


@router.post("/add")
async def add_entry(body: EntryAdd) -> dict[str, Any]:
    return await _run(_lib().add_entry, body.path, body.text)


@router.post("/forget")
async def forget(body: EntryRef) -> dict[str, Any]:
    return await _run(_lib().forget_entry, body.id)


@router.post("/aliases")
async def aliases(body: Aliases) -> dict[str, Any]:
    await _run(_lib().set_aliases, body.path, body.aliases)
    return {"ok": True}


@router.post("/revert")
async def revert(body: Revert) -> dict[str, Any]:
    await _run(_lib().revert, body.sha)
    return {"ok": True}
