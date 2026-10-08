"""T06.3 验收测试：IntentBridge —— 统一意图投影到既有 Automation（UM06）。

两块：

  * unit（默认 marker，无服务）：
    - 稳定绑定：automation_id = um-intent-<intent_id> 双向解析；非本桥前缀的
      automation 不误伤；
    - 投影结构合法性：time cue（due_at）→ date trigger；event cue → event
      trigger —— 经**临时 TOML store**（atlas.automation.store 真实
      normalize_record + validate_record）验证 §4 冻结字段形状合法；
    - 无触发面的意图拒绝投影（不另造 scheduler）；
    - 桥不写 store：create_automation_for_intent 只产出配置对象 + 引擎侧
      调用说明（wired=False 偏差如实登记）；
    - cue 适配纯函数 event_matches_cue：project_open / tool_result /
      record_updated 三类事件各命中/不命中；
    - engine 挂接偏差登记存在且锚点正确（engine.py / triggers.py）。
  * integration（um 真双服务 harness，经 Atlas 代理 /api/unified-memory/*）：
    - 判据 test_cancelled_intent_does_not_trigger 语义原样（代理面走通）：
      经代理建 ACTIVE 事件意图 → transition CANCELLED → 真实工具派发 →
      bridge.handle_atlas_event（engine 未挂接，直调 —— 偏差）→ 已取消意图
      lifecycle 保持 CANCELLED 不触发；
    - on_automation_event 回写：投影经真实 TOML store 落地 → 引擎 fire 回写
      lifecycle=TRIGGERED（receipt 留行上）；二次 fire 不重复触发；cancel 后
      不再触发（引擎侧取消 wired=False 偏差如实返回）。

被测实现：core/atlas/memory/intent_bridge.py（Atlas/MemoryOS 整合任务，
无外部来源搬运，不需要 VENDORED 条目）。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from atlas.automation.store import AutomationStore
from atlas.memory.intent_bridge import (
    ATLAS_EVENT_TYPES,
    AUTOMATION_ID_PREFIX,
    ENGINE_WIRING,
    IntentBridge,
    IntentBridgeError,
    automation_id_for_intent,
    event_matches_cue,
    intent_id_from_automation,
    projection_for_intent,
)
from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

UID = uuid.uuid4().hex[:8]   # 本文件的意图命名空间（共享 session harness）


def _make_bridge(um: UMHarness) -> IntentBridge:
    """桥接真实 MemoryOS（与代理转发的是同一服务实例）。"""
    from atlas.memory.unified_client import UnifiedMemoryClient

    return IntentBridge(client=UnifiedMemoryClient(
        service_url=um.memoryos_url, internal_token=TEST_INTERNAL_TOKEN,
        timeout=10.0))


def _sample_intent(**overrides) -> dict:
    intent = {
        "intent_id": f"int-{UID}-sample",
        "cue": {"kind": "time"},
        "action": {"kind": "remind", "message": "提醒提交报销"},
        "condition": {"report": "approved"},
        "due_at": "2026-10-19T15:00:00+08:00",
        "expires_at": "2026-10-20T15:00:00+08:00",
        "revision": 1,
    }
    intent.update(overrides)
    return intent


# ------------------------------------------------------------------ unit: 绑定

def test_automation_id_round_trip():
    """automation_id = um-intent-<intent_id> 双向可解析；非本桥前缀不误伤。"""
    intent_id = "int-abc123"
    automation_id = automation_id_for_intent(intent_id)
    assert automation_id == AUTOMATION_ID_PREFIX + intent_id
    assert intent_id_from_automation(automation_id) == intent_id
    # 其他产品 Automation（非本桥命名）→ None（on_automation_event 原样跳过）
    assert intent_id_from_automation("some-other-automation") is None
    assert intent_id_from_automation(AUTOMATION_ID_PREFIX) is None
    with pytest.raises(IntentBridgeError):
        automation_id_for_intent("")


# ------------------------------------------------------------------ unit: 投影结构

def test_projection_time_cue_is_valid_toml_record(tmp_path: Path):
    """time cue（due_at）→ date trigger；经临时 TOML store 验证 §4 形状合法。"""
    intent = _sample_intent()
    projection = projection_for_intent(intent)
    assert projection["trigger"]["kind"] == "date"
    assert projection["trigger"]["at"] == intent["due_at"]
    assert projection["id"] == f"um-intent-{intent['intent_id']}"
    assert projection["payload"]["kind"] == "agent_turn"
    assert f"intent:{intent['intent_id']}" in projection["payload"]["message"]
    assert projection["delivery"]["mode"] == "none"
    assert projection["policy"]["missed_run"] == "skip"

    store = AutomationStore(tmp_path / "automations.toml")
    stored = store.put(projection)          # normalize_record + validate_record
    reread = store.get(projection["id"])
    assert reread is not None
    assert reread["trigger"]["kind"] == "date"
    assert reread["trigger"]["at"] == intent["due_at"]
    assert reread["payload"]["message"] == stored["payload"]["message"]
    assert reread["enabled"] is True


def test_projection_event_cue_is_valid_toml_record(tmp_path: Path):
    """event cue → event trigger（event_path 结构合法声明位）；经临时 TOML
    store 验证；三类适配事件均能构成合法投影。"""
    for event_type in ATLAS_EVENT_TYPES:
        intent = _sample_intent(
            intent_id=f"int-{UID}-{event_type}",
            cue={"kind": "event", "event_type": event_type,
                 "conditions": {"project_id": "project-alpha"}},
            due_at=None)
        projection = projection_for_intent(intent, event_inbox_dir="./unified-events")
        assert projection["trigger"]["kind"] == "event"
        assert projection["trigger"]["event_path"] == "./unified-events"
        store = AutomationStore(tmp_path / f"automations-{event_type}.toml")
        store.put(projection)               # 合法性由 validate_record 把关
        assert store.get(projection["id"]) is not None


def test_projection_without_trigger_surface_rejected():
    """无 time cue（due_at）也无 event cue → 拒绝投影（不另造 scheduler）；
    缺 intent_id 同样拒绝（投影必须绑定统一意图）。"""
    with pytest.raises(IntentBridgeError):
        projection_for_intent(_sample_intent(cue=None, due_at=None))
    with pytest.raises(IntentBridgeError):
        projection_for_intent(_sample_intent(intent_id=""))


def test_bridge_create_returns_instructions_never_writes_store(tmp_path: Path):
    """create_automation_for_intent 只产出配置对象 + 引擎侧调用说明 ——
    桥绝不写 data/automations.toml（引擎侧写入路径的权威边界）。"""
    bridge = IntentBridge(client=object())   # 该路径不触达 client
    result = bridge.create_automation_for_intent(_sample_intent())
    assert "automation" in result and "instructions" in result
    assert result["instructions"]["wired"] is False
    assert "store.put" in result["instructions"]["persist"]
    # 投影不落盘：目录里没有 automations.toml
    assert not (tmp_path / "automations.toml").exists()
    # 产出的记录可被真实 store 直接消费
    store = AutomationStore(tmp_path / "automations.toml")
    store.put(result["automation"])
    assert store.get(result["automation"]["id"]) is not None


def test_event_matches_cue_three_event_types():
    """cue 适配纯函数：三类事件各命中/不命中（与 MemoryOS cue_match 同判据）。"""
    cue_open = {"kind": "event", "event_type": "project_open",
                "conditions": {"project_id": "project-demo"}}
    assert event_matches_cue(cue_open, "project_open",
                             {"project_id": "project-demo"})
    assert not event_matches_cue(cue_open, "project_open",
                                 {"project_id": "project-other"})
    assert not event_matches_cue(cue_open, "tool_result",
                                 {"project_id": "project-demo"})
    assert event_matches_cue(cue_open, "project_open",
                             {"project_id": ["a", "project-demo"]})   # any-of
    cue_tool = {"kind": "event", "event_type": "tool_result",
                "conditions": {"tool": "write-fixture-file"}}
    assert event_matches_cue(cue_tool, "tool_result",
                             {"tool": "write-fixture-file", "status": "OK"})
    assert not event_matches_cue(cue_tool, "tool_result",
                                 {"tool": "other"})
    cue_record = {"kind": "event", "event_type": "record_updated"}
    assert event_matches_cue(cue_record, "record_updated", {"ref": "memory:x"})
    assert not event_matches_cue(cue_record, "project_open", {})
    # time cue / 畸形输入永不匹配事件
    assert not event_matches_cue({"kind": "time"}, "project_open")
    assert not event_matches_cue(None, "project_open")


def test_engine_wiring_deviation_registered():
    """engine 挂接偏差如实登记：wired=False + engine.py/triggers.py 锚点 +
    store 写入边界说明（真挂接行留收口 —— T06.3 分步方式）。"""
    wiring = IntentBridge.describe_engine_wiring()
    assert wiring["wired"] is False
    files = {anchor["file"] for anchor in wiring["anchors"]}
    assert "core/atlas/automation/engine.py" in files
    assert "core/atlas/automation/triggers.py" in files
    assert "automations.toml" in wiring["store_write"]
    assert ENGINE_WIRING["reason"]


# ------------------------------------------------------------------ integration

def _proxy_create_intent(um: UMHarness, *, user_source_ref: str,
                         cue: dict, action: dict | None = None,
                         **extra) -> dict:
    body = {
        "context": um.default_context(),
        "user_source_ref": user_source_ref,
        "cue": cue,
        "action": action or {"kind": "remind", "message": f"UM06 意图（{UID}）"},
    }
    body.update(extra)
    r = um.api("POST", "/api/unified-memory/intents", json=body)
    # Atlas 代理语义（T01.3 既定偏差）：上游 2xx 统一 200（201 新建 → 200）
    assert r.status_code in (200, 201), r.text
    return r.json()


def _proxy_transition(um: UMHarness, intent_id: str, transition: str,
                      expected_revision: int, **extra) -> dict:
    body = {"context": um.default_context(),
            "transition": transition, "expected_revision": expected_revision,
            **extra}
    r = um.api("POST", f"/api/unified-memory/intents/{intent_id}/transition",
               json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _proxy_get_intent(um: UMHarness, intent_id: str) -> dict:
    r = um.api("GET", "/api/unified-memory/intents",
               params={"intent_id": intent_id})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, f"意图 {intent_id} 不存在"
    return items[0]


@pytest.mark.integration
@pytest.mark.fake_provider
def test_cancelled_intent_does_not_trigger_via_proxy(um: UMHarness):
    """任务书判据语义（代理面走通）：建 ACTIVE 事件意图 → transition
    CANCELLED → 真实工具派发 + bridge.handle_atlas_event（engine 未挂接，
    直调）→ 已取消意图 lifecycle 保持 CANCELLED；未取消的触发 TRIGGERED。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)
    cue = {"kind": "event", "event_type": "project_open",
           "conditions": {"project_id": "project-demo"}}

    live = _proxy_create_intent(
        um, user_source_ref="ATLAS_USER_MESSAGE:intent-002", cue=cue)
    assert live["lifecycle"] == "ACTIVE"        # 真实用户来源 → 服务端授权
    doomed = _proxy_create_intent(
        um, user_source_ref="ATLAS_USER_MESSAGE:intent-002", cue=cue)
    cancelled = _proxy_transition(um, doomed["intent_id"], "CANCELLED",
                                  doomed["revision"])
    assert cancelled["lifecycle"] == "CANCELLED"

    # 真实 Atlas 动作（判据草图里的 open_project 在 Atlas 无此工具 —— 用真实
    # 派发的 terminal 工具落地真实动作；偏差已记录）
    receipt = um.tool("terminal",
                      {"command": "echo open-project-demo", "shell": "powershell"})
    assert receipt["is_error"] is False

    async def scenario():
        first = await bridge.handle_atlas_event(
            "project_open", {"project_id": "project-demo"},
            context=um.default_context())
        # 二次同名事件不重复触发（已 TRIGGERED 不在 ACTIVE 匹配面）
        second = await bridge.handle_atlas_event(
            "project_open", {"project_id": "project-demo"},
            context=um.default_context())
        return first, second

    # 单一事件循环内完成全部桥调用（client 的 httpx transport 绑定一次循环，
    # 与 test_focus_context 的 scenario 模式一致）
    result, again = asyncio.run(scenario())
    fired = {t["intent_id"]: t for t in result["transitions"]}
    assert fired[live["intent_id"]]["fired"] is True, \
        f"handle_atlas_event 结果: {result}"
    assert doomed["intent_id"] not in fired     # 已取消意图不在 ACTIVE 匹配面

    assert _proxy_get_intent(um, live["intent_id"])["lifecycle"] == "TRIGGERED"
    # 判据断言原样：取消后的意图保持 CANCELLED —— 条件再成立也不触发
    assert _proxy_get_intent(um, doomed["intent_id"])["lifecycle"] == "CANCELLED"
    triggered = _proxy_get_intent(um, live["intent_id"])
    assert triggered["last_transition"]["receipt"]["kind"] == "atlas_event"
    assert live["intent_id"] not in {t["intent_id"] for t in again["transitions"]}


