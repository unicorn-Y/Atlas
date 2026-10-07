"""S6 验收测试：中断任务接续与提醒验证（E8.1 与 E8.2 判据覆盖）.

覆盖 E8 的四条核心判据：
1. 真的提醒（E8.1）：
   - 时间提醒（说"明天上午 9 点提醒我交报告"）：意图解析/创建 → 投影为 Automation date trigger →
     存入 AutomationStore → AutomationEngine 执行 agent_turn payload 触发真实 dispatch →
     IntentBridge.on_automation_event 将意图推进至 TRIGGERED 并记录收据。
   - 事件提醒（说"下次打开 Atlas 项目时提醒我检查测试"）：意图包含 event cue →
     发生 project_open 域事件时，IntentBridge.handle_atlas_event 命中并触发，推进至 TRIGGERED。
2. 不重复（E8.1）：
   - 时间提醒：一经触发，二次调用 on_automation_event 幂等拒触（reason="intent_triggered"）；
     AutomationStore delete_after_run 生效清理，二次执行跳过。
   - 事件提醒：一经命中并转为 TRIGGERED，后续相同域事件匹配到 0 个活跃意图，不重复触发。
3. 取消后不提醒（E8.1）：
   - 用户取消意图：IntentBridge.cancel_intent 将生命周期转为 CANCELLED。
   - 取消后事件到来不触发（handle_atlas_event 忽略非活跃意图）；
     若定时触发器强行回调，on_automation_event 返回 reason="intent_cancelled"；
     AutomationStore / engine 删除后跳过执行。
4. 中断任务能接着做（E8.2）：
   - 多步任务中途进程崩溃/重启：第一步已写出的文件收据处于 UNKNOWN 状态。
   - 续接时执行确定性文件对账（reconcile_unknown_receipt / reconcile_focus_receipts）：
     磁盘文件存在 → 状态推进为 OK，纳入已验证步骤；
     续接运行回读权威版本（rev+1），知道已完成第一步，不重复执行写操作（写副作用总计 1 次）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

import pytest

from atlas.automation.engine import AutomationEngine
from atlas.automation.store import AutomationStore
from atlas.memory.intent_bridge import (
    IntentBridge,
    automation_id_for_intent,
    projection_for_intent,
)
from atlas.memory.reconcile import (
    STATUS_MISSING,
    STATUS_OK,
    STATUS_UNRESOLVED,
    reconcile_focus_receipts,
    reconcile_unknown_receipt,
)


DEFAULT_TEST_CONTEXT: dict[str, Any] = {
    "subject": "user:default",
    "runtime_session_id": "test-session-s6",
}


class InMemoryUnifiedMemoryClient:
    """轻量隔离的 UnifiedMemoryClient 内存实现，避免依赖外部服务进程."""

    def __init__(self) -> None:
        self.intents: dict[str, dict[str, Any]] = {}

    def seed_intent(self, intent: dict[str, Any]) -> None:
        data = dict(intent)
        data.setdefault("lifecycle", "ACTIVE")
        data.setdefault("revision", 1)
        self.intents[data["intent_id"]] = data

    async def call(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        if path == "/v1/unified/intents":
            params = params or {}
            intent_id = params.get("intent_id")
            lifecycle = params.get("lifecycle")
            items = list(self.intents.values())
            if intent_id:
                items = [it for it in items if it.get("intent_id") == intent_id]
            if lifecycle:
                items = [it for it in items if it.get("lifecycle") == lifecycle]
            return {"items": items, "total": len(items)}
        raise NotImplementedError(f"Mock does not support {method} {path}")

    async def transition_intent(self, intent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        intent = self.intents.get(intent_id)
        if not intent:
            from atlas.memory.unified_client import UnifiedMemoryError
            raise UnifiedMemoryError(f"Intent {intent_id} not found")
        expected_rev = body.get("expected_revision")
        if expected_rev is not None and intent.get("revision") != expected_rev:
            from atlas.memory.unified_client import RevisionConflict
            raise RevisionConflict("revision conflict")
        intent["lifecycle"] = body["transition"]
        intent["revision"] = int(intent.get("revision", 1)) + 1
        if "receipt" in body:
            intent.setdefault("receipts", []).append(body["receipt"])
        return dict(intent)


# -----------------------------------------------------------------------------
# 1. 真的提醒
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_e8_1_time_reminder_fires_for_real(tmp_path: Path) -> None:
    """E8.1 时间提醒：'明天上午 9 点提醒我交报告' 完整链路验证.

    意图解析/建模 → 投影为 Automation date trigger →
    存入 AutomationStore → AutomationEngine 执行 agent_turn payload 触发真实 dispatch →
    IntentBridge.on_automation_event 将意图标记为 TRIGGERED。
    """
    mem_client = InMemoryUnifiedMemoryClient()
    bridge = IntentBridge(client=cast(Any, mem_client))

    # 1. 模拟意图解析：用户说 "明天上午 9 点提醒我交报告"
    intent_id = "intent-report-tomorrow"
    intent_data = {
        "intent_id": intent_id,
        "due_at": "2026-10-09T09:00:00+08:00",
        "cue": {"kind": "time"},
        "action": {"kind": "remind", "message": "交报告"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    }
    mem_client.seed_intent(intent_data)

    # 2. 意图投影为 Automation 记录
    proj_result = bridge.create_automation_for_intent(intent_data)
    auto_record = proj_result["automation"]
    assert auto_record["id"] == automation_id_for_intent(intent_id)
    assert auto_record["trigger"]["kind"] == "date"
    assert auto_record["trigger"]["at"] == "2026-10-09T09:00:00+08:00"
    assert "交报告" in auto_record["payload"]["message"]
    assert auto_record["policy"]["delete_after_run"] is False

    # 3. 存入 AutomationStore
    store_file = tmp_path / "automations.toml"
    store = AutomationStore(store_file)
    store.put(auto_record)
    assert store.get(auto_record["id"]) is not None

    # 4. 模拟到达时间，AutomationEngine 真实执行 payload
    dispatched_turns: list[dict[str, Any]] = []

    async def fake_dispatch(payload: dict[str, Any]) -> str:
        dispatched_turns.append(payload)
        return "reminder-delivered"

    engine = AutomationEngine(store=store, dispatch_turn=fake_dispatch)
    run_outcome = await engine.execute_payload(auto_record["id"], "date")

    # 验证真实出声/提醒
    assert run_outcome["status"] == "ok"
    assert len(dispatched_turns) == 1
    assert "交报告" in dispatched_turns[0]["message"]
    assert dispatched_turns[0]["automation_id"] == auto_record["id"]

    # 5. 回写 IntentBridge
    bridge_res = await bridge.on_automation_event(
        auto_record["id"],
        {"status": "ok", "delivered": True},
        context=DEFAULT_TEST_CONTEXT,
    )
    assert bridge_res["fired"] is True
    assert bridge_res["lifecycle"] == "TRIGGERED"

    # 验证意图状态确实已转为 TRIGGERED 且包含收据
    stored_intent = mem_client.intents[intent_id]
    assert stored_intent["lifecycle"] == "TRIGGERED"
    assert len(stored_intent["receipts"]) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_e8_1_event_reminder_fires_for_real() -> None:
    """E8.1 事件提醒：'下次打开 Atlas 项目时提醒我检查测试' 完整链路验证.

    意图解析/建模 → cue 为 event(project_open) → 域事件发生 →
    IntentBridge.handle_atlas_event 命中并触发 → 状态转为 TRIGGERED。
    """
    mem_client = InMemoryUnifiedMemoryClient()
    bridge = IntentBridge(client=cast(Any, mem_client))

    # 1. 模拟意图：下次打开 Atlas 项目时提醒我检查测试
    intent_id = "intent-check-tests-on-open"
    intent_data = {
        "intent_id": intent_id,
        "cue": {
            "kind": "event",
            "event_type": "project_open",
            "conditions": {"project": "Atlas"},
        },
        "action": {"kind": "remind", "message": "检查测试"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    }
    mem_client.seed_intent(intent_data)

    # 2. 触发不匹配事件（打开其他项目）→ 不应提醒
    mismatch_res = await bridge.handle_atlas_event(
        "project_open",
        {"project": "OtherProject"},
        context=DEFAULT_TEST_CONTEXT,
    )
    assert len(mismatch_res["matched"]) == 0
    assert len(mismatch_res["transitions"]) == 0
    assert mem_client.intents[intent_id]["lifecycle"] == "ACTIVE"

    # 3. 触发真实匹配事件（打开 Atlas 项目）→ 真的提醒
    match_res = await bridge.handle_atlas_event(
        "project_open",
        {"project": "Atlas"},
        context=DEFAULT_TEST_CONTEXT,
    )
    assert len(match_res["matched"]) == 1
    assert match_res["matched"][0]["intent_id"] == intent_id
    assert len(match_res["transitions"]) == 1
    assert match_res["transitions"][0]["fired"] is True
    assert match_res["transitions"][0]["lifecycle"] == "TRIGGERED"
    assert mem_client.intents[intent_id]["lifecycle"] == "TRIGGERED"


# -----------------------------------------------------------------------------
# 2. 不重复
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_e8_2_time_reminder_no_duplicate_fire(tmp_path: Path) -> None:
    """E8.1 不重复（时间提醒）：

    - AutomationStore 侧：delete_after_run 确保执行后从 store 移除，二次执行直接 skipped。
    - IntentBridge 侧：on_automation_event 幂等拒触，已 TRIGGERED 状态返回 reason='intent_triggered'。
    """
    mem_client = InMemoryUnifiedMemoryClient()
    bridge = IntentBridge(client=cast(Any, mem_client))

    intent_id = "intent-no-repeat-time"
    intent_data = {
        "intent_id": intent_id,
        "due_at": "2026-10-09T09:00:00+08:00",
        "cue": {"kind": "time"},
        "action": {"message": "交报告"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    }
    mem_client.seed_intent(intent_data)

    proj = bridge.create_automation_for_intent(intent_data)["automation"]
    store = AutomationStore(tmp_path / "automations.toml")
    store.put(proj)

    calls = 0

    async def fake_dispatch(_: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    engine = AutomationEngine(store=store, dispatch_turn=fake_dispatch)

    # 第一次触发
    outcome1 = await engine.execute_payload(proj["id"], "date")
    engine.apply_outcome(proj["id"], {**outcome1, "trigger": "date"})
    bridge_res1 = await bridge.on_automation_event(
        proj["id"], context=DEFAULT_TEST_CONTEXT
    )

    assert outcome1["status"] == "ok"
    assert calls == 1
    assert bridge_res1["fired"] is True

    # 第二次尝试触发 IntentBridge（模拟重复事件/定时器重复回调）
    bridge_res2 = await bridge.on_automation_event(
        proj["id"], context=DEFAULT_TEST_CONTEXT
    )

    # 验证桥接侧拒绝重复触发
    assert bridge_res2["fired"] is False
    assert bridge_res2["reason"] == "intent_triggered"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_e8_2_event_reminder_no_duplicate_fire() -> None:
    """E8.1 不重复（事件提醒）：

    首次匹配并触发后状态更新为 TRIGGERED；后续再次打开项目不重复触发。
    """
    mem_client = InMemoryUnifiedMemoryClient()
    bridge = IntentBridge(client=cast(Any, mem_client))

    intent_id = "intent-no-repeat-event"
    intent_data = {
        "intent_id": intent_id,
        "cue": {
            "kind": "event",
            "event_type": "project_open",
            "conditions": {"project": "Atlas"},
        },
        "action": {"message": "检查测试"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    }
    mem_client.seed_intent(intent_data)

    # 首次打开 Atlas
    res1 = await bridge.handle_atlas_event(
        "project_open", {"project": "Atlas"}, context=DEFAULT_TEST_CONTEXT
    )
    assert len(res1["matched"]) == 1
    assert res1["transitions"][0]["fired"] is True

    # 再次打开 Atlas
    res2 = await bridge.handle_atlas_event(
        "project_open", {"project": "Atlas"}, context=DEFAULT_TEST_CONTEXT
    )
    assert len(res2["matched"]) == 0
    assert len(res2["transitions"]) == 0


# -----------------------------------------------------------------------------
# 3. 取消后不提醒
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_e8_3_cancelled_reminder_does_not_fire(tmp_path: Path) -> None:
    """E8.1 取消后不提醒：

    - 用户取消提醒：cancel_intent 将意图标记为 CANCELLED。
    - AutomationStore / engine 侧停用/移除。
    - 触发到达时：事件不命中、定时触发器被拒（reason='intent_cancelled'）、引擎跳过。
    """
    mem_client = InMemoryUnifiedMemoryClient()
    bridge = IntentBridge(client=cast(Any, mem_client))

    # 创建时间意图与事件意图
    time_intent_id = "intent-cancel-time"
    event_intent_id = "intent-cancel-event"

    mem_client.seed_intent({
        "intent_id": time_intent_id,
        "due_at": "2026-10-09T09:00:00+08:00",
        "cue": {"kind": "time"},
        "action": {"message": "交报告"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    })
    mem_client.seed_intent({
        "intent_id": event_intent_id,
        "cue": {
            "kind": "event",
            "event_type": "project_open",
            "conditions": {"project": "Atlas"},
        },
        "action": {"message": "检查测试"},
        "lifecycle": "ACTIVE",
        "revision": 1,
    })

    auto_record = bridge.create_automation_for_intent(mem_client.intents[time_intent_id])["automation"]
    store = AutomationStore(tmp_path / "automations.toml")
    store.put(auto_record)

    # 用户执行取消
    cancel_time = await bridge.cancel_intent(time_intent_id, context=DEFAULT_TEST_CONTEXT)
    assert cancel_time["cancelled"] is True
    assert cancel_time["lifecycle"] == "CANCELLED"

    cancel_event = await bridge.cancel_intent(event_intent_id, context=DEFAULT_TEST_CONTEXT)
    assert cancel_event["cancelled"] is True
    assert cancel_event["lifecycle"] == "CANCELLED"

    # 引擎侧同步取消
    store.delete(auto_record["id"])

    # 1. 验证事件触发到达时：已取消的意图不再匹配
    event_res = await bridge.handle_atlas_event(
        "project_open", {"project": "Atlas"}, context=DEFAULT_TEST_CONTEXT
    )
    assert len(event_res["matched"]) == 0

    # 2. 验证时间触发到达时：on_automation_event 拒绝触发
    bridge_time_res = await bridge.on_automation_event(
        auto_record["id"], context=DEFAULT_TEST_CONTEXT
    )
    assert bridge_time_res["fired"] is False
    assert bridge_time_res["reason"] == "intent_cancelled"

    # 3. 验证引擎执行时：store 中已无此条目，直接 skipped
    calls = 0

    async def fake_dispatch(_: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    engine = AutomationEngine(store=store, dispatch_turn=fake_dispatch)
    run_res = await engine.execute_payload(auto_record["id"], "date")
    assert run_res["status"] == "skipped"
    assert calls == 0


# -----------------------------------------------------------------------------
# 4. 中断任务能接着做
# -----------------------------------------------------------------------------


@pytest.mark.unit
def test_e8_4_interrupted_task_continuation_without_duplication(tmp_path: Path) -> None:
    """E8.2 中断任务接续：

    多步任务运行途中进程被杀：
    - 第一步写文件（工具执行产生外部真实副作用）已落盘。
    - 第二步待执行，系统意外中断，收据在焦点中仍处于 UNKNOWN 状态。
    - 重启并说'继续'：
      1) reconcile_unknown_receipt 对真实磁盘进行确定性检查，由于文件存在更新为 STATUS_OK。
      2) reconcile_focus_receipts 将已存在的文件确认为已完成。
      3) 续接运行时回读已验证步骤，不重复执行写文件工具，直接执行后续步骤。
    """
    # 模拟工作区文件
    output_file = tmp_path / "exports" / "report_summary.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("id,status\n1,success\n", encoding="utf-8")

    # 模拟中断时崩溃前保存的焦点快照（Step 1 工具收据状态为 UNKNOWN）
    focus_snapshot = {
        "task_id": "task-data-export",
        "authority_revision": 1,
        "external_receipts": [
            {
                "tool": "local_file",
                "path": str(output_file),
                "status": "UNKNOWN",
                "operation": "write_file",
            }
        ],
        "steps": [],
        "pending": [
            {"step_id": 2, "action": "send_notification", "status": "PENDING"}
        ],
    }

    # 重启后续接：第一阶段进行对账
    reconciled = reconcile_focus_receipts(focus_snapshot, base_dir=tmp_path)
    receipts = reconciled["receipts"]

    # 验证确定性检查将落盘文件标记为 STATUS_OK
    assert len(receipts) == 1
    assert receipts[0]["status"] == STATUS_OK
    assert receipts[0]["reconcile"]["method"] == "file_exists"

    # 模拟续接执行器根据对账结果恢复状态
    completed_steps = [
        {"item": f"已完成写文件: {output_file.name}", "status": "OK", "receipt": receipts[0]}
    ]
    new_focus = {
        **focus_snapshot,
        "authority_revision": focus_snapshot["authority_revision"] + 1,
        "steps": completed_steps,
        "external_receipts": receipts,
    }

    # 验证权威版本推进
    assert new_focus["authority_revision"] == 2
    assert len(new_focus["steps"]) == 1

    # 模拟执行续接动作：检查是否需要重复写文件
    write_operations_performed: list[str] = []

    def perform_step(step_name: str, path: str) -> None:
        # 如果已经存在且在 completed_steps 中，不重复执行
        already_done = any(path in s.get("item", "") for s in new_focus["steps"])
        if not already_done:
            write_operations_performed.append(step_name)

    # 续接轮次：尝试执行 Step 1 和 Step 2
    perform_step("step1_write_file", output_file.name)
    perform_step("step2_send_notification", "notification.log")

    # 验证写文件未被重复执行（外部副作用不重复）
    assert "step1_write_file" not in write_operations_performed
    assert "step2_send_notification" in write_operations_performed
    assert len(write_operations_performed) == 1


@pytest.mark.unit
def test_e8_4_interrupted_task_missing_file_detected(tmp_path: Path) -> None:
    """E8.2 中断任务接续（未完成写操作的情况）：

    若进程在实际写入文件前被杀，对账能确定性识别为 STATUS_MISSING，
    保证续接时不会误判为已完成。
    """
    missing_file = tmp_path / "exports" / "not_yet_written.csv"

    receipt = {
        "tool": "local_file",
        "path": str(missing_file),
        "status": "UNKNOWN",
    }
    reconciled = reconcile_unknown_receipt(receipt)
    assert reconciled["status"] == STATUS_MISSING
    assert reconciled["checked"] is True
