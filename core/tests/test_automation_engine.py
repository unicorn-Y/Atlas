"""AutomationEngine × DBOS 3.0.0 集成覆盖（lane W4）.

生命周期策略（探针 tests/test_automation_dbos_probe.py 的结论）：本进程可以
多次 init/launch/destroy DBOS，但 workflow 注册表按 name 全局持有、闭包重复
注册会互相覆盖——因此**全模块共用一个 DBOS 实例 + 一个 AutomationEngine**，
用例之间用唯一 automation id 隔离，注入 hook 经可变 recorder 切换。

覆盖：cron schedule 创建幂等/更新、cron 真触发 + run history、run_now 无重复
fire（dedup receipt）、heartbeat payload 走注入 tick、agent_turn 走注入
dispatch、script payload subprocess 真跑（echo + 失败退出码）、interval 自续
loop + pause/cancel、consecutive_errors → auto-disable、date 延迟入队 +
delete_after_run、event/webhook 触发入口（triggers.py）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from atlas.automation.engine import (
    AutomationEngine,
    interval_id_prefix,
    run_id_prefix,
    schedule_name,
)
from atlas.automation.store import AutomationStore, normalize_record
from atlas.automation.triggers import EventTriggerManager

pytest.importorskip("dbos")

# DBOS 3.0.0 在首个 *_async 调用时把自己的进程级线程池设为**当前事件循环**的
# default executor；pytest-asyncio 的函数级 loop 经 asyncio.Runner 关闭时会
# shutdown default executor → DBOS 线程池被杀、后续用例全部
# "cannot schedule new futures after shutdown"。因此全模块共享一个 loop。
pytestmark = pytest.mark.asyncio(loop_scope="module")

RUN_WAIT = 15.0  # 队列轮询默认 1s + SQLite 写竞争余量


def _dbos_config(db_dir: Path) -> dict:
    return {
        "name": "atlas-automation-engine",
        "system_database_url": f"sqlite:///{(db_dir / 'dbos.sqlite').as_posix()}",
        "db_engine_kwargs": {"connect_args": {"timeout": 30}},
        "scheduler_polling_interval_sec": 1.0,
    }


class _Hooks:
    """Per-test mutable hook recorder (shared engine reads these at call time)."""

    def __init__(self) -> None:
        self.tick_calls: list[tuple[str, str]] = []
        self.dispatch_calls: list[dict[str, Any]] = []
        self.deliver_calls: list[dict[str, Any]] = []
        self.tick_delay = 0.0
        self.deliver_ok = True

    def reset(self) -> None:
        self.tick_calls.clear()
        self.dispatch_calls.clear()
        self.deliver_calls.clear()
        self.tick_delay = 0.0
        self.deliver_ok = True

    async def tick(self, agent_id: str, reason: str) -> dict[str, Any]:
        self.tick_calls.append((agent_id, reason))
        if self.tick_delay:
            await asyncio.sleep(self.tick_delay)
        return {"tick": agent_id, "reason": reason}

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.dispatch_calls.append(payload)
        return {"sent": True, "message": payload.get("message", "")}

    async def deliver(self, record: dict[str, Any], outcome: dict[str, Any]) -> bool:
        self.deliver_calls.append({"id": record.get("id"), "status": outcome.get("status")})
        return self.deliver_ok


@pytest.fixture(scope="module")
def env(tmp_path_factory) -> Any:
    tmp = tmp_path_factory.mktemp("automation-engine")
    from dbos import DBOS

    (tmp / "dbos").mkdir(parents=True, exist_ok=True)
    DBOS(config=_dbos_config(tmp / "dbos"))
    DBOS.launch()
    hooks = _Hooks()
    store = AutomationStore(tmp / "automations.toml")
    engine = AutomationEngine(
        store,
        heartbeat_tick=hooks.tick,
        dispatch_turn=hooks.dispatch,
        deliver=hooks.deliver,
    )
    engine.start(DBOS)
    yield SimpleNamespace(engine=engine, store=store, hooks=hooks, tmp=tmp)
    engine.shutdown()
    DBOS.destroy(destroy_registry=True)


def _put(env: Any, automation_id: str, **fields: Any) -> dict[str, Any]:
    record = normalize_record({"id": automation_id, "name": automation_id, **fields})
    return env.store.put(record)


async def _wait_until(predicate, timeout: float = 12.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.2)
    return bool(predicate())


async def _wait_for_runs(env: Any, automation_id: str, count: int, timeout: float = 12.0) -> list[dict]:
    runs: list[dict] = []
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        runs = await env.engine.get_runs(automation_id)
        if len(runs) >= count:
            return runs
        await asyncio.sleep(0.25)
    return runs


# ---------------------------------------------------------------------------
# cron schedule：创建幂等 / 签名更新
# ---------------------------------------------------------------------------


async def test_cron_schedule_create_is_idempotent_and_updates(env: Any) -> None:
    from dbos import DBOS

    automation_id = "eng-cron-idem"
    record = _put(
        env,
        automation_id,
        trigger={"kind": "cron", "cron_expr": "0 0 1 1 *"},  # 每年一次：测试窗口内不触发
        payload={"kind": "script", "script": "echo hi"},
    )
    name = schedule_name(automation_id)

    await env.engine.sync_automation(record)
    first = DBOS.get_schedule(name)
    assert first is not None
    assert first["schedule"] == "0 0 1 1 *"
    assert first["status"] == "ACTIVE"

    # 再同步：不重复创建、不抛（同名 create_schedule 会被 DBOS 拒绝）
    await env.engine.sync_automation(record)
    second = DBOS.get_schedule(name)
    assert second is not None
    assert second["schedule"] == first["schedule"]

    # 改表达式 → delete+create 更新到新签名
    updated = _put(env, automation_id, trigger={"kind": "cron", "cron_expr": "30 0 1 1 *"})
    await env.engine.sync_automation(updated)
    third = DBOS.get_schedule(name)
    assert third is not None
    assert third["schedule"] == "30 0 1 1 *"

    env.store.delete(automation_id)
    DBOS.delete_schedule(name)


async def test_cron_schedule_fires_and_run_history_merges_cron_runs(env: Any) -> None:
    from dbos import DBOS

    automation_id = "eng-cron-fire"
    record = _put(
        env,
        automation_id,
        trigger={"kind": "cron", "cron_expr": "*/2 * * * * *"},  # 每 2 秒
        payload={"kind": "script", "script": "echo cron-fired"},
    )
    try:
        await env.engine.sync_automation(record)
        runs = await _wait_for_runs(env, automation_id, 1, timeout=15.0)
        assert runs, "cron 触发的 run 应出现在 run history（schedule_name 过滤）"
        assert any(row["workflow_id"].startswith("sched-") for row in runs)
        assert any(row["schedule_name"] == schedule_name(automation_id) for row in runs)
        assert all(row["status"] in {"SUCCESS", "PENDING", "RUNNING", "ENQUEUED"} for row in runs)
    finally:
        DBOS.delete_schedule(schedule_name(automation_id))
        await env.engine.cancel(automation_id)
        env.store.delete(automation_id)


# ---------------------------------------------------------------------------
# run_now：receipt = DBOS workflow，活跃期间不重复 fire
# ---------------------------------------------------------------------------


async def test_run_now_no_duplicate_fire_with_heartbeat_tick(env: Any) -> None:
    automation_id = "eng-run-now"
    _put(
        env,
        automation_id,
        owner_agent_id="",
        payload={"kind": "heartbeat", "agent_id": "agent-h"},
        policy={"missed_run": "skip", "consecutive_error_disable": 3},
    )
    env.hooks.reset()
    env.hooks.tick_delay = 0.8  # 拉长 run 活跃窗口

    first = await env.engine.run_now(automation_id)
    second = await env.engine.run_now(automation_id)  # 首个 run 仍在 RUNNING
    assert first["fired"] is True
    assert first["receipt"]["kind"] == "dbos_workflow"
    assert first["workflow_id"].startswith(run_id_prefix(automation_id))
    # dedup（return-existing）：第二个请求拿到同一个 RUNNING workflow
    assert second["workflow_id"] == first["workflow_id"]

    result = await asyncio.wait_for(
        env.engine._wait_run(first["workflow_id"], timeout=RUN_WAIT), timeout=RUN_WAIT
    )
    assert result is not None and result["status"] == "ok"
    assert env.hooks.tick_calls == [("agent-h", "schedule")]  # W3 接缝：只执行一次
    env.store.delete(automation_id)


async def test_heartbeat_requires_injected_tick(env: Any) -> None:
    automation_id = "eng-tick-missing"
    _put(env, automation_id, payload={"kind": "heartbeat", "agent_id": "agent-x"})
    bare = AutomationEngine(env.store)  # 未注入 heartbeat_tick 的同 store 引擎
    result = await bare.execute_payload(automation_id, "manual")
    assert result["status"] == "error"
    assert "heartbeat_tick" in result["error"]
    env.store.delete(automation_id)


# ---------------------------------------------------------------------------
# payload 执行：agent_turn / script / delivery outcome
# ---------------------------------------------------------------------------


async def test_agent_turn_payload_goes_to_injected_dispatch(env: Any) -> None:
    automation_id = "eng-agent-turn"
    _put(
        env,
        automation_id,
        owner_agent_id="owner-a",
        payload={"kind": "agent_turn", "message": "做一件事", "model": "gpt-x", "reasoning_effort": "high"},
    )
    env.hooks.reset()
    receipt = await env.engine.run_now(automation_id, wait=RUN_WAIT)
    assert receipt["status"] == "SUCCESS"
    assert receipt["result"]["status"] == "ok"
    assert receipt["result"]["delivery"] == "not-requested"  # delivery.mode=none
    call = env.hooks.dispatch_calls[0]
    assert call["automation_id"] == automation_id
    assert call["message"] == "做一件事"
    assert call["agent_id"] == "owner-a"  # payload.agent_id 为空时回退 owner
    assert call["model"] == "gpt-x"
    assert call["reasoning_effort"] == "high"
    assert call["trigger"] == "manual"
    env.store.delete(automation_id)


async def test_script_payload_runs_real_subprocess(env: Any) -> None:
    automation_id = "eng-script-echo"
    _put(env, automation_id, payload={"kind": "script", "script": "echo atlas-w4-ok"})
    receipt = await env.engine.run_now(automation_id, wait=RUN_WAIT)
    assert receipt["status"] == "SUCCESS"
    result = receipt["result"]
    assert result["status"] == "ok"
    assert result["delivery"] == "not-requested"
    assert "atlas-w4-ok" in result["result"]["stdout"]
    assert result["result"]["exit_code"] == 0
    env.store.delete(automation_id)


async def test_script_failure_yields_error_outcome(env: Any) -> None:
    automation_id = "eng-script-fail"
    _put(env, automation_id, payload={"kind": "script", "script": "exit 7"})
    receipt = await env.engine.run_now(automation_id, wait=RUN_WAIT)
    assert receipt["result"]["status"] == "error"
    assert "exit 7" in receipt["result"]["error"]
    assert receipt["result"]["delivery"] == "unknown"  # 执行失败 → 投递结果未知
    state = env.store.get(automation_id)["state"]
    assert state["last_status"] == "error"
    assert state["consecutive_errors"] == 1
    env.store.delete(automation_id)


async def test_delivery_channel_outcomes(env: Any) -> None:
    automation_id = "eng-deliver"
    _put(
        env,
        automation_id,
        payload={"kind": "script", "script": "echo delivered"},
        delivery={"mode": "channel", "channel": "telegram", "target": "chat-1"},
    )
    env.hooks.reset()
    ok = await env.engine.run_now(automation_id, wait=RUN_WAIT)
    assert ok["result"]["delivery"] == "delivered"
    assert env.hooks.deliver_calls[-1]["id"] == automation_id

    env.hooks.deliver_ok = False
    not_delivered = await env.engine.run_now(automation_id, wait=RUN_WAIT)
    assert not_delivered["result"]["delivery"] == "not-delivered"
    env.store.delete(automation_id)


# ---------------------------------------------------------------------------
# interval：自续 loop → 多次 run；pause/cancel 停止
# ---------------------------------------------------------------------------


async def test_interval_loop_fires_pause_stops_and_resume_restarts(env: Any) -> None:
    automation_id = "eng-interval"
    record = _put(
        env,
        automation_id,
        trigger={"kind": "interval", "every_seconds": 0.3},
        payload={"kind": "script", "script": "echo tick"},
    )
    await env.engine.sync_automation(record)
    runs = await _wait_for_runs(env, automation_id, 2, timeout=15.0)
    assert len(runs) >= 2, "interval 自续 loop 应产生多次 run"
    loop_id = await env.engine.active_interval_workflow(automation_id)
    assert loop_id is not None and loop_id.startswith(interval_id_prefix(automation_id))

    await env.engine.pause(automation_id)
    state = env.store.get(automation_id)["state"]
    assert state["paused_reason"] == "user"
    assert await env.engine.active_interval_workflow(automation_id) is None
    paused_runs = len(await env.engine.get_runs(automation_id))

    # 暂停期间：不新增 run、run-now 拒绝
    await asyncio.sleep(1.5)
    assert len(await env.engine.get_runs(automation_id)) == paused_runs
    with pytest.raises(RuntimeError, match="暂停"):
        await env.engine.run_now(automation_id)

    await env.engine.resume(automation_id)
    assert env.store.get(automation_id)["state"]["paused_reason"] == ""
    runs_after = await _wait_for_runs(env, automation_id, paused_runs + 1, timeout=15.0)
    assert len(runs_after) > paused_runs

    cancelled = await env.engine.cancel(automation_id)
    assert cancelled["cancelled"], "cancel 应停掉活跃 run / interval loop"
    env.store.delete(automation_id)


# ---------------------------------------------------------------------------
# consecutive_errors → auto-disable（默认阈值 10，此处用 2 加速）
# ---------------------------------------------------------------------------


async def test_consecutive_errors_auto_disables(env: Any) -> None:
    from dbos import DBOS

    automation_id = "eng-auto-disable"
    record = _put(
        env,
        automation_id,
        trigger={"kind": "cron", "cron_expr": "0 0 1 1 *"},
        payload={"kind": "script", "script": "exit 3"},
        policy={"missed_run": "skip", "consecutive_error_disable": 2},
    )
    await env.engine.sync_automation(record)
    assert DBOS.get_schedule(schedule_name(automation_id))["status"] == "ACTIVE"

    await env.engine.run_now(automation_id, wait=RUN_WAIT)
    state = env.store.get(automation_id)["state"]
    assert state["paused_reason"] == ""  # 第 1 次失败：仅计数
    assert state["consecutive_errors"] == 1

    await env.engine.run_now(automation_id, wait=RUN_WAIT)
    state = env.store.get(automation_id)["state"]
    assert state["consecutive_errors"] == 2
    assert state["paused_reason"] == "consecutive-errors"

    # auto-disable 同步到 DBOS schedule + 拒绝手动 fire
    assert DBOS.get_schedule(schedule_name(automation_id))["status"] == "PAUSED"
    with pytest.raises(RuntimeError, match="暂停"):
        await env.engine.run_now(automation_id)

    # resume 清零恢复（调度重新 ACTIVE；consecutive_errors 复位由下一次成功归零）
    await env.engine.resume(automation_id)
    assert DBOS.get_schedule(schedule_name(automation_id))["status"] == "ACTIVE"
    DBOS.delete_schedule(schedule_name(automation_id))
    env.store.delete(automation_id)


# ---------------------------------------------------------------------------
# date：延迟入队 + delete_after_run
# ---------------------------------------------------------------------------


async def test_date_trigger_delayed_run_and_delete_after_run(env: Any) -> None:
    from dbos import DBOS

    automation_id = "eng-date"
    at = (datetime.now(UTC) + timedelta(seconds=1.2)).isoformat()
    record = _put(
        env,
        automation_id,
        trigger={"kind": "date", "at": at},
        payload={"kind": "script", "script": "echo one-shot"},
        policy={"missed_run": "skip", "delete_after_run": True},
    )
    await env.engine.sync_automation(record)
    await env.engine.sync_automation(record)  # 幂等：不重复入队
    delayed = await DBOS.list_workflows_async(
        workflow_id_prefix=run_id_prefix(automation_id), limit=10, load_input=False, load_output=False
    )
    assert len(delayed) == 1, "date 触发应恰好一个待执行 run"

    ok_runs: list[dict] = []
    deadline = asyncio.get_running_loop().time() + RUN_WAIT
    while asyncio.get_running_loop().time() < deadline:
        ok_runs = [
            row
            for row in await env.engine.get_runs(automation_id)
            if row["status"] == "SUCCESS"
        ]
        if ok_runs:
            break
        await asyncio.sleep(0.25)
    assert ok_runs, "one-shot run 应执行成功"
    assert await _wait_until(lambda: env.store.get(automation_id) is None), (
        "delete_after_run：成功后删除产品记录"
    )


# ---------------------------------------------------------------------------
# event / webhook 触发入口（triggers.py）
# ---------------------------------------------------------------------------


async def test_event_and_webhook_triggers_enqueue_runs(env: Any) -> None:
    automation_id = "eng-event"
    watch_dir = env.tmp / "watch"
    watch_dir.mkdir(exist_ok=True)
    record = _put(
        env,
        automation_id,
        trigger={
            "kind": "event",
            "event_path": str(watch_dir),
            "event_glob": "*.log",
            "event_debounce": 0.1,
        },
        payload={"kind": "script", "script": "echo event"},
    )
    await env.engine.sync_automation(record)
    manager = EventTriggerManager(env.engine)
    manager.start()
    try:
        # 不匹配的文件：不触发
        manager.on_file_event(str(watch_dir / "notes.txt"))
        await asyncio.sleep(0.5)
        assert automation_id not in manager._debounce

        # 匹配的文件：防抖后触发（同路径连续两次只触发一次）
        manager.on_file_event(str(watch_dir / "build.log"))
        manager.on_file_event(str(watch_dir / "build.log"))
        assert automation_id in manager._debounce
        runs = await _wait_for_runs(env, automation_id, 1)
        assert len(runs) >= 1

        # webhook 同路入口
        fired = await manager.trigger_webhook(automation_id, {"topic": "deploy"})
        assert fired["fired"] is True
        assert fired["workflow_id"].startswith(run_id_prefix(automation_id))
    finally:
        manager.stop()
        await env.engine.cancel(automation_id)
        env.store.delete(automation_id)
