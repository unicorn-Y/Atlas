"""T05.2 bridge 单测：multimodal_bridge（Atlas 侧媒体导入 → MemoryOS 派生观察）。

覆盖：
  * FakeUnderstandingProvider（TEST runtime 确定性）走完整管线：音频 →
    AUDIO_RANGE 转写观察；图片 → IMAGE_REGION OCR/caption 观察；观察契约
    形状（speaker_role=UNKNOWN、epistemic_kind=INFERRED、media_refs 只带
    asset_id、content_hash 与 MemoryOS 同一 §2 规则可验算）。
  * 认知纪律：缺失显式 missing（不补虚假 caption）；live provider 无密钥/
    无 vision 模型 → available False，绝不伪造；音频活路径显式不支持。
  * 关联调用走 facade.call → POST /v1/unified/multimodal/associate（服务端
    API 挂载由集成收口代理补齐；挂载前如实 FeatureNotReady 上抛）。

运行（core 解释器）：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \\
      -m pytest core/tests/unified_memory/test_multimodal_bridge.py -o addopts= \\
      -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from atlas.memory.multimodal_bridge import (
    EPISTEMIC_INFERRED,
    SPEAKER_ROLE_UNKNOWN,
    FakeUnderstandingProvider,
    LiveVisionChatProvider,
    MultimodalBridge,
    build_media_observation,
)
from atlas.memory.unified_client import observation_content_hash


def unique_tag() -> str:
    return uuid.uuid4().hex[:8]


class FakeFacade:
    """duck-typed UnifiedMemoryFacade：记录 ingest/observe/call 调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def ingest_media(self, *, data, mime, **kwargs):
        asset_id = "asset-" + uuid.uuid4().hex[:32]
        self.calls.append(("ingest", mime, asset_id))
        return {"asset_id": asset_id, "mime": mime, "relative_path": f"media/aa/{asset_id}"}

    async def observe_batch(self, batch):
        self.calls.append(("observe", batch.get("event_class"), len(batch["observations"])))
        return {"accepted": len(batch["observations"])}

    async def call(self, method, path, json=None, params=None):
        self.calls.append((method, path, json))
        return {"associated": True}


def run(coro):
    return asyncio.run(coro)


def make_bridge(provider=None) -> tuple[MultimodalBridge, FakeFacade]:
    facade = FakeFacade()
    bridge = MultimodalBridge(facade=facade,
                              provider=provider or FakeUnderstandingProvider())
    return bridge, facade


def test_audio_import_produces_transcription_observations():
    """音频导入：AUDIO_RANGE 转写观察（UNKNOWN/INFERRED；asset 引用；hash 可验算）。"""
    bridge, facade = make_bridge()
    data = b"RIFF-fake-wav-" + unique_tag().encode()
    receipt = run(bridge.import_audio(
        data, "audio/wav", source_object_id="aud-1",
        occurred_at="2026-10-06T09:00:00Z"))
    asset_id = receipt["asset"]["asset_id"]
    assert receipt["observations"], "fake provider 可用 → 有转写观察"
    assert receipt["missing"] == []
    for obs in receipt["observations"]:
        assert obs["speaker_role"] == SPEAKER_ROLE_UNKNOWN, "不推测说话人"
        assert obs["epistemic_kind"] == EPISTEMIC_INFERRED, "转写是推测不是用户断言"
        assert obs["media_refs"] == [asset_id], "只引用受控资产（不埋 base64）"
        kind, value = obs["locator"]["kind"], obs["locator"]["value"]
        assert kind == "AUDIO_RANGE"
        start, end = value.split("-")
        assert float(end) > float(start) >= 0.0, "时间段定位"
        # §2 内容哈希与 MemoryOS 同一规则可验算（重算一致）
        assert obs["content_hash"] == observation_content_hash(obs)
    # 观察批已经 facade.observe_batch 发送
    assert any(call[0] == "observe" for call in facade.calls)


def test_image_import_produces_ocr_and_caption_observations():
    """图片导入：OCR 区域观察（bbox locator）+ 全帧 caption 观察。"""
    bridge, _ = make_bridge()
    data = b"\x89PNG-fake-" + unique_tag().encode()
    receipt = run(bridge.import_image(
        data, "image/png", source_object_id="shot-1",
        occurred_at="2026-10-06T09:00:00Z"))
    ocr = [o for o in receipt["observations"]
           if o["source_object_id"].endswith("-ocr-0")]
    caption = [o for o in receipt["observations"]
               if o["source_object_id"].endswith("-caption")]
    assert ocr and caption
    assert "," in ocr[0]["locator"]["value"], "OCR 区域 bbox 定位"
    assert ocr[0]["epistemic_kind"] == EPISTEMIC_INFERRED, "OCR 推测不是用户断言"
    assert caption[0]["epistemic_kind"] == EPISTEMIC_INFERRED, "caption 同为推测"


