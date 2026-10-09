"""MemOS 记忆的 Atlas 内置入口：变动记录、暂停 / 恢复、删除对话记录、归档技能。

- GET  /api/memory/changes   变动记录（新增 / 删除 / 修改 / 淡忘 / 归档 / 评分变化）
- GET  /api/memory/state     是否暂停、MemOS 面板地址
- POST /api/memory/pause     {"paused": bool} 暂停后 Atlas 既不召回也不写入记忆（下一轮即生效）
- POST /api/memory/delete    {"entity": "traces", "ids": [...]} 删除对话记录；skills → 归档
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.config import DATA_ROOT
from atlas.memory import memos_changes

router = APIRouter(prefix="/api/memory", tags=["memory-changes"])

MEMOS_VIEWER = "http://127.0.0.1:18800"
PAUSE_FLAG = DATA_ROOT / "memory_paused"


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


def _memos_post(path: str, payload: dict[str, Any]) -> Any:
    req = urllib.request.Request(MEMOS_VIEWER + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed loopback URL
        body = resp.read().decode("utf-8") or "null"
    return json.loads(body)


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
        else:
            raise HTTPException(400, f"暂不支持删除这类记忆：{body.entity}")
    except HTTPException:
        raise
    except Exception as exc:  # MemOS offline / rejected
        raise HTTPException(502, f"MemOS 没有响应：{exc}") from exc
    await asyncio.to_thread(memos_changes.scan)  # record the deletion right away
    return {"ok": True, "result": result}
