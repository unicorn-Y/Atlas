"""AutomationEngine — DBOS 之上的 durable 触发与执行（W4）.

职责边界：产品状态在 :mod:`atlas.automation.store`（automations.toml），
durable 的调度/执行/run history 全部是 DBOS 原生对象（不建第二 durable 层）。

DBOS 落点（integration-map §4 映射）：

- cron    → ``DBOS.create_schedule(schedule_name="atlas-auto-{id}", ...)``，
  workflow_id 形如 ``sched-{name}-{iso}`` 天然 no-duplicate-fire；
  ``automatic_backfill = policy.missed_run == "catchup"``。
- interval → 自续 workflow（基础 id ``atlas-auto-interval-{id}``）+
  ``DBOS.sleep_async(every_seconds)`` 循环；每次迭代经 dedup 入队一个 run。
- date    → ``enqueue_workflow_with_options(delay_seconds=...)``。
- event/webhook → :mod:`atlas.automation.triggers` 入口 → dedup enqueue。
- run receipt = DBOS workflow（ENQUEUED/DELAYED/PENDING/RUNNING 即活跃），
  run history = ``DBOS.list_workflows(workflow_id_prefix=...)``。

兼容性要点（dbos==3.0.0 实测，见 tests/test_automation_dbos_probe.py）：

- 所有 workflow/step 装饰器必须带显式 ``name=``——闭包的 ``__qualname__``
  含 ``<locals>``，按名字 enqueue/恢复时对不上。
- SQLite 不支持 ``list_workflows(attributes=...)``，run history / 活跃 run
  一律用 ``workflow_id_prefix``（run id 统一前缀 ``atlas-auto-run-{id}-``）。
- 在事件循环里必须用 ``*_async`` 变体（``check_async`` 守卫）；
  schedule 系 API 无 async 变体但只是普通 DB 写，循环内可直接调用。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Awaitable, Callable

import structlog

from atlas.automation.store import AutomationStore, normalize_record

log = structlog.get_logger()


def _message_with_webhook_payload(
    message: str, trigger: str, payload: dict[str, Any] | None,
) -> str:
    if trigger != "webhook" or not payload:
        return message
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)[:64_000]
    return f"{message}\n\n外部 Webhook 事件数据（JSON）：\n```json\n{encoded}\n```".strip()

HeartbeatTick = Callable[[str, str], Awaitable[Any]]
DispatchTurn = Callable[[dict[str, Any]], Awaitable[Any]]
DeliverHook = Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]]

RUN_STATUS_ACTIVE = ("ENQUEUED", "DELAYED", "PENDING", "RUNNING")
WORKFLOW_RUN_NAME = "automation_run"
WORKFLOW_INTERVAL_NAME = "automation_interval_loop"

DELIVERY_OUTCOMES = ("delivered", "not-delivered", "unknown", "not-requested")


def schedule_name(automation_id: str) -> str:
    return f"atlas-auto-{automation_id}"


def run_id_prefix(automation_id: str) -> str:
    return f"atlas-auto-run-{automation_id}-"


def interval_id_prefix(automation_id: str) -> str:
    return f"atlas-auto-interval-{automation_id}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _iso(ms: int | float | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _ensure_launched() -> None:
    """Defensively launch the process-global DBOS (no-op when already launched)."""
    from dbos import DBOS
    from dbos import _dbos as _dbos_module

    # _dbos_global_instance lives on the dbos._dbos MODULE, not on the DBOS
    # class — a class-level getattr always misses (W10 integration fix).
    instance = getattr(_dbos_module, "_dbos_global_instance", None)
    if instance is not None and not getattr(instance, "_launched", False):
        DBOS.launch()


def _run_isolated(coro: Awaitable[Any]) -> Any:
    """Run a coroutine on a throwaway loop *without* Runner semantics.

    ``asyncio.run`` closes the loop through ``asyncio.Runner``, which shuts the
    loop's default executor down on exit — and DBOS installs its process-wide
    thread pool as that default executor on the first ``*_async`` call, which
    would kill every later DBOS async call in the process. A plain loop +
    ``close()`` keeps the executor alive.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Same value as atlas.automation.reminders.REMINDER_PREFIX (that module imports this one).
REMINDER_NAME_PREFIX = "提醒："


def _is_reminder(record: dict[str, Any]) -> bool:
    """Chat-created reminder records are tagged by their name prefix (see reminders.py)."""
    return str(record.get("name") or "").startswith(REMINDER_NAME_PREFIX)


