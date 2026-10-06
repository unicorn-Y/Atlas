"""Observation capture builder — Atlas side (UM02 / T02.1).

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
    稳定对象 ID；重试沿用，不生成新 UUID（§2）。本波只提供 builder；真实
    消息/工具事件接入在 T02.2（run_phases / tool_node 不属本任务范围）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

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
