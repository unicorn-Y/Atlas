"""Observation capture builder + CaptureService — Atlas side (UM02 / T02.1-T02.2).

把 Atlas 侧事件构造为契约 Observation（UM-WIN-1.0 §2），并在第一次接收时
持久化到 :class:`~atlas.memory.outbox.OperationalOutbox`（源事件 ACK 前不丢
唯一原始内容）。

边界：
  * **不 import MemoryOS Python 包**（契约 §1）。``observation_content_hash``
    是与 ``service/unified/contracts.py`` 相同规则（canonical JSON + sha256，
    只覆盖业务字段、不含运输时间）的**镜像实现**；一致性由
    ``tests/unified_memory/test_source_idempotency.py`` 的 parity 测试用
    MemoryOS 契约源码双实现比对守护（不跨环境 import）。
  * ``source_event_id`` 规范：``atlas:{source_kind}:{source_object_id}:``
    ``{source_revision}:{event_action}`` —— 消息尚无原 ID 时由调用方先分配
    稳定对象 ID；重试沿用，不生成新 UUID（§2）。

T02.2：:class:`CaptureService` 是对话/模型输出/工具调用的**真实捕获**入口 ——
在原消息/工具事件拥有稳定 ID（SessionDB ``message_uid`` / LLM ``tool_call_id``）
之后调用，经 outbox 耐久排队后再 flush 到统一记忆服务；**不是** UI 每次重绘
再采集。采集默认开启（``memory.unified.capture_mode``，缺省 enabled）、可配置
关闭；采集失败绝不打断聊天主流程（本地 outbox 兜底 + 日志）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import structlog

log = structlog.get_logger()

CONTRACT_VERSION = "UM-WIN-1.0"

MAX_CONTENT_BYTES = 2 * 1024 * 1024   # §2：单条规范化内容最多 2 MiB

#: §2 内容哈希覆盖的业务字段（与 MemoryOS service/unified/contracts.py
#: HASH_BASIS_FIELDS 逐项一致；运输重试时间不进哈希）
HASH_BASIS_FIELDS = (
    "source_event_id",
    "source_kind",
    "source_object_id",
    "source_revision",
    "event_action",
    "occurred_at",
    "source_timezone",
    "time_status",
    "speaker_role",
    "epistemic_kind",
    "content",
    "locator",
    "media_refs",
    "derived_from",
)

SOURCE_KINDS = (
    "ATLAS_USER_MESSAGE",
    "ATLAS_ASSISTANT_MESSAGE",
    "ATLAS_TOOL_OBSERVATION",
    "ATLAS_AGENT_TOOL_RESULT",
    "ATLAS_VERIFICATION",
    "USER_IMPORT",
    "DERIVED",
)
SPEAKER_ROLES = ("USER", "ATLAS", "TOOL", "THIRD_PARTY", "UNKNOWN")
EPISTEMIC_KINDS = ("OBSERVED", "USER_ASSERTED", "THIRD_PARTY_ASSERTED",
                   "INFERRED", "SIMULATED")
EVENT_ACTIONS = ("UPSERT", "DELETE")
TIME_STATUSES = ("KNOWN", "UNKNOWN")


class ContentTooLarge(Exception):
    """§2 超限：显式拒绝，不静默截断（blob 引用路径 UM05 接入）。"""

    def __init__(self, size_bytes: int) -> None:
        super().__init__(
            f"CONTENT_TOO_LARGE: normalized content is {size_bytes} bytes "
            f"(limit {MAX_CONTENT_BYTES}); media must be submitted separately "
            "(blob path lands in UM05)")
        self.size_bytes = size_bytes
        self.code = "CONTENT_TOO_LARGE"


def canonical_json(obj: Any) -> str:
    """稳定序列化：排序 key、紧凑分隔符、不转义非 ASCII（双仓同一规则）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def observation_content_hash(observation: dict[str, Any]) -> str:
    """按 §2 规则计算观察内容哈希（服务端会重算校验，不一致 → 422）。"""
    basis = {key: observation.get(key) for key in HASH_BASIS_FIELDS}
    digest = hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def content_size_bytes(content: Any) -> int:
    """规范化 content 的字节数（§2 上限判据）。"""
    return len(canonical_json(content).encode("utf-8"))


