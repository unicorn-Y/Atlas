"""追新路由（``/api/upstream``）：组件清单、检查、一键追新、任务进度、设置。

检查与追新都在后台跑（检查几十秒到几分钟，追新在独立进程里跑几分钟到几十分钟），
接口立即返回，界面轮询 ``GET /api/upstream`` 与 ``GET /api/upstream/run``。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.upstream import check, service, staging

upstream_router = APIRouter(prefix="/api/upstream")


@upstream_router.get("")
async def get_view() -> dict[str, Any]:
    """完整清单 + 分类汇总 + 设置 + 当前任务 + 待重启的追新结果。"""
    view = check.view()
    view["checking"] = service.is_checking()
    view["run"] = staging.read_run(check.upstream_root())
    view["pending"] = service.pending_merge()
    view["supported"] = service.repo_supported()
    return view


@upstream_router.post("/check")
async def start_check() -> dict[str, Any]:
    return {"started": service.start_check_background(), "checking": True}


class ApplyBody(BaseModel):
    ids: list[str] = Field(default_factory=list)
    category: str | None = None


@upstream_router.post("/apply")
async def apply(body: ApplyBody) -> dict[str, Any]:
    """一键追新：不给 ids 与分类时处理全部可更新项。"""
    return await service.apply(body.ids or None, body.category)


@upstream_router.get("/run")
async def get_run() -> dict[str, Any]:
    return staging.read_run(check.upstream_root())


@upstream_router.post("/run/cancel")
async def cancel_run() -> dict[str, Any]:
    return {"cancelled": staging.cancel(check.upstream_root())}


class SettingsBody(BaseModel):
    mode: str | None = None
    interval_hours: int | None = None
    push: bool | None = None


@upstream_router.put("/settings")
async def put_settings(body: SettingsBody) -> dict[str, Any]:
    try:
        return check.save_settings(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class HoldBody(BaseModel):
    id: str
    reason: str = "手动锁定"


@upstream_router.post("/holds")
async def add_hold(body: HoldBody) -> dict[str, Any]:
    holds = dict(check.load_settings().get("holds") or {})
    holds[body.id] = body.reason
    return check.save_settings({"holds": holds})


@upstream_router.delete("/holds/{component_id:path}")
async def remove_hold(component_id: str) -> dict[str, Any]:
    holds = dict(check.load_settings().get("holds") or {})
    holds.pop(component_id, None)
    return check.save_settings({"holds": holds})


@upstream_router.delete("/failures/{component_id:path}")
async def clear_failure(component_id: str) -> dict[str, Any]:
    """忘掉某项的失败记录，让自动追新重新尝试它。"""
    check.clear_failure(component_id)
    return {"ok": True}