def compute_next_run_at(record: dict[str, Any], *, from_time: datetime | None = None) -> str:
    """展示用 next_run_at：cron 用 croniter 推导；interval 从 last_run_at 顺推。"""
    trigger = record.get("trigger") or {}
    kind = trigger.get("kind")
    now = from_time or datetime.now(UTC)
    try:
        if kind == "cron" and trigger.get("cron_expr"):
            from croniter import croniter

            tz = str(trigger.get("tz") or "")
            base = now.astimezone(zoneinfo.ZoneInfo(tz)) if tz else now
            nxt = croniter(
                trigger["cron_expr"], base, second_at_beginning=True
            ).get_next(datetime)
            return nxt.astimezone(UTC).isoformat()
        if kind == "interval" and float(trigger.get("every_seconds") or 0) > 0:
            last = (record.get("state") or {}).get("last_run_at")
            base = datetime.fromisoformat(last) if last else now
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
            return (base + timedelta(seconds=float(trigger["every_seconds"]))).isoformat()
        if kind == "date" and trigger.get("at"):
            at = datetime.fromisoformat(str(trigger["at"]))
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            return at.isoformat() if at > now else ""
    except Exception:  # 展示字段，绝不抛
        log.exception("automation.next_run_time_failed")
        return ""
    return ""


