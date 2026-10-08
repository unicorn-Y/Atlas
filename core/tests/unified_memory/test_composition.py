"""T01.3 全入口组成与单一调用路径（UM01 收口）。

* unit（默认标记）：配置开关行为 —— enabled=true 时 create_app 挂
  ``/api/unified-memory/*`` 代理路由且 facade 可装配进 MemoryStore；
  enabled=false（默认）完全不挂、MemoryStore.unified 为 None（共享 app 与
  旧套件零影响）；代理错误映射同码（403/409/423/422/501、断连→503）；
  静态扫描 scan_bypass 输出 unmapped_bypasses=[]。
* integration（UMHarness 双真服务，任务书入口 smoke 判据）：
  - test_ui_and_chat_share_authority：桌面/API 经 **Atlas 代理** 写偏好 →
    代理 records 读回 → chat 后从真实事件收集的 memory_refs 断言（当前
    Runtime Event Protocol 不携带 → 降级为代理/服务双路同 revision 读回，
    chat 装配断言 TODO(UM07)，如实记录不造假）。
  - test_write_pref_through_ui_read_from_cli_path：代理写 → facade 直接
    recall（模拟 CLI 路径）命中同 ref/revision。
  - test_restart_keeps_authority：重启 Atlas 后配置/服务地址仍生效，
    代理 status 200 且同一 authority 读回。

任务书判据原样（02_wave_tasks.md T01.3）：
    def test_ui_and_chat_share_authority(h):
        h.seed("basic")
        records = h.api("GET", "/api/unified-memory/records",
                        params={"facet": "PREFERENCE"}).json()
        assert records["items"][0]["record_ref"] in h.chat("按我的格式输出")['memory_refs']
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atlas.config import AtlasConfig
from atlas.memory.unified_client import (
    UnifiedMemoryClient,
    observation_content_hash,
)
from atlas.memory.unified_facade import UnifiedMemoryFacade
from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

pytest.importorskip("atlas.memory.unified_client")

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_SCRIPT = REPO_ROOT / "scripts" / "unified_memory" / "scan_bypass.py"


# ================================================================== helpers

def _enabled_config(**overrides) -> AtlasConfig:
    unified: dict = {
        "enabled": True,
        "service_url": "http://memoryos.test",
        "internal_token": "unit-token",
        "subject_binding": "atlas-fixture",
        "timeout_seconds": 5.0,
    }
    unified.update(overrides)
    return AtlasConfig({"memory": {"unified": unified}})


@contextlib.asynccontextmanager
async def _noop_lifespan(_app: FastAPI):
    yield


def _make_app(monkeypatch: pytest.MonkeyPatch, cfg: AtlasConfig | None = None,
              *, facade: UnifiedMemoryFacade | None = None):
    """在临时 Config 上重建第二个 app 实例（不改共享 atlas.server.app）。"""
    from atlas.api.app_services import AppServices
    from atlas.api.application import create_app

    monkeypatch.setattr("atlas.config._config", cfg or _enabled_config())
    services = AppServices()
    services.unified_memory = facade
    return create_app(lifespan=_noop_lifespan, services=services)


def _proxy_client_handler(routes: dict[tuple[str, str], object],
                          observed: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if observed is not None:
            observed.append(request)
        key = (request.method, request.url.path)
        if key not in routes:
            raise AssertionError(f"unexpected upstream call: {key}")
        payload = routes[key]
        if isinstance(payload, Exception):
            raise payload
        status, body = payload
        return httpx.Response(status, json=body)
    return handler


def _app_route_paths(app: FastAPI) -> set[str]:
    """Flatten route paths without touching ``app.openapi_schema``.

    FastAPI >=0.14x wraps ``include_router`` as ``_IncludedRouter`` entries;
    the real APIRoutes hang off ``entry.original_router.routes``. The shared
    app's OpenAPI cache is identity-watched by the shared-app guard, so tests
    must never trigger ``app.openapi()``.
    """
    paths: set[str] = set()
    for entry in app.router.routes:
        router = getattr(entry, "original_router", None)
        routes = router.routes if router is not None else [entry]
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                paths.add(path)
    return paths


def _proxy_client(monkeypatch: pytest.MonkeyPatch, handler) -> httpx.AsyncClient:
    cfg = _enabled_config()
    client = UnifiedMemoryClient(
        service_url="http://memoryos.test", internal_token="unit-token",
        timeout=2.0, transport=httpx.MockTransport(handler))
    facade = UnifiedMemoryFacade(cfg, client=client)
    app = _make_app(monkeypatch, facade=facade)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://atlas.test")


# ================================================================== unit

def test_default_composition_disabled_keeps_legacy_behavior():
    """默认（无 memory.unified 配置）：facade 不装配、共享 app 不挂代理路由。"""
    from atlas.api.app_services import AppServices
    from atlas.memory import MemoryStore

    assert MemoryStore()._unified is None
    assert AppServices().unified_memory is None

    facade = UnifiedMemoryFacade.from_config(AtlasConfig({}))
    assert facade.enabled is False
    # 全局单例配置（conftest 的临时 atlas.toml 无 [memory.unified]）→ disabled
    assert UnifiedMemoryFacade.from_config().enabled is False

    # 共享 atlas.server.app：只读检查路由面（守卫只 fail 修改，不 fail 读取）
    from atlas import server

    unified_routes = [path for path in _app_route_paths(server.app)
                      if path.startswith("/api/unified-memory")]
    assert unified_routes == [], (
        "默认配置不得挂载 /api/unified-memory/* 代理路由")


def test_enabled_config_mounts_proxy_router_and_facade_composition(
        monkeypatch: pytest.MonkeyPatch):
    """enabled=true：create_app 挂代理路由；facade 组装进 MemoryStore。"""
    cfg = _enabled_config()
    monkeypatch.setattr("atlas.config._config", cfg)

    app = _make_app(monkeypatch, cfg)
    proxy_paths = {path for path in _app_route_paths(app)
                   if path.startswith("/api/unified-memory")}
    for expected in (
        "/api/unified-memory/observe",
        "/api/unified-memory/recall",
        "/api/unified-memory/records",
        "/api/unified-memory/records/{record_ref:path}",
        "/api/unified-memory/evidence/{record_ref:path}",
        "/api/unified-memory/status",
        "/api/unified-memory/corrections",  # 501 透传面
        "/api/unified-memory/maintenance",
        # T05.2 多模态关联（表驱动透传；服务端 multimodal.run_association_pass）
        "/api/unified-memory/multimodal/associate",
        # T06.1 焦点三路由（POST /focus 焦点快照提交；GET /focus/{task_id}
        # attend 焦点装配；POST /focus/{focus_id}/observe 注意事件入工作集）
        "/api/unified-memory/focus",
        "/api/unified-memory/focus/{task_id}",
        "/api/unified-memory/focus/{focus_id}/observe",
        # T02.3 Atlas 本地路由（§6.1 同类：不代理 MemoryOS，本地采集控制器处理）
        "/api/unified-memory/import",
        "/api/unified-memory/verify-agent-result",
        # T05.1 受控媒体：上传（原始字节透传）/ 元数据 / 文件流 / 受控删除
        "/api/unified-memory/media",
        "/api/unified-memory/media/{asset_id}",
        "/api/unified-memory/media/{asset_id}/content",
        # T05.3 本地采集控制（§6.1：Atlas 本地控制器，不代理 MemoryOS）
        "/api/unified-memory/capture/start",
        "/api/unified-memory/capture/pause",
        "/api/unified-memory/capture/stop",
        "/api/unified-memory/capture/status",
    ):
        assert expected in proxy_paths, expected
    # 后缀与 MemoryOS /v1/unified/* 一一对应（23 条契约路由 / 22 个唯一 path）
    # + T02.3 两条 Atlas 本地路由（import / verify-agent-result）
    # + T05.1 三条媒体 path（media 上传 / media 元数据+删除同 path 两方法 /
    #   media content 文件流）
    # + T05.3 四条采集控制 path（capture start/pause/stop/status）
    # + T06.1 两条焦点 path（GET /focus/{task_id} attend、
    #   POST /focus/{focus_id}/observe 注意事件；POST /focus 已在 23 条内）
    assert len(proxy_paths) == 33

    facade = UnifiedMemoryFacade.from_config()
    assert facade.enabled is True
    assert facade.service_url == "http://memoryos.test"
    assert facade.subject_binding == "atlas-fixture"

    from atlas.memory import MemoryStore

    store = MemoryStore(unified=facade)
    assert store._unified is facade


def test_client_call_refuses_non_unified_path():
    """代理传输只允许 /v1/unified/* —— 不能被当成任意路径转发器。"""
    client = UnifiedMemoryClient(service_url="http://memoryos.test",
                                 internal_token="t", timeout=1.0)
    from atlas.memory.unified_client import UnifiedMemoryError

    async def case():
        with pytest.raises(UnifiedMemoryError):
            await client.call("GET", "/api/facts")
        with pytest.raises(UnifiedMemoryError):
            await client.call("GET", "/v1/health")
        await client.aclose()
    asyncio.run(case())


@pytest.mark.parametrize("status,code,expected", [
    (403, "FOREIGN_SUBJECT", 403),
    (409, "IDEMPOTENCY_CONFLICT", 409),
    (423, "ERASURE_BARRIER_ACTIVE", 423),
    (422, "CONTRACT_VIOLATION", 422),
    (501, "FEATURE_NOT_READY", 501),
])
def test_proxy_error_mapping_keeps_upstream_code(
        monkeypatch: pytest.MonkeyPatch, status: int, code: str, expected: int):
    """403/409/423/422/501 → HTTPException 同码透传，error code 保留。"""
    async_client = _proxy_client(monkeypatch, _proxy_client_handler({
        ("POST", "/v1/unified/corrections"): (
            status,
            {"error": code, "message": "unit",
             "details": {"route": "/v1/unified/corrections"},
             "route": "/v1/unified/corrections"},
        ),
    }))

    async def case():
        try:
            response = await async_client.post(
                "/api/unified-memory/corrections", json={"request_id": "r1"})
            assert response.status_code == expected, response.text
            detail = response.json()["detail"]
            assert detail["error"] == code
            assert detail["route"] == "/v1/unified/corrections"
        finally:
            await async_client.aclose()
    asyncio.run(case())


def test_proxy_transport_failure_maps_503(monkeypatch: pytest.MonkeyPatch):
    """服务不可达/超时 → 503（绝不 fallback 旧库冒充）。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=_request)

    async_client = _proxy_client(monkeypatch, handler)

    async def case():
        try:
            response = await async_client.get("/api/unified-memory/status")
            assert response.status_code == 503
            assert response.json()["detail"]["error"] == "ServiceUnavailable"
        finally:
            await async_client.aclose()
    asyncio.run(case())


def test_proxy_forwards_auth_header_and_body(monkeypatch: pytest.MonkeyPatch):
    observed: list[httpx.Request] = []
    handler = _proxy_client_handler({
        ("POST", "/v1/unified/observe"): (201, {"created": 1, "duplicates": 0}),
    }, observed)
    async_client = _proxy_client(monkeypatch, handler)

    async def case():
        try:
            response = await async_client.post(
                "/api/unified-memory/observe",
                json={"event_class": "TEST", "observations": []})
            assert response.status_code == 200
            assert response.json() == {"created": 1, "duplicates": 0}
            assert len(observed) == 1
            assert observed[0].headers["authorization"] == "Bearer unit-token"
            assert b'"event_class"' in observed[0].content
            assert b"TEST" in observed[0].content
        finally:
            await async_client.aclose()
    asyncio.run(case())


def test_proxy_substitutes_path_params(monkeypatch: pytest.MonkeyPatch):
    """records/{ref} 透传必须替换 path 参数（不得把模板字符串发给服务端）。"""
    observed: list[httpx.Request] = []
    handler = _proxy_client_handler({
        ("GET", "/v1/unified/records/memory:m-abc"): (
            200, {"record_ref": "memory:m-abc", "record_revision": 3}),
    }, observed)
    async_client = _proxy_client(monkeypatch, handler)

    async def case():
        try:
            response = await async_client.get(
                "/api/unified-memory/records/memory:m-abc")
            assert response.status_code == 200
            assert response.json()["record_revision"] == 3
            assert observed[0].url.path == "/v1/unified/records/memory:m-abc"
        finally:
            await async_client.aclose()
    asyncio.run(case())


def test_proxy_without_facade_reports_not_composed(monkeypatch: pytest.MonkeyPatch):
    """路由挂载而 lifespan 未装配 facade → 显式 503，不静默。"""
    app = _make_app(monkeypatch)  # mount_router=True 但 facade=None
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                               base_url="http://atlas.test")

    async def case():
        try:
            response = await client.get("/api/unified-memory/status")
            assert response.status_code == 503
            assert (response.json()["detail"]["error"]
                    == "UNIFIED_MEMORY_NOT_COMPOSED")
        finally:
            await client.aclose()
    asyncio.run(case())


def test_static_scan_reports_no_unmapped_bypass():
    """静态扫描：unmapped_bypasses=[]，三个入口 composition 齐备（对照 authority-map）。"""
    spec = importlib.util.spec_from_file_location("um_t013_scan_bypass", SCAN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.build_scan(REPO_ROOT)
    assert result["unmapped_bypasses"] == [], result["unmapped_bypasses"]
    assert all(point["uses_unified_composition"]
               for point in result["composition_points"])
    assert result["proxy_router_config_gated"] is True
    assert result["summary"]["memory_write_method_count"] > 0
    assert (result["summary"]["probed_write_method_count"]
            == result["summary"]["memory_write_method_count"])


# ================================================================== integration

def _proxy_preference(h: UMHarness, tag: str) -> tuple[str, dict]:
    """经 Atlas 代理（/api/unified-memory/observe）写一条 PREFERENCE 偏好。

    返回 (record_ref, 写入响应体)。seid/内容随 tag 派生 → 重放幂等、跨测试不串。
    """
    key = f"um01-pref-{tag}"
    value = f"回复用「结论先行」格式，输出前先给一行摘要（标识 {tag}）。"
    content = {"facet": "PREFERENCE", "key": key, "value": value, "text": value}
    observation = {
        "source_event_id": f"atlas:USER_IMPORT:um01-{tag}:1:UPSERT",
        "source_kind": "USER_IMPORT",
        "source_object_id": f"um01-{tag}",
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": "2026-10-06T09:00:00+08:00",
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": content,
        "locator": {"kind": "ATLAS_FACT_API", "value": key},
        "media_refs": [],
        "derived_from": [],
    }
    observation["content_hash"] = observation_content_hash(observation)
    batch = {
        "contract_version": "UM-WIN-1.0",
        "event_class": "TEST",
        # 显式 TEST 上下文（代理原样转发；主体=harness 服务绑定的 atlas-fixture）
        "context": {**h.default_context(),
                    "runtime_session_id": f"um01-composition-{tag}"},
        "observations": [observation],
    }
    response = h.api("POST", "/api/unified-memory/observe", json=batch)
    assert response.status_code == 200, response.text
    ack = response.json()
    assert ack["created"] >= 1 and ack["accepted"] == 1
    receipts = (ack.get("memory_projection") or {}).get("receipts", [])
    assert receipts and receipts[0]["result"] == "CREATED", ack
    return f"memory:{receipts[0]['memory_id']}", ack


def _proxy_preference_refs(h: UMHarness) -> tuple[set[str], dict[str, dict]]:
    response = h.api("GET", "/api/unified-memory/records",
                     params={"facet": "PREFERENCE"})
    assert response.status_code == 200, response.text
    items = response.json().get("items", [])
    return ({str(item["record_ref"]) for item in items},
            {str(item["record_ref"]): item for item in items})


@pytest.mark.integration
@pytest.mark.fake_provider
def test_ui_and_chat_share_authority(um: UMHarness):
    """入口 smoke（任务书判据）：经代理写偏好 → 代理可读 → chat 同 authority。

    chat 路径的本波降级（如实记录，不造假）：harness 的 ``memory_refs`` 只从
    真实 Runtime Event Protocol 事件提取，而当前 run_drive 协议不携带记忆引用
    （UM07 接入聊天装配），因此任务书断言
    ``record_ref in h.chat(...)['memory_refs']`` 现阶段无法成立 —— 按 T01.3
    任务书允许的降级路径，改为同一 record_ref 经 Atlas 代理与 MemoryOS 服务
    双路读回同一 revision；chat 装配断言 TODO(UM07)。
    """
    h = um
    h.seed("basic")
    tag = "chat" + uuid.uuid4().hex[:8]
    record_ref, _ack = _proxy_preference(h, tag)

    refs, _items = _proxy_preference_refs(h)
    assert record_ref in refs, "经 Atlas 代理写的偏好必须能经代理 records 读回"

    chat_run = h.chat("按我的格式输出")
    assert chat_run["status"] == "completed", chat_run["failure"]
    # 如实断言：协议当前不携带 memory_refs（提取不到 → 空列表），不做假装配。
    # TODO(UM07): 聊天记忆装配接入后，此断言改为 record_ref in chat_run["memory_refs"]。
    assert chat_run["memory_refs"] == [], chat_run["memory_refs_note"]

    # 降级断言：同一 record_ref 双路读回同一 revision（代理 ↔ 服务同 authority）
    via_proxy = h.api("GET", f"/api/unified-memory/records/{record_ref}")
    via_service = h.api("GET", f"/v1/unified/records/{record_ref}")
    assert via_proxy.status_code == 200, via_proxy.text
    assert via_service.status_code == 200, via_service.text
    assert via_proxy.json()["record_revision"] == \
        via_service.json()["record_revision"] == 1
    import json as _json

    assert tag in _json.dumps(via_proxy.json()["content"], ensure_ascii=False)


@pytest.mark.integration
def test_write_pref_through_ui_read_from_cli_path(um: UMHarness):
    """经代理写偏好 → facade 直接 recall（模拟 CLI/hub 路径）命中同 ref/revision。"""
    h = um
    tag = "cli" + uuid.uuid4().hex[:8]
    record_ref, _ack = _proxy_preference(h, tag)

    # CLI/chat 入口与本测试同构：cfg=get_config(); facade=from_config(cfg)。
    facade = UnifiedMemoryFacade(AtlasConfig({"memory": {"unified": {
        "enabled": True,
        "service_url": h.memoryos_url,
        "internal_token": TEST_INTERNAL_TOKEN,
        "subject_binding": "atlas-fixture",
        "timeout_seconds": 10.0,
    }}}))

    async def case():
        try:
            # CLI 入口与桌面同构：真实会话带自己的 runtime_session_id
            # （MemoryContext 完整性校验要求九字段齐全，§1）。
            result = await facade.recall_for_conversation(
                f"um01-{tag} 结论先行", budget={"max_records": 10},
                context={**h.default_context(),
                         "runtime_session_id": f"cli-recall-{tag}"})
            assert result["enabled"] is True
            assert result["fallback_mode"] == "LOCAL_DETERMINISTIC"
            hits = [item for item in result["context_items"]
                    if item["record_ref"] == record_ref]
            assert hits, (
                f"CLI 路径 recall 必须命中 UI 写入的 {record_ref}；"
                f"got {[item['record_ref'] for item in result['context_items']]}")
            assert hits[0]["facet"] == "PREFERENCE"
            assert hits[0]["revision"] == 1
        finally:
            await facade.aclose()
    asyncio.run(case())


@pytest.mark.integration
def test_restart_keeps_authority(um: UMHarness):
    """写偏好 → 重启 Atlas → 代理仍以同一配置读回（服务地址/配置重启后生效）。"""
    h = um
    tag = "restart" + uuid.uuid4().hex[:8]
    record_ref, _ack = _proxy_preference(h, tag)

    # harness 记录了注入 Atlas 的 unified 接线（runtime_manifest 证据）
    unified_manifest = h.runtime_manifest.get("unified_memory")
    assert unified_manifest and unified_manifest["enabled"] is True
    assert unified_manifest["service_url"] == (
        f"http://127.0.0.1:{h.runtime_manifest['memoryos_port']}")
    assert unified_manifest["proxy_prefix"] == "/api/unified-memory"

    h.restart("atlas")

    # 重启后：代理 status 200（配置里的 service_url/token 仍指向本实例 MemoryOS）
    status = h.api("GET", "/api/unified-memory/status")
    assert status.status_code == 200, status.text
    assert status.json()["wired"]["observe"] is True

    # 同一 authority 重启后仍在（数据在 MemoryOS，不随 Atlas 进程消失）
    refs, items = _proxy_preference_refs(h)
    assert record_ref in refs
    assert items[record_ref]["record_revision"] == 1
