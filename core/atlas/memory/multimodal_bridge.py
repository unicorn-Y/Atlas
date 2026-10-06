"""Multimodal bridge — Atlas media imports → MemoryOS multimodal layer (UM05/T05.2).

职责（新文件+说明式接线；不改 windows_sources.py / unified_memory_router.py /
tools/** —— 集成收口由后续代理完成，接线点见下）：

  * 把导入的图片/音频接**现有模型能力面**：本仓现状是 ——
      - ``atlas.models.ModelManager``（atlas/models/__init__.py）只有模型目录/
        选择/凭据管理，**没有任何推理方法**；``supports_vision`` 只是 chat
        模型的能力标记（list_models()[i]["capabilities"]）。
      - 真正的 chat/视觉调用发生在 agent 循环（agent/run_phases.py，本波
        禁区）经 LiteLLM 以 ``state.litellm_model`` 完成；Atlas core 内**没有
        本地 ASR/OCR 模型**（全仓 grep：无 whisper/ocr/transcribe 本地实现）。
    因此 bridge 按「封装调用签名 + 注明接线点」处理（任务书 T05.2 授权路径）：
      - :class:`LiveVisionChatProvider` —— 活路径：经 ModelManager 解析
        supports_vision 模型，按 LiteLLM chat 多模态消息形状
        （``image_url`` content part，与 agent 循环同形）发视觉请求。
        **接线点**：``litellm.acompletion(model=manager.current_litellm_model,
        messages=...)`` —— 与 run_phases.py 的调用同形；等集成收口把 provider
        挂进导入链路时无需改 bridge 形状。无 vision 模型 / 无网关密钥 →
        ``available()`` False，调用方跳过（活路径**绝不伪造**结果）。
      - :class:`FakeUnderstandingProvider` —— TEST runtime 确定性 provider
        （同字节同输出），测试走完整管线（任务书：无可用本地模型时）。
  * 产出 MemoryOS 契约形状的转录/caption 观察（speaker_role=UNKNOWN、
    epistemic_kind=INFERRED —— 转录/OCR 是推测不是用户断言；说话人不推测；
    片段 locator 指向受控资产，可回原证据），经
    ``UnifiedMemoryFacade.observe_batch`` 入库（T05.1 媒体引用预检面）。
  * ``associate`` —— multimodal 关联调用：``facade.call("POST",
    "/v1/unified/multimodal/associate")``。服务端模块
    （MemoryOS ``service/unified/multimodal.py``）已就绪，API 挂载一行留给
    集成收口代理；挂载前该调用按代理错误映射抛 FeatureNotReady（501）——
    如实上抛，不本地伪造回执（01_contracts.md §8）。

认知纪律（T05.2 禁令，bridge 硬编码）：
  * 转录/OCR/caption 观察：``speaker_role="UNKNOWN"``（不推测说话人）、
    ``epistemic_kind="INFERRED"``（不是用户断言）、``derived_from=[]``、
    ``media_refs=[asset_id]``（不埋 base64，§3：媒体不进记录表）。
  * OCR/caption 缺失显式 missing（``missing`` 列表带原因），不补虚假 caption。
  * 位置/区域只表达该媒体片段（locator），不外推时间。
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas.memory.unified_client import observation_content_hash

CONTRACT_VERSION = "UM-WIN-1.0"

#: 说话人/认知纪律常量（T05.2）：转录与 OCR 是机器推测。
SPEAKER_ROLE_UNKNOWN = "UNKNOWN"
EPISTEMIC_INFERRED = "INFERRED"

SOURCE_KIND = "ATLAS_TOOL_OBSERVATION"


# ------------------------------------------------------------------ provider 面


@dataclass(frozen=True)
class TranscriptSegment:
    """转写段（秒区间；对齐 MemoryOS AUDIO_RANGE locator 值形状）。"""

    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class OcrRegion:
    """OCR 区域（归一化 bbox x,y,w,h；对齐 IMAGE_REGION locator 值形状）。"""

    text: str
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)


class MediaUnderstandingProvider(Protocol):
    """媒体理解 provider 最小面（ASR / OCR / caption）。"""

    name: str

    def available(self, *, mime: str = "") -> bool:
        """能力就绪与否（按 mime 细分：如活路径无 ASR → 音频 False）；
        False 时调用方跳过（绝不伪造结果）。"""
        ...

    async def transcribe_audio(self, data: bytes, mime: str) -> list[TranscriptSegment]:
        """音频 → 转写段（说话人未知：不产 speaker 标签）。"""
        ...

    async def ocr_image(self, data: bytes, mime: str) -> list[OcrRegion]:
        """图片 → OCR 文本区域（无文本 → 空列表：显式缺失，不补虚假文字）。"""
        ...

    async def caption_image(self, data: bytes, mime: str) -> str | None:
        """图片 → 说明文字（不可得 → None：显式缺失，不编造）。"""
        ...


class FakeUnderstandingProvider:
    """TEST runtime 确定性 provider（同字节同输出；无网络、无模型）。"""

    name = "fake-deterministic"

    def __init__(self, *, transcript_text: str = "fake-transcript 评审",
                 ocr_text: str = "fake-ocr 王小明",
                 caption: str | None = "fake-caption 会议截图") -> None:
        self._transcript_text = transcript_text
        self._ocr_text = ocr_text
        self._caption = caption

    def available(self, *, mime: str = "") -> bool:
        return True

    def _digest(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:8]

    async def transcribe_audio(self, data: bytes, mime: str) -> list[TranscriptSegment]:
        digest = self._digest(data)
        return [TranscriptSegment(text=f"{self._transcript_text} [{digest}]",
                                  start_ms=0, end_ms=min(len(data) * 10, 60000))]

    async def ocr_image(self, data: bytes, mime: str) -> list[OcrRegion]:
        digest = self._digest(data)
        return [OcrRegion(text=f"{self._ocr_text} [{digest}]",
                          bbox=(0.1, 0.1, 0.5, 0.4))]

    async def caption_image(self, data: bytes, mime: str) -> str | None:
        if self._caption is None:
            return None
        return f"{self._caption} [{self._digest(data)}]"


class LiveVisionChatProvider:
    """活路径：视觉 chat 模型（LiteLLM 多模态消息形状）。

    接线点（任务书授权的「封装调用签名」方式）：
      * 模型解析：``ModelManager.list_models()`` 中 ``capabilities.
        supports_vision`` 为真的条目（优先当前选中）；``current_litellm_model``
        给出 LiteLLM 模型名。
      * 调用形状：``litellm.acompletion(model=..., messages=[{role: "user",
        content: [{"type": "image_url", "image_url": {"url": "data:<mime>;
        base64,<b64>"}}, {"type": "text", "text": prompt}]}])`` —— 与 agent
        循环（run_phases.py）同一 LiteLLM 面。本波不 import run_phases
        （禁区）；集成收口把本 provider 接进导入链路即可。
      * 音频 ASR：本仓无本地 ASR、LiteLLM 面也无统一 audio 输入约定 →
        ``available()`` 对音频恒 False（显式不支持，不伪造转写）。
    """

    name = "live-vision-chat"

    def __init__(self, *, model_manager: Any = None,
                 model_resolver: Any = None) -> None:
        # model_resolver：测试注入的 (manager) -> (litellm_model, model_id)；
        # 生产惰性走 ModelManager（atlas/models/__init__.py）。
        self._model_manager = model_manager
        self._model_resolver = model_resolver

    def _manager(self) -> Any:
        if self._model_manager is not None:
            return self._model_manager
        from atlas.models import ModelManager  # 惰性：避免测试环境读用户设置

        return ModelManager()

    def resolve_vision_model(self) -> tuple[str, str] | None:
        """(litellm_model, model_id)；无 vision 模型 → None（显式，不猜）。"""
        if self._model_resolver is not None:
            return self._model_resolver(self._manager())
        manager = self._manager()
        models = manager.list_models()
        current = manager.current_model()
        vision = [m for m in models
                  if (m.get("capabilities") or {}).get("supports_vision")]
        if not vision:
            return None
        for model in vision:  # 当前选中的 vision 模型优先
            if model["id"] == current:
                return str(model.get("litellm_model") or model["id"]), str(model["id"])
        first = vision[0]
        return str(first.get("litellm_model") or first["id"]), str(first["id"])

    def available(self, *, mime: str = "") -> bool:
        if mime.startswith("audio/"):
            return False  # 无本地 ASR / 无统一 audio 面：显式不支持
        manager = self._manager()
        if not manager.api_key_configured:
            return False
        return self.resolve_vision_model() is not None

    async def transcribe_audio(self, data: bytes, mime: str) -> list[TranscriptSegment]:
        raise RuntimeError(
            "live provider has no ASR path this wave (no local ASR model; "
            "wiring point documented in module docstring)")

    async def ocr_image(self, data: bytes, mime: str) -> list[OcrRegion]:
        text = await self._vision_chat(data, mime, prompt=(
            "Transcribe all visible text with their approximate normalized "
            "bounding boxes. If none, reply exactly NONE."))
        if not text or text.strip().upper() == "NONE":
            return []
        return [OcrRegion(text=text.strip(), bbox=(0.0, 0.0, 1.0, 1.0))]

    async def caption_image(self, data: bytes, mime: str) -> str | None:
        return await self._vision_chat(data, mime, prompt=(
            "Describe this screenshot in one factual sentence."))

    async def _vision_chat(self, data: bytes, mime: str, *, prompt: str) -> str | None:
        resolved = self.resolve_vision_model()
        if resolved is None:
            raise RuntimeError("no vision-capable model configured")
        import litellm  # 与 agent 循环同一 LiteLLM 面

        b64 = base64.b64encode(data).decode("ascii")
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }]
        response = await litellm.acompletion(model=resolved[0], messages=messages)
        return response.choices[0].message.content


# ------------------------------------------------------------------ 观察装配


def _now_ms() -> int:
    return int(time.time() * 1000)


def _range_value(start_ms: int, end_ms: int) -> str:
    return f"{max(0, start_ms) / 1000:.1f}-{max(0, end_ms) / 1000:.1f}"


def _bbox_value(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{float(v):.4f}".rstrip("0").rstrip(".") for v in bbox)


def build_media_observation(*, source_object_id: str, text: str,
                            locator_kind: str, locator_value: str,
                            asset_id: str, occurred_at: str,
                            source_revision: str = "1") -> dict[str, Any]:
    """契约形状的媒体派生观察（§2 + T05.2 认知纪律）。

    speaker_role=UNKNOWN / epistemic_kind=INFERRED 固定 —— 转录/OCR/caption
    是推测不是用户断言；locator + media_refs 可回原片段；content_hash 按
    §2 规则（Atlas/MemoryOS 同一实现，unified_client.observation_content_hash）。
    """
    observation = {
        "source_event_id":
            f"atlas:{SOURCE_KIND}:{source_object_id}:{source_revision}:UPSERT",
        "source_kind": SOURCE_KIND,
        "source_object_id": source_object_id,
        "source_revision": source_revision,
        "event_action": "UPSERT",
        "occurred_at": occurred_at,
        "source_timezone": "UTC",
        "time_status": "KNOWN",
        "speaker_role": SPEAKER_ROLE_UNKNOWN,
        "epistemic_kind": EPISTEMIC_INFERRED,
        "content": {"text": text, "media_kind": locator_kind},
        "locator": {"kind": locator_kind, "value": locator_value},
        "media_refs": [asset_id],
        "derived_from": [],
    }
    observation["content_hash"] = observation_content_hash(observation)
    return observation


# ------------------------------------------------------------------ bridge


@dataclass
class MultimodalBridge:
    """导入媒体 → 受控资产 + 派生观察 + 关联调用（单一 Atlas 侧装配点）。"""

    facade: Any                      # UnifiedMemoryFacade（duck-typed：3 个方法）
    provider: MediaUnderstandingProvider
    clock: Any = field(default_factory=lambda: _now_ms)

    async def import_audio(self, data: bytes, mime: str, *,
                           source_object_id: str, occurred_at: str | None = None,
                           context: dict[str, Any] | None = None,
                           associate: bool = False) -> dict[str, Any]:
        """导入音频：受控入库 + （provider 可用时）转写观察批。"""
        asset = await self._ingest(data, mime)
        occurred = occurred_at or _iso_from_ms(self.clock())
        observations: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        if self.provider.available(mime=mime):
            for index, segment in enumerate(
                    await self.provider.transcribe_audio(data, mime)):
                observations.append(build_media_observation(
                    source_object_id=f"{source_object_id}-asr-{index}",
                    text=segment.text, locator_kind="AUDIO_RANGE",
                    locator_value=_range_value(segment.start_ms, segment.end_ms),
                    asset_id=asset["asset_id"], occurred_at=occurred))
        else:
            missing.append({"kind": "transcription",
                            "reason": f"provider {self.provider.name} unavailable"})
        return await self._finish(asset, observations, missing, context,
                                  associate=associate)

    async def import_image(self, data: bytes, mime: str, *,
                           source_object_id: str, occurred_at: str | None = None,
                           context: dict[str, Any] | None = None,
                           associate: bool = False) -> dict[str, Any]:
        """导入图片：受控入库 + OCR 区域观察 + caption 观察（可得时）。"""
        asset = await self._ingest(data, mime)
        occurred = occurred_at or _iso_from_ms(self.clock())
        observations: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        if self.provider.available(mime=mime):
            for index, region in enumerate(await self.provider.ocr_image(data, mime)):
                observations.append(build_media_observation(
                    source_object_id=f"{source_object_id}-ocr-{index}",
                    text=region.text, locator_kind="IMAGE_REGION",
                    locator_value=_bbox_value(region.bbox),
                    asset_id=asset["asset_id"], occurred_at=occurred))
            caption = await self.provider.caption_image(data, mime)
            if caption:
                observations.append(build_media_observation(
                    source_object_id=f"{source_object_id}-caption",
                    text=caption, locator_kind="IMAGE_REGION",
                    locator_value=_bbox_value((0.0, 0.0, 1.0, 1.0)),
                    asset_id=asset["asset_id"], occurred_at=occurred))
            else:
                missing.append({"kind": "caption",
                                "reason": "provider returned none (explicit)"})
        else:
            missing.append({"kind": "visual-understanding",
                            "reason": f"provider {self.provider.name} unavailable"})
        return await self._finish(asset, observations, missing, context,
                                  associate=associate)

    async def associate(self, memory_subject_id: str | None = None) -> Any:
        """multimodal 关联调用（服务端 API 挂载一行由集成收口代理补齐）。

        挂载前代理按错误映射抛 FeatureNotReady（501）—— 如实上抛，不伪造。
        """
        return await self.facade.call(
            "POST", "/v1/unified/multimodal/associate",
            json={"memory_subject_id": memory_subject_id} if memory_subject_id else None)

    # ---- 内部

    async def _ingest(self, data: bytes, mime: str) -> dict[str, Any]:
        return await self.facade.ingest_media(data=data, mime=mime)

    async def _finish(self, asset: dict[str, Any],
                      observations: list[dict[str, Any]],
                      missing: list[dict[str, Any]],
                      context: dict[str, Any] | None, *,
                      associate: bool) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "asset": asset,
            "provider": self.provider.name,
            "observations": observations,
            "missing": missing,
            "discipline": {
                "speaker_role": SPEAKER_ROLE_UNKNOWN,
                "epistemic_kind": EPISTEMIC_INFERRED,
                "never_user_asserted": True,
            },
        }
        if observations:
            batch = {"event_class": "PRODUCTION", "observations": observations}
            if context is not None:
                batch["context"] = context
            receipt["observe"] = await self.facade.observe_batch(batch)
        if associate:
            # 关联触发与观察入库同桥交付；服务未挂载时 FeatureNotReady 上抛。
            receipt["association"] = await self.associate()
        return receipt


def _iso_from_ms(ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
