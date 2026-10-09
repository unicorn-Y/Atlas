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
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from atlas.automation.engine import AutomationEngine
from atlas.automation.reminders import (
    REMINDER_PREFIX,
    ReminderError,
    cancel_reminder,
    create_reminder,
    list_reminders,
    parse_due,
    update_reminder,
)
from atlas.automation.store import AutomationStore
from atlas.memory.intent_bridge import IntentBridge, automation_id_for_intent
from atlas.memory.observer_drain import MemoryObserverDrain
from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

UID = uuid.uuid4().hex[:8]
NOW = datetime(2026, 10, 4, 14, 0, 0)          # 测试时钟（S29 "明天上午 9 点"）


def _engine(tmp_path: Path) -> AutomationEngine:
    """未启动的真引擎（``sync_automation`` no-op，``cancel`` 有 started 守卫）。"""
    return AutomationEngine(AutomationStore(tmp_path / "automations.toml"))


# --------------------------------------------------------------- 1. 时间解析

@pytest.mark.parametrize("text,expected", [
    ("明天上午9点", "2026-10-05T09:00:00"),
    ("明天上午 9 点提醒我交报告", "2026-10-05T09:00:00"),
    ("今天下午3点", "2026-10-04T15:00:00"),
    ("后天晚上八点半", "2026-10-06T20:30:00"),
    ("明天中午十二点", "2026-10-05T12:00:00"),
    ("9:30", "2026-10-05T09:30:00"),                # 只说钟点且已过 → 明天
    ("明天", "2026-10-05T09:00:00"),                # 只有日期 → 09:00 默认
    ("2026-10-05T09:00:00", "2026-10-05T09:00:00"),  # ISO 直通
    ("2026-10-05 09:00:00 提醒我", "2026-10-05T09:00:00"),
])
def test_parse_due_convertible_forms(text: str, expected: str) -> None:
    assert parse_due(text, now=NOW).isoformat() == expected


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
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine))
    assert first["created"] is True
    trigger = first["automation"]["trigger"]
    assert trigger["kind"] == "date" and trigger["at"] == "2026-10-05T09:00:00"
    assert first["automation"]["name"].startswith(REMINDER_PREFIX)
    assert first["automation"]["enabled"] is True

    # 同正文 + 同时间（含口语前缀"提醒我"）→ 不重复建第二条
    again = asyncio.run(create_reminder(
        message="提醒我交报告", due_text="明天上午9点", now=NOW, engine=engine))
    assert again["created"] is False and again.get("deduped") is True
    assert len(store.list()) == 1

    # 不同事 → 各建一条
    other = asyncio.run(create_reminder(
        message="交周报", due_text="明天上午9点", now=NOW, engine=engine))
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
        query="周报", due_text="明天下午3点", now=NOW, engine=engine))
    assert updated["updated"] is True
    assert updated["automation"]["id"] == other["automation"]["id"]
    assert updated["automation"]["trigger"]["at"] == "2026-10-05T15:00:00"
    assert len(store.list()) == 2

    # 取消失败的诚实返回（无匹配 → 不假装成功）
    miss = asyncio.run(cancel_reminder(query="不存在的提醒", now=NOW, engine=engine))
    assert miss["cancelled"] is False and miss["reason"] == "no_matching_reminder"


def test_reminder_syncs_engine_every_mutation(tmp_path: Path, monkeypatch) -> None:
    """每次变更都 sync 到引擎（started 时）；未启动时 sync 为 no-op 不报错。"""
    engine = _engine(tmp_path)
    synced: list[str] = []

    async def _record(record):
        synced.append(str(record.get("id")))

    monkeypatch.setattr(engine, "sync_automation", _record)
    created = asyncio.run(create_reminder(
        message="喝水", due_text="今天下午3点", now=NOW, engine=engine))
    asyncio.run(cancel_reminder(query="喝水", now=NOW, engine=engine))
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
    def __init__(self, intents: list[dict[str, Any]] | None = None) -> None:
        self.intents = intents or []
        self.listed = 0

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


def _batch() -> _Batch:
    return _Batch("batch-1", {"observations": [
        {"source_event_id": "src-1", "kind": "chat_message", "text": "明天上午 9 点提醒我交报告"},
    ]})


def test_observer_drain_creates_automation_for_time_intent(tmp_path: Path) -> None:
    """drain ACK 后把带时间条件的 ACTIVE 意图投影成真实 Automation。"""
    intent = {
        "intent_id": f"int-{UID}-drain",
        "cue": {"kind": "time"},
        "action": {"kind": "remind", "message": f"交报告（{UID}）"},
        "due_at": "2026-10-05T09:00:00+08:00",
        "lifecycle": "ACTIVE",
    }
    facade = _Facade([intent])
    engine = _engine(tmp_path)
    drain = MemoryObserverDrain(_Observer(["session-a"], [_batch(), None]), facade,
                                intent_bridge=IntentBridge(client=object()),
                                automation_engine=engine)

    asyncio.run(drain.drain_once())

    assert facade.listed == 1
    records = engine.store.list()
    assert len(records) == 1
    assert records[0]["id"] == automation_id_for_intent(intent["intent_id"])
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
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine))
    assert created["created"] is True

    cancelled = asyncio.run(cancel_reminder(query=query, now=NOW, engine=engine))
    assert cancelled["cancelled"] is True, query
    assert cancelled["automation"]["id"] == created["automation"]["id"]


def test_cancel_does_not_false_match_similar_words(tmp_path: Path) -> None:
    """"周报" 不能把 "报告" 的提醒取消掉（放宽匹配不许误伤）。"""
    engine = _engine(tmp_path)
    kept = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine))
    asyncio.run(create_reminder(
        message="交周报", due_text="明天上午9点", now=NOW, engine=engine))

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
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine))
    asyncio.run(cancel_reminder(query="报告", now=NOW, engine=engine))

    listing = list_reminders(engine=engine)
    assert len(listing["reminders"]) == 1          # 审计视角：还在
    assert listing["reminders"][0]["id"] == created["automation"]["id"]
    assert listing["active_count"] == 0            # 回答视角：没了
    assert listing["active_reminders"] == []


def test_update_matches_whole_sentence_query(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(create_reminder(
        message="交报告", due_text="明天上午9点", now=NOW, engine=engine))

    moved = asyncio.run(update_reminder(
        query="把明天上午交报告那个提醒改到下午3点", due_text="明天下午3点",
        now=NOW, engine=engine))
    assert moved["updated"] is True
    assert moved["automation"]["id"] == created["automation"]["id"]
    assert moved["automation"]["trigger"]["at"] == "2026-10-05T15:00:00"
    assert len(engine.store.list()) == 1           # 原地改，不新建
