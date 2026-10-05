"""``/api/automations`` — Cron Agent API（W4；挂载由 server 集成方完成）.

产品面 = CRUD + run-now/cancel/runs + pause/resume + import-legacy
（integration-map §5 契约；Hermes cron 产品面 ∪ OpenClaw cron-tool actions 的交集）。

engine 未启动（DBOS 未接）时 CRUD 照常（只写 automations.toml），
run-now / cancel / runs 返回 503。
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.automation import (
    AutomationValidationError,
    get_automation_engine,
    set_automation_engine,
)
from atlas.automation.engine import AutomationEngine, compute_next_run_at
from atlas.automation.migrate import import_legacy_schedules
from atlas.automation.store import normalize_record

log = structlog.get_logger()

automation_router = APIRouter(prefix="/api/automations")


# ---------------------------------------------------------------------------
# request models（宽松：字段缺省走 store 的 normalize+validate）
# ---------------------------------------------------------------------------


class TriggerSpec(BaseModel):
    kind: Literal["cron", "interval", "date", "event", "webhook"] = "cron"
    cron_expr: str = ""
    tz: str = ""
    every_seconds: float = 0
    at: str = ""
    event_path: str = ""
    event_glob: str = ""
    event_debounce: float = 2.0


class PayloadSpec(BaseModel):
    kind: Literal["agent_turn", "heartbeat", "script"] = "agent_turn"
    message: str = ""
    agent_id: str = ""
    model: str = ""
    skills: list[str] = Field(default_factory=list)
    script: str = ""
    timeout_seconds: float = 60.0
    wake_mode: Literal["", "now", "next-heartbeat"] = ""


class DeliverySpec(BaseModel):
    mode: Literal["none", "channel"] = "none"
    channel: str = ""
    target: str = ""


class PolicySpec(BaseModel):
    missed_run: Literal["catchup", "skip"] = "skip"
    max_catchup: int = 5
    delete_after_run: bool = False
    consecutive_error_disable: int = 10


class AutomationCreate(BaseModel):
    id: str | None = Field(default=None, description="缺省自动生成")
    name: str = ""
    enabled: bool = True
    owner_agent_id: str = ""
    trigger: TriggerSpec = Field(default_factory=TriggerSpec)
    payload: PayloadSpec = Field(default_factory=PayloadSpec)
    delivery: DeliverySpec = Field(default_factory=DeliverySpec)
    policy: PolicySpec = Field(default_factory=PolicySpec)


class AutomationPatch(BaseModel):
    """PATCH 语义：只覆盖显式给出的字段（嵌套节整体替换或置 null 恢复默认）。"""

    name: str | None = None
    enabled: bool | None = None
    owner_agent_id: str | None = None
    trigger: TriggerSpec | None = None
    payload: PayloadSpec | None = None
    delivery: DeliverySpec | None = None
    policy: PolicySpec | None = None


class ImportLegacyRequest(BaseModel):
    toml_path: str | None = Field(default=None, description="缺省 data/schedules.toml")


def _engine() -> AutomationEngine:
    return get_automation_engine()


def _require_started_engine() -> AutomationEngine:
    engine = _engine()
    if not engine.started:
        raise HTTPException(
            status_code=503,
            detail="automation engine 未启动（DBOS 未接线）",
        )
    return engine


def _project(record: dict[str, Any]) -> dict[str, Any]:
    """产品记录 + 运行投影（next_run_at 展示值）。"""
    projected = dict(record)
    projected["next_run_at"] = compute_next_run_at(record)
    return projected


def _validation_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _not_found(automation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"automation 不存在: {automation_id}")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@automation_router.get("")
async def list_automations() -> dict[str, Any]:
    engine = _engine()
    items = [_project(record) for record in engine.store.list()]
    return {"automations": items, "engine_started": engine.started}


@automation_router.post("")
async def create_automation(body: AutomationCreate) -> dict[str, Any]:
    engine = _engine()
    record = normalize_record(body.model_dump())
    record["name"] = record["name"] or record["id"]
    try:
        saved = engine.store.put(record)
    except AutomationValidationError as exc:
        raise _validation_error(exc) from exc
    await engine.sync_automation(saved)
    return {"automation": _project(saved)}


@automation_router.get("/{automation_id}")
async def get_automation(automation_id: str) -> dict[str, Any]:
    record = _engine().store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    return {"automation": _project(record)}


@automation_router.patch("/{automation_id}")
async def patch_automation(automation_id: str, body: AutomationPatch) -> dict[str, Any]:
    engine = _engine()
    record = engine.store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    updates = body.model_dump(exclude_none=True, exclude_unset=True)
    for section in ("trigger", "payload", "delivery", "policy"):
        if section in updates and isinstance(updates[section], dict):
            updates[section] = {**record[section], **updates[section]}
    merged = {**record, **updates}
    try:
        saved = engine.store.put(merged)
    except AutomationValidationError as exc:
        raise _validation_error(exc) from exc
    await engine.sync_automation(saved)
    return {"automation": _project(saved)}


@automation_router.delete("/{automation_id}")
async def delete_automation(automation_id: str) -> dict[str, Any]:
    engine = _engine()
    if engine.store.get(automation_id) is None:
        raise _not_found(automation_id)
    await engine.remove(automation_id)
    deleted = engine.store.delete(automation_id)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# run controls
# ---------------------------------------------------------------------------


@automation_router.post("/{automation_id}/run-now")
async def run_automation_now(
    automation_id: str,
    wait: float | None = Query(default=None, ge=0, le=120, description="同步等待结果秒数"),
) -> dict[str, Any]:
    engine = _require_started_engine()
    try:
        receipt = await engine.run_now(automation_id, wait=wait)
    except KeyError as exc:
        raise _not_found(automation_id) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return receipt


@automation_router.post("/{automation_id}/cancel")
async def cancel_automation(automation_id: str) -> dict[str, Any]:
    engine = _require_started_engine()
    try:
        return await engine.cancel(automation_id)
    except KeyError as exc:
        raise _not_found(automation_id) from exc


@automation_router.get("/{automation_id}/runs")
async def list_automation_runs(
    automation_id: str, limit: int = Query(default=20, ge=1, le=200)
) -> dict[str, Any]:
    engine = _require_started_engine()
    if engine.store.get(automation_id) is None:
        raise _not_found(automation_id)
    runs = await engine.get_runs(automation_id, limit=limit)
    return {"runs": runs, "limit": limit}


@automation_router.post("/{automation_id}/pause")
async def pause_automation(automation_id: str) -> dict[str, Any]:
    engine = _engine()
    try:
        return await engine.pause(automation_id)
    except KeyError as exc:
        raise _not_found(automation_id) from exc


@automation_router.post("/{automation_id}/resume")
async def resume_automation(automation_id: str) -> dict[str, Any]:
    engine = _engine()
    try:
        return await engine.resume(automation_id)
    except KeyError as exc:
        raise _not_found(automation_id) from exc


@automation_router.post("/import-legacy")
async def import_legacy(body: ImportLegacyRequest | None = None) -> dict[str, Any]:
    """旧 ``schedules.toml`` 一次性导入；导入后暂停旧任务，防止新旧双触发（P10）。"""
    engine = _engine()
    report = import_legacy_schedules(
        toml_path=(body.toml_path if body else None),
        store=engine.store,
        pause_legacy=True,
    )
    await engine.reconcile_async()
    return report.to_dict()


# ---------------------------------------------------------------------------
# engine wiring helpers（server 集成 / 测试用）
# ---------------------------------------------------------------------------


def install_automation_engine(engine: AutomationEngine) -> AutomationEngine | None:
    """注册单例并返回旧值；server 启动路径与测试 fixture 共用。"""
    return set_automation_engine(engine)


__all__ = [
    "automation_router",
    "install_automation_engine",
    "get_automation_engine",
]