def build_observation(*, source_kind: str, source_object_id: str,
                      source_revision: str, content: dict[str, Any],
                      speaker_role: str, epistemic_kind: str,
                      occurred_at: str | None = None,
                      source_timezone: str | None = None,
                      time_status: str | None = None,
                      locator: dict[str, Any] | None = None,
                      media_refs: list[Any] | None = None,
                      derived_from: list[Any] | None = None,
                      event_action: str = "UPSERT") -> dict[str, Any]:
    """构造契约 Observation dict（含 source_event_id 与 content_hash）。

    §2 校验的本地镜像：kind/role/epistemic/action 枚举、occurred_at=null 必须
    time_status=UNKNOWN、occurred_at 存在必须带 source_timezone、内容超限抛
    :class:`ContentTooLarge`。
    """
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind 必须是 {SOURCE_KINDS} 之一，收到 {source_kind!r}")
    if event_action not in EVENT_ACTIONS:
        raise ValueError(f"event_action 必须是 {EVENT_ACTIONS} 之一，收到 {event_action!r}")
    if speaker_role not in SPEAKER_ROLES:
        raise ValueError(f"speaker_role 必须是 {SPEAKER_ROLES} 之一，收到 {speaker_role!r}")
    if epistemic_kind not in EPISTEMIC_KINDS:
        raise ValueError(f"epistemic_kind 必须是 {EPISTEMIC_KINDS} 之一，收到 {epistemic_kind!r}")
    if not str(source_object_id).strip() or not str(source_revision).strip():
        raise ValueError("source_object_id / source_revision 不能为空")

    effective_time_status = time_status or ("KNOWN" if occurred_at else "UNKNOWN")
    if effective_time_status not in TIME_STATUSES:
        raise ValueError(f"time_status 必须是 {TIME_STATUSES} 之一")
    if not occurred_at and effective_time_status != "UNKNOWN":
        raise ValueError("occurred_at 为 null 时必须 time_status=UNKNOWN（§2）")
    if occurred_at and not (source_timezone or "").strip():
        raise ValueError("occurred_at 存在时 source_timezone 必填（§2 保存原时区）")
    if content_size_bytes(content) > MAX_CONTENT_BYTES:
        raise ContentTooLarge(content_size_bytes(content))

    observation: dict[str, Any] = {
        "source_event_id": f"atlas:{source_kind}:{source_object_id}:"
                           f"{source_revision}:{event_action}",
        "source_kind": source_kind,
        "source_object_id": source_object_id,
        "source_revision": str(source_revision),
        "event_action": event_action,
        "time_status": effective_time_status,
        "occurred_at": occurred_at,
        "source_timezone": source_timezone,
        "speaker_role": speaker_role,
        "epistemic_kind": epistemic_kind,
        "content": content,
        "locator": locator,
        "media_refs": list(media_refs or []),
        "derived_from": list(derived_from or []),
    }
    observation["content_hash"] = observation_content_hash(observation)
    return observation


class ObservationBuilder:
    """带默认 context / event_class 的 builder（T02.2 的采集入口用同一实例）。"""

    def __init__(self, *, context: dict[str, Any] | None = None,
                 event_class: str = "PRODUCTION") -> None:
        self._context = context
        self._event_class = event_class

    @property
    def context(self) -> dict[str, Any] | None:
        return self._context

    @property
    def event_class(self) -> str:
        return self._event_class

    def build(self, **kwargs: Any) -> dict[str, Any]:
        return build_observation(**kwargs)

    def batch(self, observations: list[dict[str, Any]], *,
              context: dict[str, Any] | None = None,
              event_class: str | None = None) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "event_class": event_class or self._event_class,
            "context": context or self._context or {},
            "observations": list(observations),
        }


def enqueue_capture(outbox: Any, observation: dict[str, Any], *,
                    context: dict[str, Any] | None = None,
                    event_class: str = "PRODUCTION") -> dict[str, Any]:
    """采集入库 = builder 产物 + outbox 第一次接收即持久化。

    返回 ``{"id", "source_event_id", "state", "created"}``；同 ID 异内容在本地
    即被 :class:`~atlas.memory.outbox.OutboxConflict` 拒绝（不等到服务端 409）。
    """
    return outbox.enqueue(observation, context=context, event_class=event_class)


# ---------------------------------------------------------------------------
# 稳定 ID 体系（T02.2 / 任务书第 4 项）
# ---------------------------------------------------------------------------

def atlas_message_object_id(message: Any) -> str:
    """Atlas 消息 → 捕获 source_object_id（§2 对象 ID 必须是稳定 ID）。

    Atlas 会话消息只有**一套**稳定 ID 体系：Hermes SessionDB 的
    ``message_uid``（``atlas/engine/session_sync.py::_message_for_atlas`` 的
    ``id`` 字段；pre-C1 遗留行回落到 SessionDB 数字 row id）。run_drive 的
    ``done.message_id``、``/api/conversations/*/messages`` 的 ``id`` 与本函数
    输出同源，因此 capture 不另造第二套 ID，locator ``{session}/{message}``
    可以直接被 UI 与 evidence 查询解析。工具调用对象 ID 则是 LLM/引擎的
    ``tool_call_id``（同一 ID 贯穿 dispatch/result/verification 三类观察）。
    """
    if isinstance(message, dict):
        raw = message.get("message_uid") or message.get("id") or ""
    else:
        raw = message
    return str(raw).strip()


def next_source_revision(revision: str | int) -> str:
    """编辑/分支语义：同一来源对象产生新版本事件（UPSERT rev+1，原版本保留）。

    数值版本直接 +1（"1"→"2"）；非数值版本（外部系统字符串）追加序号
    （"r7"→"r7.2"）。重试沿用同一 rev，不在这里变更。
    """
    text = str(revision or "").strip() or "1"
    try:
        return str(int(text) + 1)
    except ValueError:
        base, _, count = text.rpartition(".")
        if base and count.isdigit():
            return f"{base}.{int(count) + 1}"
        return f"{text}.2"


