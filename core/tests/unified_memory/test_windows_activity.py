"""T05.3 验收测试：Atlas 电脑/浏览器活动和记录控制（unified-memory/waves UM05）。

判据（02_wave_tasks.md T05.3 + 01_contracts.md §6.1）：
  * unit：PassiveCaptureController 状态机 STOPPED→RUNNING→PAUSED→STOPPED
    （revision 受控迁移递增、request_id 幂等重放、expected_revision 不符 409、
    request_id 复用 409）；授权 sources 校验（无全系统种类、现有隐私门
    computer_use.permission_mode=deny 拒绝桌面观察，config_refs 只记引用，
    不建新 settings 文件）；watermark 只在被动观察真实入队后前进、stop 后冻结、
    进程重启不回退；x2 收据捕获（观察/点击请求/实际结果三类分开、截图经受控
    媒体只引用 asset_id 不塞 base64、同帧去重）。
  * integration（um harness + ATLAS_X2_COMPUTER_FAKE=1 的真实双子服务）：
    - 判据 test_stop_capture_stops_new_observations 原样语义：seed
      windows_activity → capture/stop → 被动水位不再前进。**注释：这只限制
      主动开启的被动采集器；普通工具截图仍正常记入工具经历** —— 反向断言
      证明 stop 后 h.tool 截图类工具照常产生 TOOL 观察。
    - 状态机走真实 HTTP（start 幂等/409/pause/stop/start 重入水位不回退）；
      pause/stop 不影响聊天（h.chat 照常产生 USER 观察）。
    - 截图 receipt capture：h.tool 截图类工具 → 服务端出现带 asset_id 的 TOOL
      观察，且 asset_id 可回查 T05.1 媒体元数据。

测试环境约束（如实偏差）：真实窗口截图在 CI/无人值守下不可依赖 —— 集成用例
统一用 harness 的 fake 工具路径（ATLAS_X2_COMPUTER_FAKE=1，确定性假帧）驱动
receipt capture；真 Windows 桌面的窗口操作冒烟（选择窗口/采集/暂停/停止/回看）
留 UM12 桌面证据。当前 Atlas 无后台连续截屏/标题轮询能力，被动入口只记录选择
范围内真实到达的 x2 工具收据（controller/status.collector 如实标注
PARTIAL_NOT_IMPLEMENTED，不假装在录）。

运行（Atlas core 解释器）：
  cd /d/Atlas && core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \\
      -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
from typing import Any

import pytest

from atlas.memory.capture import CaptureService
from atlas.memory.outbox import OperationalOutbox
from atlas.memory.windows_sources import (
    CAPTURE_STATE_PAUSED,
    CAPTURE_STATE_RUNNING,
    CAPTURE_STATE_STOPPED,
    CaptureControlError,
    PassiveCaptureController,
    WindowsSourceService,
    capture_watermarks,
)
from tests.unified_memory.harness import EVENT_CLASS, UMHarness


# ------------------------------------------------------------------ 夹具


@pytest.fixture(autouse=True)
def _reset_singletons():
    """单例隔离：进程级 CaptureService / 被动采集控制器逐用例复位。"""
    from atlas.memory.capture import reset_capture_service
    from atlas.memory.windows_sources import reset_passive_capture_controller

    reset_capture_service()
    reset_passive_capture_controller()
    yield
    reset_capture_service()
    reset_passive_capture_controller()


def _png_data_url(pixel: int) -> str:
    """确定性单色 PNG 的 data URL（两帧不同像素 → 不同内容寻址）。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (pixel, pixel, pixel)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class _FakeFacade:
    """flush/媒体测试替身：ingest_media 按 hash 去重；observe_batch 只记录。"""

    def __init__(self, *, fail_media: bool = False) -> None:
        self.batches: list[dict[str, Any]] = []
        self.fail_media = fail_media
        self._assets: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def default_context(self, **overrides: Any) -> dict[str, Any]:
        context = {
            "owner_id": "owner-fixture", "memory_subject_id": "atlas-fixture",
            "client_id": "atlas-desktop", "actor_id": "atlas-main",
            "runtime_session_id": "", "task_id": None, "project_id": None,
            "environment_id": "windows-fixture", "model_deployment_id": None,
        }
        context.update(overrides)
        return context

    def client(self) -> "_FakeFacade":
        """CaptureService.facade.client() 契约：媒体方法在本对象上。"""
        return self

    async def observe_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        self.batches.append(batch)
        return {"created": len(batch["observations"]), "duplicates": 0, "receipts": []}

    async def ingest_media(self, *, data: bytes, mime: str,
                           duration_ms: int | None = None, width: int | None = None,
                           height: int | None = None) -> dict[str, Any]:
        if self.fail_media:
            raise RuntimeError("memoryos media channel down for test")
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        existing = self._assets.get(digest)
        if existing is not None:
            return {"assets": [{**existing, "duplicate": True}], "duplicates": 1}
        self._counter += 1
        asset = {"asset_id": f"asset-{self._counter:04d}",
                 "content_hash": f"sha256:{digest}", "mime": mime,
                 "relative_path": f"media/{digest[:12]}.bin"}
        self._assets[digest] = asset
        return {"assets": [dict(asset)], "duplicates": 0}


