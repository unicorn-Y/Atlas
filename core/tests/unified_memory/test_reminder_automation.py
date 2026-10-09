"""F3-B2（E8）：自然语言提醒 → 既有 AutomationEngine 的真实建任务链路。

覆盖四层：

1. 时间短语解析（只认可换算形式；含糊说法拒绝，不猜）；
2. **真实 AutomationStore** 上的 create / 去重 / cancel / update / list；
3. **真实服务测试**：经代理在 MemoryOS 建 ACTIVE 时间意图 → 桥
   ``persist_automation_for_intent`` → 真 ``automations.toml`` 记录（date 触发 +
   ``um-intent-<intent_id>`` 绑定）→ 桥取消 → ``enabled=False``；
4. 观察者落库收口（``observer_drain``）注入桥后自动建任务；未注入时行为不变。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from tzlocal import get_localzone_name

from atlas.automation.engine import AutomationEngine
from atlas.automation.reminders import (
    REMINDER_PREFIX,
    ReminderError,
    _same_action,
    cancel_reminder,
    create_reminder,
    find_reminder,
    list_reminders,
    parse_due,
    resolve_update_due,
    update_reminder,
)
from atlas.automation.store import AutomationStore
from atlas.memory.intent_bridge import IntentBridge, automation_id_for_intent
from atlas.memory.observer_drain import MemoryObserverDrain
from atlas.time_context import attach_user_timezone
from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

UID = uuid.uuid4().hex[:8]
NOW = datetime(2026, 10, 4, 14, 0, 0)          # 测试时钟（S29 "明天上午 9 点"）
SHANGHAI_CONFIG = {"user": {"timezone": "Asia/Shanghai"}}


def _engine(tmp_path: Path) -> AutomationEngine:
    """未启动的真引擎（``sync_automation`` no-op，``cancel`` 有 started 守卫）。"""
    return AutomationEngine(AutomationStore(tmp_path / "automations.toml"))


def _run_automation_manage_tool(monkeypatch, tmp_path: Path, engine: AutomationEngine,
                                arguments: dict[str, Any], *, bridge: Any = None
                                ) -> dict[str, Any]:
    """Run the real tool execution node against an isolated AutomationEngine."""
    import atlas.agent as agent_module
    import atlas.agent.tool_node as tool_node
    import atlas.automation as automation_module

    async def no_hook(*args: Any, **kwargs: Any) -> None:
        return None

    config = SimpleNamespace(
        db_path=tmp_path / "atlas.db",
        get=lambda key, default=None: default,
    )
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    monkeypatch.setattr(agent_module, "safety_review_enabled", lambda: False)
    monkeypatch.setattr(automation_module, "get_automation_engine", lambda: engine)
    monkeypatch.setattr(tool_node, "_capture_tool_event", lambda *a, **k: None)
    if bridge is not None:
        monkeypatch.setattr(
            IntentBridge, "from_config", classmethod(lambda cls, config=None: bridge))

    runtime = SimpleNamespace(
        run_id="run-reminder-tool-test", conversation_id="conversation-reminder-test",
        model="fake-model", project_id=None, workspace=None, allowed_paths=[],
        permission_mode="full_access", cancel_event=None, pause_event=None,
        event_queue=asyncio.Queue(), process_notifications=asyncio.Queue(),
        user_hook_callback=None, ssh_tool_callback=None, ssh_checkpoint_callback=None,
        sandbox_tool_callback=None, sandbox_enabled=False, workspace_trusted=False,
        agent_role="leaf", agent_type="general", agent_depth=0, tool_allow=None,
        tool_deny=[], read_only=False, mode="act", changed_paths=set(),
        verification_passed=False, approval_callback=None, goal=None,
    )
    agent = SimpleNamespace(
        _model_mgr=SimpleNamespace(current_model="fake-model"),
        _mcp=None, _projects=None, _local_execution=None,
        _model_facing_tools=lambda: [], _emit_hook=no_hook,
        trajectory_reviewer=SimpleNamespace(reviewer=None),
        APPROVAL_REQUIRED_TOOLS=set(),
    )
    state = {
        "messages": [HumanMessage(content="改一下提醒"), AIMessage(content="", tool_calls=[{
            "name": "automation_manage", "args": arguments, "id": "tool-reminder-update",
        }])],
        "pending_events": [], "runtime": runtime,
    }
    result = asyncio.run(tool_node.execute_tools_node(agent, state))
    return next(item for item in result["pending_events"]
                if item.get("type") == "tool_result")


# --------------------------------------------------------------- 1. 时间解析

@pytest.mark.parametrize("text,expected", [
    ("明天上午9点", "2026-10-05T09:00:00+08:00"),
    ("明天上午 9 点提醒我交报告", "2026-10-05T09:00:00+08:00"),
    ("今天下午3点", "2026-10-04T15:00:00+08:00"),
    ("后天晚上八点半", "2026-10-06T20:30:00+08:00"),
    ("明天中午十二点", "2026-10-05T12:00:00+08:00"),
    ("9:30", "2026-10-05T09:30:00+08:00"),                # 只说钟点且已过 → 明天
    ("明天", "2026-10-05T09:00:00+08:00"),                # 只有日期 → 09:00 默认
    ("2026-10-05T09:00:00", "2026-10-05T09:00:00+08:00"),  # ISO 直通
    ("2026-10-05 09:00:00 提醒我", "2026-10-05T09:00:00+08:00"),
])
def test_parse_due_convertible_forms(text: str, expected: str) -> None:
    assert parse_due(text, now=NOW, config=SHANGHAI_CONFIG).isoformat() == expected


def test_f4_relative_reminder_time_is_aware_in_user_timezone() -> None:
    due = parse_due("明天上午 9 点", now=NOW, config=SHANGHAI_CONFIG)

    assert due.isoformat() == "2026-10-05T09:00:00+08:00"


@pytest.mark.parametrize("text,expected", [
    ("明天上午 9 点", "2026-10-05T09:00:00+08:00"),
    ("下周三下午三点", "2026-10-07T15:00:00+08:00"),
    ("下周三15点", "2026-10-07T15:00:00+08:00"),
    ("今晚八点", "2026-10-04T20:00:00+08:00"),
    ("今晚20点", "2026-10-04T20:00:00+08:00"),
])
def test_f4_natural_reminder_times_keep_local_zone(text: str, expected: str) -> None:
    try:
        due = parse_due(text, now=NOW, config=SHANGHAI_CONFIG)
    except ReminderError:
        due = None

    assert due is not None and due.isoformat() == expected


def test_f4_tomorrow_uses_local_date_when_utc_now_is_before_local_midnight() -> None:
    now = datetime(2026, 10, 4, 15, 30, tzinfo=ZoneInfo("UTC"))

    due = parse_due("明天上午9点", now=now, config=SHANGHAI_CONFIG)

    assert due.isoformat() == "2026-10-05T09:00:00+08:00"


def test_f4_configured_timezone_applies_dst_rules_to_future_dates() -> None:
    now = datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("UTC"))

    due = parse_due("明天上午9点", now=now,
                    config={"user": {"timezone": "America/New_York"}})

    assert due.isoformat() == "2026-11-01T09:00:00-05:00"


def test_f4_relative_time_rejects_nonexistent_dst_wall_time() -> None:
    now = datetime(2026, 3, 7, 23, 0, tzinfo=ZoneInfo("UTC"))

    with pytest.raises(ReminderError):
        parse_due("明天凌晨2点半", now=now,
                  config={"user": {"timezone": "America/New_York"}})


def test_f4_aware_zoneinfo_gap_is_rejected() -> None:
    invalid = datetime(2026, 3, 8, 2, 30, tzinfo=ZoneInfo("America/New_York"))

    with pytest.raises(ValueError, match="invalid in America/New_York"):
        attach_user_timezone(invalid, {"user": {"timezone": "America/New_York"}})


def test_f4_relative_time_uses_first_occurrence_for_dst_fold() -> None:
    now = datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("UTC"))

    due = parse_due("明天凌晨1点半", now=now,
                    config={"user": {"timezone": "America/New_York"}})

    assert due.isoformat() == "2026-11-01T01:30:00-04:00"


def test_f4_iso_offset_is_preserved_before_trailing_reminder_text() -> None:
    now = datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("UTC"))

    due = parse_due("2026-11-01T09:00:00+08:00 提醒我", now=now,
                    config={"user": {"timezone": "America/New_York"}})

    assert due.isoformat() == "2026-10-31T21:00:00-04:00"


def test_f4_intent_bridge_passes_user_timezone_to_reminder_service(monkeypatch) -> None:
    from atlas.automation import reminders as reminder_service

    config = {"user": {"timezone": "America/New_York"}}
    observed: dict[str, Any] = {}

    async def fake_create_reminder(**kwargs):
        observed.update(kwargs)
        return {"automation": {"id": kwargs["automation_id"]}, "created": True}

    monkeypatch.setattr(reminder_service, "create_reminder", fake_create_reminder)
    bridge = IntentBridge(client=object(), config=config)
    result = asyncio.run(bridge.persist_automation_for_intent({
        "intent_id": "intent-f4-timezone",
        "action": {"kind": "remind", "message": "交报告"},
        "due_at": "2026-11-01T09:00:00-05:00",
    }))

    assert result["created"] is True
    assert observed["config"] is config


def test_f4_create_reminder_default_uses_system_iana_timezone(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    result = asyncio.run(create_reminder(
        message="默认时区提醒", due_text="明天上午9点", engine=engine))
    due = datetime.fromisoformat(result["due_at"])

    assert due.tzinfo is not None
    system_zone = ZoneInfo(get_localzone_name())
    local_due = due.astimezone(system_zone)
    assert local_due.hour == 9 and local_due.minute == 0
    assert due.utcoffset() == local_due.utcoffset()


@pytest.mark.parametrize("text", ["", "晚点", "回头", "有空的时候", "9点"[:0]])
def test_parse_due_rejects_vague_or_empty(text: str) -> None:
    """含糊说法必须拒绝 —— 猜出来的提醒是假承诺。"""
    with pytest.raises(ReminderError):
        parse_due(text, now=NOW)


# ------------------------------------------------- 2. 真实 store 上的 CRUD

def test_create_dedupe_cancel_update_list_on_real_store(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = engine.store

    first = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    assert first["created"] is True
    trigger = first["automation"]["trigger"]
    assert trigger["kind"] == "date" and trigger["at"] == "2026-10-05T09:00:00+08:00"
    assert first["automation"]["name"].startswith(REMINDER_PREFIX)
    assert first["automation"]["enabled"] is True

    # 同正文 + 同时间（含口语前缀"提醒我"）→ 不重复建第二条
    again = asyncio.run(create_reminder(
        message="提醒我交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    assert again["created"] is False and again.get("deduped") is True
    assert len(store.list()) == 1

    # 不同事 → 各建一条
    other = asyncio.run(create_reminder(
        message="交周报", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    assert other["created"] is True
    assert len(store.list()) == 2

    listed = list_reminders(engine=engine)["reminders"]
    assert {item["message"] for item in listed} == {"交报告", "交周报"}
    assert all(item["enabled"] is True for item in listed)

    # 取消 → 保留记录（可审计）但 enabled=False
    cancelled = asyncio.run(cancel_reminder(query="报告", now=NOW, engine=engine))
    assert cancelled["cancelled"] is True
    assert cancelled["automation"]["enabled"] is False
    assert cancelled["automation"]["id"] == first["automation"]["id"]
    assert len(store.list()) == 2                      # 不删行
    assert store.get(first["automation"]["id"]) is not None

    # 改期 → 原地更新同一条，不新建
    updated = asyncio.run(update_reminder(
        query="周报", due_text="明天下午3点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    assert updated["updated"] is True
    assert updated["automation"]["id"] == other["automation"]["id"]
    assert updated["automation"]["trigger"]["at"] == "2026-10-05T15:00:00+08:00"
    assert len(store.list()) == 2

    # 取消失败的诚实返回（无匹配 → 不假装成功）
    miss = asyncio.run(cancel_reminder(query="不存在的提醒", now=NOW, engine=engine))
    assert miss["cancelled"] is False and miss["reason"] == "no_matching_reminder"


def test_source_run_binding_dedupes_one_intent_without_merging_other_messages(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    due = "2026-10-05T09:00:00+08:00"

    first = asyncio.run(create_reminder(
        message="交报告", due_at=due,
        source_binding={"request_run_id": "run-source-1"}, engine=engine,
        config=SHANGHAI_CONFIG))
    same_intent = asyncio.run(create_reminder(
        message="提交报告", due_at=due,
        source_binding={"request_run_id": "run-source-1"}, engine=engine,
        config=SHANGHAI_CONFIG))
    another_task_same_message = asyncio.run(create_reminder(
        message="发邮件", due_at=due,
        source_binding={"request_run_id": "run-source-1"}, engine=engine,
        config=SHANGHAI_CONFIG))
    same_text_different_message = asyncio.run(create_reminder(
        message="交报告", due_at=due,
        source_binding={"request_run_id": "run-source-2"}, engine=engine,
        config=SHANGHAI_CONFIG))

    assert first["created"] is True
    assert same_intent["created"] is False
    assert same_intent["automation"]["id"] == first["automation"]["id"]
    assert another_task_same_message["created"] is True
    assert same_text_different_message["created"] is True
    assert len(engine.store.list()) == 3
    assert engine.store.get(first["automation"]["id"])["source_binding"]["request_run_id"] == "run-source-1"

    same_due_distinct_actions = asyncio.run(create_reminder(
        message="交报告给张三", due_at=due,
        source_binding={"request_run_id": "run-source-3"}, engine=engine,
        config=SHANGHAI_CONFIG))
    other_same_due_distinct_action = asyncio.run(create_reminder(
        message="交报告给老板", due_at=due,
        source_binding={"request_run_id": "run-source-3"}, engine=engine,
        config=SHANGHAI_CONFIG))
    assert other_same_due_distinct_action["created"] is True
    assert same_due_distinct_actions["automation"]["id"] != other_same_due_distinct_action["automation"]["id"]
    assert len(engine.store.list()) == 5


def test_source_action_match_ignores_shared_uid_but_not_shared_prefix_suffix() -> None:
    assert _same_action("提醒我提交报告", "交报告")
    assert not _same_action("提交报告（a1b2c3d4）", "发送邮件（a1b2c3d4）")
    assert not _same_action("交报告给张三", "交报告")
    assert not _same_action("提交报告草稿", "提交报告")


def test_same_source_due_distinct_uid_actions_create_two_automations(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    due = "2026-10-05T09:00:00+08:00"
    binding = {"request_run_id": "run-two-actions"}

    first = asyncio.run(create_reminder(
        message="提交报告（a1b2c3d4）", due_at=due,
        source_binding=binding, engine=engine, config=SHANGHAI_CONFIG))
    second = asyncio.run(create_reminder(
        message="发送邮件（a1b2c3d4）", due_at=due,
        source_binding=binding, engine=engine, config=SHANGHAI_CONFIG))

    assert first["created"] is True
    assert second["created"] is True
    assert second["automation"]["id"] != first["automation"]["id"]
    assert len(engine.store.list()) == 2


def test_cancelled_intent_binding_cannot_be_recreated_by_replay(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    binding = {"request_run_id": "run-cancel-1", "intent_id": "intent-cancel-1"}

    created = asyncio.run(create_reminder(
        message="交报告", due_at="2026-10-05T09:00:00+08:00",
        automation_id="um-intent-intent-cancel-1", source_binding=binding,
        engine=engine, config=SHANGHAI_CONFIG))
    cancelled = asyncio.run(cancel_reminder(
        automation_id=created["automation"]["id"], engine=engine, config=SHANGHAI_CONFIG))
    replay = asyncio.run(create_reminder(
        message="交报告", due_at="2026-10-05T09:00:00+08:00",
        automation_id=created["automation"]["id"], source_binding=binding,
        engine=engine, config=SHANGHAI_CONFIG))

    assert cancelled["cancelled"] is True
    assert replay["created"] is False
    assert replay["automation"]["enabled"] is False
    assert len(engine.store.list()) == 1


def test_update_keeps_automation_id_and_rebinds_source_intent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_at="2026-10-05T09:00:00+08:00",
        automation_id="um-intent-intent-update-1",
        source_binding={"request_run_id": "run-create-1", "intent_id": "intent-update-1"},
        engine=engine, config=SHANGHAI_CONFIG))

    updated = asyncio.run(update_reminder(
        automation_id=created["automation"]["id"], due_at="2026-10-05T15:00:00+08:00",
        source_binding={"request_run_id": "run-update-1", "intent_id": "intent-update-2"},
        now=NOW, engine=engine, config=SHANGHAI_CONFIG))

    assert updated["automation"]["id"] == created["automation"]["id"]
    assert updated["automation"]["trigger"]["at"] == "2026-10-05T15:00:00+08:00"
    assert updated["automation"]["source_binding"] == {
        "request_run_id": "run-update-1", "intent_id": "intent-update-2",
    }
    assert len(engine.store.list()) == 1


def test_tool_update_invalid_due_preserves_bound_intent_and_automation(
    tmp_path: Path, monkeypatch,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_at="2030-10-05T09:00:00+08:00",
        source_binding={"request_run_id": "run-invalid-update",
                        "intent_id": "intent-invalid-update"},
        engine=engine, config=SHANGHAI_CONFIG))
    before = engine.store.get(created["automation"]["id"])

    class BridgeMustNotBeCalled:
        calls = 0

        async def cancel_intent(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            raise AssertionError("invalid due must be rejected before intent cancellation")

    bridge = BridgeMustNotBeCalled()
    event = _run_automation_manage_tool(
        monkeypatch, tmp_path, engine,
        {"action": "update", "automation_id": before["id"],
         "due_at": "2020-01-01T00:00:00+08:00"}, bridge=bridge)

    assert event["is_error"] is True
    assert bridge.calls == 0
    after = engine.store.get(before["id"])
    assert after["enabled"] is True
    assert after["trigger"]["at"] == before["trigger"]["at"]
    assert after["source_binding"]["intent_id"] == "intent-invalid-update"
    assert len(engine.store.list()) == 1


def test_tool_update_memoryos_failure_does_not_partially_update_automation(
    tmp_path: Path, monkeypatch,
) -> None:
    from atlas.memory.unified_client import UnifiedMemoryError

    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_at="2030-10-05T09:00:00+08:00",
        source_binding={"request_run_id": "run-service-failure",
                        "intent_id": "intent-service-failure"},
        engine=engine, config=SHANGHAI_CONFIG))
    before = engine.store.get(created["automation"]["id"])

    class FailingTransitionClient:
        transitions = 0

        async def call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            assert method == "GET" and path == "/v1/unified/intents"
            return {"items": [{"intent_id": "intent-service-failure",
                               "revision": 3,
                               "automation_id": before["id"]}]}

        async def transition_intent(self, intent_id: str,
                                    body: dict[str, Any]) -> dict[str, Any]:
            self.transitions += 1
            raise UnifiedMemoryError("MemoryOS unavailable", status_code=503)

    client = FailingTransitionClient()
    facade = SimpleNamespace(
        enabled=True,
        default_context=lambda: {"runtime_session_id": "test-reminder-context"},
    )
    bridge = IntentBridge(facade=facade, client=client)
    event = _run_automation_manage_tool(
        monkeypatch, tmp_path, engine,
        {"action": "update", "automation_id": before["id"],
         "due_at": "2030-10-05T15:00:00+08:00"}, bridge=bridge)

    after = engine.store.get(before["id"])
    assert event["is_error"] is True
    assert client.transitions == 1, event
    assert after["enabled"] is True
    assert after["trigger"]["at"] == before["trigger"]["at"]
    assert after["source_binding"]["intent_id"] == "intent-service-failure"
    assert len(engine.store.list()) == 1


def test_reminder_lookup_rejects_missing_explicit_id_and_ambiguous_query(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    first = asyncio.run(create_reminder(
        message="交报告", due_at="2030-10-05T09:00:00+08:00", engine=engine,
        config=SHANGHAI_CONFIG))
    second = asyncio.run(create_reminder(
        message="检查报告", due_at="2030-10-06T09:00:00+08:00", engine=engine,
        config=SHANGHAI_CONFIG))
    original = {item["id"]: item for item in engine.store.list()}

    assert find_reminder(query="报告", automation_id="missing-explicit-id",
                         engine=engine) is None
    assert find_reminder(query="报告", engine=engine) is None
    cancel = asyncio.run(cancel_reminder(
        query="报告", automation_id="missing-explicit-id", engine=engine,
        config=SHANGHAI_CONFIG))
    update = asyncio.run(update_reminder(
        query="报告", due_at="2030-10-07T09:00:00+08:00", engine=engine,
        config=SHANGHAI_CONFIG))

    assert cancel["cancelled"] is False
    assert update["updated"] is False
    assert engine.store.get(first["automation"]["id"]) == original[first["automation"]["id"]]
    assert engine.store.get(second["automation"]["id"]) == original[second["automation"]["id"]]
    assert len(engine.store.list()) == 2


def test_reminder_syncs_engine_every_mutation(tmp_path: Path, monkeypatch) -> None:
    """每次变更都 sync 到引擎（started 时）；未启动时 sync 为 no-op 不报错。"""
    engine = _engine(tmp_path)
    synced: list[str] = []

    async def _record(record):
        synced.append(str(record.get("id")))

    monkeypatch.setattr(engine, "sync_automation", _record)
    created = asyncio.run(create_reminder(
        message="喝水", due_text="今天下午3点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    asyncio.run(cancel_reminder(query="喝水", now=NOW, engine=engine,
                                config=SHANGHAI_CONFIG))
    assert synced == [created["automation"]["id"], created["automation"]["id"]]


# --------------------------------------------------- 3. 真实服务：意图 → 任务

def _make_bridge(um: UMHarness) -> IntentBridge:
    from atlas.memory.unified_client import UnifiedMemoryClient

    return IntentBridge(client=UnifiedMemoryClient(
        service_url=um.memoryos_url, internal_token=TEST_INTERNAL_TOKEN,
        timeout=10.0))


@pytest.mark.integration
@pytest.mark.fake_provider
def test_time_intent_creates_real_automation_via_bridge(um: UMHarness,
                                                        tmp_path: Path) -> None:
    """真实服务：MemoryOS 建时间意图 → 桥真建 Automation → 桥取消 → 停用。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    engine = _engine(tmp_path)

    body = {
        "context": um.default_context(),
        "user_source_ref": "ATLAS_USER_MESSAGE:intent-002",
        "cue": {"kind": "time"},
        "action": {"kind": "remind", "message": f"交报告（{UID}）"},
        "due_at": "2026-10-05T09:00:00+08:00",
    }
    r = um.api("POST", "/api/unified-memory/intents", json=body)
    assert r.status_code in (200, 201), r.text
    intent = r.json()
    intent_id = intent["intent_id"]
    assert intent["lifecycle"] == "ACTIVE"

    result = asyncio.run(bridge.persist_automation_for_intent(intent, engine=engine))
    assert result["created"] is True
    automation = result["automation"]
    assert automation["id"] == automation_id_for_intent(intent_id)
    assert automation["trigger"]["kind"] == "date"
    assert automation["trigger"]["at"] == "2026-10-05T09:00:00+08:00"
    assert automation["enabled"] is True
    # 真落盘（不是内存投影）
    assert (tmp_path / "automations.toml").exists()
    assert engine.store.get(automation["id"]) is not None

    # 幂等重放（同一意图再投影）→ 不产生第二条
    replay = asyncio.run(bridge.persist_automation_for_intent(intent, engine=engine))
    assert replay["created"] is False
    assert len(engine.store.list()) == 1

    # 桥取消（对应 MemoryOS transition CANCELLED 的 Automation 半边）
    cancelled = asyncio.run(bridge.cancel_automation_for_intent(intent_id, engine=engine))
    assert cancelled["cancelled"] is True
    assert engine.store.get(automation["id"])["enabled"] is False