def _normalize_time(occurred_at: Any, source_timezone: str | None = None,
                    ) -> tuple[str | None, str | None, str]:
    """occurred_at 归一化 → (iso, timezone, time_status)（§2 不接受无时区绝对时间）。

    datetime/epoch 数字一律转 UTC ISO（+00:00，source_timezone="UTC"——epoch
    本身无原时区，如实记 UTC 而不伪造本地时区）；字符串原样采用（调用方来自
    SessionDB 的时间均带 +00:00 偏移）；缺失 → (None, None, UNKNOWN)。
    """
    if occurred_at is None or occurred_at == "":
        return None, None, "UNKNOWN"
    tz = (source_timezone or "").strip() or None
    if isinstance(occurred_at, datetime):
        value = occurred_at if occurred_at.tzinfo is not None else occurred_at.replace(
            tzinfo=UTC)
        return value.isoformat(), tz or "UTC", "KNOWN"
    if isinstance(occurred_at, (int, float)):
        return (datetime.fromtimestamp(float(occurred_at), UTC).isoformat(),
                tz or "UTC", "KNOWN")
    text = str(occurred_at).strip()
    if not text:
        return None, None, "UNKNOWN"
    return text, tz or "UTC", "KNOWN"


def _utc_now_iso() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.isoformat(), "UTC"


#: 内容超限（§2 2 MiB，blob 路径 UM05 才接入）时的显式节流上限：截取正文并
#: **显式标记** omitted（不静默截断 —— 记录里保留原字节数与策略说明）。
_EXCERPT_CHARS = 100_000


def _fit_content(content: dict[str, Any]) -> dict[str, Any]:
    """content 超 2 MiB 时显式降级（正文节选 + omitted 标记），绝不静默截断。"""
    if content_size_bytes(content) <= MAX_CONTENT_BYTES:
        return content
    fitted = dict(content)
    text = fitted.get("text")
    original_bytes = content_size_bytes(content)
    if isinstance(text, str):
        fitted["text"] = text[:_EXCERPT_CHARS]
    if content_size_bytes(fitted) > MAX_CONTENT_BYTES and isinstance(
            fitted.get("text"), str):
        fitted["text"] = ""
    fitted["content_omitted"] = {
        "original_bytes": original_bytes,
        "kept_chars": len(str(fitted.get("text") or "")),
        "reason": "CONTRACT_LIMIT_2MIB",
        "note": "受控 blob 引用在 UM05 接入；此处显式节选，不静默截断（§2）",
    }
    return fitted


# ---------------------------------------------------------------------------
# CaptureService（T02.2 真实捕获入口）
# ---------------------------------------------------------------------------

#: 工具调用对象的版本语义：dispatch=1 → result=2 → verification=3。
#: 契约冻结 event_action ∈ {UPSERT, DELETE}（MemoryOS 侧校验），因此三类观察
#: 共享 source_kind/source_object_id、以 source_revision + content.phase 区分
#: —— 同版本同内容只产生一次观察（§2），重试幂等键不变。
TOOL_REVISION_DISPATCH = "1"
TOOL_REVISION_RESULT = "2"
TOOL_REVISION_VERIFICATION = "3"


def capture_enabled(config: Any) -> bool:
    """采集开关：``memory.unified.enabled`` 且 ``capture_mode`` 未禁用。

    capture_mode **默认 enabled**（对话/工具可靠采集开，契约 §8）；显式
    ``disabled``/``off``/``false``/``0`` 才关闭。enabled=false 时整体禁用。
    """
    if config is None or not bool(config.get("memory.unified.enabled", False)):
        return False
    mode = str(config.get("memory.unified.capture_mode") or "enabled").strip().lower()
    return mode not in {"disabled", "off", "false", "0"}


def _configured_event_class(config: Any) -> str:
    """观察批次 event_class：环境变量 > 配置 > PRODUCTION。

    ``ATLAS_UNIFIED_EVENT_CLASS`` 供隔离测试环境注入 TEST（00_master_task §8：
    测试产生的所有 MemoryOS 事件类必须是 TEST）。
    """
    from_env = os.environ.get("ATLAS_UNIFIED_EVENT_CLASS", "").strip()
    if from_env:
        return from_env
    from_config = str((config or {}).get("memory.unified.event_class") or "").strip()
    return from_config or "PRODUCTION"


def _load_config() -> Any | None:
    try:
        from atlas.config import get_config

        return get_config()
    except Exception:  # pragma: no cover — 配置系统不可用时按禁用处理
        return None