def _service(tmp_path: Any, facade: Any,
             controller: PassiveCaptureController | None = None,
             ) -> WindowsSourceService:
    capture = CaptureService(facade=facade,
                             outbox_path=tmp_path / "unified_outbox.sqlite3",
                             event_class=EVENT_CLASS)
    return WindowsSourceService(
        capture=capture, registry_path=tmp_path / "import_sources.json",
        passive_controller=controller or PassiveCaptureController(
            state_path=tmp_path / "passive_capture_state.json"))


def _outbox_observations(tmp_path: Any) -> list[dict[str, Any]]:
    outbox = OperationalOutbox(tmp_path / "unified_outbox.sqlite3")
    try:
        return [row["payload"]["observation"] for row in outbox.poll_pending(200)]
    finally:
        outbox.close()


def _png_payload(data_url: str) -> str:
    """data URL 的 base64 载荷（断言观察正文不携带原始帧字节）。"""
    return data_url.partition(",")[2]


def _start_running(controller: PassiveCaptureController, request_id: str = "r-start",
                   sources: list[Any] | None = None) -> dict[str, Any]:
    return controller.start(
        request_id, sources if sources is not None else [{"kind": "screen", "value": "*"}])


class _DenyConfig(dict):
    def __getattr__(self, name: str) -> Any:
        if name == "computer_use_permission_mode":
            return "deny"
        raise AttributeError(name)


class _FullAccessConfig(dict):
    def __getattr__(self, name: str) -> Any:
        if name == "computer_use_permission_mode":
            return "full_access"
        raise AttributeError(name)


# ------------------------------------------------------------------ unit：状态机


@pytest.mark.unit
def test_capture_state_machine_transitions_and_revisions(tmp_path) -> None:
    """STOPPED→RUNNING→PAUSED→STOPPED→RUNNING：revision 只在受控迁移时递增。"""
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    assert controller.status()["state"] == CAPTURE_STATE_STOPPED
    assert controller.status()["revision"] == 0
    assert controller.status()["passive_capture_watermark"] == 0

    with pytest.raises(CaptureControlError) as not_running:
        controller.pause("r-pause-0")
    assert not_running.value.code == "NOT_RUNNING"
    assert not_running.value.http_status == 409

    started = _start_running(controller, "r-start-1")
    assert started["state"] == CAPTURE_STATE_RUNNING
    assert started["revision"] == 1
    assert started["sources"] == [{"kind": "screen", "value": "*"}]

    with pytest.raises(CaptureControlError) as already:
        _start_running(controller, "r-start-2")
    assert already.value.code == "ALREADY_RUNNING"

    paused = controller.pause("r-pause-1")
    assert paused["state"] == CAPTURE_STATE_PAUSED
    assert paused["revision"] == 2
    assert paused["drained"] is True

    stopped = controller.stop("r-stop-1", expected_revision=2)
    assert stopped["state"] == CAPTURE_STATE_STOPPED
    assert stopped["revision"] == 3

    again = controller.stop("r-stop-2")
    assert again["already_stopped"] is True
    assert again["revision"] == 3  # 重复 stop 不推进 revision

    resumed = controller.start("r-start-3", [{"kind": "window", "value": "VS Code"}],
                               expected_revision=3)
    assert resumed["state"] == CAPTURE_STATE_RUNNING
    assert resumed["revision"] == 4
    assert resumed["sources"] == [{"kind": "window", "value": "VS Code"}]
    assert controller.status()["passive_capture_watermark"] == 0


@pytest.mark.unit
def test_capture_request_id_idempotent_replay_and_reuse_conflict(tmp_path) -> None:
    """同 request_id 重放幂等（不推进 revision）；同 ID 换动作 → 409。"""
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    first = _start_running(controller, "same-request")
    replay = _start_running(controller, "same-request")
    assert replay == first
    assert controller.status()["revision"] == 1

    with pytest.raises(CaptureControlError) as reused:
        controller.stop("same-request")
    assert reused.value.code == "REQUEST_ID_REUSED"
    assert reused.value.http_status == 409

    # pause 同 ID 亦复用冲突；stop 新 ID 正常迁移后，同 ID 重放返回同一快照。
    stopped = controller.stop("stop-1")
    assert controller.stop("stop-1") == stopped
    assert controller.status()["revision"] == 2


@pytest.mark.unit
def test_capture_expected_revision_conflict(tmp_path) -> None:
    """expected_revision 与当前 revision 不符 → 409；非法值 → 422。"""
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1")  # revision 1
    with pytest.raises(CaptureControlError) as conflict:
        controller.pause("r2", expected_revision=99)
    assert conflict.value.code == "REVISION_CONFLICT"
    assert conflict.value.http_status == 409
    assert conflict.value.details["current_revision"] == 1
    with pytest.raises(CaptureControlError) as invalid:
        controller.pause("r3", expected_revision="not-a-number")
    assert invalid.value.code == "INVALID_EXPECTED_REVISION"
    assert invalid.value.http_status == 422
    # 客户端按 status 对齐版本后迁移成功。
    paused = controller.pause("r4", expected_revision="1")
    assert paused["state"] == CAPTURE_STATE_PAUSED


