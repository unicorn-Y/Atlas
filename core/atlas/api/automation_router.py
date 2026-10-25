"""``/api/automations`` — Cron Agent API（W4；挂载由 server 集成方完成）.

产品面 = CRUD + run-now/cancel/runs + pause/resume + import-legacy
（integration-map §5 契约；Hermes cron 产品面 ∪ OpenClaw cron-tool actions 的交集）。

engine 未启动（DBOS 未接）时 CRUD 照常（只写 automations.toml），
run-now / cancel / runs 返回 503。
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from atlas.automation import (
    AutomationValidationError,
    get_automation_engine,
    set_automation_engine,
)
from atlas.automation.engine import AutomationEngine, compute_next_run_at
from atlas.automation.migrate import import_legacy_schedules
from atlas.automation.store import normalize_record
from atlas.automation.webhooks import get_webhook_credentials

log = structlog.get_logger()

automation_router = APIRouter(prefix="/api/automations")
_INBOX_BACKFILL_AT = 0.0


async def _backfill_automation_inbox() -> None:
    global _INBOX_BACKFILL_AT
    if time.monotonic() - _INBOX_BACKFILL_AT < 300:
        return
    engine = get_automation_engine()
    if engine is None or not engine.started:
        return
    _INBOX_BACKFILL_AT = time.monotonic()
    from atlas.automation.inbox import import_run

    for record in engine.store.list():
        try:
            for run in await engine.get_runs(str(record["id"]), limit=100):
                import_run(record, run)
        except Exception as exc:
            log.warning("automation.inbox_backfill_failed", automation_id=record.get("id"), error=str(exc))


@automation_router.get("/inbox/unread-count")
async def automation_inbox_unread_count() -> dict[str, int]:
    await _backfill_automation_inbox()
    from atlas.automation.inbox import unread_count

    return {"unread": unread_count()}


@automation_router.get("/inbox/runs")
async def automation_inbox_runs(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    status: str = Query(default="all", pattern="^(all|ok|error|skipped|queued|running|cancelled)$"),
    source: str = Query(default="all", pattern="^(all|automation|heartbeat|script)$"),
    unread: bool = Query(default=False),
) -> dict[str, Any]:
    await _backfill_automation_inbox()
    from atlas.automation.inbox import list_runs

    return list_runs(limit=limit, offset=offset, status=status, source=source, unread=unread)


@automation_router.post("/inbox/read")
async def mark_automation_inbox_read(request: dict[str, Any]) -> dict[str, Any]:
    raw_ids = request.get("run_ids")
    if raw_ids is not None and (not isinstance(raw_ids, list) or any(not isinstance(item, str) for item in raw_ids)):
        raise HTTPException(status_code=422, detail="run_ids 必须是字符串数组")
    if isinstance(raw_ids, list) and len(raw_ids) > 1000:
        raise HTTPException(status_code=422, detail="每次最多标记 1000 条运行记录")
    from atlas.automation.inbox import mark_read, unread_count

    updated = mark_read(raw_ids)
    return {"updated": updated, "unread": unread_count()}


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
    reasoning_effort: Literal["", "off", "minimal", "low", "medium", "high"] = ""
    skills: list[str] = Field(default_factory=list)
    script: str = ""
    timeout_seconds: float = 60.0
    wake_mode: Literal["", "now", "next-heartbeat"] = ""
    conversation_id: str = ""
    execution_mode: Literal["local", "worktree"] = "local"
    base_directory: str = ""
    cleanup_policy: Literal["keep", "remove_after_run"] = "keep"
    worktree_path: str = ""
    worktree_branch: str = ""
    base_branch: str = ""


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


class AutomationDeleteRequest(BaseModel):
    conversation_policy: Literal["archive", "keep"]


def _delete_impact(automation_id: str, record: dict[str, Any]) -> dict[str, Any]:
    from atlas.automation.inbox import runs_for_automation

    runs = runs_for_automation(automation_id)
    configured_id = str((record.get("payload") or {}).get("conversation_id") or "").strip()
    conversations: dict[str, dict[str, Any]] = {}
    for run in runs:
        conversation_id = str(run.get("conversation_id") or "").strip()
        if conversation_id:
            conversations.setdefault(conversation_id, {"id": conversation_id, "run_count": 0, "runs": []})
            conversations[conversation_id]["run_count"] += 1
            conversations[conversation_id]["runs"].append(run["run_key"])
    if configured_id:
        conversations.setdefault(configured_id, {"id": configured_id, "run_count": 0, "runs": [], "configured": True})
    return {"automation_id": automation_id, "automation_name": str(record.get("name") or automation_id),
            "run_count": len(runs), "conversations": list(conversations.values()),
            "configured_conversation_id": configured_id}


async def _conversation_details(impact: dict[str, Any], memory: Any) -> dict[str, Any]:
    conversations = []
    for item in impact["conversations"]:
        row = dict(item)
        if memory is None:
            row.update({"status": "unavailable", "title": row["id"], "archived": None})
        else:
            try:
                conversation = await memory.get_conversation(row["id"])
                if conversation is None:
                    row.update({"status": "missing", "title": row["id"], "archived": None})
                else:
                    row.update({"status": "available", "title": str(conversation.get("title") or row["id"]),
                                "archived": bool(conversation.get("archived"))})
            except Exception as exc:
                row.update({"status": "unavailable", "title": row["id"], "archived": None,
                            "error": type(exc).__name__})
        conversations.append(row)
    return {**impact, "conversations": conversations}


MAX_WEBHOOK_BODY = 256 * 1024


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
    # Disabled / cancelled automations have no next run.
    projected["next_run_at"] = compute_next_run_at(record) if record.get("enabled", True) else ""
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


@automation_router.get("/global-pause")
async def global_pause_status() -> dict[str, Any]:
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "data" / "automation-emergency-pause.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"paused": False, "resume_ids": [], "affected": []}


@automation_router.post("/global-pause")
async def global_pause(request: Request) -> dict[str, Any]:
    result = await _engine().emergency_pause()
    # 总刹车不只停自动化：正在跑的对话任务、子 agent、后台进程、浏览器会话也一并停下。
    services = getattr(request.app.state, "services", None)
    if services is not None:
        from atlas.api.diagnostics_router import stop_all_activity
        try:
            result["activity"] = await stop_all_activity(services)
        except Exception as exc:
            result["activity"] = {"stopped": [], "failed": [{"id": "*", "kind": "全部活动", "reason": str(exc)}]}
    return result


@automation_router.post("/global-resume")
async def global_resume() -> dict[str, Any]:
    return await _engine().emergency_resume()


@automation_router.post("")
async def create_automation(body: AutomationCreate) -> dict[str, Any]:
    engine = _engine()
    record = normalize_record(body.model_dump())
    if engine._global_pause_active():
        record["state"]["paused_reason"] = "global-emergency"
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
    if engine._global_pause_active() and merged.get("enabled") and not (merged.get("state") or {}).get("paused_reason"):
        merged["state"] = {**(merged.get("state") or {}), "paused_reason": "global-emergency"}
    try:
        saved = engine.store.put(merged)
    except AutomationValidationError as exc:
        raise _validation_error(exc) from exc
    await engine.sync_automation(saved)
    return {"automation": _project(saved)}


@automation_router.delete("/{automation_id}")
async def delete_automation(
    automation_id: str, request: Request, body: AutomationDeleteRequest | None = None,
) -> dict[str, Any]:
    engine = _engine()
    record = engine.store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    impact = _delete_impact(automation_id, record)
    services = getattr(request.app.state, "services", None)
    memory = getattr(services, "memory", None)
    detail = await _conversation_details(impact, memory)
    if body is None and detail["conversations"]:
        raise HTTPException(status_code=409, detail={"message": "删除前必须确认关联会话策略", **detail})
    policy = body.conversation_policy if body else "keep"
    archived: list[str] = []
    retained: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    if policy == "archive":
        for conversation in detail["conversations"]:
            conversation_id = conversation["id"]
            if conversation["status"] != "available":
                retained.append({"id": conversation_id, "reason": conversation["status"],
                                 "runs": conversation.get("runs", [])})
                continue
            try:
                await memory.update_conversation(conversation_id, archived=True)
                archived.append(conversation_id)
            except Exception as exc:
                failed.append({"id": conversation_id, "reason": type(exc).__name__})
        if failed:
            raise HTTPException(status_code=409, detail={
                "message": "部分关联会话未能归档；自动化和关联记录均已保留，请处理后重试或选择保留会话",
                "archived": archived, "retained": retained, "failed": failed, **detail,
            })
    await engine.remove(automation_id)
    deleted = engine.store.delete(automation_id)
    get_webhook_credentials().delete(automation_id)
    if policy == "keep":
        retained = [{"id": item["id"], "reason": "user_selected_keep", "runs": item.get("runs", [])}
                    for item in detail["conversations"]]
    return {"deleted": deleted, "conversation_policy": policy, "archived": archived,
            "retained": retained, "run_count": detail["run_count"]}


@automation_router.get("/{automation_id}/delete-impact")
async def automation_delete_impact(automation_id: str, request: Request) -> dict[str, Any]:
    record = _engine().store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    services = getattr(request.app.state, "services", None)
    return await _conversation_details(_delete_impact(automation_id, record), getattr(services, "memory", None))


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
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@automation_router.post("/{automation_id}/webhook/rotate-secret")
async def rotate_webhook_secret(automation_id: str) -> dict[str, Any]:
    """Rotate a task's webhook signing secret. The plaintext is returned only once."""
    record = _engine().store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    if (record.get("trigger") or {}).get("kind") != "webhook":
        raise HTTPException(status_code=409, detail="该自动化不是 Webhook 触发")
    secret = get_webhook_credentials().rotate(automation_id)
    return {"url": f"/api/automations/{automation_id}/webhook", "secret": secret}