def test_caption_missing_is_explicit_not_fabricated():
    """caption 不可得 → 显式 missing（不补虚假 caption）。"""
    provider = FakeUnderstandingProvider(caption=None)
    bridge, _ = make_bridge(provider)
    receipt = run(bridge.import_image(
        b"\x89PNG-fake-", "image/png", source_object_id="shot-2",
        occurred_at="2026-10-06T09:00:00Z"))
    assert not any(o["source_object_id"].endswith("-caption")
                   for o in receipt["observations"])
    assert any(m["kind"] == "caption" for m in receipt["missing"]), \
        "缺失显式列出原因"


def test_fake_provider_is_deterministic():
    """TEST provider 同字节同输出（确定性管线可重放）。"""
    data = b"RIFF-deterministic"
    first = run(FakeUnderstandingProvider().transcribe_audio(data, "audio/wav"))
    second = run(FakeUnderstandingProvider().transcribe_audio(data, "audio/wav"))
    assert first == second
    obs_a = build_media_observation(source_object_id="x", text=first[0].text,
                                    locator_kind="AUDIO_RANGE", locator_value="0.0-1.0",
                                    asset_id="asset-" + "0" * 32,
                                    occurred_at="2026-10-06T09:00:00Z")
    obs_b = build_media_observation(source_object_id="x", text=second[0].text,
                                    locator_kind="AUDIO_RANGE", locator_value="0.0-1.0",
                                    asset_id="asset-" + "0" * 32,
                                    occurred_at="2026-10-06T09:00:00Z")
    assert obs_a["content_hash"] == obs_b["content_hash"]


def test_live_provider_refuses_without_gateway_or_vision_model():
    """活路径纪律：无网关密钥 / 无 vision 模型 → available False；不伪造结果。"""

    class StubManager:
        def __init__(self, *, key, models, current="m1"):
            self._key, self._models, self._current = key, models, current

        @property
        def api_key_configured(self):
            return self._key

        def list_models(self):
            return self._models

        def current_model(self):
            return self._current

    no_key = LiveVisionChatProvider(model_manager=StubManager(key=False, models=[
        {"id": "m1", "litellm_model": "openai/gpt-4o",
         "capabilities": {"supports_vision": True}}]))
    assert no_key.available() is False

    no_vision = LiveVisionChatProvider(model_manager=StubManager(key=True, models=[
        {"id": "m1", "litellm_model": "openai/gpt-4o-mini",
         "capabilities": {"supports_vision": False}}]))
    assert no_vision.available() is False
    assert no_vision.resolve_vision_model() is None

    vision = LiveVisionChatProvider(model_manager=StubManager(key=True, models=[
        {"id": "m1", "litellm_model": "openai/gpt-4o",
         "capabilities": {"supports_vision": True}}]))
    assert vision.available() is True
    assert vision.resolve_vision_model() == ("openai/gpt-4o", "m1")

    # 音频：活路径本波显式不支持（无本地 ASR；不伪造转写）
    assert vision.available(mime="audio/wav") is False
    with pytest.raises(RuntimeError, match="ASR"):
        run(vision.transcribe_audio(b"RIFF", "audio/wav"))


def test_associate_calls_service_route_via_facade():
    """关联调用走 facade.call → POST /v1/unified/multimodal/associate。"""
    bridge, facade = make_bridge()
    result = run(bridge.associate())
    method, path, _ = facade.calls[-1]
    assert method == "POST" and path == "/v1/unified/multimodal/associate"
    assert result == {"associated": True}


def test_associate_disabled_facade_raises_not_silently_drops():
    """facade disabled → ServiceUnavailable 如实上抛（不本地伪造回执）。"""
    from atlas.memory.unified_client import ServiceUnavailable

    class DisabledFacade:
        async def call(self, method, path, json=None, params=None):
            raise ServiceUnavailable("unified memory disabled")

    bridge = MultimodalBridge(facade=DisabledFacade(),
                              provider=FakeUnderstandingProvider())
    with pytest.raises(ServiceUnavailable):
        run(bridge.associate())


def test_associate_ready_when_mounted_full_pipeline():
    """集成收口后形状：观察批 + 关联调用同一桥交付（associate=True）。"""
    bridge, facade = make_bridge()
    receipt = run(bridge.import_audio(
        b"RIFF-full-pipeline", "audio/wav", source_object_id="aud-9",
        occurred_at="2026-10-06T09:00:00Z", associate=True))
    assert receipt["association"] == {"associated": True}
    assert any(call[0] == "observe" for call in facade.calls)