class AutomationEngine:
    """Own the DBOS wiring for automations; the DBOS instance is injected.

    Usage::

        engine = AutomationEngine(store, heartbeat_tick=..., dispatch_turn=...)
        await engine.start_async(dbos)      # dbos 已由调用方构造（可未 launch）
        ...
        engine.shutdown()                   # 不销毁注入的 DBOS 实例
    """

    QUEUE_NAME = "atlas-automation"

    def __init__(
        self,
        store: AutomationStore,
        *,
        heartbeat_tick: HeartbeatTick | None = None,
        dispatch_turn: DispatchTurn | None = None,
        deliver: DeliverHook | None = None,
        scheduler_timezone: str | None = None,
        queue_concurrency: int = 2,
    ) -> None:
        self._store = store
        self._heartbeat_tick = heartbeat_tick
        self._dispatch_turn = dispatch_turn
        self._deliver = deliver
        self._tz = scheduler_timezone
        self._queue_concurrency = queue_concurrency
        self._dbos: Any = None
        self._wf: SimpleNamespace | None = None
        self._started = False
        self._triggers: Any = None

    # -- lifecycle -----------------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    @property
    def store(self) -> AutomationStore:
        return self._store

    def _define_workflows(self) -> None:
        """Register the durable workflow/step closures on the injected instance.

        Same pattern as DurableBackend (decorate at start), plus explicit
        ``name=`` so enqueue-by-name and crash recovery can dispatch.
        """
        from dbos import DBOS

        engine = self
        store = self._store

        @DBOS.step(name="automation_execute")
        async def automation_execute(
            automation_id: str, trigger: str, trigger_payload: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await engine.execute_payload(automation_id, trigger, trigger_payload)

        @DBOS.step(name="automation_record_outcome")
        async def automation_record_outcome(automation_id: str, run: dict[str, Any]) -> None:
            engine.apply_outcome(automation_id, run)

        @DBOS.workflow(name=WORKFLOW_RUN_NAME)
        async def automation_run(scheduled_or_id: Any, ctx: Any = None, trigger_payload: Any = None) -> dict[str, Any]:
            if engine._global_pause_active():
                return {"status": "paused", "reason": "global-emergency-pause"}
            # cron 触发: (datetime, context dict)；enqueue 触发: (id, trigger str)
            if isinstance(scheduled_or_id, str):
                automation_id, trigger = scheduled_or_id, str(ctx or "manual")
            else:
                automation_id, trigger = (ctx or {}).get("automation_id", ""), "cron"
            run = await automation_execute(
                automation_id, trigger,
                trigger_payload if isinstance(trigger_payload, dict) else None,
            )
            await automation_record_outcome(automation_id, {**run, "trigger": trigger})
            return run

        @DBOS.workflow(name=WORKFLOW_INTERVAL_NAME)
        async def automation_interval_loop(automation_id: str) -> dict[str, Any]:
            while True:
                record = store.get(automation_id)
                if (
                    engine._global_pause_active()
                    or record is None
                    or not record.get("enabled")
                    or record["state"].get("paused_reason")
                ):
                    return {"stopped": True, "automation_id": automation_id}
                await engine._enqueue_run(automation_id, "interval")
                await DBOS.sleep_async(
                    max(0.05, float(record["trigger"].get("every_seconds") or 1.0))
                )

        self._wf = SimpleNamespace(
            run=automation_run,
            interval_loop=automation_interval_loop,
        )

    def start(self, dbos: Any) -> dict[str, Any]:
        """Sync startup（只能在没有事件循环的线程里调；服务器请用 start_async）。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("AutomationEngine.start() 不能在事件循环内调用，请用 start_async()")
        self._define_workflows()
        self._dbos = dbos
        _ensure_launched()
        self._register_queue_sync()
        self._started = True
        _run_isolated(self.reconcile_async())
        return self.status()

    async def start_async(self, dbos: Any) -> dict[str, Any]:
        """Async startup（server loop / 测试）。"""
        self._define_workflows()
        self._dbos = dbos
        _ensure_launched()
        from dbos import DBOS

        await DBOS.register_queue_async(
            self.QUEUE_NAME, global_concurrency=self._queue_concurrency
        )
        self._started = True
        await self.reconcile_async()
        return self.status()

    def shutdown(self) -> None:
        """Stop background pieces; the injected DBOS instance stays owned by its creator."""
        if self._triggers is not None:
            self._triggers.stop()
        self._started = False

    def attach_triggers(self, manager: Any) -> None:
        """Register the event-trigger manager (created by automation.triggers)."""
        self._triggers = manager

    @property
    def triggers(self) -> Any:
        return self._triggers

    def status(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "queue": self.QUEUE_NAME,
            "dbos": self._dbos is not None,
        }

    def _register_queue_sync(self) -> None:
        from dbos import DBOS

        try:
            DBOS.register_queue(self.QUEUE_NAME, global_concurrency=self._queue_concurrency)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("automation.queue_register_failed", error=str(exc))

    def _require_started(self) -> None:
        if not self._started or self._dbos is None or self._wf is None:
            raise RuntimeError("AutomationEngine 未启动（先 start/start_async）")

    # -- reconcile: store -> DBOS ---------------------------------------------

    async def reconcile_async(self) -> None:
        """Bring DBOS objects in line with the store (idempotent; safe to repeat)."""
        for record in self._store.list():
            try:
                await self._sync_automation(record)
            except Exception as exc:
                log.exception(
                    "automation.sync_failed",
                    automation_id=record.get("id"),
                    error=str(exc),
                )

    def reconcile(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            _run_isolated(self.reconcile_async())
            return
        task = asyncio.get_running_loop().create_task(self.reconcile_async())
        task.add_done_callback(self._log_task_error)

    async def sync_automation(self, record: dict[str, Any]) -> None:
        """Re-sync a single automation after CRUD (no-op when not started)."""
        if not self._started:
            return
        await self._sync_automation(normalize_record(record))

    async def _sync_automation(self, record: dict[str, Any], *, emergency_resume: bool = False) -> None:
        kind = record["trigger"]["kind"]
        enabled = (bool(record.get("enabled")) and not record["state"].get("paused_reason")
                   and (emergency_resume or not self._global_pause_active()))
        if kind == "cron":
            self._sync_cron_schedule(record, enabled)
        elif kind == "interval":
            if enabled:
                await self._spawn_interval_loop_async(record)
            else:
                await self._stop_interval_loop(record["id"])
        elif kind == "date":
            if enabled:
                await self._schedule_date_run_async(record)

    # -- cron ------------------------------------------------------------------

    def _cron_signature(self, record: dict[str, Any]) -> dict[str, Any]:
        trigger = record["trigger"]
        return {
            "schedule": trigger["cron_expr"],
            "cron_timezone": trigger.get("tz") or self._tz,
            "automatic_backfill": record["policy"]["missed_run"] == "catchup",
            "workflow_name": WORKFLOW_RUN_NAME,
            "context": {"automation_id": record["id"]},
        }

    def _create_schedule(self, record: dict[str, Any]) -> None:
        from dbos import DBOS

        from atlas.capabilities.durable.dbos_compat import apply_scheduler_wait_shim

        # Ensure the schedule thread's wait is bounded before this schedule
        # (re)starts — a far-future cron overflows threading's wait and would
        # otherwise kill the scheduler thread. Idempotent.
        apply_scheduler_wait_shim()

        desired = self._cron_signature(record)
        DBOS.create_schedule(
            schedule_name=schedule_name(record["id"]),
            workflow_fn=self._wf.run,
            schedule=desired["schedule"],
            context=desired["context"],
            automatic_backfill=desired["automatic_backfill"],
            cron_timezone=desired["cron_timezone"],
            queue_name=self.QUEUE_NAME,
        )

    def _sync_cron_schedule(self, record: dict[str, Any], enabled: bool) -> None:
        from dbos import DBOS

        if self._wf is None:  # pragma: no cover - define_workflows 先行
            raise RuntimeError("workflows 未注册")
        name = schedule_name(record["id"])
        desired = self._cron_signature(record)
        existing = DBOS.get_schedule(name)
        if existing is None:
            self._create_schedule(record)
            existing = DBOS.get_schedule(name)
        else:
            differs = (
                existing.get("schedule") != desired["schedule"]
                or (existing.get("cron_timezone") or None) != desired["cron_timezone"]
                or bool(existing.get("automatic_backfill")) != desired["automatic_backfill"]
                or existing.get("workflow_name") != desired["workflow_name"]
            )
            if differs:
                # 3.0.0 没有 update API：delete + create（历史 run 保留在 sys_db）。
                DBOS.delete_schedule(name)
                self._create_schedule(record)
                existing = DBOS.get_schedule(name)
        if existing is None:  # pragma: no cover - create_schedule failed loudly
            return
        want_status = "ACTIVE" if enabled else "PAUSED"
        if (existing.get("status") or "ACTIVE") != want_status:
            if want_status == "PAUSED":
                DBOS.pause_schedule(name)
            else:
                DBOS.resume_schedule(name)

    def _remove_cron_schedule(self, automation_id: str) -> None:
        from dbos import DBOS

        DBOS.delete_schedule(schedule_name(automation_id))

    # -- interval ---------------------------------------------------------------

    async def active_interval_workflow(self, automation_id: str) -> str | None:
        from dbos import DBOS

        rows = await DBOS.list_workflows_async(
            workflow_id_prefix=interval_id_prefix(automation_id),
            status=list(RUN_STATUS_ACTIVE),
            limit=1,
            load_input=False,
            load_output=False,
        )
        return rows[0].workflow_id if rows else None

    async def _spawn_interval_loop_async(self, record: dict[str, Any]) -> str | None:
        """Start (or adopt) the self-continuing interval loop workflow."""
        from dbos import DBOS, SetWorkflowID

        self._require_started()
        automation_id = record["id"]
        if await self.active_interval_workflow(automation_id):
            return None
        prefix = interval_id_prefix(automation_id)
        previous = await DBOS.list_workflows_async(
            workflow_id_prefix=prefix, limit=1, sort_desc=True,
            load_input=False, load_output=False,
        )
        generation = len(previous)
        workflow_id = prefix if generation == 0 else f"{prefix}-g{generation}"
        with SetWorkflowID(workflow_id):
            handle = await DBOS.start_workflow_async(self._wf.interval_loop, automation_id)
        return handle.workflow_id

    async def _stop_interval_loop(self, automation_id: str) -> None:
        from dbos import DBOS

        loop_id = await self.active_interval_workflow(automation_id)
        if loop_id:
            await DBOS.cancel_workflow_async(loop_id)

    # -- date --------------------------------------------------------------------

    def _parse_at(self, at: str) -> datetime:
        dt = datetime.fromisoformat(at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)  # naive 视为 UTC
        return dt

    async def _schedule_date_run_async(self, record: dict[str, Any]) -> str | None:
        """Ensure exactly one pending (DELAYED) run for the one-shot date trigger."""
        from dbos import DBOS

        run_at = self._parse_at(record["trigger"]["at"])
        delay = (run_at - datetime.now(UTC)).total_seconds()
        if delay <= 0:
            return None
        pending = await DBOS.list_workflows_async(
            workflow_id_prefix=run_id_prefix(record["id"]),
            status=["ENQUEUED", "DELAYED", "PENDING", "RUNNING"],
            limit=1,
            load_input=False,
            load_output=False,
        )
        if pending:  # 已有待执行的 run，不重复入队
            return None
        handle = await self._enqueue_run(record["id"], "date", delay_seconds=delay)
        return handle.workflow_id

    # -- run enqueue（manual / event / webhook / date / interval child）-----------

    async def _enqueue_run(
        self,
        automation_id: str,
        trigger: str,
        *,
        delay_seconds: float | None = None,
        trigger_payload: dict[str, Any] | None = None,
    ) -> Any:
        """Enqueue one ``automation_run``；dedup id 保证同一 automation 同时至多一个活跃 run."""
        from dbos import DBOS

        self._require_started()
        if self._global_pause_active():
            raise RuntimeError("所有自动化正处于全局紧急暂停状态")
        options: dict[str, Any] = {
            "workflow_name": WORKFLOW_RUN_NAME,
            "queue_name": self.QUEUE_NAME,
            "workflow_id": f"{run_id_prefix(automation_id)}{uuid.uuid4().hex[:12]}",
            "deduplication_id": f"atlas-auto-run-{automation_id}",
            "duplication_policy": "return-existing",
            "attributes": {"automation_id": automation_id, "trigger": trigger},
        }
        if delay_seconds is not None and delay_seconds > 0:
            options["delay_seconds"] = float(delay_seconds)
        handle = await DBOS.enqueue_workflow_with_options_async(
            options, automation_id, trigger, trigger_payload or {},
        )
        log.info(
            "automation.run_enqueued",
            automation_id=automation_id,
            trigger=trigger,
            workflow_id=handle.workflow_id,
        )
        return handle

    def _run_receipt(self, workflow_id: str) -> dict[str, Any]:
        return {
            "fired": True,
            "receipt": {"kind": "dbos_workflow", "workflow_id": workflow_id},
            "workflow_id": workflow_id,
        }

    async def run_now(
        self, automation_id: str, *, trigger: str = "manual", wait: float | None = None
    ) -> dict[str, Any]:
        """Fire immediately; receipt = the DBOS workflow holding this run.

        活跃 run（ENQUEUED/DELAYED/PENDING/RUNNING）存在时 dedup 会合并到既有
        workflow，不重复 fire（receipt 即那个 RUNNING workflow）。
        """
        record = self._require_automation(automation_id)
        self._require_started()
        if self._global_pause_active():
            raise RuntimeError("所有自动化正处于全局紧急暂停状态")
        if not record.get("enabled") or record["state"].get("paused_reason"):
            raise RuntimeError("automation 已停用或暂停，先 resume 再 run-now")
        handle = await self._enqueue_run(automation_id, trigger)
        receipt = self._run_receipt(handle.workflow_id)
        if wait is not None:
            receipt["result"] = await self._wait_run(handle.workflow_id, timeout=wait)
            receipt["status"] = await self._workflow_status(handle.workflow_id)
        return receipt

    async def trigger_event(
        self, automation_id: str, *, source: str = "event", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Event/webhook 入口：经 dedup 入队（同一 automation 活跃时合并为既有 run）。"""
        record = self._require_automation(automation_id)
        self._require_started()
        if self._global_pause_active():
            return {"fired": False, "reason": "global-emergency-pause"}
        if not record.get("enabled") or record["state"].get("paused_reason"):
            return {"fired": False, "reason": "paused"}
        handle = await self._enqueue_run(automation_id, source, trigger_payload=payload)
        return {"fired": True, "workflow_id": handle.workflow_id, "payload": payload or {}}

    async def _wait_run(self, workflow_id: str, timeout: float) -> Any:
        from dbos import DBOS

        try:
            return await asyncio.wait_for(DBOS.get_result_async(workflow_id), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    async def _workflow_status(self, workflow_id: str) -> str | None:
        from dbos import DBOS

        status = await DBOS.get_workflow_status_async(workflow_id)
        return getattr(status, "status", None)

    # -- cancel / pause / resume --------------------------------------------------

    async def active_run_workflows(self, automation_id: str) -> list[str]:
        from dbos import DBOS

        rows = await DBOS.list_workflows_async(
            workflow_id_prefix=run_id_prefix(automation_id),
            status=list(RUN_STATUS_ACTIVE),
            load_input=False,
            load_output=False,
        )
        return [row.workflow_id for row in rows]

    async def cancel(self, automation_id: str) -> dict[str, Any]:
        """Cancel 活跃 run + interval loop（cron schedule 保留）。"""
        self._require_automation(automation_id)
        self._require_started()
        from dbos import DBOS

        cancelled: list[str] = []
        for workflow_id in await self.active_run_workflows(automation_id):
            await DBOS.cancel_workflow_async(workflow_id)
            cancelled.append(workflow_id)
        loop_id = await self.active_interval_workflow(automation_id)
        if loop_id:
            await DBOS.cancel_workflow_async(loop_id)
            cancelled.append(loop_id)
        record = self._require_automation(automation_id)
        self._cleanup_record_worktree(record)
        return {"cancelled": cancelled}

    async def remove(self, automation_id: str) -> None:
        """Delete 之前的 DBOS 清理：cron schedule、活跃 run、interval loop。"""
        if not self._started:
            record = self._store.get(automation_id)
            if record is not None:
                self._cleanup_record_worktree(record)
            return
        from dbos import DBOS

        self._remove_cron_schedule(automation_id)
        for workflow_id in await self.active_run_workflows(automation_id):
            await DBOS.cancel_workflow_async(workflow_id)
        await self._stop_interval_loop(automation_id)
        record = self._store.get(automation_id)
        if record is not None:
            self._cleanup_record_worktree(record)

    async def pause(self, automation_id: str, reason: str = "user") -> dict[str, Any]:
        self._require_automation(automation_id)
        self._store.update_state(automation_id, paused_reason=reason)
        record = self._require_automation(automation_id)
        await self._sync_automation(record)  # cron→pause schedule；interval→cancel loop/runs
        return {"id": automation_id, "paused": True, "reason": reason}

    async def resume(self, automation_id: str, *, emergency_resume: bool = False) -> dict[str, Any]:
        self._require_automation(automation_id)
        if self._global_pause_active() and not emergency_resume:
            raise RuntimeError("全局紧急暂停期间不能单独恢复自动化")
        self._store.update_state(automation_id, paused_reason=None)
        record = self._require_automation(automation_id)
        await self._sync_automation(record, emergency_resume=emergency_resume)
        return {"id": automation_id, "paused": False}

    async def emergency_pause(self) -> dict[str, Any]:
        """Pause every automation, persist the exact resume set, then cancel active runs."""
        from atlas.config import DATA_ROOT
        import json, os, tempfile

        lock = getattr(self, "_emergency_lock", None)
        if lock is None:
            lock = self._emergency_lock = asyncio.Lock()
        async with lock:
            manifest = DATA_ROOT / "data" / "automation-emergency-pause.json"
            records = self._store.list()
            state = {"version": 1, "paused": True, "resume_ids": [r["id"] for r in records
                     if r.get("enabled") and not r.get("state", {}).get("paused_reason")],
                     "affected": [], "updated_at": __import__("time").time()}
            manifest.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".automation-emergency-", dir=manifest.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(state, handle, ensure_ascii=False)
                    handle.flush(); os.fsync(handle.fileno())
                os.replace(temporary, manifest)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            for record in records:
                aid = str(record["id"])
                try:
                    if record.get("enabled") and not record.get("state", {}).get("paused_reason"):
                        await self.pause(aid, reason="global-emergency")
                    cancelled = await self.cancel(aid)
                    state["affected"].append({"id": aid, "name": record.get("name", aid),
                                              "cancelled": len(cancelled.get("cancelled", [])), "error": None})
                except Exception as exc:
                    state["affected"].append({"id": aid, "name": record.get("name", aid),
                                              "cancelled": 0, "error": str(exc)})
            state["updated_at"] = __import__("time").time()
            manifest.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            return state

    async def emergency_resume(self) -> dict[str, Any]:
        """Resume only automations recorded as enabled before the global pause."""
        from atlas.config import DATA_ROOT
        import json

        lock = getattr(self, "_emergency_lock", None)
        if lock is None:
            lock = self._emergency_lock = asyncio.Lock()
        async with lock:
            manifest = DATA_ROOT / "data" / "automation-emergency-pause.json"
            try:
                state = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = {"paused": False, "resume_ids": [], "affected": []}
            resumed, failures = [], []
            for aid in state.get("resume_ids", []):
                record = self._store.get(str(aid))
                if not record or not record.get("enabled") or record.get("state", {}).get("paused_reason") != "global-emergency":
                    continue
                try:
                    await self.resume(str(aid), emergency_resume=True); resumed.append(str(aid))
                except Exception as exc:
                    failures.append({"id": aid, "error": str(exc)})
            state.update({"paused": False, "resume_ids": [], "resumed": resumed, "failures": failures})
            manifest.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            return state

    @staticmethod
    def _global_pause_active() -> bool:
        """Authoritative gate for manual, event and newly-added triggers."""
        import json
        from atlas.config import DATA_ROOT
        try:
            return bool(json.loads((DATA_ROOT / "data" / "automation-emergency-pause.json").read_text(encoding="utf-8")).get("paused"))
        except (OSError, ValueError, AttributeError):
            return False

    # -- payload 执行（step 内运行）-------------------------------------------------

    async def execute_payload(
        self, automation_id: str, trigger: str,
        trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个 automation 的 payload；在 DBOS step 内调用（可安全做副作用）。"""
        run_id = uuid.uuid4().hex
        record = self._store.get(automation_id)
        started_at = _utc_now_iso()
        if record is None:
            return {"status": "skipped", "reason": "missing", "delivery": "not-requested"}
        if not record.get("enabled") or record["state"].get("paused_reason"):
            return {"status": "skipped", "reason": "paused", "delivery": "not-requested"}
        payload = record["payload"]
        status, error, result = "ok", "", None
        try:
            kind = payload["kind"]
            if kind == "heartbeat":
                if self._heartbeat_tick is None:
                    raise RuntimeError("heartbeat_tick 未注入")
                agent_id = payload.get("agent_id") or record.get("owner_agent_id") or ""
                result = await self._heartbeat_tick(agent_id, "schedule")
            elif kind == "agent_turn" and _is_reminder(record):
                # A reminder is a notification, not a task: never run the agent on
                # "交周报" — deliver the reminder text itself.
                result = REMINDER_NAME_PREFIX + str(payload.get("message") or "")
            elif kind == "agent_turn":
                if self._dispatch_turn is None:
                    raise RuntimeError("dispatch_turn 未注入")
                execution = self._prepare_execution(record)
                result = await self._dispatch_turn(
                    {
                        "automation_id": automation_id,
                        "trigger": trigger,
                        "message": _message_with_webhook_payload(
                            str(payload.get("message", "")), trigger, trigger_payload,
                        ),
                        "webhook_payload": trigger_payload or {},
                        "agent_id": payload.get("agent_id") or record.get("owner_agent_id", ""),
                        "agent_preset_id": payload.get("agent_preset_id", "default"),
                        "permission_preset": payload.get("permission_preset", "ask"),
                        "model": payload.get("model", ""),
                        "reasoning_effort": payload.get("reasoning_effort", ""),
                        "skills": payload.get("skills", []),
                        "wake_mode": payload.get("wake_mode", ""),
                        "conversation_id": payload.get("conversation_id", ""),
                        "workspace": execution.get("workspace", ""),
                        "worktree_path": execution.get("worktree_path", ""),
                        "worktree_branch": execution.get("worktree_branch", ""),
                        "base_branch": execution.get("base_branch", ""),
                        "cleanup_policy": payload.get("cleanup_policy", "keep"),
                    }
                )
                if execution.get("worktree_path"):
                    result = ({**result} if isinstance(result, dict) else {"text": str(result or "")})
                    result.update({key: value for key, value in execution.items() if key != "workspace"})
                    if payload.get("cleanup_policy") == "remove_after_run":
                        self._cleanup_record_worktree(self._require_automation(automation_id))
            elif kind == "script":
                result = await self._run_script(payload, trigger_payload=trigger_payload)
            else:
                raise ValueError(f"未知 payload.kind: {kind!r}")
        except (asyncio.TimeoutError, TimeoutError):
            status, error = "error", "script timeout"
        except Exception as exc:  # 失败进入 consecutive_errors 统计
            log.exception("automation.script_failed", automation_id=record["id"])
            status, error = "error", str(exc)
        if status != "ok" and payload.get("cleanup_policy") == "remove_after_run":
            latest = self._store.get(automation_id)
            if latest is not None:
                self._cleanup_record_worktree(latest)
        delivery = await self._settle_delivery(record, {"status": status, "result": result})
        return {
            "run_id": run_id,
            "automation_id": automation_id,
            "automation_name": str(record.get("name") or automation_id),
            "conversation_id": str(payload.get("conversation_id") or f"automation-{automation_id}")
                if payload.get("kind") == "agent_turn" and not _is_reminder(record) else "",
            "status": status,
            "error": error,
            "delivery": delivery,
            "trigger": trigger,
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
            "result": _summarize(result),
        }

    async def _run_script(
        self, payload: dict[str, Any], *, trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        script = str(payload.get("script", ""))
        timeout = float(payload.get("timeout_seconds") or 60.0)
        proc = await asyncio.create_subprocess_shell(
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "ATLAS_WEBHOOK_PAYLOAD": json.dumps(trigger_payload or {}, ensure_ascii=False)},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            raise
        text = (stdout or b"").decode("utf-8", "replace").strip()
        err = (stderr or b"").decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"script exit {proc.returncode}: {err[:500] or text[:500]}")
        return {"exit_code": proc.returncode, "stdout": text[:4000]}

    def _prepare_execution(self, record: dict[str, Any]) -> dict[str, str]:
        """Resolve local cwd or create and durably record a per-run git worktree."""
        payload = record["payload"]
        base = str(payload.get("base_directory") or "").strip()
        if payload.get("execution_mode", "local") != "worktree":
            return {"workspace": base}
        root = Path(base).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Automation base directory does not exist: {base}")

        def git(*args: str) -> str:
            proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
            if proc.returncode:
                raise ValueError(proc.stderr.strip() or "git command failed")
            return proc.stdout.strip()

        git_root = Path(git("rev-parse", "--show-toplevel")).resolve()
        base_branch = git("branch", "--show-current") or "HEAD"
        run_key = uuid.uuid4().hex[:12]
        branch = f"atlas/automation-{record['id'][:28]}-{run_key}"
        worktree = git_root / ".atlas-worktrees" / "automations" / f"{record['id']}-{run_key}"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", branch, str(worktree), base_branch)
        self._store.put({**record, "payload": {**payload, "worktree_path": str(worktree),
                          "worktree_branch": branch, "base_branch": base_branch}})
        return {"workspace": str(worktree), "worktree_path": str(worktree),
                "worktree_branch": branch, "base_branch": base_branch}

    def _cleanup_record_worktree(self, record: dict[str, Any]) -> None:
        payload = record.get("payload") or {}
        path = str(payload.get("worktree_path") or "").strip()
        branch = str(payload.get("worktree_branch") or "").strip()
        base = str(payload.get("base_directory") or "").strip()
        if not path or not branch or not base:
            return
        root = Path(base).expanduser().resolve()
        worktree = Path(path).expanduser().resolve()
        try:
            repo = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            if repo.returncode:
                return
            git_root = Path(repo.stdout.strip()).resolve()
            if not worktree.is_relative_to(git_root / ".atlas-worktrees" / "automations"):
                return
            subprocess.run(["git", "-C", str(git_root), "worktree", "remove", "--force", str(worktree)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            subprocess.run(["git", "-C", str(git_root), "branch", "-D", branch],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        except OSError:
            log.exception("automation.worktree_cleanup_failed", automation_id=record.get("id"), path=path)

    async def _settle_delivery(self, record: dict[str, Any], outcome: dict[str, Any]) -> str:
        """delivery outcome ∈ delivered | not-delivered | unknown | not-requested."""
        if outcome["status"] == "error":
            return "unknown"
        delivery = record.get("delivery") or {}
        # Reminders always notify the owner, including ones stored with mode "none".
        if delivery.get("mode") != "channel" and not _is_reminder(record):
            return "not-requested"
        if self._deliver is None:
            return "not-delivered"
        try:
            delivered = await self._deliver(record, outcome)
        except Exception as exc:
            log.exception("automation.delivery_failed", automation_id=record["id"], error=str(exc))
            return "not-delivered"
        return "delivered" if delivered else "not-delivered"

    def apply_outcome(self, automation_id: str, run: dict[str, Any]) -> None:
        """把一次 run 的结果写回 store state；连续失败达阈值 → auto disable.

        在 DBOS step 内调用（崩溃恢复重放安全：等值写回）。
        """
        record = self._store.get(automation_id)
        if record is None:
            return
        from atlas.automation.inbox import record_run

        record_run(record, {**run, "automation_id": automation_id})
        status = run.get("status", "error")
        fields: dict[str, Any] = {
            "last_run_at": run.get("finished_at") or _utc_now_iso(),
            "last_status": status,
            "last_error": run.get("error", ""),
        }
        if status == "ok":
            fields["consecutive_errors"] = 0
        else:
            threshold = int(record["policy"].get("consecutive_error_disable") or 10)
            errors = int(record["state"].get("consecutive_errors") or 0) + 1
            fields["consecutive_errors"] = errors
            if (
                errors >= threshold
                and record["state"].get("paused_reason") != "consecutive-errors"
            ):
                fields["paused_reason"] = "consecutive-errors"
        self._store.update_state(automation_id, **fields)
        if fields.get("paused_reason"):
            fresh = self._store.get(automation_id)
            if fresh is not None and fresh["trigger"]["kind"] == "cron":
                self._sync_cron_schedule(fresh, enabled=False)
            log.warning(
                "automation.auto_disabled",
                automation_id=automation_id,
                consecutive_errors=fields["consecutive_errors"],
            )
        # one-shot：date 触发成功后按 delete_after_run 清理
        if (
            status == "ok"
            and run.get("trigger") == "date"
            and record["policy"].get("delete_after_run")
        ):
            self._store.delete(automation_id)

    # -- 查询 -----------------------------------------------------------------------

    async def get_runs(self, automation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Run history = DBOS workflow rows.

        两个来源合并（SQLite 无 attributes 过滤）：手动/event/date/interval 的
        run 用统一 ``atlas-auto-run-{id}-`` 前缀；cron 触发的 run 挂在
        schedule_name（``sched-{name}-{iso}`` workflow id）下。
        """
        from dbos import DBOS

        rows = await DBOS.list_workflows_async(
            workflow_id_prefix=run_id_prefix(automation_id),
            limit=limit * 2,
            sort_desc=True,
            load_input=False,
            load_output=True,
        )
        try:
            cron_rows = await DBOS.list_workflows_async(
                schedule_name=schedule_name(automation_id),
                limit=limit * 2,
                sort_desc=True,
                load_input=False,
                load_output=True,
            )
        except Exception as exc:  # pragma: no cover - 防御：schedule 过滤不可用时降级
            log.exception("automation.cron_runs_query_failed", error=str(exc))
            cron_rows = []
        merged: dict[str, dict[str, Any]] = {}
        for row in [*cron_rows, *rows]:
            merged[row.workflow_id] = self._run_row(row)
        runs = sorted(merged.values(), key=lambda item: item["created_at"], reverse=True)
        return runs[:limit]

    def _run_row(self, row: Any) -> dict[str, Any]:
        error = row.error
        return {
            "workflow_id": row.workflow_id,
            "status": row.status,
            "name": row.name,
            "queue_name": row.queue_name,
            "schedule_name": getattr(row, "schedule_name", None) or "",
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
            "completed_at": _iso(getattr(row, "completed_at", None)),
            "error": str(error) if error else "",
            "attributes": getattr(row, "attributes", None) or {},
            "result": _summarize(getattr(row, "output", None)),
        }

    # -- helpers -----------------------------------------------------------------

    def _require_automation(self, automation_id: str) -> dict[str, Any]:
        record = self._store.get(automation_id)
        if record is None:
            raise KeyError(f"automation 不存在: {automation_id}")
        return record

    def _log_task_error(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("automation.background_task_failed", error=str(exc))


def _summarize(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        keys = list(result)[:10]
        if "result" in result and "result" not in keys:
            keys[-1:] = ["result"]
        return {key: result[key] for key in keys}
    return str(result)[:2000]
