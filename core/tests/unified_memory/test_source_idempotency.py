"""T02.1 验收测试：来源幂等与耐久 outbox（Atlas 侧，unified-memory/waves UM02）。

判据（02_wave_tasks.md T02.1）：
  * unit：outbox enqueue/poll/ack/重试/BLOCKED/recover 状态机全路径；
    同 ID 不同内容第二次 enqueue → 本地拒绝（OutboxConflict）。
  * content_hash 镜像一致性：Atlas 实现 == MemoryOS contracts 的
    ``observation_content_hash``（读 MemoryOS 契约源码双实现比对 —— 不跨环境
    import；MemoryOS 仓库不可达时 skip）。
  * 集成（um harness）：enqueue 3 条观察 → flush → /v1/unified/records 可读、
    status source_objects=3、outbox 0 pending；kill 边界（flush 前退出 → 独立
    outbox 文件 + 新实例恢复）→ flush 成功且服务端无重复（DUPLICATE_OK）；
    任务书判据 ``test_conflicting_retry_fails`` 原样实现（同 ID 改内容 → 409）；
    sources/change：EDIT 新 revision → 202/200、旧 revision SUPERSEDED、重试
    幂等；DELETE 后 observe 同 source_event_id → 423。

运行（Atlas core 解释器）：
  cd /d/Atlas && core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \\
      -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import random
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from atlas.config import AtlasConfig
from atlas.memory.capture import (
    HASH_BASIS_FIELDS,
    ContentTooLarge,
    ObservationBuilder,
    build_observation,
    enqueue_capture,
    observation_content_hash,
)
from atlas.memory.outbox import (
    STATE_ACKED,
    STATE_BLOCKED,
    STATE_RETRYABLE,
    STATE_SENDING,
    OutboxConflict,
    OperationalOutbox,
    flush_once,
)
from atlas.memory.unified_client import UnifiedMemoryClient
from atlas.memory.unified_facade import UnifiedMemoryFacade
from tests.unified_memory.harness import ATLAS_REPO, TEST_INTERNAL_TOKEN

MEMORYOS_CONTRACTS = ATLAS_REPO.parent / "MemoryOS" / "service" / "unified" / "contracts.py"


# ------------------------------------------------------------------ 夹具

class _Clock:
    """可推进的假时钟（lease / 退避判定不靠 sleep）。"""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _context(session: str) -> dict[str, Any]:
    return {
        "owner_id": "owner-fixture",
        "memory_subject_id": "atlas-fixture",
        "client_id": "atlas-desktop",
        "actor_id": "atlas-main",
        "runtime_session_id": session,
        "task_id": None,
        "project_id": None,
        "environment_id": "windows-fixture",
        "model_deployment_id": "model-fixture",
    }


def _builder(session: str) -> ObservationBuilder:
    return ObservationBuilder(context=_context(session), event_class="TEST")


def _three_observations(session: str, tag: str) -> list[dict[str, Any]]:
    builder = _builder(session)
    return [
        builder.build(
            source_kind="ATLAS_USER_MESSAGE", source_object_id=f"{tag}-msg-{i}",
            source_revision="1",
            content={"text": f"T02.1 outbox 夹具 {tag} 第{i}条"},
            occurred_at="2026-10-06T09:0%d:00+08:00" % i,
            source_timezone="Asia/Hong_Kong",
            speaker_role="USER", epistemic_kind="USER_ASSERTED",
            locator={"kind": "MESSAGE", "value": f"{session}/{tag}-msg-{i}"},
        )
        for i in range(3)
    ]


def _facade_with(handler: Any) -> UnifiedMemoryFacade:
    client = UnifiedMemoryClient(
        "http://memoryos.test", internal_token="internal",
        transport=httpx.MockTransport(handler))
    return UnifiedMemoryFacade(
        # TOML [memory.unified] 经 tomllib 解析为嵌套 dict —— 构造用同形状
        config=AtlasConfig(data={"memory": {"unified": {"enabled": True}}}),
        client=client)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/unified/observe"
    return httpx.Response(201, json={"created": 1, "duplicates": 0, "receipts": []})


# ================================================================== unit: outbox

def test_outbox_enqueue_persists_first_receipt_with_stable_id(tmp_path):
    outbox = OperationalOutbox(tmp_path / "outbox" / "unified_outbox.sqlite3")
    obs = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="m-1", source_revision="1",
        content={"text": "第一次接收即持久化"}, occurred_at="2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong", speaker_role="USER",
        epistemic_kind="USER_ASSERTED")
    first = enqueue_capture(outbox, obs, context=_context("s"), event_class="TEST")
    assert first["created"] is True and first["state"] == "NEW"
    assert first["source_event_id"] == "atlas:ATLAS_USER_MESSAGE:m-1:1:UPSERT"
    # 重试沿用同一 ID（不生成新 UUID）
    replay = enqueue_capture(outbox, obs, context=_context("s"), event_class="TEST")
    assert replay["created"] is False and replay["id"] == first["id"]
    assert outbox.stats()["total"] == 1
    outbox.close()


def test_outbox_same_id_different_content_rejected_locally(tmp_path):
    outbox = OperationalOutbox(tmp_path / "o.sqlite3")
    base = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="m-2", source_revision="1",
        content={"text": "原始内容"}, occurred_at="2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong", speaker_role="USER",
        epistemic_kind="USER_ASSERTED")
    enqueue_capture(outbox, base)
    tampered = dict(base, content={"text": "同 ID 改内容（拒绝）"})
    with pytest.raises(OutboxConflict) as excinfo:
        enqueue_capture(outbox, tampered)
    assert excinfo.value.source_event_id == base["source_event_id"]
    assert outbox.stats()["total"] == 1
    outbox.close()


def test_outbox_poll_marks_sending_and_lease_blocks_repoll(tmp_path):
    clock = _Clock()
    outbox = OperationalOutbox(tmp_path / "o.sqlite3", clock=clock)
    obs = build_observation(
        source_kind="ATLAS_TOOL_OBSERVATION", source_object_id="t-1",
        source_revision="1", content={"text": "poll"},
        speaker_role="TOOL", epistemic_kind="OBSERVED", time_status="UNKNOWN",
        occurred_at=None)
    enqueue_capture(outbox, obs)
    polled = outbox.poll_pending(10)
    assert len(polled) == 1 and polled[0]["state"] == STATE_SENDING
    assert polled[0]["attempts"] == 1
    assert polled[0]["payload"]["observation"]["source_event_id"] == \
        obs["source_event_id"]
    # lease 未过期：二次 poll 为空
    assert outbox.poll_pending(10) == []
    outbox.close()


def test_outbox_retry_backoff_then_ack_same_id(tmp_path):
    clock = _Clock()
    outbox = OperationalOutbox(tmp_path / "o.sqlite3", clock=clock)
    obs = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="m-3", source_revision="1",
        content={"text": "网络失败退避"}, occurred_at="2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong", speaker_role="USER",
        epistemic_kind="USER_ASSERTED")
    enqueue_capture(outbox, obs)

    seen: list[str] = []

    def flaky_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["observations"][0]["source_event_id"])
        raise httpx.ConnectError("service down")

    def ok_handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["observations"][0]["source_event_id"])
        return httpx.Response(201, json={"created": 1, "duplicates": 0, "receipts": []})

    facade = _facade_with(flaky_handler)
    report = asyncio.run(flush_once(outbox, facade, backoff_seconds=5))
    assert report["acked"] == 0 and report["retryable"] == 1
    row = outbox.get(obs["source_event_id"])
    assert row["state"] == STATE_RETRYABLE
    assert row["next_retry_at"] > clock.now          # 退避记账
    assert seen == [obs["source_event_id"]]          # 第一次尝试

    clock.now = row["next_retry_at"] + 1             # 退避到期
    report2 = asyncio.run(flush_once(outbox, facade, backoff_seconds=5))
    # 服务仍然不可达 → 再次 RETRYABLE，且 **重试不改 ID**
    assert report2["retryable"] == 1
    assert seen == [obs["source_event_id"], obs["source_event_id"]]

    ok = _facade_with(ok_handler)
    clock.now = outbox.get(obs["source_event_id"])["next_retry_at"] + 1
    report3 = asyncio.run(flush_once(outbox, ok))
    assert report3["acked"] == 1
    assert seen.count(obs["source_event_id"]) == 3   # 第三次成功，仍是同一 ID
    assert outbox.stats()["pending"] == 0
    assert outbox.stats()["acked"] == 1
    outbox.close()


def test_outbox_conflict_and_barrier_block_without_retry(tmp_path):
    outbox = OperationalOutbox(tmp_path / "o.sqlite3")

    def conflict_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "IDEMPOTENCY_CONFLICT",
                                         "message": "同 ID 异内容", "details": {}})

    def barrier_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(423, json={"error": "ERASURE_BARRIER_ACTIVE",
                                         "message": "屏障", "details": {}})

    def make(tag: str) -> dict[str, Any]:
        return build_observation(
            source_kind="ATLAS_USER_MESSAGE", source_object_id=tag,
            source_revision="1", content={"text": f"blocked {tag}"},
            occurred_at="2026-10-06T09:00:00+08:00", source_timezone="Asia/Hong_Kong",
            speaker_role="USER", epistemic_kind="USER_ASSERTED")

    enqueue_capture(outbox, make("c-1"), event_class="TEST")
    enqueue_capture(outbox, make("c-2"), event_class="TEST")
    report = asyncio.run(flush_once(outbox, _facade_with(conflict_handler), limit=1))
    assert report["blocked"] == 1
    barrier_report = asyncio.run(
        flush_once(outbox, _facade_with(barrier_handler), limit=1))
    assert barrier_report["blocked"] == 1
    stats = outbox.stats()
    assert stats["blocked"] == 2 and stats["pending"] == 0
    # BLOCKED 不重试：poll 永远为空
    assert outbox.poll_pending(10) == []
    assert outbox.get("atlas:ATLAS_USER_MESSAGE:c-1:1:UPSERT")["last_error"]
    outbox.close()


def test_outbox_recover_leases_on_new_instance_after_kill(tmp_path):
    """kill 边界（本地半边）：SENDING 中进程退出 → 新实例 recover → RETRYABLE。"""
    clock = _Clock()
    path = tmp_path / "o.sqlite3"
    first = OperationalOutbox(path, clock=clock)
    obs = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="m-4", source_revision="1",
        content={"text": "kill 边界"}, occurred_at="2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong", speaker_role="USER",
        epistemic_kind="USER_ASSERTED")
    enqueue_capture(first, obs)
    assert first.poll_pending(10)[0]["state"] == STATE_SENDING
    first.close()                                    # 进程在这里"死亡"

    clock.now += 3600                                # lease 早已过期
    second = OperationalOutbox(path, clock=clock)    # 新实例，同一持久文件
    assert second.stats()["sending"] == 1
    assert second.recover_leases() == 1
    polled = second.poll_pending(10)
    assert len(polled) == 1 and polled[0]["attempts"] == 2
    assert polled[0]["source_event_id"] == obs["source_event_id"]
    second.close()


# ================================================================== unit: parity

def _memoryos_observation_content_hash() -> Any:
    """从 MemoryOS 契约**源码**提取 canonical_json / observation_content_hash。

    不跨环境 import（契约 §1）；MemoryOS 仓库不可达时 skip（parity 无法成立）。
    """
    if not MEMORYOS_CONTRACTS.exists():
        pytest.skip(f"MemoryOS 契约源码不可达: {MEMORYOS_CONTRACTS}")
    source = MEMORYOS_CONTRACTS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"canonical_json", "observation_content_hash"}
    segments: list[str] = []
    for node in tree.body:
        name = getattr(node, "name", None) or getattr(
            getattr(node, "targets", [None])[0], "id", "")
        if name in wanted or name == "HASH_BASIS_FIELDS":
            segment = ast.get_source_segment(source, node)
            assert segment, name
            segments.append(segment)
    assert len(segments) == 3, f"契约提取不完整: {sorted(wanted)}"
    namespace: dict[str, Any] = {}
    exec("from __future__ import annotations\n"
         "import hashlib, json\nfrom typing import Any\n"
         + "\n".join(segments), namespace)  # noqa: S102 - 受控测试夹具
    return namespace["observation_content_hash"], namespace["HASH_BASIS_FIELDS"]


def test_content_hash_mirror_matches_memoryos_contracts():
    memoryos_hash, memoryos_basis = _memoryos_observation_content_hash()
    assert tuple(memoryos_basis) == HASH_BASIS_FIELDS, "哈希基础字段集漂移"

    # 固定契约样本（01_contracts.md §2 的字段形状）
    fixed = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="msg-001",
        source_revision="1",
        content={"text": "这周晚上不要给我安排工作，项目明天上午继续。"},
        occurred_at="2026-10-06T09:00:00+08:00", source_timezone="Asia/Hong_Kong",
        speaker_role="USER", epistemic_kind="USER_ASSERTED",
        locator={"kind": "MESSAGE", "value": "chat-001/msg-001"})
    # 随机 20 组内容（含 CJK / 嵌套结构 / UNKNOWN 时间 / DELETE 动作）
    samples = [dict(fixed, content=dict(fixed["content"]))]
    rng = random.Random(20261006)
    for i in range(20):
        role = ("USER", "ATLAS", "TOOL", "THIRD_PARTY", "UNKNOWN")[i % 5]
        kind = ("ATLAS_USER_MESSAGE", "ATLAS_TOOL_OBSERVATION", "USER_IMPORT",
                "ATLAS_VERIFICATION", "DERIVED")[i % 5]
        epistemic = ("OBSERVED", "USER_ASSERTED", "THIRD_PARTY_ASSERTED",
                     "INFERRED", "SIMULATED")[i % 5]
        occurred = (None if i % 4 == 0
                    else f"2026-10-0{i % 6 + 1}T0{i % 9}:30:00+08:00")
        samples.append(build_observation(
            source_kind=kind, source_object_id=f"obj-{i}-随机{rng.randint(0, 9999)}",
            source_revision=str(i % 3 + 1),
            content={"text": f"随机样本{i}「{rng.random()}」",
                     "nested": {"b": i, "a": [1, 2, {"c": "中文"}]},
                     "when": occurred},
            occurred_at=occurred,
            source_timezone=None if occurred is None else "Asia/Hong_Kong",
            speaker_role=role, epistemic_kind=epistemic,
            locator={"kind": "MESSAGE", "value": f"s/{i}"},
            media_refs=[], derived_from=[],
            event_action="DELETE" if i % 7 == 6 else "UPSERT"))
    assert len(samples) == 21
    for observation in samples:
        atlas_hash = observation_content_hash(observation)
        memoryos_value = memoryos_hash(observation)
        assert atlas_hash == memoryos_value, observation["source_event_id"]
        assert atlas_hash.startswith("sha256:") and len(atlas_hash) == 71
    # 运输时间不得进哈希：同内容不同 recorded/sent 时间哈希一致
    assert observation_content_hash(dict(samples[0], recorded_at="2026-01-01")) == \
        memoryos_hash(samples[0])


def test_builder_contract_shape_and_oversize_rejection():
    observation = build_observation(
        source_kind="ATLAS_USER_MESSAGE", source_object_id="m-9", source_revision="2",
        content={"text": "形状"}, occurred_at="2026-10-06T09:00:00+08:00",
        source_timezone="Asia/Hong_Kong", speaker_role="ATLAS",
        epistemic_kind="OBSERVED")
    assert observation["source_event_id"] == "atlas:ATLAS_USER_MESSAGE:m-9:2:UPSERT"
    assert observation["content_hash"] == observation_content_hash(observation)
    with pytest.raises(ValueError):
        build_observation(
            source_kind="ATLAS_USER_MESSAGE", source_object_id="m-9",
            source_revision="2", content={"text": "x"}, occurred_at=None,
            speaker_role="ATLAS", epistemic_kind="OBSERVED", time_status="KNOWN")
    with pytest.raises(ContentTooLarge):
        build_observation(
            source_kind="ATLAS_USER_MESSAGE", source_object_id="big",
            source_revision="1", content={"text": "巨" * (1024 * 1024)},
            speaker_role="USER", epistemic_kind="USER_ASSERTED",
            time_status="UNKNOWN", occurred_at=None)


# ================================================================== integration

def _real_facade(um) -> UnifiedMemoryFacade:
    config = AtlasConfig(data={"memory": {"unified": {
        "enabled": True,
        "service_url": um.memoryos_url,
        "internal_token": TEST_INTERNAL_TOKEN,
        "subject_binding": "atlas-fixture",
        "timeout_seconds": 10.0,
    }}})
    return UnifiedMemoryFacade(config=config)


@pytest.mark.integration
def test_conflicting_retry_fails(um):
    """任务书判据原样：同 ID 改内容 → 409。"""
    batch = um.seed("conversation")["observation_batch"]
    batch["observations"][0]["content"]["text"] = "changed without revision"
    assert um.api("POST", "/v1/unified/observe", json=batch).status_code == 409


@pytest.mark.integration
def test_flush_roundtrip_records_readable_status_counts_outbox_drained(um):
    tag = f"flush{uuid.uuid4().hex[:10]}"
    session = f"chat-{tag}"
    observations = _three_observations(session, tag)
    builder = _builder(session)
    before = um.api("GET", "/v1/unified/status").json()["source_objects"]["total"]

    outbox = OperationalOutbox(um.atlas_data / "outbox" / "unified_outbox.sqlite3")
    try:
        for observation in observations:
            enqueue_capture(outbox, observation, context=builder.context,
                            event_class="TEST")
        assert outbox.stats()["pending"] == 3

        report = asyncio.run(flush_once(outbox, _real_facade(um)))
        assert report["acked"] == 3, report
        assert report["outbox"]["pending"] == 0
        assert outbox.poll_pending(10) == []             # 全部 ACKED，不再投递

        # records 同时含 episode 与 memory 投影；每个 source_event 可能有
        # 多个 projection ref。按唯一 source_event 集合验证三条输入都可读。
        items = um.api("GET", "/v1/unified/records",
                       params={"limit": 200}).json()["items"]
        hits = [item for item in items if tag in str(item)]
        assert len(hits) >= 3, f"flush 后 records 必须可读: {tag}"
        expected_events = {observation["source_event_id"] for observation in observations}
        episode_events = {
            ref["source_event_id"]
            for item in hits if item["record_ref"].startswith("episode:")
            for ref in item.get("source_refs", [])
            if ref.get("source_event_id")
        }
        assert episode_events == expected_events, (
            f"episode projections must cover exactly the 3 flushed events; "
            f"expected={expected_events}, actual={episode_events}")

        # status source_objects 计数 +3
        after = um.api("GET", "/v1/unified/status").json()["source_objects"]
        assert after["total"] == before + 3
        assert after["active"] >= 3
    finally:
        outbox.close()


@pytest.mark.integration
def test_kill_before_flush_recovers_without_duplicates(um):
    tag = f"kill{uuid.uuid4().hex[:10]}"
    session = f"chat-{tag}"
    observations = _three_observations(session, tag)
    builder = _builder(session)
    path = um.atlas_data / "outbox" / "unified_outbox.sqlite3"

    # 进程一：enqueue 3 条后、flush 前"死亡"（close 持久文件）
    first = OperationalOutbox(path)
    for observation in observations:
        enqueue_capture(first, observation, context=builder.context,
                        event_class="TEST")
    assert first.stats()["pending"] == 3
    first.close()

    # 进程二（重启后）：同一独立 outbox 文件恢复 → flush 全部成功。
    # 单一事件循环内完成全部 async 步骤（httpx.AsyncClient 绑定首根 loop，
    # 跨 asyncio.run 复用会撞 Event loop is closed —— 真实进程同样是单 loop）。
    second = OperationalOutbox(path)
    facade = _real_facade(um)

    async def _recovered_scenario() -> tuple[dict[str, Any], dict[str, Any],
                                             dict[str, Any]]:
        report = await flush_once(second, facade)
        replay = await facade.observe_batch(builder.batch(observations))
        final = await flush_once(second, facade)
        return report, replay, final

    report, replay, final = asyncio.run(_recovered_scenario())
    assert report["acked"] == 3 and report["outbox"]["pending"] == 0

    # 服务端无重复：同批重放 → DUPLICATE_OK（created=0, duplicates=3）
    assert replay["created"] == 0
    assert replay["duplicates"] == 3, replay
    # 再 flush：无待投递
    assert final["sent"] == 0
    second.close()


@pytest.mark.integration
def test_sources_change_edit_delete_and_deleted_observe_423(um):
    tag = f"src{uuid.uuid4().hex[:10]}"
    builder = _builder(f"chat-{tag}")
    v1 = builder.build(
        source_kind="ATLAS_USER_MESSAGE", source_object_id=f"{tag}-obj",
        source_revision="1", content={"text": f"将被编辑的版本 {tag}"},
        occurred_at="2026-10-06T10:00:00+08:00", source_timezone="Asia/Hong_Kong",
        speaker_role="USER", epistemic_kind="USER_ASSERTED")
    outbox = OperationalOutbox(um.atlas_data / "outbox" / "unified_outbox.sqlite3")
    enqueue_capture(outbox, v1, context=builder.context, event_class="TEST")
    assert asyncio.run(flush_once(outbox, _real_facade(um)))["acked"] == 1

    superseded_before = um.api("GET", "/v1/unified/status").json(
        )["source_objects"]["superseded"]

    # EDIT → 新 revision：202 受理
    edit = um.api("POST", "/v1/unified/sources/change", json={
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": f"{tag}-obj",
        "source_revision": "2", "action": "EDIT"})
    assert edit.status_code == 202, edit.text
    change_id = edit.json()["change_id"]
    assert {"source_revision": "1", "lifecycle": "SUPERSEDED"} in \
        edit.json()["affected_revisions"]

    # EDIT 重试幂等 → 200 + 同 change_id
    replay = um.api("POST", "/v1/unified/sources/change", json={
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": f"{tag}-obj",
        "source_revision": "2", "action": "EDIT"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["change_id"] == change_id

    superseded_after = um.api("GET", "/v1/unified/status").json(
        )["source_objects"]["superseded"]
    assert superseded_after == superseded_before + 1

    # 新 revision 内容经 outbox observe 落地 → 正常 ack
    v2 = builder.build(
        source_kind="ATLAS_USER_MESSAGE", source_object_id=f"{tag}-obj",
        source_revision="2", content={"text": f"编辑后的版本 {tag}"},
        occurred_at="2026-10-06T10:05:00+08:00", source_timezone="Asia/Hong_Kong",
        speaker_role="USER", epistemic_kind="USER_ASSERTED")
    enqueue_capture(outbox, v2, context=builder.context, event_class="TEST")
    assert asyncio.run(flush_once(outbox, _real_facade(um)))["acked"] == 1

    # DELETE → 同 source_event_id 再 observe → 423（删除屏障拒绝复活）
    delete = um.api("POST", "/v1/unified/sources/change", json={
        "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": f"{tag}-obj",
        "source_revision": "2", "action": "DELETE"})
    assert delete.status_code == 202, delete.text
    blocked = um.api("POST", "/v1/unified/observe",
                     json=builder.batch([v1]))
    assert blocked.status_code == 423, blocked.text
    assert blocked.json()["error"] == "SOURCE_DELETED"
    outbox.close()