@automation_router.post("/{automation_id}/webhook")
async def receive_automation_webhook(automation_id: str, request: Request) -> dict[str, Any]:
    """Verify a signed raw request and enqueue it through the normal event trigger."""
    engine = _require_started_engine()
    record = engine.store.get(automation_id)
    if record is None:
        raise _not_found(automation_id)
    if (record.get("trigger") or {}).get("kind") != "webhook":
        raise HTTPException(status_code=409, detail="该自动化不是 Webhook 触发")
    length = request.headers.get("content-length")
    if length and (not length.isdecimal() or int(length) > MAX_WEBHOOK_BODY):
        raise HTTPException(status_code=413, detail="Webhook 请求体超过 256 KiB")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BODY:
        raise HTTPException(status_code=413, detail="Webhook 请求体超过 256 KiB")
    timestamp = request.headers.get("x-atlas-timestamp", "")
    signature = request.headers.get("x-atlas-signature", "")
    if not get_webhook_credentials().verify(automation_id, timestamp, signature, raw):
        raise HTTPException(status_code=401, detail="Webhook 签名无效、过期或已使用")
    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook 请求体必须是 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook JSON 顶层必须是对象")
    try:
        return await engine.trigger_event(automation_id, source="webhook", payload=payload)
    except KeyError as exc:
        raise _not_found(automation_id) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