@pytest.mark.unit
def test_capture_sources_validation_and_privacy_gate(tmp_path, monkeypatch) -> None:
    """sources 必填且只有窗口/屏幕/会话/媒体四类；桌面观察被现有隐私门拒绝时
    显式 422（引用现有 computer_use.permission_mode，不建新 settings 文件）。"""
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    with pytest.raises(CaptureControlError) as required:
        controller.start("r0", [])
    assert required.value.code == "SOURCES_REQUIRED"
    assert required.value.http_status == 422

    with pytest.raises(CaptureControlError) as invalid_kind:
        controller.start("r1", [{"kind": "system", "value": "*"}])
    assert invalid_kind.value.code == "INVALID_SOURCE"

    with pytest.raises(CaptureControlError) as empty_value:
        controller.start("r2", [{"kind": "window", "value": "  "}])
    assert empty_value.value.code == "INVALID_SOURCE"

    monkeypatch.setattr("atlas.config.get_config", lambda: _DenyConfig())
    with pytest.raises(CaptureControlError) as denied:
        controller.start("r3", [{"kind": "screen", "value": "*"}])
    assert denied.value.code == "PRIVACY_GATE_DENIES"
    assert denied.value.http_status == 422

    # 非桌面入口（会话）不受桌面隐私门限制；config_refs 如实记录现有设置引用。
    started = controller.start("r4", [{"kind": "session", "value": "chat-1"}])
    assert started["state"] == CAPTURE_STATE_RUNNING
    assert started["config_refs"]["computer_use.permission_mode"] == "deny"
    assert "settings" not in started["config_refs"]


@pytest.mark.unit
def test_capture_scope_matching(tmp_path) -> None:
    """授权入口匹配：窗口子串/屏幕精确/会话相等/媒体任意；范围外与 PAUSED 不入。"""
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1", sources=[
        {"kind": "window", "value": "VS Code"},
        {"kind": "screen", "value": "desktop"},
        {"kind": "session", "value": "chat-9"},
        {"kind": "media", "value": "*"},
    ])

    def _probe(candidates: list[tuple[str, str]], session: str = "") -> dict[str, str] | None:
        matched = controller.begin_passive(candidates, session_id=session)
        controller.finish_passive(created=False)
        return matched

    assert _probe([("window", "vs code - atlas")])["kind"] == "window"
    assert _probe([("window", "Chrome")]) is None
    assert _probe([("screen", "desktop")])["kind"] == "screen"
    assert _probe([("screen", "monitor")]) is None          # screen 精确匹配
    assert _probe([("session", "chat-9")], session="chat-9")["kind"] == "session"
    assert _probe([("session", "chat-9")], session="other") is None
    assert _probe([("media", "*")])["kind"] == "media"       # 媒体入口任意带媒体收据

    controller.pause("r-pause")
    assert controller.begin_passive([("window", "vs code - atlas")]) is None


@pytest.mark.unit
def test_watermark_monotonic_across_restart_and_stop_freeze(tmp_path) -> None:
    """watermark 只在真实入队后前进；stop 后冻结；重启不回退、旧帧重复不重复记账。"""
    path = tmp_path / "state.json"
    controller = PassiveCaptureController(state_path=path)
    _start_running(controller, "r1", sources=[{"kind": "media", "value": "*"}])
    for _ in range(2):
        assert controller.begin_passive([("media", "*")]) is not None
        controller.finish_passive(created=True)
    assert controller.status()["passive_capture_watermark"] == 2
    controller.stop("r-stop")

    # 同进程 stop 后：范围内收据也不再入被动账。
    assert controller.begin_passive([("media", "*")]) is None
    assert controller.status()["passive_capture_watermark"] == 2

    # 进程重启（新控制器同状态文件）：计数不回退、状态如实回 STOPPED。
    restarted = PassiveCaptureController(state_path=path)
    assert restarted.status()["passive_capture_watermark"] == 2
    assert restarted.status()["state"] == CAPTURE_STATE_STOPPED
    assert restarted.status()["revision"] == 2
    assert any("PROCESS_RESTART_STATE_RESET" in note
               for note in restarted.status()["notes"])
    resumed = restarted.start("r2", [{"kind": "media", "value": "*"}],
                              expected_revision=2)
    assert resumed["revision"] == 3
    assert restarted.status()["passive_capture_watermark"] == 2  # 恢复不回退

    # 旧帧重复入队（created=False，服务端/本地幂等去重）不重复推进水位。
    assert restarted.begin_passive([("media", "*")]) is not None
    restarted.finish_passive(created=False)
    assert restarted.status()["passive_capture_watermark"] == 2
    assert restarted.begin_passive([("media", "*")]) is not None
    restarted.finish_passive(created=True)
    assert restarted.status()["passive_capture_watermark"] == 3