@pytest.mark.integration
def test_automation_event_writeback_and_cancel_via_proxy(um: UMHarness):
    """投影落真实 TOML store → on_automation_event 回写 TRIGGERED（receipt
    留行上）→ 二次 fire 不重复 → cancel 后不再触发（引擎侧取消 wired=False）。"""
    data = um.seed("intent")
    assert data.get("ingested"), data.get("ingest_error")
    bridge = _make_bridge(um)

    created = _proxy_create_intent(
        um, user_source_ref="ATLAS_USER_MESSAGE:intent-001",
        cue={"kind": "time"},
        due_at="2026-12-01T09:00:00+08:00",
        expires_at="2026-12-02T09:00:00+08:00",
        action={"kind": "remind", "message": "提醒提交报销（time 投影）"})
    intent = _proxy_get_intent(um, created["intent_id"])
    assert intent["lifecycle"] == "ACTIVE"      # 真实用户来源 → 服务端授权
    assert intent["due_at"] == "2026-12-01T09:00:00+08:00"

    projection = bridge.create_automation_for_intent(intent)
    automation_id = projection["automation"]["id"]
    assert automation_id == f"um-intent-{intent['intent_id']}"

    # 引擎侧持久化（本桥不写 store；此处代引擎执行以验证投影可用）
    store = AutomationStore(um.atlas_data / "automations.toml")
    stored = store.put(projection["automation"])
    assert stored["id"] == automation_id

    async def scenario():
        fired = await bridge.on_automation_event(
            automation_id, {"kind": "date", "at": intent["due_at"]},
            context=um.default_context())
        after = _proxy_get_intent(um, intent["intent_id"])   # 同步代理读（单循环内）
        # 二次 fire：已 TRIGGERED 不重复触发（版本 + 状态双重闸门）
        again = await bridge.on_automation_event(
            automation_id, {}, context=um.default_context())
        # 取消：服务端 CANCELLED + Automation 取消说明（引擎侧 wired=False）
        cancel = await bridge.cancel_intent(
            intent["intent_id"], context=um.default_context())
        # cancel 后不再触发
        late = await bridge.on_automation_event(
            automation_id, {}, context=um.default_context())
        final = _proxy_get_intent(um, intent["intent_id"])
        return fired, after, again, cancel, late, final

    fired, after, again, cancel, late, final = asyncio.run(scenario())
    assert fired["fired"] is True and fired["lifecycle"] == "TRIGGERED"
    assert after["lifecycle"] == "TRIGGERED"
    assert after["automation_id"] == automation_id
    assert after["last_transition"]["receipt"]["automation_id"] == automation_id

    assert again["fired"] is False and again["reason"] == "intent_triggered"

    assert cancel["cancelled"] is True
    assert cancel["lifecycle"] == "CANCELLED"
    assert cancel["automation_cancel"]["automation_id"] == automation_id
    assert cancel["automation_cancel"]["wired"] is False

    assert late["fired"] is False and late["reason"] == "intent_cancelled"
    assert final["lifecycle"] == "CANCELLED"


@pytest.mark.integration
def test_on_automation_event_ignores_foreign_automation(um: UMHarness):
    """非 um-intent- 前缀的 automation（其他产品 Automation）→ 原样跳过，
    不误查不误触发（稳定绑定的边界）。"""
    bridge = _make_bridge(um)
    result = asyncio.run(bridge.on_automation_event(
        "some-other-automation", {"path": "x"}))
    assert result["fired"] is False
    assert result["reason"] == "not_intent_automation"