@pytest.mark.integration
@pytest.mark.fake_provider
def test_tool_and_observer_same_source_run_reuse_one_automation(um: UMHarness,
                                                                 tmp_path: Path) -> None:
    """真实MemoryOS意图 + 工具先建Automation + Observer回流只绑定不再建一条。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    engine = _engine(tmp_path)
    source_ref = "ATLAS_USER_MESSAGE:intent-002"
    request_run_id = f"run-f4-b-{UID}"
    due = "2026-10-05T09:00:00+08:00"

    def create_memory_intent(message: str) -> dict[str, Any]:
        response = um.api("POST", "/api/unified-memory/intents", json={
            "context": um.default_context(),
            "user_source_ref": source_ref,
            "cue": {"kind": "time", "at": due},
            "action": {"kind": "remind", "message": message},
            "due_at": due,
        })
        assert response.status_code in (200, 201), response.text
        return response.json()

    report_intent = create_memory_intent(f"提交报告（{UID}）")
    email_intent = create_memory_intent(f"发送邮件（{UID}）")

    def pipeline_record(message: str) -> dict[str, Any]:
        return {
            "facet": "INTENT", "lifecycle": "ACTIVE",
            "metadata": {"request_run_id": request_run_id},
            "content": {"text": message,
                        "evidence_chains": {"chain_keys": [source_ref]}},
            "valid_time": {"valid_from": due},
        }

    async def run() -> None:
        tool_report = await create_reminder(
            message=f"交报告（{UID}）", due_at=due,
            source_binding={"request_run_id": request_run_id},
            engine=engine, config=SHANGHAI_CONFIG)
        tool_email = await create_reminder(
            message=f"发邮件（{UID}）", due_at=due,
            source_binding={"request_run_id": request_run_id},
            engine=engine, config=SHANGHAI_CONFIG)
        results = []
        for message, expected_intent in (
            (f"提交报告（{UID}）", report_intent),
            (f"发送邮件（{UID}）", email_intent),
        ):
            record = pipeline_record(message)
            ensured = await bridge.ensure_intent_from_record(
                record, context=um.default_context())
            assert ensured["intent_id"] == expected_intent["intent_id"], (
                f"ensured={ensured!r}; record={record!r}")
            intent = bridge.persist_input_from_record(ensured)
            result = await bridge.persist_automation_for_intent(intent, engine=engine)
            results.append(result)

        assert results[0]["automation"]["id"] == tool_report["automation"]["id"]
        assert results[1]["automation"]["id"] == tool_email["automation"]["id"]
        assert results[0]["automation"]["id"] != results[1]["automation"]["id"]
        assert len(engine.store.list()) == 2
        assert all(item["automation"]["source_binding"]["request_run_id"] == request_run_id
                   for item in results)
        assert all(item["automation"]["source_binding"]["intent_id"]
                   for item in results)

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.fake_provider
def test_tool_cancel_before_observer_drain_terminalizes_late_intent(um: UMHarness) -> None:
    """真实WS工具先建后取消；延迟ObserverDrain形成的同源意图也必须终态化。"""
    assert um._fake is not None
    task_text = f"交报告（{UID}）"
    due = "2030-10-05T09:00:00+08:00"
    create_user_text = f"请在2030年10月5日上午9点提醒我{task_text}。"
    cancel_user_text = f"请取消{task_text}的提醒。"
    conversation_id = um._new_conversation()
    observer_requests: list[dict[str, Any]] = []

    def observer_intent_for_create(request: dict[str, Any]):
        observer_requests.append(request)
        # 假 LLM 服务器把**请求记录**（path/kind/auth/headers/body）交给 aux，
        # 消息体在 record["body"] —— 见 tests/fakes/k1_harness.py 的 default_aux。
        raw_body = request.get("body")
        body = raw_body if isinstance(raw_body, dict) else {}
        messages = body.get("messages") or []
        from tests.fakes.fake_llm_provider import Text

        prompt = "\n".join(str(item.get("content") or "") for item in messages
                           if isinstance(item, dict) and item.get("role") == "user")
        source = None
        for line in prompt.splitlines():
            if not line.startswith("* (") or ") " not in line:
                continue
            try:
                value = json.loads(line.split(") ", 1)[1])
            except (TypeError, ValueError):
                continue
            if value.get("text") == create_user_text and value.get("speaker_role") == "USER":
                source = value
                break
        if source is None:
            return Text('{"observations":[]}')
        return Text(json.dumps({"observations": [{
            "text": task_text, "priority": "HIGH", "facet": "INTENT",
            "key": None, "value": {"action": task_text, "due_at": due},
            "entities": [], "valid_from": due, "valid_to": None,
            "is_change": False, "evidence": [source["source_event_id"]],
            "speaker": "USER",
        }]}, ensure_ascii=False))

    um._fake._aux = observer_intent_for_create

    def dispatch(user_text: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from tests.fakes.fake_llm_provider import Text, ToolCall

        um._fake.push(ToolCall("automation_manage", arguments), Text("done"))
        return um.chat(user_text, session_id=conversation_id)

    created_run = dispatch(create_user_text, {
        "action": "create", "message": task_text, "due_at": due,
    })
    created_tool = next(item for item in created_run["tool_calls"]
                        if item["name"] == "automation_manage")
    assert created_tool["is_error"] is False, created_tool
    created_run_id = created_run["run_id"]
    listed = um.api("GET", "/api/automations").json()["automations"]
    matching = [item for item in listed
                if item.get("name") == REMINDER_PREFIX + task_text]
    assert len(matching) == 1
    automation_id = matching[0]["id"]

    cancelled_run = dispatch(cancel_user_text, {"action": "cancel", "query": task_text})
    cancelled_tool = next(item for item in cancelled_run["tool_calls"]
                          if item["name"] == "automation_manage")
    assert cancelled_tool["is_error"] is False, cancelled_tool
    before_drain = um.api("GET", f"/api/automations/{automation_id}").json()["automation"]
    assert before_drain["enabled"] is False
    assert before_drain["trigger"]["at"] == due

    source_records: list[dict[str, Any]] = []
    source_deadline = time.monotonic() + 45
    while time.monotonic() < source_deadline:
        source_response = um.api("GET", "/v1/unified/records", params={"limit": 200})
        assert source_response.status_code == 200, source_response.text
        source_records = [item for item in source_response.json().get("items", [])
                          if (item.get("content") or {}).get("text") == create_user_text
                          and (item.get("metadata") or {}).get("request_run_id")
                          == created_run_id]
        if source_records:
            break
        time.sleep(0.2)
    assert source_records, "真实USER source未由Atlas捕获并由MemoryOS ACK"

    close = um.api("POST", "/api/unified-memory/session/close",
                    json={"session_id": conversation_id})
    assert close.status_code == 200, close.text

    matching_intents: list[dict[str, Any]] = []
    matching_records: list[dict[str, Any]] = []
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        intents_response = um.api("GET", "/v1/unified/intents", params={"limit": 200})
        assert intents_response.status_code == 200, intents_response.text
        intent_items = intents_response.json().get("items", [])
        matching_intents = [item for item in intent_items
                            if (item.get("action") or {}).get("message") == task_text
                            and item.get("due_at") == due]
        records_response = um.api("GET", "/v1/unified/records", params={
            "facet": "INTENT", "status": "ACTIVE", "limit": 200,
        })
        assert records_response.status_code == 200, records_response.text
        matching_records = [item for item in records_response.json().get("items", [])
                            if (item.get("content") or {}).get("text") == task_text]
        if matching_intents and matching_records:
            break
        time.sleep(0.2)

    assert observer_requests, "session close did not invoke the real Observer model route"
    assert len(matching_intents) == 1, matching_intents
    assert matching_intents[0]["lifecycle"] == "CANCELLED", matching_intents[0]
    assert len(matching_records) == 1, matching_records
    metadata = matching_records[0].get("metadata") or {}
    assert metadata.get("request_run_id") == created_run_id
    source_events = metadata.get("source_events") or []
    assert len(source_events) == 1
    assert source_events[0].get("event_class") == "TEST"
    assert source_events[0].get("source_timezone")

    after_drain = um.api("GET", f"/api/automations/{automation_id}").json()["automation"]
    assert after_drain["enabled"] is False
    assert after_drain["trigger"]["at"] == due
    assert after_drain["source_binding"]["request_run_id"] == created_run_id
    assert after_drain["source_binding"]["intent_id"] == matching_intents[0]["intent_id"]
    assert len(um.api("GET", "/api/automations").json()["automations"]) == 1


@pytest.mark.integration
@pytest.mark.fake_provider
def test_cancel_and_update_intent_replays_keep_one_current_automation(um: UMHarness,
                                                                      tmp_path: Path) -> None:
    """取消/改时同时更新MemoryOS意图和同一Automation；旧意图重放不复活。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    engine = _engine(tmp_path)
    source_ref = "ATLAS_USER_MESSAGE:intent-002"
    old_due = "2026-10-05T09:00:00+08:00"
    new_due = "2026-10-05T15:00:00+08:00"

    def create_memory_intent(run_id: str, due: str, message: str) -> dict[str, Any]:
        response = um.api("POST", "/api/unified-memory/intents", json={
            "context": um.default_context(),
            "user_source_ref": source_ref,
            "cue": {"kind": "time", "at": due},
            "action": {"kind": "remind", "message": message},
            "due_at": due,
        })
        assert response.status_code in (200, 201), response.text
        value = response.json()
        value["source_binding"] = {"request_run_id": run_id,
                                   "source_message_ref": source_ref}
        return value

    old_intent = create_memory_intent(f"run-create-{UID}", old_due, f"交报告（{UID}）")
    old_record = {
        "facet": "INTENT", "lifecycle": "ACTIVE",
        "metadata": {"request_run_id": f"run-create-{UID}"},
        "content": {"text": f"交报告（{UID}）",
                    "evidence_chains": {"chain_keys": [source_ref]}},
        "valid_time": {"valid_from": old_due},
    }

    successor = create_memory_intent(f"run-update-{UID}", new_due, f"交报告（{UID}）")

    async def run() -> None:
        created = await bridge.persist_automation_for_intent(old_intent, engine=engine)
        automation_id = created["automation"]["id"]
        transition = await bridge.cancel_intent(
            old_intent["intent_id"], context=um.default_context(), engine=None)
        assert transition["cancelled"] is True
        updated = await update_reminder(
            automation_id=automation_id, due_at=new_due,
            source_binding={**successor["source_binding"], "intent_id": successor["intent_id"]},
            now=NOW, engine=engine, config=SHANGHAI_CONFIG)
        rebound = await bridge.persist_automation_for_intent(successor, engine=engine)

        assert updated["automation"]["id"] == automation_id
        assert updated["automation"]["trigger"]["at"] == new_due
        assert rebound["automation"]["id"] == automation_id
        assert len(engine.store.list()) == 1
        assert engine.store.get(automation_id)["enabled"] is True
        assert engine.store.get(automation_id)["source_binding"]["intent_id"] == successor["intent_id"]

        replay = await bridge.ensure_intent_from_record(
            old_record, context=um.default_context())
        assert replay["intent_id"] == old_intent["intent_id"]
        assert replay["intent"]["lifecycle"] == "CANCELLED"
        assert bridge.persist_input_from_record(replay) is None
        assert engine.store.get(automation_id)["trigger"]["at"] == new_due
        assert len(engine.store.list()) == 1

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.fake_provider
def test_event_cue_intent_is_not_persisted_and_says_so(um: UMHarness,
                                                       tmp_path: Path) -> None:
    """事件 cue 意图：事件分发点未统一 → 桥**不假装**建任务，如实返回原因。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    engine = _engine(tmp_path)

    body = {
        "context": um.default_context(),
        "user_source_ref": "ATLAS_USER_MESSAGE:intent-002",
        "cue": {"kind": "event", "event_type": "project_open",
                "conditions": {"project_id": "project-demo"}},
        "action": {"kind": "remind", "message": f"打开项目时提醒（{UID}）"},
    }
    r = um.api("POST", "/api/unified-memory/intents", json=body)
    assert r.status_code in (200, 201), r.text
    intent = r.json()

    result = asyncio.run(bridge.persist_automation_for_intent(intent, engine=engine))
    assert result["created"] is False
    assert result["reason"] == "event_cue_not_wired"
    assert engine.store.list() == []
    assert not (tmp_path / "automations.toml").exists()


# --------------------------------------------- 4. 观察者落库收口 → 自动建任务

@dataclass
class _Batch:
    batch_id: str
    payload: dict[str, Any] | None


class _Observer:
    def __init__(self, sessions: list[str], batches: list[_Batch | None]) -> None:
        self.sessions = sessions
        self.batches = batches

    def pending_sessions(self) -> list[str]:
        return self.sessions

    def mark_session_ended(self, session_id: str) -> None:
        return None

    async def resume(self, session_id: str, *, context=None, session_ended=False):
        return self.batches.pop(0)

    async def ack_batch(self, batch_id: str):
        return self.batches.pop(0)


class _Facade:
    def __init__(self, intents: list[dict[str, Any]] | None = None,
                 client_obj: Any = None) -> None:
        self.intents = intents or []
        self.listed = 0
        self._client = client_obj

    def client(self) -> Any:
        assert self._client is not None, "本替身只在注入 client 的用例里用"
        return self._client

    def default_context(self, **kwargs):
        return kwargs

    async def observe_batch(self, payload):
        return {"accepted": len(payload["observations"]),
                "receipts": [{"source_event_id": item["source_event_id"]}
                             for item in payload["observations"]]}

    async def list_records(self, *, facet=None, status=None, cursor=None, limit=50):
        self.listed += 1
        assert facet == "INTENT" and status == "ACTIVE"
        return {"items": list(self.intents)}


def _intent_record() -> dict[str, Any]:
    """INTENT 记忆记录的**真形状**（取自 F1-D S29 真跑隔离库 mem-fm-1 的投影）。

    三处要害：``facet=INTENT`` + ``status=ACTIVE``；用户来源在
    ``content.evidence_chains.chain_keys``（``ATLAS_USER_MESSAGE:<object_id>``）；
    ``valid_time.valid_from`` 是**带时区**的绝对到期时刻。扁平的意图行
    （intent_id/cue/due_at）不是 ``/v1/unified/records`` 的形状 —— 拿它当记录
    喂进来，桥只能如实判 ``not_eligible``（这正是修复前的坏状态）。
    """
    return {
        "record_ref": f"mem-fm-{UID}-drain",
        "facet": "INTENT",
        "status": "ACTIVE",
        "valid_time": {"valid_from": "2026-10-05T09:00:00+08:00"},
        "content": {
            "text": f"交报告（{UID}）",
            "evidence_chains": {"chain_keys": [
                f"ATLAS_USER_MESSAGE:msg-{UID}-drain",
                f"DERIVED:observer-{UID}-drain",
            ]},
        },
        "source_refs": [
            {"source_event_id": f"atlas:ATLAS_USER_MESSAGE:msg-{UID}-drain:1:UPSERT"},
            {"source_event_id": f"atlas:DERIVED:observer-{UID}-drain:1:UPSERT"},
        ],
    }


class _IntentClient:
    """桥需要的两个服务端调用（fake facade 的 client 面）。"""

    def __init__(self, intent_id: str) -> None:
        self.intent_id = intent_id
        self.created: list[dict[str, Any]] = []

    async def call(self, method: str, path: str, json: Any = None,
                   params: dict[str, Any] | None = None) -> Any:
        assert (method, path) == ("GET", "/v1/unified/intents")
        return {"items": []}                 # 首查：无同来源同意图 → 走创建路径

    async def create_intent(self, request: dict[str, Any]) -> dict[str, Any]:
        self.created.append(dict(request))
        # 真服务端行为：来源查证通过 → ACTIVE（只有查不到才 PROPOSED）
        return {"intent_id": self.intent_id, "lifecycle": "ACTIVE",
                "user_source_ref": request.get("user_source_ref")}


def _batch() -> _Batch:
    return _Batch("batch-1", {"observations": [
        {"source_event_id": "src-1", "kind": "chat_message", "text": "明天上午 9 点提醒我交报告"},
    ]})


def test_observer_drain_creates_automation_for_time_intent(tmp_path: Path) -> None:
    """drain ACK 后把带时间 cue 的 ACTIVE INTENT **记录**投影成真实 Automation。

    形状按真服务投影（见 :func:`_intent_record`）：记忆记录 → 意图行 → Automation
    两跳都真走。重放同一条记录不产生第二份 Automation（automation_id 稳定 +
    同正文同时间由 reminders 层去重）。
    """
    intent_id = f"int-{UID}-drain"
    client = _IntentClient(intent_id)
    facade = _Facade([_intent_record()], client_obj=client)
    engine = _engine(tmp_path)
    drain = MemoryObserverDrain(
        _Observer(["session-a"], [_batch(), None, _batch(), None]), facade,
        intent_bridge=IntentBridge(facade=facade),  # type: ignore[arg-type]
        automation_engine=engine,
    )

    asyncio.run(drain.drain_once())
    asyncio.run(drain.drain_once())   # 同一条记录重放（记忆读再走一遍）

    assert facade.listed == 2
    assert client.created, "带用户来源链的时间意图必须真建意图行"
    assert client.created[0]["user_source_ref"].startswith("ATLAS_USER_MESSAGE:")
    assert client.created[0]["due_at"] == "2026-10-05T09:00:00+08:00"
    records = engine.store.list()
    assert len(records) == 1
    assert records[0]["id"] == automation_id_for_intent(intent_id)
    assert records[0]["trigger"]["at"] == "2026-10-05T09:00:00+08:00"


def test_observer_drain_without_bridge_does_not_touch_automations(tmp_path: Path) -> None:
    """未注入桥 → 与从前完全一致（不查意图、不建任务）。"""
    facade = _Facade([{"intent_id": "int-x", "cue": {"kind": "time"},
                       "due_at": "2026-10-05T09:00:00+08:00"}])
    drain = MemoryObserverDrain(_Observer(["session-a"], [_batch(), None]), facade)

    asyncio.run(drain.drain_once())

    assert facade.listed == 0
    assert not (tmp_path / "automations.toml").exists()


# ---------------------------------------------- 取消/改期的整句容错匹配

@pytest.mark.parametrize("query", [
    "报告",                                   # 裸核心词
    "交报告",                                 # 完整正文
    "取消明天上午交报告的那个提醒",              # 模型回述整句
    "明天上午交报告",                          # 带时间的前缀
    "把交报告那个提醒删掉",                     # 命令式包裹
])
def test_cancel_matches_whole_sentence_query(tmp_path: Path, query: str) -> None:
    """S29 第 2 轮实测：模型常把整句塞进 query，必须仍能取消掉。"""
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    assert created["created"] is True

    cancelled = asyncio.run(cancel_reminder(query=query, now=NOW, engine=engine))
    assert cancelled["cancelled"] is True, query
    assert cancelled["automation"]["id"] == created["automation"]["id"]


def test_cancel_does_not_false_match_similar_words(tmp_path: Path) -> None:
    """"周报" 不能把 "报告" 的提醒取消掉（放宽匹配不许误伤）。"""
    engine = _engine(tmp_path)
    kept = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    asyncio.run(create_reminder(
        message="交周报", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))

    missed = asyncio.run(cancel_reminder(
        query="取消明天上午交周报的那个提醒", now=NOW, engine=engine))
    assert missed["cancelled"] is True
    assert missed["automation"]["id"] != kept["automation"]["id"]
    # "交报告" 那条必须还活着
    assert engine.store.get(kept["automation"]["id"])["enabled"] is True


def test_list_exposes_active_count_after_cancel(tmp_path: Path) -> None:
    """已取消的留在 store（可审计），但 active 列表要把它排除。"""
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))
    asyncio.run(cancel_reminder(query="报告", now=NOW, engine=engine))

    listing = list_reminders(engine=engine)
    assert len(listing["reminders"]) == 1          # 审计视角：还在
    assert listing["reminders"][0]["id"] == created["automation"]["id"]
    assert listing["active_count"] == 0            # 回答视角：没了
    assert listing["active_reminders"] == []


def test_update_matches_whole_sentence_query(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine,
        config=SHANGHAI_CONFIG))

    moved = asyncio.run(update_reminder(
        query="把明天上午交报告那个提醒改到下午3点", due_text="明天下午3点",
        now=NOW, engine=engine, config=SHANGHAI_CONFIG))
    assert moved["updated"] is True
    assert moved["automation"]["id"] == created["automation"]["id"]
    assert moved["automation"]["trigger"]["at"] == "2026-10-05T15:00:00+08:00"
    assert len(engine.store.list()) == 1           # 原地改，不新建


@pytest.mark.integration
@pytest.mark.fake_provider
def test_intent_cancelled_before_automation_persist_disables_late_automation(
        um: UMHarness, tmp_path: Path) -> None:
    """意图在 drain 确认 ACTIVE 之后、Automation 落库之前被取消 → 落库后立即停用。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    engine = _engine(tmp_path)
    due = "2031-03-05T09:00:00+08:00"
    response = um.api("POST", "/api/unified-memory/intents", json={
        "context": um.default_context(),
        "user_source_ref": "ATLAS_USER_MESSAGE:intent-002",
        "cue": {"kind": "time", "at": due},
        "action": {"kind": "remind", "message": f"晚到落库（{UID}）"},
        "due_at": due,
    })
    assert response.status_code in (200, 201), response.text
    stale_active = response.json()
    assert stale_active["lifecycle"] == "ACTIVE"

    async def run() -> None:
        # 取消先到：此时还没有 Automation，取消侧什么也没停。
        transition = await bridge.cancel_intent(
            stale_active["intent_id"], context=um.default_context(), engine=None)
        assert transition["cancelled"] is True
        # drain 手里仍是取消前读到的 ACTIVE 快照。
        result = await bridge.persist_automation_for_intent(stale_active, engine=engine)
        assert result["created"] is False
        assert result["reason"] == "intent_cancelled_after_persist"
        stored = engine.store.get(result["automation_id"])
        assert stored is not None and stored["enabled"] is False

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.fake_provider
def test_equivalent_actions_prefer_exact_text_over_newest(um: UMHarness) -> None:
    """同源同时刻并存「交报告」(已取消) 与「提交报告」(ACTIVE)：各按原文命中自己。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    due = "2031-04-05T09:00:00+08:00"
    source_ref = "ATLAS_USER_MESSAGE:intent-002"

    def create(message: str) -> dict[str, Any]:
        response = um.api("POST", "/api/unified-memory/intents", json={
            "context": um.default_context(),
            "user_source_ref": source_ref,
            "cue": {"kind": "time", "at": due},
            "action": {"kind": "remind", "message": message},
            "due_at": due,
        })
        assert response.status_code in (200, 201), response.text
        return response.json()

    def record(message: str) -> dict[str, Any]:
        return {"facet": "INTENT", "lifecycle": "ACTIVE", "metadata": {},
                "content": {"text": message,
                            "evidence_chains": {"chain_keys": [source_ref]}},
                "valid_time": {"valid_from": due}}

    short = create(f"交报告（{UID}-eq）")
    long = create(f"提交报告（{UID}-eq）")

    async def run() -> None:
        assert (await bridge.cancel_intent(
            short["intent_id"], context=um.default_context(), engine=None))["cancelled"]
        # 无论列表顺序/同秒并列，原文完全相同者优先。
        for _ in range(3):
            a = await bridge.ensure_intent_from_record(
                record(f"交报告（{UID}-eq）"), context=um.default_context())
            b = await bridge.ensure_intent_from_record(
                record(f"提交报告（{UID}-eq）"), context=um.default_context())
            assert a["intent_id"] == short["intent_id"]
            assert b["intent_id"] == long["intent_id"]

    asyncio.run(run())