@pytest.mark.unit
def test_stop_drains_inflight_passive_before_success(tmp_path, monkeypatch) -> None:
    """stop/pause 排空在途被动观察后才报告成功（§6.1）；超时未排空显式记缺口。"""
    from atlas.memory import windows_sources

    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1")
    selected = controller.begin_passive([("screen", "desktop")])  # 在途 #1
    assert selected is not None
    controller.finish_passive(created=True)  # 在途完成 → 水位记账

    drained = controller.stop("r-stop")
    assert drained["drained"] is True
    assert controller.status()["in_flight"] == 0
    assert controller.status()["passive_capture_watermark"] == 1

    # 在途未收账：stop 等待排空超时 → 显式记缺口后再报告成功（不无限等待）。
    monkeypatch.setattr(windows_sources, "_INFLIGHT_DRAIN_TIMEOUT_SECONDS", 0.2)
    controller2 = PassiveCaptureController(state_path=tmp_path / "state2.json")
    _start_running(controller2, "r1")
    assert controller2.begin_passive([("screen", "desktop")]) is not None
    stalled = controller2.stop("r-stop")
    assert stalled["drained"] is False
    assert any(gap["code"] == "STOP_WITH_INFLIGHT_OBSERVATIONS"
               for gap in stalled["gaps"])
    controller2.finish_passive(created=False)  # 迟到收账配对，不影响断言

    # 收账失败 → 显式缺口（不静默丢账），水位不前进。
    controller3 = PassiveCaptureController(state_path=tmp_path / "state3.json")
    _start_running(controller3, "r1")
    assert controller3.begin_passive([("screen", "desktop")]) is not None
    controller3.finish_passive(created=False, error="outbox exploded")
    status = controller3.status()
    assert status["passive_capture_watermark"] == 0
    assert status["gaps"] and status["gaps"][-1]["code"] == "PASSIVE_CAPTURE_FAILED"
    assert "outbox exploded" in status["last_error"]
    controller3.finish_passive(created=False)  # 配对收账，不影响断言


# ------------------------------------------------- unit：x2 收据捕获


@pytest.mark.unit
def test_receipt_capture_media_asset_idempotent_and_passive_watermark(tmp_path) -> None:
    """截图收据：受控资产只引用 asset_id；同帧去重不重复入账；被动水位真实推进。"""
    facade = _FakeFacade()
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1", sources=[{"kind": "screen", "value": "*"}])
    service = _service(tmp_path, facade, controller)

    first = asyncio.run(service.capture_tool_receipt(
        tool="computer_observe", action="observe:desktop", session_id="chat-1",
        summary="K1_FAKE_DESKTOP capture ok", image_data_url=_png_data_url(16),
        target="desktop", request_args={"target": "desktop"},
        result_extra={"action_result": {"ok": True, "action": "capture"}}))
    frame_payload = _png_payload(_png_data_url(16))
    assert first["created"] is True
    assert first["asset_id"]
    assert first["passive"]["created"] is True
    assert controller.status()["passive_capture_watermark"] == 1

    observations = _outbox_observations(tmp_path)
    assert len(observations) == 2  # 主动收据 + 被动收据各一条
    asset_hash = next(iter(facade._assets.values()))["content_hash"]
    by_prefix: dict[str, dict[str, Any]] = {}
    for observation in observations:
        content = observation["content"]
        by_prefix.setdefault("passive" if content.get("passive")
                             else str(content["x2_kind"]), observation)
        assert observation["speaker_role"] == "TOOL"
        assert observation["epistemic_kind"] == "OBSERVED"
        assert observation["media_refs"] == [
            {"asset_id": first["asset_id"], "hash": asset_hash}]
        # 观察 / 点击请求 / 实际结果三类分开记录。
        assert content["phase"] == "receipt"
        assert content["observation"]["target"] == "desktop"
        assert content["request"]["arguments"] == {"target": "desktop"}
        assert content["result"]["ok"] is True
        assert content["result"]["action_result"] == {"ok": True, "action": "capture"}
        assert frame_payload not in json.dumps(content)  # 正文绝不携带原始帧字节
    active = by_prefix["observe_receipt"]
    passive = by_prefix["passive"]
    assert active["source_object_id"].startswith("x2receipt-")
    assert passive["source_object_id"].startswith("passive-")
    assert passive["content"]["passive"] is True
    assert passive["content"]["source_selection"] == {"kind": "screen", "value": "*"}

    # 同帧重放：内容寻址去重（created=False），水位不重复推进。
    replay = asyncio.run(service.capture_tool_receipt(
        tool="computer_observe", action="observe:desktop", session_id="chat-1",
        summary="K1_FAKE_DESKTOP capture ok", image_data_url=_png_data_url(16),
        target="desktop", request_args={"target": "desktop"}))
    assert replay["created"] is False
    assert replay["passive"]["created"] is False
    assert controller.status()["passive_capture_watermark"] == 1