class CaptureService:
    """单例采集服务：builder + OperationalOutbox（+ 可选 facade 供 flush）。

    生命周期：server lifespan 在 ``memory.unified.enabled`` 时
    :func:`configure_capture_service` 装配；所有接线点（run_phases / tool_node）
    经 :func:`get_capture_service` 取用，**disabled 时返回 None，接线点必须
    容忍 None**。flush 由服务端的 :func:`capture_flush_loop` 事件驱动
    （入队即唤醒；空闲期兜底处理退避与遗留行）。

    幂等键体系：``source_event_id = atlas:{kind}:{真实对象ID}:{rev}:{UPSERT}``。
    同一 ID 重入只产生一次 —— 进程内 ``_seen`` set 先去重，outbox
    ``source_event_id UNIQUE`` 兜底；同 ID 异内容（如重复的异步完成回调带了
    流片段）按 first-write-wins 保留第一次的完整原文并记日志，不覆盖、不冲突
    上抛。任何失败都只记录、返回非 created 结果，**绝不向调用方抛异常**。
    """

    def __init__(self, *, facade: Any = None, config: Any = None,
                 context: dict[str, Any] | None = None, outbox: Any = None,
                 outbox_path: str | Path | None = None,
                 event_class: str | None = None) -> None:
        self._facade = facade
        self._config = config
        self._base_context = context
        self._outbox = outbox
        self._outbox_path = outbox_path
        if outbox_path is None and config is not None:
            configured = str(config.get("memory.unified.outbox_path") or "").strip()
            if configured:
                self._outbox_path = configured
        if self._outbox_path is None:
            from atlas.memory.outbox import default_outbox_path

            self._outbox_path = default_outbox_path()
        self._event_class = event_class or _configured_event_class(config)
        self._builder = ObservationBuilder(event_class=self._event_class)
        self._seen: set[str] = set()
        self._enqueue_lock = threading.Lock()
        self._flush_lock = asyncio.Lock()
        # flush 循环唤醒通道：本服务新入队 → 立即 flush（事件驱动，不做盲目
        # 周期轮询 —— 共享 outbox 文件还可能被诊断/恢复方直接使用，见
        # test_source_idempotency；空闲期 30s 一次兜底 flush 处理退避重试）。
        self._wake_event: asyncio.Event | None = None
        self._wake_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ 装配信息

    @property
    def event_class(self) -> str:
        return self._event_class

    @property
    def outbox_path(self) -> Path:
        return Path(self._outbox_path)  # type: ignore[arg-type]

    @property
    def facade(self) -> Any:
        return self._facade

    def _ensure_outbox(self) -> Any:
        if self._outbox is None:
            from atlas.memory.outbox import OperationalOutbox

            self._outbox = OperationalOutbox(self._outbox_path)
        return self._outbox

    def _context(self, overrides: dict[str, Any] | None) -> dict[str, Any] | None:
        """§1 九字段 MemoryContext：优先 facade 配置绑定，再叠调用方覆盖。"""
        if self._facade is not None:
            try:
                return self._facade.default_context(**dict(overrides or {}))
            except Exception:  # noqa: BLE001 — 配置缺项回落到静态 context
                pass
        merged = dict(self._base_context or {})
        merged.update(overrides or {})
        return merged or None

    # ------------------------------------------------------------ 入队核心

    def attach_wake(self, event: asyncio.Event) -> None:
        """绑定 flush 循环的唤醒事件（在循环协程内调用，绑定其事件循环）。"""
        self._wake_event = event
        try:
            self._wake_loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover — 仅在无循环环境构造时发生
            self._wake_loop = None

    def _request_flush(self) -> None:
        """新观察入队后唤醒 flush 循环（线程安全：跨线程走 call_soon_threadsafe）。"""
        event, loop = self._wake_event, self._wake_loop
        if event is None or loop is None or event.is_set():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            event.set()
        else:
            loop.call_soon_threadsafe(event.set)

    def _enqueue(self, observation: dict[str, Any],
                 context_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        source_event_id = str(observation.get("source_event_id") or "")
        with self._enqueue_lock:
            if source_event_id in self._seen:
                # builder 层 set 去重：同 ID 重入第二次起不再触碰 outbox。
                return {"source_event_id": source_event_id, "created": False,
                        "deduplicated": True}
            try:
                result = enqueue_capture(
                    self._ensure_outbox(), observation,
                    context=self._context(context_overrides),
                    event_class=self._event_class)
            except Exception as exc:
                from atlas.memory.outbox import OutboxConflict

                if isinstance(exc, OutboxConflict):
                    # 同 ID 异内容：first-write-wins（例如异步完成回调重放带了
                    # 流片段）——保留第一次的完整原文，不覆盖、不上抛。
                    log.warning("memory.capture_conflict_kept_first",
                                source_event_id=source_event_id, error=str(exc))
                    self._seen.add(source_event_id)
                    return {"source_event_id": source_event_id, "created": False,
                            "conflict": True}
                # 护栏：本地兜底写失败也只记录（观察留在内存外——本次未入队，
                # 下次重入重试），绝不向聊天主流程抛异常。
                log.warning("memory.capture_enqueue_failed",
                            source_event_id=source_event_id, error=str(exc))
                return {"source_event_id": source_event_id, "created": False,
                        "error": str(exc)}
            self._seen.add(source_event_id)
        self._request_flush()
        return result

    def _capture(self, *, source_kind: str, source_object_id: str,
                 source_revision: str, content: dict[str, Any],
                 speaker_role: str, epistemic_kind: str,
                 occurred_at: Any, source_timezone: str | None,
                 locator: dict[str, Any] | None,
                 context_overrides: dict[str, Any] | None = None,
                 derived_from: list[Any] | None = None) -> dict[str, Any] | None:
        occurred, tz, time_status = _normalize_time(occurred_at, source_timezone)
        observation = self._builder.build(
            source_kind=source_kind, source_object_id=source_object_id,
            source_revision=str(source_revision), content=_fit_content(content),
            speaker_role=speaker_role, epistemic_kind=epistemic_kind,
            occurred_at=occurred, source_timezone=tz, time_status=time_status,
            locator=locator, derived_from=derived_from)
        return self._enqueue(observation, context_overrides)

    # ------------------------------------------------------------ 消息捕获

    def capture_user_message(self, session_id: str, message_id: str, text: str,
                             occurred_at: Any = None, branch: str | None = None, *,
                             revision: int | str = 1, source_timezone: str | None = None,
                             model_deployment_id: str | None = None,
                             project_id: str | None = None,
                             task_id: str | None = None) -> dict[str, Any] | None:
        """用户原话（ATLAS_USER_MESSAGE / USER / USER_ASSERTED）。

        ``message_id`` 必须是 SessionDB 稳定 ``message_uid``（含 legacy row id
        回落）；编辑/分支沿源事件版本：新内容用 ``next_source_revision`` 产生的
        rev 重新 UPSERT，原版本保留（§2）。
        """
        object_id = atlas_message_object_id(message_id)
        if not object_id or not str(session_id or "").strip():
            return None
        return self._capture(
            source_kind="ATLAS_USER_MESSAGE", source_object_id=object_id,
            source_revision=str(revision),
            content={"text": str(text or ""), "branch": branch,
                     "session_id": str(session_id)},
            speaker_role="USER", epistemic_kind="USER_ASSERTED",
            occurred_at=occurred_at, source_timezone=source_timezone,
            locator={"kind": "MESSAGE", "value": f"{session_id}/{object_id}"},
            context_overrides=self._message_context(
                session_id, model_deployment_id=model_deployment_id,
                project_id=project_id, task_id=task_id))

    def capture_assistant_message(self, session_id: str, message_id: str, text: str,
                                  occurred_at: Any = None,
                                  branch: str | None = None, *,
                                  revision: int | str = 1,
                                  source_timezone: str | None = None,
                                  model: str | None = None,
                                  model_deployment_id: str | None = None,
                                  project_id: str | None = None,
                                  task_id: str | None = None
                                  ) -> dict[str, Any] | None:
        """Atlas 当次输出（ATLAS_ASSISTANT_MESSAGE / ATLAS / OBSERVED）。

        **自报完成不是任务验证**：epistemic_kind 恒为 OBSERVED，content 不携带
        任何 ``verification="VERIFIED"`` 语义（验证证据属 ATLAS_VERIFICATION，
        由真实检查产生）；``only_assistant_claim`` 显式标注该观察只是模型自述。
        """
        object_id = atlas_message_object_id(message_id)
        if not object_id or not str(session_id or "").strip():
            return None
        return self._capture(
            source_kind="ATLAS_ASSISTANT_MESSAGE", source_object_id=object_id,
            source_revision=str(revision),
            content={"text": str(text or ""), "branch": branch,
                     "session_id": str(session_id), "model": model,
                     "only_assistant_claim": True},
            speaker_role="ATLAS", epistemic_kind="OBSERVED",
            occurred_at=occurred_at, source_timezone=source_timezone,
            locator={"kind": "MESSAGE", "value": f"{session_id}/{object_id}"},
            context_overrides=self._message_context(
                session_id, model_deployment_id=model_deployment_id or model,
                project_id=project_id, task_id=task_id))

    def _message_context(self, session_id: str, *, model_deployment_id: str | None,
                         project_id: str | None,
                         task_id: str | None) -> dict[str, Any]:
        overrides: dict[str, Any] = {"runtime_session_id": str(session_id)}
        if model_deployment_id:
            overrides["model_deployment_id"] = model_deployment_id
        if project_id:
            overrides["project_id"] = project_id
        if task_id:
            overrides["task_id"] = task_id
        return overrides

    # ------------------------------------------------------------ 工具捕获

    def capture_tool_call(self, session_id: str, tool_call_id: str, name: str,
                          arguments: dict[str, Any] | None = None, *,
                          occurred_at: Any = None, actor_id: str | None = None,
                          model_deployment_id: str | None = None,
                          project_id: str | None = None) -> dict[str, Any] | None:
        """工具派发（rev=1，phase=dispatch）——模型真实发起的调用动作。"""
        object_id = atlas_message_object_id(tool_call_id)
        if not object_id or not str(session_id or "").strip():
            return None
        now, tz = _utc_now_iso()
        return self._capture(
            source_kind="ATLAS_TOOL_OBSERVATION", source_object_id=object_id,
            source_revision=TOOL_REVISION_DISPATCH,
            content={"phase": "dispatch", "tool": str(name), "session_id": str(session_id),
                     "arguments": dict(arguments or {})},
            speaker_role="TOOL", epistemic_kind="OBSERVED",
            occurred_at=occurred_at or now, source_timezone=tz,
            locator={"kind": "TOOL_CALL", "value": f"{session_id}/{object_id}"},
            context_overrides=self._message_context(
                session_id, model_deployment_id=model_deployment_id,
                project_id=project_id, task_id=None))

    def capture_tool_result(self, session_id: str, tool_call_id: str, name: str,
                            text: str = "", *, is_error: bool = False,
                            error_category: str | None = None,
                            full_output_path: str | None = None,
                            occurred_at: Any = None, actor_id: str | None = None,
                            model_deployment_id: str | None = None,
                            project_id: str | None = None) -> dict[str, Any] | None:
        """工具结果（rev=2，phase=result）——完整原文/受控 blob，不重复流片段。

        异常与取消也记录：``is_error=True`` + ``error_category``（tool/policy/
        safety/hook/approval_denied）。异步或流式工具在**完成回调**处调用一次，
        带完整结果；重复调用（同 ID）按 first-write-wins 幂等。
        """
        object_id = atlas_message_object_id(tool_call_id)
        if not object_id or not str(session_id or "").strip():
            return None
        now, tz = _utc_now_iso()
        content: dict[str, Any] = {"phase": "result", "tool": str(name),
                                   "session_id": str(session_id),
                                   "text": str(text or ""), "is_error": bool(is_error)}
        if error_category:
            content["error_category"] = str(error_category)
        if full_output_path:
            content["full_output_path"] = str(full_output_path)
        return self._capture(
            source_kind="ATLAS_TOOL_OBSERVATION", source_object_id=object_id,
            source_revision=TOOL_REVISION_RESULT, content=content,
            speaker_role="TOOL", epistemic_kind="OBSERVED",
            occurred_at=occurred_at or now, source_timezone=tz,
            locator={"kind": "TOOL_CALL", "value": f"{session_id}/{object_id}"},
            context_overrides=self._message_context(
                session_id, model_deployment_id=model_deployment_id,
                project_id=project_id, task_id=None))

    def capture_tool_verification(self, session_id: str, tool_call_id: str,
                                  name: str, evidence_text: str = "", *,
                                  verified: bool = True, occurred_at: Any = None,
                                  model_deployment_id: str | None = None,
                                  project_id: str | None = None
                                  ) -> dict[str, Any] | None:
        """验证证据（rev=3，source_kind=ATLAS_VERIFICATION）。

        只有真实检查命令成功产出才记录（失败走 result 的 error 观察）；这是
        可观察结果证据，与 assistant 自报（OBSERVED 自述）严格分开（§1.1）。
        """
        object_id = atlas_message_object_id(tool_call_id)
        if not object_id or not str(session_id or "").strip():
            return None
        now, tz = _utc_now_iso()
        return self._capture(
            source_kind="ATLAS_VERIFICATION", source_object_id=object_id,
            source_revision=TOOL_REVISION_VERIFICATION,
            content={"phase": "verification", "tool": str(name),
                     "session_id": str(session_id), "text": str(evidence_text or ""),
                     "verified": bool(verified)},
            speaker_role="ATLAS", epistemic_kind="OBSERVED",
            occurred_at=occurred_at or now, source_timezone=tz,
            locator={"kind": "TOOL_CALL", "value": f"{session_id}/{object_id}"},
            context_overrides=self._message_context(
                session_id, model_deployment_id=model_deployment_id,
                project_id=project_id, task_id=None))

    def capture_agent_tool_result(self, session_id: str, tool_call_id: str,
                                  actor_id: str, text: str = "", *,
                                  is_error: bool = False, occurred_at: Any = None,
                                  project_id: str | None = None,
                                  tool_name: str = "agent",
                                  result_payload: dict[str, Any] | None = None,
                                  log_refs: dict[str, Any] | list[Any] | None = None,
                                  atlas_session: bool = True,
                                  ) -> dict[str, Any] | None:
        """被调用 Agent 的返回（T02.3 真实接线：tool_node / agent_backends_router）。

        ATLAS_AGENT_TOOL_RESULT / THIRD_PARTY / THIRD_PARTY_ASSERTED：对方自己的
        推理与声明不是 Atlas 的独立事实权威（§1.1），所以按第三方断言记录；
        ``only_assistant_claim=True`` 显式标注这只是对方的自报完成 —— **对方的
        声明不是验证**（验证证据属 ATLAS_VERIFICATION，由 Atlas 独立检查产生，
        见 :meth:`~atlas.memory.windows_sources.WindowsSourceService.verify_agent_result`）。
        ``actor_id`` 区分被调用的 Agent/工具身份（如 ``tool-zcode``）；
        ``log_refs`` 保留原日志定位（受控 blob 路径 / 子任务 ID / 后端会话 ID）。

        ``session_id`` 是 Atlas 对话 ID（tool_node 路径）；agent_backends_router
        的后端直连路径没有 Atlas 对话，传 ``atlas_session=False`` 并把后端
        会话 ID 放进 ``log_refs``（locator 用 AGENT_BACKEND_SESSION，避免把后端
        会话伪造成 Atlas 运行会话）。
        """
        object_id = atlas_message_object_id(tool_call_id)
        if not object_id:
            return None
        if atlas_session and not str(session_id or "").strip():
            return None
        now, tz = _utc_now_iso()
        content: dict[str, Any] = {"phase": "result", "tool": str(tool_name or "agent"),
                                   "actor_id": str(actor_id or ""),
                                   "session_id": str(session_id or ""),
                                   "text": str(text or ""),
                                   "is_error": bool(is_error),
                                   "only_assistant_claim": True}
        if result_payload:
            content["result_payload"] = result_payload
        if log_refs:
            content["log_refs"] = log_refs
        if atlas_session:
            locator: dict[str, Any] = {"kind": "TOOL_CALL",
                                       "value": f"{session_id}/{object_id}"}
        else:
            locator = {"kind": "AGENT_BACKEND_SESSION", "value": str(object_id)}
        # MemoryContext 完整性（§1 runtime_session_id 必填）：后端直连路径没有
        # Atlas 对话，用 agent-backend 命名空间的合成会话 ID（locator 已明确
        # 区分，不把后端会话伪造成 Atlas 运行会话）。
        overrides = (self._message_context(
            str(session_id), model_deployment_id=None, project_id=project_id,
            task_id=None) if atlas_session else
            {"runtime_session_id": f"agent-backend:{object_id}"})
        return self._capture(
            source_kind="ATLAS_AGENT_TOOL_RESULT", source_object_id=object_id,
            source_revision=TOOL_REVISION_RESULT, content=content,
            speaker_role="THIRD_PARTY", epistemic_kind="THIRD_PARTY_ASSERTED",
            occurred_at=occurred_at or now, source_timezone=tz,
            locator=locator, context_overrides=overrides)

    def capture_agent_verification(self, session_id: str, tool_call_id: str,
                                   tool_name: str, checks: list[dict[str, Any]],
                                   *, verified: bool | None = None,
                                   occurred_at: Any = None,
                                   project_id: str | None = None,
                                   atlas_session: bool = True,
                                   ) -> dict[str, Any] | None:
        """被调 Agent 结果的 Atlas 独立验证追加（T02.3）。

        ATLAS_VERIFICATION / ATLAS / OBSERVED：与被调方的 THIRD_PARTY 自报严格
        分开（§1.1「对方声明不是验证」）。``checks`` 必须来自 Atlas 自己的真实
        检查（文件存在 / 真实产物 / 可观察结果），同一 ``tool_call_id`` 作
        source_object_id（revision=3）与 result 观察关联；episode outcome 更新
        留 UM09，本波只落验证观察。``atlas_session=False``（agent_backends_router
        直连后端路径没有 Atlas 对话）用 AGENT_BACKEND_SESSION locator，
        不把后端会话伪造成 Atlas 运行会话。
        """
        object_id = atlas_message_object_id(tool_call_id)
        if not object_id:
            return None
        if atlas_session and not str(session_id or "").strip():
            return None
        now, tz = _utc_now_iso()
        check_list = [dict(item) for item in (checks or []) if isinstance(item, dict)]
        effective_verified = bool(check_list) and all(
            bool(item.get("passed")) for item in check_list
        ) if verified is None else bool(verified)
        locator: dict[str, Any] = (
            {"kind": "TOOL_CALL", "value": f"{session_id}/{object_id}"}
            if atlas_session
            else {"kind": "AGENT_BACKEND_SESSION", "value": str(object_id)})
        overrides = (self._message_context(
            str(session_id), model_deployment_id=None, project_id=project_id,
            task_id=None) if atlas_session else
            {"runtime_session_id": f"agent-backend:{object_id}"})
        return self._capture(
            source_kind="ATLAS_VERIFICATION", source_object_id=object_id,
            source_revision=TOOL_REVISION_VERIFICATION,
            content={"phase": "verification", "tool": str(tool_name or "agent"),
                     "session_id": str(session_id or ""), "checks": check_list,
                     "verified": effective_verified},
            speaker_role="ATLAS", epistemic_kind="OBSERVED",
            occurred_at=occurred_at or now, source_timezone=tz,
            locator=locator, context_overrides=overrides)

    def enqueue_observation(self, observation: dict[str, Any], *,
                            context_overrides: dict[str, Any] | None = None,
                            ) -> dict[str, Any]:
        """通用观察入库入口（T02.3：USER_IMPORT 等由 WindowsSourceService 构造
        观察后经同一 outbox 幂等管线入库；同 ID 同内容 created=False）。"""
        return self._enqueue(observation, context_overrides)

    # ------------------------------------------------------------ 读取/flush

    def stats(self) -> dict[str, Any]:
        """outbox 状态（诊断用；队列不是可查询知识库）。"""
        if self._outbox is None and not self.outbox_path.exists():
            return {"total": 0, "new": 0, "sending": 0, "acked": 0, "retryable": 0,
                    "blocked": 0, "pending": 0,
                    "note": "outbox 未创建（尚无采集发生）"}
        return self._ensure_outbox().stats()

    async def flush(self, *, limit: int = 50,
                    backoff_seconds: float | None = None) -> dict[str, Any]:
        """单次 flush tick：把到期观察 POST /v1/unified/observe（outbox 状态机）。"""
        if self._facade is None:
            return {"skipped": True, "reason": "NO_FACADE", "outbox": self.stats(),
                    "note": "无 facade：观察留在本地 outbox 兜底，不丢失、不伪造成功"}
        async with self._flush_lock:
            from atlas.memory.outbox import DEFAULT_BACKOFF_SECONDS, flush_once

            return await flush_once(
                self._ensure_outbox(), self._facade, limit=limit,
                backoff_seconds=(DEFAULT_BACKOFF_SECONDS if backoff_seconds is None
                                 else backoff_seconds))

    def close(self) -> None:
        if self._outbox is not None:
            self._outbox.close()
            self._outbox = None


# ------------------------------------------------------------ 进程级单例

_capture_service: CaptureService | None = None
_capture_configured = False
_capture_singleton_lock = threading.Lock()
_observer_session_started: Callable[[str], None] | None = None


def register_observer_session_callback(
    callback: Callable[[str], None] | None,
) -> None:
    """Bind the lifespan-owned session-switch signal used by MemoryObserver."""
    global _observer_session_started
    _observer_session_started = callback


def notify_observer_session_started(session_id: str) -> None:
    """Signal a real foreground conversation start without doing background work."""
    callback = _observer_session_started
    if callback is None or not str(session_id or "").strip():
        return
    try:
        callback(str(session_id))
    except Exception as exc:  # noqa: BLE001 — observer scheduling must not break chat
        log.exception("memory.observer_session_signal_failed", error=str(exc))


def configure_capture_service(*, facade: Any = None, config: Any = None,
                              outbox: Any = None,
                              outbox_path: str | Path | None = None,
                              event_class: str | None = None,
                              context: dict[str, Any] | None = None,
                              ) -> CaptureService | None:
    """server lifespan 组装入口：enabled 才建实例；disabled 返回 None。"""
    global _capture_service, _capture_configured

    cfg = config if config is not None else _load_config()
    if not capture_enabled(cfg):
        _capture_configured = True
        return None
    with _capture_singleton_lock:
        if facade is None:
            from atlas.memory.unified_facade import UnifiedMemoryFacade

            facade = UnifiedMemoryFacade(config=cfg)
        service = CaptureService(facade=facade, config=cfg, context=context,
                                 outbox=outbox, outbox_path=outbox_path,
                                 event_class=event_class)
        _capture_service = service
        _capture_configured = True
        return service


def get_capture_service() -> CaptureService | None:
    """接线点取用入口；未组装时按全局配置惰性组装一次（CLI 等入口同样生效）。

    disabled / 配置系统不可用 → None（接线点必须容忍 None 并直接返回）。
    """
    global _capture_configured

    if _capture_service is not None or _capture_configured:
        return _capture_service
    with _capture_singleton_lock:
        if _capture_service is not None or _capture_configured:
            return _capture_service
        _capture_configured = True
        cfg = _load_config()
        if not capture_enabled(cfg):
            return None
        from atlas.memory.unified_facade import UnifiedMemoryFacade

        service = CaptureService(facade=UnifiedMemoryFacade(config=cfg), config=cfg)
        globals()["_capture_service"] = service
        return service


def reset_capture_service() -> None:
    """丢弃进程级单例（server lifespan 关停 / 测试隔离用）。仅关服务自持的 outbox。"""
    global _capture_service, _capture_configured

    with _capture_singleton_lock:
        service = _capture_service
        _capture_service = None
        _capture_configured = False
    if service is not None:
        service.close()


async def capture_flush_loop(service: CaptureService, *,
                             idle_seconds: float = 30.0,
                             after_flush_tick: Callable[[], None] | None = None) -> None:
    """事件驱动的后台 flush 循环（server lifespan 启动/取消）。

    * 本服务每次成功入队都会唤醒循环，立即把新观察 flush 出去；
    * 空闲期每 ``idle_seconds`` 秒兜底 flush 一次，处理 RETRYABLE 退避到期、
      上一进程遗留的 outbox 行（重启回收）；
    * flush_once 自带退避/租约恢复：服务不可达时观察留在本地 outbox（RETRYABLE），
      循环本身对任何异常免疫，只记录日志。
    """
    wake = asyncio.Event()
    service.attach_wake(wake)
    while True:
        try:
            await service.flush()
            if after_flush_tick is not None:
                try:
                    after_flush_tick()
                except Exception as exc:  # noqa: BLE001 — callback must not stop source flush
                    log.exception("memory.capture_after_flush_callback_failed", error=str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — flush 失败不终止循环
            log.warning("memory.capture_flush_loop_error", error=str(exc))
        try:
            await asyncio.wait_for(wake.wait(), timeout=idle_seconds)
        except asyncio.TimeoutError:
            pass
        wake.clear()
