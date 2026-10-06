"""T01.1 Atlas-side contract tests: UnifiedMemoryClient / UnifiedMemoryFacade.

* unit（默认标记）：httpx.MockTransport 逐错误类断言（403/409/423/422/501/超时 →
  ServiceUnavailable）、路由表、内容哈希规则、客户端从不执行 SQL 的静态断言、
  facade 配置装配 —— 不起真服务。
* integration：UMHarness 双真服务下 observe → recall 命中、get_status、
  foreign subject 403；断连（h.fault service_down）→ ServiceUnavailable 且
  两个数据目录都**没有任何本地写库 fallback**（sqlite/db 文件集合与 mtime 不变）。

任务书判据（02_wave_tasks T01.1 原样）：
    def test_foreign_subject_is_rejected(h):
        r = h.api("POST", "/v1/unified/recall", json={"context": {"memory_subject_id": "foreign"}, "query": "我是谁"})
        assert r.status_code == 403
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest

from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

from atlas.memory.unified_client import (
    CONTRACT_VERSION,
    ContractViolation,
    ErasureBlocked,
    FeatureNotReady,
    ForbiddenSubject,
    RevisionConflict,
    ServiceUnavailable,
    UnifiedMemoryClient,
    UnifiedMemoryError,
    observation_content_hash,
)
from atlas.memory.unified_facade import UnifiedMemoryFacade

pytest.importorskip("atlas.memory.unified_client")

# 服务端（隔离环境）配置的绑定主体；MemoryOS 测试环境不设置
# MEMORYOS_MEMORY_SUBJECT_ID，因此 = db.MEMORY_SUBJECT_ID。
SUBJECT = "subject-default"


def make_client(handler) -> UnifiedMemoryClient:
    return UnifiedMemoryClient(service_url="http://memoryos.test",
                               internal_token="test-token", timeout=2.0,
                               transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def route_table_handler(expected: list[tuple[str, str]], observed: list):
    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.path))
        if expected:
            assert (request.method, request.url.path) == expected[len(observed) - 1], (
                f"第 {len(observed)} 个请求应为 {expected[len(observed) - 1]}，"
                f"实际 {(request.method, request.url.path)}")
        return httpx.Response(200, json={"ok": True})
    return handler


def context(**overrides) -> dict:
    base = {
        "owner_id": "owner-fixture",
        "memory_subject_id": SUBJECT,
        "client_id": "atlas-desktop",
        "actor_id": "atlas-main",
        "runtime_session_id": "chat-unit-001",
        "task_id": None,
        "project_id": None,
        "environment_id": "windows-unit",
        "model_deployment_id": None,
    }
    base.update(overrides)
    return base


# ================================================================== unit：路由表

def test_every_client_method_issues_its_contract_route():
    """§6 路由表：13 个 §5 方法 + 2 个 UM01 已接线 GET，各发真实 HTTP 请求。"""
    expected = [
        ("POST", "/v1/unified/observe"),
        ("POST", "/v1/unified/recall"),
        ("GET", "/v1/unified/evidence/memory:m-1"),
        ("POST", "/v1/unified/corrections"),
        ("POST", "/v1/unified/sources/change"),
        ("POST", "/v1/unified/focus"),
        ("POST", "/v1/unified/intents"),
        ("POST", "/v1/unified/intents/int-9/transition"),
        ("POST", "/v1/unified/outcomes"),
        ("POST", "/v1/unified/feedback"),
        ("POST", "/v1/unified/applications"),
        ("POST", "/v1/unified/dependencies/check"),
        ("GET", "/v1/unified/status"),
        ("GET", "/v1/unified/records"),
        ("GET", "/v1/unified/records/memory:m-1"),
    ]
    observed: list = []
    client = make_client(route_table_handler(expected, observed))
    body = {"context": context()}

    async def case():
        await client.observe({"observations": []})
        await client.recall({"query": "x"})
        await client.evidence("memory:m-1")
        await client.correct(body)
        await client.source_changed(body)
        await client.update_focus(body)
        await client.create_intent(body)
        await client.transition_intent("int-9", body)
        await client.record_outcome(body)
        await client.apply_feedback(body)
        await client.record_application(body)
        await client.check_dependencies(body)
        await client.get_status()
        await client.list_records()
        await client.get_record("memory:m-1")
        await client.aclose()
    run(case())
    assert observed == expected


# ================================================================== unit：错误映射

def _status_handler(status_code: int, body: dict) -> httpx.Response:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)
    return handler


def test_501_maps_to_feature_not_ready_with_route():
    async def case():
        client = make_client(_status_handler(501, {
            "error": "FEATURE_NOT_READY", "message": "...",
            "route": "/v1/unified/corrections"}))
        with pytest.raises(FeatureNotReady) as excinfo:
            await client.correct({})
        assert excinfo.value.route == "/v1/unified/corrections"
        await client.aclose()
    run(case())


def test_409_maps_to_revision_conflict_preserving_code_and_detail():
    detail = {"source_event_id": "atlas:ATLAS_USER_MESSAGE:msg-1:1:UPSERT",
              "existing_content_hash": "sha256:aa", "incoming_content_hash": "sha256:bb"}
    async def case():
        client = make_client(_status_handler(409, {
            "error": "IDEMPOTENCY_CONFLICT", "message": "conflict", "details": detail}))
        with pytest.raises(RevisionConflict) as excinfo:
            await client.observe({"observations": []})
        assert excinfo.value.status_code == 409
        assert excinfo.value.code == "IDEMPOTENCY_CONFLICT"
        assert excinfo.value.detail == detail
        await client.aclose()
    run(case())


def test_423_maps_to_erasure_blocked():
    async def case():
        client = make_client(_status_handler(423, {
            "error": "ERASURE_BARRIER_ACTIVE", "message": "barrier",
            "details": {"source_event_id": "x"}}))
        with pytest.raises(ErasureBlocked):
            await client.observe({"observations": []})
        await client.aclose()
    run(case())


def test_403_maps_to_forbidden_subject():
    async def case():
        client = make_client(_status_handler(403, {
            "error": "FOREIGN_SUBJECT", "message": "mismatch",
            "details": {"configured": SUBJECT, "got": "foreign"}}))
        with pytest.raises(ForbiddenSubject) as excinfo:
            await client.recall({"query": "我是谁"})
        assert excinfo.value.code == "FOREIGN_SUBJECT"
        await client.aclose()
    run(case())


def test_422_maps_to_contract_violation():
    async def case():
        client = make_client(_status_handler(422, {
            "error": "CONTENT_HASH_MISMATCH", "message": "hash mismatch",
            "details": {"expected": "sha256:cc"}}))
        with pytest.raises(ContractViolation) as excinfo:
            await client.observe({"observations": []})
        assert excinfo.value.code == "CONTENT_HASH_MISMATCH"
        await client.aclose()
    run(case())


def test_timeout_maps_to_service_unavailable_not_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def case():
        client = make_client(handler)
        with pytest.raises(ServiceUnavailable):
            await client.recall({"query": "x"})
        with pytest.raises(ServiceUnavailable):
            await client.get_status()
        await client.aclose()
    run(case())


def test_connect_error_maps_to_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async def case():
        client = make_client(handler)
        with pytest.raises(ServiceUnavailable) as excinfo:
            await client.recall({"query": "x"})
        assert excinfo.value.route == "/v1/unified/recall"
        # observe 同样如实失败 —— 绝不吞成空列表 / None（01_contracts §8）
        with pytest.raises(ServiceUnavailable):
            await client.observe({"observations": []})
        await client.aclose()
    run(case())


def test_5xx_maps_to_service_unavailable():
    async def case():
        client = make_client(_status_handler(503, {"error": "X", "message": "down"}))
        with pytest.raises(ServiceUnavailable):
            await client.get_status()
        await client.aclose()
    run(case())


def test_observe_success_returns_ack_body():
    ack = {"accepted": 1, "created": 1, "duplicates": 0,
           "receipts": [{"source_event_id": "s", "event_id": "ev-1", "result": "CREATED"}],
           "watermarks": {"OBSERVATION_ACKED": {"event_count": 1}}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content)
        assert payload["contract_version"] == CONTRACT_VERSION
        return httpx.Response(201, json=ack)

    async def case():
        client = make_client(handler)
        result = await client.observe({"observations": []})
        assert result == ack
        await client.aclose()
    run(case())


# ================================================================== unit：静态与规则

def test_client_never_touches_sql_or_memoryos_packages():
    """客户端不执行 SQL、不 import MemoryOS 包 —— 源码静态断言（动态扫描自身）。"""
    import inspect

    for module in (__import__("atlas.memory.unified_client", fromlist=["x"]),
                   __import__("atlas.memory.unified_facade", fromlist=["x"])):
        source = inspect.getsource(module)
        for banned in ("aiosqlite", "sqlite3", "import storage", "import db",
                       "from db", "from service", "unified.repository",
                       "execute(", "executemany("):
            assert banned not in source, f"{module.__name__} 不应包含 {banned!r}"


def test_observation_content_hash_is_stable_and_typed():
    obs = {
        "source_event_id": "atlas:ATLAS_USER_MESSAGE:msg-1:1:UPSERT",
        "source_kind": "ATLAS_USER_MESSAGE", "source_object_id": "msg-1",
        "source_revision": "1", "event_action": "UPSERT",
        "occurred_at": "2026-10-06T09:00:00+08:00", "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN", "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": {"text": "哈希规则"}, "locator": None,
        "media_refs": [], "derived_from": [],
    }
    first = observation_content_hash(obs)
    second = observation_content_hash(dict(obs))
    assert first == second
    assert first.startswith("sha256:") and len(first) == len("sha256:") + 64
    # 内容变化 → 哈希变化；运输重试字段（recorded_at 等）不参与
    changed = dict(obs, content={"text": "变了"})
    assert observation_content_hash(changed) != first
    transport_only = dict(obs, recorded_at="2099-01-01T00:00:00+00:00")
    assert observation_content_hash(transport_only) == first


# ================================================================== unit：facade

def test_facade_reads_memory_unified_namespace_from_atlas_config():
    from atlas.config import AtlasConfig

    cfg = AtlasConfig({"memory": {"unified": {
        "enabled": True,
        "service_url": "http://127.0.0.1:8099",
        "subject_binding": "atlas-primary",
        "timeout_seconds": 3.5,
    }}})
    facade = UnifiedMemoryFacade(cfg)
    assert facade.enabled is True
    assert facade.service_url == "http://127.0.0.1:8099"
    assert facade.subject_binding == "atlas-primary"
    assert facade.timeout_seconds == 3.5
    ctx = facade.default_context(runtime_session_id="chat-1")
    assert ctx["memory_subject_id"] == "atlas-primary"
    assert set(ctx) == {"owner_id", "memory_subject_id", "client_id", "actor_id",
                        "runtime_session_id", "task_id", "project_id",
                        "environment_id", "model_deployment_id"}


def test_facade_disabled_reports_explicitly_and_observe_refuses():
    from atlas.config import AtlasConfig

    facade = UnifiedMemoryFacade(AtlasConfig({}))  # 无配置 → 默认 disabled
    assert facade.enabled is False
    result = run(facade.recall_for_conversation("anything"))
    assert result["enabled"] is False
    assert result["reason"] == "MEMORY_UNIFIED_DISABLED"
    with pytest.raises(ServiceUnavailable):
        run(facade.observe_batch({"observations": []}))


def test_facade_observe_batch_fills_missing_content_hash():
    from atlas.config import AtlasConfig

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"created": 1, "duplicates": 0,
                                         "receipts": [], "watermarks": {}})

    async def case():
        cfg = AtlasConfig({"memory": {"unified": {"enabled": True}}})
        facade = UnifiedMemoryFacade(cfg, client=make_client(handler))
        await facade.observe_batch({"event_class": "TEST", "observations": [{
            "source_event_id": "atlas:ATLAS_USER_MESSAGE:msg-h:1:UPSERT",
            "source_kind": "ATLAS_USER_MESSAGE", "source_object_id": "msg-h",
            "source_revision": "1", "event_action": "UPSERT",
            "occurred_at": "2026-10-06T09:00:00+08:00",
            "source_timezone": "Asia/Hong_Kong", "time_status": "KNOWN",
            "speaker_role": "USER", "epistemic_kind": "USER_ASSERTED",
            "content": {"text": "补哈希"}, "locator": None,
            "media_refs": [], "derived_from": [],
        }]})
        obs = seen["body"]["observations"][0]
        assert obs["content_hash"] == observation_content_hash(obs)
        await facade.aclose()
    run(case())


def test_facade_recall_for_conversation_shapes_lightweight_items():
    from atlas.config import AtlasConfig

    response = {
        "read_id": "read-1", "authority_revision": 7,
        "context_hash": "sha256:" + "a" * 64,
        "fallback_mode": "LOCAL_DETERMINISTIC", "trace_ref": "audit:aud-1",
        "context_items": [{
            "record_ref": "memory:m-1", "record_revision": 1, "facet": "PREFERENCE",
            "lifecycle": "ACTIVE", "epistemic_kind": "USER_ASSERTED",
            "content": {"summary": "偏好"}, "source_refs": [{"source_id": "s"}],
            "applicability": {"project_id": None},
            "valid_time": {"valid_from": None, "valid_to": None, "time_status": "UNKNOWN"},
            "extra_not_for_model": "secret-ish",
        }],
        "source_snippets": [], "conflicts": [],
        "missing_evidence": [{"record_ref": "memory:m-1", "reason": "NO_SOURCE_REFS"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/unified/recall"
        return httpx.Response(200, json=response)

    async def case():
        cfg = AtlasConfig({"memory": {"unified": {"enabled": True,
                                                  "subject_binding": SUBJECT}}})
        facade = UnifiedMemoryFacade(cfg, client=make_client(handler))
        shaped = await facade.recall_for_conversation("偏好", budget={"max_records": 3})
        assert shaped["enabled"] is True
        assert shaped["read_id"] == "read-1"
        assert shaped["context_hash"].startswith("sha256:")
        item = shaped["context_items"][0]
        assert item["record_ref"] == "memory:m-1" and item["revision"] == 1
        assert item["epistemic_kind"] == "USER_ASSERTED"
        assert item["source_refs"]
        assert "extra_not_for_model" not in item
        assert shaped["missing_evidence"]
        await facade.aclose()
    run(case())


# ================================================================== integration

def _client_for(harness: UMHarness) -> UnifiedMemoryClient:
    return UnifiedMemoryClient(service_url=harness.memoryos_url,
                               internal_token=TEST_INTERNAL_TOKEN, timeout=10.0)


def _observation(seid: str, text: str) -> dict:
    parts = seid.split(":")
    obs = {
        "source_event_id": seid, "source_kind": "ATLAS_USER_MESSAGE",
        "source_object_id": parts[2], "source_revision": parts[3],
        "event_action": parts[4], "occurred_at": "2026-10-06T09:00:00+08:00",
        "source_timezone": "Asia/Hong_Kong", "time_status": "KNOWN",
        "speaker_role": "USER", "epistemic_kind": "USER_ASSERTED",
        "content": {"text": text}, "locator": {"kind": "MESSAGE", "value": parts[2]},
        "media_refs": [], "derived_from": [],
    }
    obs["content_hash"] = observation_content_hash(obs)
    return obs


@pytest.mark.integration
def test_foreign_subject_is_rejected(um: UMHarness):
    """任务书判据原样：foreign subject 必须被真实服务拒绝（403）。"""
    r = um.api("POST", "/v1/unified/recall",
               json={"context": {"memory_subject_id": "foreign"}, "query": "我是谁"})
    assert r.status_code == 403
    # 客户端同一判据
    client = _client_for(um)

    async def case():
        with pytest.raises(ForbiddenSubject):
            await client.recall({"context": context(memory_subject_id="foreign"),
                                 "query": "我是谁"})
        await client.aclose()
    run(case())


@pytest.mark.integration
def test_client_roundtrip_observe_recall_status_against_real_services(um: UMHarness):
    client = _client_for(um)
    tag = "cli" + uuid.uuid4().hex[:8]
    ctx = context(runtime_session_id=f"chat-{tag}")

    async def case():
        batch = {
            "contract_version": CONTRACT_VERSION,
            "event_class": "TEST",
            "context": ctx,
            "observations": [_observation(
                f"atlas:ATLAS_USER_MESSAGE:cli-{tag}:1:UPSERT",
                f"客户端回路夹具{tag} 晚上不要安排工作")],
        }
        ack = await client.observe(batch)
        assert ack["created"] == 1 and ack["accepted"] == 1
        assert ack["watermarks"]["OBSERVATION_ACKED"]["wired"] is True

        replay = await client.observe(batch)
        assert replay["created"] == 0 and replay["duplicates"] >= 1

        result = await client.recall({
            "context": ctx, "query": f"客户端回路夹具 {tag} 晚上安排工作"})
        assert result["read_id"] and result["context_hash"].startswith("sha256:")
        assert result["fallback_mode"] == "LOCAL_DETERMINISTIC"
        assert any(tag in str(item) for item in result["context_items"]), \
            "recall 必须命中 observe 过的记录"

        status = await client.get_status()
        assert status["wired"]["observe"] is True and status["wired"]["recall"] is True

        records = await client.list_records(facet="EPISODE")
        assert any(tag in str(item) for item in records["items"])
        await client.aclose()
    run(case())


@pytest.mark.integration
def test_service_down_raises_and_no_local_fallback_write(um: UMHarness):
    """断连负例：服务停机 → ServiceUnavailable，且**没有旧事实库 fallback 写入**。"""

    def db_snapshot(root: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for pattern in ("*.db", "*.sqlite*", "*.sqlite3-*"):
            for path in root.rglob(pattern):
                try:
                    stat = path.stat()
                    snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    continue
        return snapshot

    atlas_before = db_snapshot(Path(um.atlas_data))
    memoryos_before = db_snapshot(Path(um.memoryos_data))

    client = _client_for(um)
    try:
        um.fault("service_down", True)

        async def case():
            with pytest.raises(ServiceUnavailable):
                await client.recall({"context": context(), "query": "断连也要如实失败"})
            with pytest.raises(ServiceUnavailable):
                await client.observe({"context": context(), "observations": []})
            # 显式确认没有任何本地写库 fallback：客户端与 facade 都不落库
            from atlas.config import AtlasConfig

            facade = UnifiedMemoryFacade(
                AtlasConfig({"memory": {"unified": {
                    "enabled": True, "service_url": um.memoryos_url,
                    "internal_token": TEST_INTERNAL_TOKEN}}}),
                client=client)
            with pytest.raises(ServiceUnavailable):
                await facade.recall_for_conversation("也不许静默成功")
            await client.aclose()
        run(case())

        atlas_after = db_snapshot(Path(um.atlas_data))
        memoryos_after = db_snapshot(Path(um.memoryos_data))
        assert set(atlas_after) == set(atlas_before), "Atlas 数据目录出现新库文件"
        assert atlas_after == atlas_before, "Atlas 既有库文件被 fallback 写入"
        assert set(memoryos_after) == set(memoryos_before)
        assert memoryos_after == memoryos_before
        # 无任何新 sqlite（WAL/SHM 亦不允许）
        for path in Path(um.atlas_data).rglob("*"):
            if path.is_file() and path.suffix in {".sqlite", ".db", ".sqlite3",
                                                  ".wal", ".shm"}:
                assert str(path) in atlas_before, f"意外的新库文件: {path}"
    finally:
        um.fault("service_up", True)  # 恢复真实服务，供后续测试使用


@pytest.mark.integration
def test_conflicting_retry_surfaces_revision_conflict_via_client(um: UMHarness):
    client = _client_for(um)
    tag = uuid.uuid4().hex[:8]

    async def case():
        seid = f"atlas:ATLAS_USER_MESSAGE:cli-conf-{tag}:1:UPSERT"
        batch = {"contract_version": CONTRACT_VERSION, "event_class": "TEST",
                 "context": context(runtime_session_id=f"chat-{tag}"),
                 "observations": [_observation(seid, "原始内容")]}
        ack = await client.observe(batch)
        assert ack["created"] == 1

        changed = _observation(seid, "没有新版本就改内容")
        with pytest.raises(RevisionConflict) as excinfo:
            await client.observe({"context": batch["context"],
                                  "event_class": "TEST",
                                  "observations": [changed]})
        assert excinfo.value.code == "IDEMPOTENCY_CONFLICT"
        assert excinfo.value.detail.get("source_event_id") == seid
        await client.aclose()
    run(case())