@pytest.mark.unit
def test_receipt_capture_after_stop_active_continues_no_passive(tmp_path) -> None:
    """stop 后：范围内新帧不再产生被动观察、水位冻结；主动收据照常入库。"""
    facade = _FakeFacade()
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1")
    service = _service(tmp_path, facade, controller)
    before = asyncio.run(service.capture_tool_receipt(
        tool="computer_observe", action="observe:desktop", session_id="chat-1",
        summary="frame before stop", image_data_url=_png_data_url(32),
        target="desktop", request_args={"target": "desktop"}))
    assert before["passive"]["created"] is True
    assert controller.status()["passive_capture_watermark"] == 1
    controller.stop("r-stop")

    after = asyncio.run(service.capture_tool_receipt(
        tool="computer_observe", action="observe:desktop", session_id="chat-2",
        summary="frame after stop", image_data_url=_png_data_url(48),
        target="desktop", request_args={"target": "desktop"}))
    assert after["created"] is True          # 普通工具截图照常记入（反向判据）
    assert after["passive"] is None          # 不再产生被动观察
    assert controller.status()["passive_capture_watermark"] == 1  # 水位冻结

    observations = _outbox_observations(tmp_path)
    passive_rows = [obs for obs in observations if obs["content"].get("passive")]
    assert len(passive_rows) == 1            # stop 前的那一条，stop 后无新增


@pytest.mark.unit
def test_receipt_capture_media_failure_is_explicit(tmp_path) -> None:
    """媒体通道失败：收据显式带 media.error，不伪造资产引用、不塞 base64。"""
    facade = _FakeFacade(fail_media=True)
    controller = PassiveCaptureController(state_path=tmp_path / "state.json")
    _start_running(controller, "r1")
    service = _service(tmp_path, facade, controller)
    result = asyncio.run(service.capture_tool_receipt(
        tool="computer_observe", action="observe:desktop", session_id="chat-1",
        summary="capture with media down", image_data_url=_png_data_url(64),
        target="desktop", request_args={"target": "desktop"}))
    assert result["created"] is True
    assert result["asset_id"] is None
    observations = _outbox_observations(tmp_path)
    assert observations[0]["content"]["media"]["error"].startswith(
        "MEDIA_INGEST_FAILED")
    assert observations[0]["media_refs"] == []
    assert _png_payload(_png_data_url(64)) not in json.dumps(observations[0]["content"])


@pytest.mark.unit
def test_capture_watermarks_counts_buckets(tmp_path) -> None:
    """conversation/tool 水位按 outbox 本地记账三分（与 passive 分开）。"""
    capture = CaptureService(facade=None, outbox_path=tmp_path / "unified_outbox.sqlite3",
                             event_class=EVENT_CLASS)
    assert capture.capture_user_message("conv-1", "msg-1", "原话") is not None
    assert capture.capture_assistant_message("conv-1", "msg-2", "回复") is not None
    assert capture.capture_tool_result("conv-1", "tc-1", "local_shell", "ok") is not None
    counts = capture_watermarks(tmp_path / "unified_outbox.sqlite3")
    assert counts["buckets"]["conversation"] == {
        "enqueued": 2, "acked": 0, "pending": 2}
    assert counts["buckets"]["tool"] == {"enqueued": 1, "acked": 0, "pending": 1}
    missing = capture_watermarks(tmp_path / "does-not-exist.sqlite3")
    assert missing["buckets"]["conversation"]["enqueued"] == 0


