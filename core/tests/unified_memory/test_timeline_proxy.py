"""T04.1 Atlas-side integration: /api/unified-memory/timeline via proxy (UM04).

T01.3 的代理面是**表驱动透传**（core/atlas/api/unified_memory_router.py
``PROXY_ROUTES`` 已含 GET /timeline、POST /observe、GET /records），query/body
原样转发（facade.call 不改写），MemoryOS 侧 T04.1 接线后代理自动跟随 ——
本文件验证：

  * seed daily（frozen seed，经 harness.seed → 真实 /v1/unified/observe，
    TEST 批直接形成）→ 经 Atlas 代理 GET /api/unified-memory/timeline 200 且
    任务书判据原样成立：首条 items[0].source_refs 非空、
    content.participants 存在；daily 的 day-1001 事件可按原话事件 id 定位
    （record_ref episode: 前缀、source_refs 指回
    atlas:ATLAS_USER_MESSAGE:msg-d1-01；seed 只声明 speaker_role，形成层
    如实给角色派生参与者 kind=ROLE）；
  * KNOWN 时间升序；daily 无 time_status != KNOWN 的记录，unknown 分组断言
    由**额外一条 UNKNOWN 时间观察经代理 observe** 给出（不改冻结 seed）：
    进 unknown 段、不进 items、不伪造时间排序；
  * TEST 批形成路径（Atlas 集成 observe → DIRECT_TEST_BATCH 直接形成）：
    代理 observe 后经代理 GET /records?facet=EPISODE 该事件可读
    （facet=EPISODE、projection=FORMED_EPISODE、source_refs/participants）。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径
（harness._refuse_production_env 兜底）。会话级 harness 共库：跨测试断言
只定位本文件自己的事件（UID 命名空间），全集断言只用对所有统一形成事件
恒真的性质（source_refs 非空 / participants 存在 / KNOWN 升序）。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \
    -m pytest core/tests/unified_memory -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import uuid

import pytest
from atlas.memory.unified_client import observation_content_hash

from tests.unified_memory.harness import UMHarness

SUBJECT = "atlas-fixture"          # harness 绑定主体（_memoryos_env）
UID = uuid.uuid4().hex[:8]         # 每次运行的种子命名空间（会话级 harness 复用）
HKT = "Asia/Hong_Kong"

#: day-1001（frozen seed）的原话事件 id（只读断言，不改 seed）。
DAY1_SEID = "atlas:ATLAS_USER_MESSAGE:msg-d1-01:1:UPSERT"


def _context(harness: UMHarness, session: str) -> dict:
    return {**harness.default_context(), "runtime_session_id": session}


def _timeline_via_proxy(harness: UMHarness, **params) -> dict:
    r = harness.api("GET", "/api/unified-memory/timeline", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _all_timeline_records(harness: UMHarness, **params) -> dict:
    """cursor 翻页取全量（会话共库可能超过单页 limit=200 上限）。"""
    items: list[dict] = []
    unknown: list[dict] = []
    cursor: str | None = None
    for _ in range(50):
        page = _timeline_via_proxy(harness, cursor=cursor,
                                   limit=200, **params)
        items.extend(page["items"])
        unknown.extend(page["unknown"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert cursor is None, "timeline 翻页 50 页未穷尽（异常状态）"
    return {"items": items, "unknown": unknown}


def _observe_via_proxy(harness: UMHarness, observations: list[dict],
                       session: str) -> dict:
    body = {
        "contract_version": "UM-WIN-1.0",
        "event_class": "TEST",
        "context": _context(harness, session),
        "observations": observations,
    }
    r = harness.api("POST", "/api/unified-memory/observe", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _message_obs(object_id: str, text: str, *, occurred_at: str | None,
                 time_status: str, **content_extra) -> dict:
    content = {"text": text}
    content.update(content_extra)
    obs = {
        "source_event_id": f"atlas:ATLAS_USER_MESSAGE:{object_id}:1:UPSERT",
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": object_id,
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": occurred_at,
        "source_timezone": HKT,
        "time_status": time_status,
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": content,
        "locator": {"kind": "MESSAGE", "value": "chat-timeline/" + object_id},
        "media_refs": [],
        "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    return obs


def _episode_by_source_ref(records: list[dict], seid: str) -> dict | None:
    for item in records:
        if any(ref.get("source_event_id") == seid
               for ref in (item.get("source_refs") or [])):
            return item
    return None


@pytest.mark.integration
def test_timeline_proxy_seed_daily_first_item_has_evidence_and_participants(
        um: UMHarness):
    """seed daily → 代理 timeline 200；任务书判据（T04.1）原样：
    items[0].source_refs 非空且 content.participants 存在；day-1001 事件
    可按原话事件 id 定位（episode: 前缀 + source_refs 回指 + 参与者）。"""
    seed = um.seed("daily")
    assert seed.get("ingested") is True, seed

    payload = _all_timeline_records(um)
    items, unknown = payload["items"], payload["unknown"]
    # 统一形成的事件必有原话证据与参与者（全集恒真性质 —— 会话共库下
    # items[0] 判据与 MemoryOS 侧 test_daily_event_has_original_evidence 同形）。
    assert items, "timeline items 为空（daily seed 未形成任何事件？）"
    first = items[0]
    assert first["source_refs"], "timeline 首条必须带 source_refs（原话可回看）"
    assert first["record_ref"].startswith("episode:")
    assert first["content"]["participants"], "timeline 首条必须带 participants"

    # day-1001（seed 元数据 ground_truth.topic=配色稿）：定位本 seed 的事件
    day1 = _episode_by_source_ref(items + unknown, DAY1_SEID)
    assert day1 is not None, f"day-1001 事件不在 timeline: {DAY1_SEID}"
    assert day1["record_ref"].startswith("episode:")
    assert day1["facet"] == "EPISODE"
    # frozen seed 只声明 speaker_role=USER（无显式 content.participants）——
    # 形成层如实给角色派生参与者（kind=ROLE），不猜文本里的人名。
    participants = day1["content"]["participants"]
    assert {str(p.get("kind") or "") for p in participants} == {"ROLE"}
    assert {str(p.get("name") or "") for p in participants} == {"USER"}
    # frozen seed 无显式 topic → 形成层如实给 raw: 前缀键（逐字精确重复
    # 语义；LLM 主题概括留 T04.3，不猜）。ground_truth 的「配色稿」在原话里。
    assert str(day1["content"]["topic"]).startswith("raw:"), day1["content"]["topic"]
    assert "配色稿" in str(day1["content"]["topic"])

    # KNOWN 升序（存储归一 UTC 的 ISO 字符串序 = 时间序）
    valid_froms = [item["valid_time"]["valid_from"] for item in items]
    assert all(valid_froms), "KNOWN 段不允许缺 valid_from"
    assert valid_froms == sorted(valid_froms)
    # unknown 段不混入 KNOWN
    assert all(item["valid_time"]["time_status"] == "KNOWN" for item in items)


@pytest.mark.integration
def test_timeline_proxy_unknown_time_grouped_into_unknown_section(um: UMHarness):
    """UNKNOWN 时间的观察 → 进 unknown 段（不进 items、不伪造时间排序）。

    frozen daily seed 全部 KNOWN，本断言的 UNKNOWN 记录由额外一次代理
    observe 给出（不改冻结 seed；「seed 里如有」判据的对齐实现）。"""
    tag = f"unk-{UID}"
    ack = _observe_via_proxy(
        um, [_message_obs(f"ptl-u-{tag}", f"不知道具体时候说的事{tag}",
                          occurred_at=None, time_status="UNKNOWN")],
        f"timeline-proxy-{tag}")
    formation = ack["episode_formation"]
    assert formation["path"] == "DIRECT_TEST_BATCH"
    episode_id = formation["episodes"][0]["episode_id"]
    unknown_ref = f"episode:{episode_id}"

    payload = _all_timeline_records(um)
    items_refs = {item["record_ref"] for item in payload["items"]}
    unknown_refs = {item["record_ref"] for item in payload["unknown"]}
    assert unknown_ref in unknown_refs, "UNKNOWN 时间事件必须进 unknown 段"
    assert unknown_ref not in items_refs, "UNKNOWN 时间事件不得混入 KNOWN 排序"
    mine = next(item for item in payload["unknown"]
                if item["record_ref"] == unknown_ref)
    assert mine["valid_time"]["time_status"] == "UNKNOWN"
    assert mine["valid_time"]["valid_from"] is None   # 不伪造时间戳
    assert mine["source_refs"], "unknown 段事件同样必须带原话证据"


@pytest.mark.integration
def test_timeline_proxy_observe_test_batch_forms_readable_episode(um: UMHarness):
    """TEST 批形成路径（Atlas 集成 observe → DIRECT_TEST_BATCH 直接形成）：
    经代理 observe 后，代理 GET /records?facet=EPISODE 该事件可读
    （facet=EPISODE / projection=FORMED_EPISODE / source_refs / participants）。"""
    tag = f"form-{UID}"
    ack = _observe_via_proxy(
        um, [_message_obs(f"ptl-f-{tag}", f"和小王确定了发布时间{tag}",
                          occurred_at="2026-10-04T10:00:00+08:00",
                          time_status="KNOWN", topic=f"发布定档-{tag}")],
        f"timeline-proxy-{tag}")
    formation = ack["episode_formation"]
    assert formation["path"] == "DIRECT_TEST_BATCH"
    receipt = formation["episodes"][0]
    assert receipt["action"] == "CREATED"
    record_ref = receipt["record_ref"]
    assert record_ref.startswith("episode:")

    r = um.api("GET", "/api/unified-memory/records",
               params={"facet": "EPISODE"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    mine = [item for item in items if item["record_ref"] == record_ref]
    assert len(mine) == 1, f"facet=EPISODE 记录里找不到 {record_ref}"
    item = mine[0]
    assert item["facet"] == "EPISODE"
    assert item["content"]["projection"] == "FORMED_EPISODE"
    assert item["content"]["topic"] == f"发布定档-{tag}"
    assert item["source_refs"], "形成记录必须带 source_refs（原始定位必填）"
    assert item["source_refs"][0]["source_event_id"] == \
        f"atlas:ATLAS_USER_MESSAGE:ptl-f-{tag}:1:UPSERT"
    assert item["content"]["participants"], "participants 必须存在"
    assert item["valid_time"]["time_status"] == "KNOWN"