@pytest.mark.unit
def test_computer_runtime_receipt_wiring(monkeypatch) -> None:
    """X2ComputerRuntime.call_tool 把截图收据交给 capture_tool_receipt（fake 驱动）。"""
    from atlas.tools.x2 import computer as x2computer
    from atlas.tools.x2.context import X2Context, reset_context, set_context
    from atlas.tools.x2.fake_computer import (
        FAKE_PNG_B64,
        FakeComputerBackend,
        FakeHermesComputerTool,
    )

    captured: list[dict[str, Any]] = []

    class _RecordingService:
        async def capture_tool_receipt(self, **kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return {"created": True}

    monkeypatch.setattr(x2computer, "get_config", lambda: _FullAccessConfig())
    monkeypatch.setattr(x2computer, "_receipt_service", lambda: _RecordingService())
    runtime = x2computer.X2ComputerRuntime(
        backend=FakeComputerBackend(), hermes_tool=FakeHermesComputerTool())
    token = set_context(X2Context(run_id="run-1", session_id="conv-x2"))
    try:
        result = asyncio.run(runtime.call_tool("computer_observe", {"target": "desktop"}))
    finally:
        reset_context(token)
    assert result["is_error"] is False
    assert len(captured) == 1
    kwargs = captured[0]
    assert kwargs["tool"] == "computer_observe"
    assert kwargs["session_id"] == "conv-x2"
    assert kwargs["action"] == "observe:desktop"
    assert kwargs["target"] == "desktop"
    assert kwargs["result_ok"] is True
    assert FAKE_PNG_B64 in str(kwargs["image_data_url"])

    # 采集管线故障绝不影响工具结果（护栏）。
    def _boom() -> Any:
        raise RuntimeError("capture service exploded")

    monkeypatch.setattr(x2computer, "_receipt_service", _boom)
    token = set_context(X2Context(run_id="run-2", session_id="conv-x2"))
    try:
        recovered = asyncio.run(runtime.call_tool(
            "computer_observe", {"target": "desktop"}))
    finally:
        reset_context(token)
    assert recovered["is_error"] is False

    # 点击动作收据：请求（坐标）/实际结果与观察收据分开（x2_kind=action_receipt）。
    captured.clear()
    monkeypatch.setattr(x2computer, "_receipt_service", lambda: _RecordingService())
    token = set_context(X2Context(run_id="run-3", session_id="conv-x2"))
    try:
        clicked = asyncio.run(runtime.call_tool(
            "computer_mouse", {"action": "click", "x": 12, "y": 34}))
    finally:
        reset_context(token)
    assert clicked["is_error"] is False
    assert len(captured) == 1
    click_kwargs = captured[0]
    assert click_kwargs["tool"] == "computer_mouse"
    assert click_kwargs["action"] == "click@12,34"
    assert click_kwargs["image_data_url"] is None  # 点击收据无截图
    assert click_kwargs["request_args"] == {"action": "click", "x": 12, "y": 34}


@pytest.mark.unit
def test_browser_runtime_receipt_wiring(monkeypatch) -> None:
    """X2BrowserRuntime 导航收据：URL/DOM 快照 + 页面观察，会话入口匹配被动账。"""
    from atlas.tools.x2 import browser as x2browser
    from atlas.tools.x2.context import X2Context, reset_context, set_context

    captured: list[dict[str, Any]] = []

    class _RecordingService:
        async def capture_tool_receipt(self, **kwargs: Any) -> dict[str, Any]:
            captured.append(kwargs)
            return {"created": True}

    class _FakeBrowserBackend:
        async def call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
            assert action == "navigate"
            return {"success": True, "url": params["url"],
                    "title": "Example Domain",
                    "snapshot": '- heading "Example Domain" [ref=e1]'}

    monkeypatch.setattr(x2browser, "_receipt_service",
                        lambda: _RecordingService())
    runtime = x2browser.X2BrowserRuntime(backend=_FakeBrowserBackend())
    token = set_context(X2Context(run_id="run-1", session_id="conv-br"))
    try:
        result = asyncio.run(runtime.call_tool(
            "browser_navigate", {"url": "https://example.com"}))
    finally:
        reset_context(token)
    assert result["is_error"] is False
    assert len(captured) == 1
    kwargs = captured[0]
    assert kwargs["tool"] == "browser_navigate"
    assert kwargs["session_id"] == "conv-br"
    assert kwargs["url"] == "https://example.com"
    assert kwargs["title"] == "Example Domain"
    assert "Example Domain" in kwargs["snapshot"]
    assert kwargs["x2_kind"] == "page_receipt"
    assert kwargs["result_ok"] is True


# ------------------------------------------------------------------ integration


@pytest.fixture
def um_x2():
    """每用例独立双子服务 harness：Atlas 子进程固定走确定性 fake 桌面驱动。

    ATLAS_X2_COMPUTER_FAKE=1 经 os.environ 传给子进程（harness 只剥凭据类变量），
    与 K1 每日路径的 fake driver 先例一致；真 Windows 桌面冒烟留 UM12。

    每用例新进程的原因（已知引擎边界，非本任务引入）：bind_atlas_tools 每次运行
    都会用 _execute_tools_node 处理器 override 重绑 legacy computer 工具名，而
    bind_x2_tools 每进程只绑一次 —— 第二个聊天运行起 X2 桥被 legacy 路径盖掉
    （engine/tool_registry.py + x2/registration.py 的既有行为，修复属引擎侧）。
    本模块需要 X2 收据路径的用例因此把 x2 工具调用放在每个服务器进程的第一个
    聊天运行里，并逐用例换新进程。
    """
    os.environ["ATLAS_X2_COMPUTER_FAKE"] = "1"
    harness = UMHarness()
    harness.start()
    try:
        yield harness
    finally:
        try:
            harness.stop()
        finally:
            os.environ.pop("ATLAS_X2_COMPUTER_FAKE", None)


def _fetch_records(h: UMHarness) -> list[dict[str, Any]]:
    response = h.api("GET", "/v1/unified/records", params={"limit": 200})
    assert response.status_code == 200, response.text[:300]
    return response.json()["items"]


def _wait_for_records(h: UMHarness, predicate: Any, *, timeout: float = 90.0,
                      description: str = "") -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    seen = 0
    while time.monotonic() < deadline:
        items = _fetch_records(h)
        seen = len(items)
        hits = [item for item in items if predicate(item)]
        if hits:
            return hits
        time.sleep(1.0)
    raise AssertionError(f"等待记录超时（{timeout:.0f}s）: {description}；当前 {seen} 条")


def _obs_content(item: dict[str, Any]) -> dict[str, Any]:
    text = item.get("content", {}).get("text")
    return text if isinstance(text, dict) else {}


def _projection(item: dict[str, Any]) -> dict[str, Any]:
    """记录投影层（item["content"]）：source_kind/speaker_role/locator 在这一层。"""
    content = item.get("content")
    return content if isinstance(content, dict) else {}


def _capture_status(h: UMHarness) -> dict[str, Any]:
    response = h.api("GET", "/api/unified-memory/capture/status")
    assert response.status_code == 200, response.text[:300]
    return response.json()


def _capture_call(h: UMHarness, action: str, body: dict[str, Any]) -> Any:
    return h.api("POST", f"/api/unified-memory/capture/{action}", json=body)


@pytest.mark.integration
@pytest.mark.fake_provider
def test_stop_capture_stops_new_observations(um_x2) -> None:
    """任务书判据（原样语义）：seed windows_activity → capture/stop → 被动水位
    不再前进。

    **这只限制主动开启的被动采集器；普通工具截图仍正常记入工具经历** ——
    反向断言：stop 后 h.tool 截图类工具（computer_observe）照常产生 TOOL 观察。
    """
    h = um_x2
    seed = h.seed("windows_activity")
    assert seed.get("ingested") is True, seed.get("ingest_error")

    stopped = _capture_call(h, "stop", {"request_id": "judge-stop-initial"})
    assert stopped.status_code == 200, stopped.text[:300]
    assert stopped.json()["state"] == CAPTURE_STATE_STOPPED
    assert stopped.json()["already_stopped"] is True

    before = _capture_status(h)["passive_capture_watermark"]
    receipt = h.tool("computer_observe", {"target": "desktop"})
    assert receipt["status"] == "completed"
    assert not receipt["is_error"], receipt
    after = _capture_status(h)
    # 被动水位保持不动（采集器处于停止态；即使收据在授权范围内也不入被动账）。
    assert after["passive_capture_watermark"] == before

    session_id = receipt["conversation_id"]
    hits = _wait_for_records(
        um_x2,
        lambda item: (_obs_content(item).get("session_id") == session_id
                      and _obs_content(item).get("phase") == "receipt"
                      and _obs_content(item).get("tool") == "computer_observe"),
        description="stop 后 computer_observe 的 TOOL 收据观察")
    assert len(hits) == 1
    assert _obs_content(hits[0]).get("passive") is not True  # 主动工具经历，非被动
    assert hits[0]["epistemic_kind"] == "OBSERVED"
    assert _capture_status(h)["passive_capture_watermark"] == before


@pytest.mark.integration
@pytest.mark.fake_provider
def test_capture_lifecycle_over_http(um_x2) -> None:
    """状态机走真实 HTTP：start 幂等/版本冲突 409/pause/stop/重入 RUNNING；
    普通聊天在 RUNNING/PAUSED 状态均照常产生 USER 观察。"""
    h = um_x2
    initial = _capture_status(h)
    assert initial["state"] == CAPTURE_STATE_STOPPED
    assert initial["collector"]["background_polling"] == "PARTIAL_NOT_IMPLEMENTED"
    assert set(initial["watermarks"]) == {"conversation", "tool", "passive"}

    sources = [{"kind": "screen", "value": "*"}, {"kind": "media", "value": "*"}]
    started = _capture_call(h, "start", {"request_id": "life-start-1",
                                         "sources": sources})
    assert started.status_code == 200, started.text[:300]
    assert started.json()["state"] == CAPTURE_STATE_RUNNING
    assert started.json()["revision"] == initial["revision"] + 1
    assert started.json()["config_refs"].get("memory.unified.capture_mode") == "enabled"

    replay = _capture_call(h, "start", {"request_id": "life-start-1",
                                        "sources": sources})
    assert replay.status_code == 200 and replay.json() == started.json()

    conflict = _capture_call(h, "start", {"request_id": "life-start-2",
                                          "sources": sources})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "ALREADY_RUNNING"

    revision_mismatch = _capture_call(
        h, "pause", {"request_id": "life-pause-1",
                     "expected_revision": started.json()["revision"] + 5})
    assert revision_mismatch.status_code == 409
    assert revision_mismatch.json()["detail"]["error"] == "REVISION_CONFLICT"

    # 被动屏幕采集冻结（单独测试标记 frozen_v1）。保留状态机与真实聊天
    # 检查，不把 fake computer tool 冒充成真实被动采集。
    running_chat = h.chat("采集运行期间继续一条普通聊天。")
    assert running_chat["status"] == "completed"
    running_session_id = running_chat["conversation_id"]
    _wait_for_records(
        h, lambda item: (_obs_content(item).get("session_id") == running_session_id
                         and _projection(item).get("source_kind")
                         == "ATLAS_USER_MESSAGE"),
        description=f"session {running_session_id} 的 USER 观察（RUNNING 不影响聊天）")
    running_watermark = _capture_status(h)["passive_capture_watermark"]
    assert running_watermark == started.json()["passive_capture_watermark"]

    paused = _capture_call(h, "pause", {
        "request_id": "life-pause-2",
        "expected_revision": started.json()["revision"]})
    assert paused.status_code == 200, paused.text[:300]
    assert paused.json()["state"] == CAPTURE_STATE_PAUSED
    assert paused.json()["revision"] == started.json()["revision"] + 1

    # PAUSED 期间：聊天照常（用户原话照常入统一记忆），被动采集器不生产。
    chat = h.chat("暂停记录当前活动，然后我们正常聊。")
    assert chat["status"] == "completed"
    session_id = chat["conversation_id"]
    _wait_for_records(
        h, lambda item: (_obs_content(item).get("session_id") == session_id
                         and _projection(item).get("source_kind")
                         == "ATLAS_USER_MESSAGE"),
        description=f"session {session_id} 的 USER 观察（pause 不影响聊天）")

    h.tool("computer_window", {"action": "list"})
    assert _capture_status(h)["passive_capture_watermark"] == running_watermark

    stopped = _capture_call(h, "stop", {"request_id": "life-stop-1"})
    assert stopped.status_code == 200
    assert stopped.json()["state"] == CAPTURE_STATE_STOPPED
    assert stopped.json()["drained"] is True
    repeat = _capture_call(h, "stop", {"request_id": "life-stop-2"})
    assert repeat.status_code == 200
    assert repeat.json()["already_stopped"] is True
    assert repeat.json()["revision"] == stopped.json()["revision"]

    # 重入 RUNNING：revision 继续单调，被动水位不回退（不重复旧帧）。
    resumed = _capture_call(h, "start", {
        "request_id": "life-start-3",
        "sources": sources,
        "expected_revision": stopped.json()["revision"]})
    assert resumed.status_code == 200, resumed.text[:300]
    final = _capture_status(h)
    assert final["state"] == CAPTURE_STATE_RUNNING
    assert final["revision"] == stopped.json()["revision"] + 1
    assert final["passive_capture_watermark"] == running_watermark
    assert final["sources"] == sources


@pytest.mark.integration
@pytest.mark.fake_provider
def test_screenshot_receipt_media_and_action_receipts(um_x2) -> None:
    """截图收据进统一记忆：TOOL 观察带 asset_id（可回查 T05.1 媒体元数据）；
    观察/点击请求/实际结果三类在同一条收据观察里分开记录。
    （点击动作收据的构成在 unit 的 computer_runtime_receipt_wiring 覆盖；
    集成只取服务器进程第一个聊天运行里的 observe —— X2 桥在第二个运行起被
    引擎既有的重绑行为盖回 legacy，见 um_x2 fixture 注释。）"""
    h = um_x2
    observe = h.tool("computer_observe", {"target": "desktop"})
    assert observe["status"] == "completed" and not observe["is_error"]
    observe_session = observe["conversation_id"]

    observe_hits = _wait_for_records(
        h, lambda item: (_obs_content(item).get("session_id") == observe_session
                         and _obs_content(item).get("phase") == "receipt"
                         and _obs_content(item).get("x2_kind") == "observe_receipt"),
        description="computer_observe 截图收据观察")
    content = _obs_content(observe_hits[0])
    asset_id = str((content.get("media") or {}).get("asset_id") or "")
    assert asset_id, content
    assert content["result"]["ok"] is True
    assert content["request"]["arguments"] == {"target": "desktop"}
    assert content["observation"]["target"] == "desktop"
    assert content["observation"]["frame_sha256"] == content["media"]["media_sha256"]
    from atlas.tools.x2.fake_computer import FAKE_PNG_B64

    assert FAKE_PNG_B64 not in json.dumps(content)  # 只引用 asset_id，不塞帧字节

    # asset_id 回查 T05.1 元数据（Atlas 代理 → MemoryOS 受控资产）。
    media = h.api("GET", f"/api/unified-memory/media/{asset_id}")
    assert media.status_code == 200, media.text[:300]
    assert media.json()["mime"] == "image/png"
    assert media.json()["content_hash"] == content["media"]["media_sha256"]


@pytest.mark.integration
@pytest.mark.frozen_v1(reason="F1-C: V1 passive screen collection is explicitly frozen; a fake computer receipt cannot prove a live passive collector.")
@pytest.mark.skip(reason="frozen_v1: passive screen/media collection is frozen for V1; retain the watermark test for thaw-time verification.")
def test_running_capture_passive_watermark_advances(um_x2) -> None:
    """RUNNING 且收据在授权范围内 → 被动水位真实前进；范围外收据不入被动账。"""
    h = um_x2
    started = _capture_call(h, "start", {
        "request_id": "passive-start-1",
        "sources": [{"kind": "screen", "value": "*"}]})
    assert started.status_code == 200, started.text[:300]
    base = started.json()["passive_capture_watermark"]

    receipt = h.tool("computer_observe", {"target": "desktop"})
    assert receipt["status"] == "completed"
    session_id = receipt["conversation_id"]
    after = _capture_status(h)
    assert after["passive_capture_watermark"] == base + 1  # 真实入队才记账

    passive_hits = _wait_for_records(
        h, lambda item: (_obs_content(item).get("session_id") == session_id
                         and _obs_content(item).get("phase") == "receipt"
                         and _obs_content(item).get("passive") is True),
        description="被动观察（passive=true）落统一记忆")
    assert _obs_content(passive_hits[0])["source_selection"] == {
        "kind": "screen", "value": "*"}

    # 会话入口范围外（只授权其他会话）：被动账不动，主动收据照常。
    paused = _capture_call(h, "pause", {"request_id": "passive-pause-1"})
    assert paused.status_code == 200
    resumed = _capture_call(h, "start", {
        "request_id": "passive-start-2",
        "sources": [{"kind": "session", "value": "chat-not-this-one"}]})
    assert resumed.status_code == 200
    frozen = _capture_status(h)["passive_capture_watermark"]
    outside = h.tool("computer_window", {"action": "list"})
    assert outside["status"] == "completed"
    assert _capture_status(h)["passive_capture_watermark"] == frozen
    _stop = _capture_call(h, "stop", {"request_id": "passive-stop-1"})
    assert _stop.status_code == 200
