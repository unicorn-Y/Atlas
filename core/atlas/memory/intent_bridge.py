"""IntentBridge — 统一意图 → 既有 Automation 的投影与事件适配（UM06 / T06.3）.

职责边界（02_wave_tasks T06.3；权威分割的 Atlas 半边）：

  * **MemoryOS 管意图及依据**（unified_intents / unified/intentions.py），
    **Atlas Automation 仍管触发/运行**（automation/store.py 产品状态 +
    engine.py DBOS durable 调度）—— 双方通过稳定 intent ID / automation ID
    绑定：``automation_id = "um-intent-" + intent_id``（可双向解析，
    :func:`automation_id_for_intent` / :func:`intent_id_from_automation`）。
  * 本模块是**映射层**：:meth:`IntentBridge.create_automation_for_intent`
    把意图投影成 ``data/automations.toml`` §4 冻结字段的记录结构
    （cron/date/event trigger），**不直接写 store** —— store/engine 写入
    路径属引擎侧，桥只产出配置对象 + 调用说明（偏差登记见
    :data:`ENGINE_WIRING`；结构合法性由单测用临时 TOML store 验证）。
  * **事件适配，不另造 scheduler**：project_open / tool_result / record_updated
    三类 Atlas 事件 → :meth:`IntentBridge.handle_atlas_event`（cue 匹配纯函数
    :func:`event_matches_cue`）→ 服务端 transition TRIGGERED（带触发 receipt）。
    Automation 侧回调入口是 :meth:`IntentBridge.on_automation_event`（引擎
    date/event trigger 真实 fire 后回写 lifecycle 用）。
  * **触发器不改事实权威**：本模块只回写 lifecycle + receipt，不执行意图的
    action；取消/延期/完成与触发竞争以 expected_revision 版本校验阻止重复
    （409 RevisionConflict → 不重复触发，返回 fired=False）。
  * cue 匹配语义与 MemoryOS ``intentions.cue_match`` 完全一致（事件类型 +
    条件子集、任一侧 list 即 any-of）—— 两仓库各自实现的**同一判据**（不跨
    仓库 import 是既定边界；两侧单测互为对照锁定行为一致）。

**engine 挂接状态（F3-B2 更新）**：

  时间条件意图已真挂接：``persist_automation_for_intent`` → ``reminders`` →
  ``AutomationStore``（automations.toml）+ ``AutomationEngine.sync_automation``，
  观察者落库收口（``observer_drain._persist_intents``）在 ACK 后自动投影。
  **事件 cue 未统一**：Atlas 事件产生点分散，事件触发仍靠调用方直调
  ``handle_atlas_event``；engine.py / triggers.py 的**回调**挂接行未落
  （挂接点如下，engine 侧调用方已有事件循环）::

      # atlas/automation/engine.py  AutomationEngine.start_async() 末尾
      #   （attach_triggers 之后）：
      self.intent_bridge = IntentBridge.from_config()

      # atlas/automation/triggers.py  EventTriggerManager._submit() 的
      #   _fire() 内（或未来的统一事件分发点），fire 后回写：
      await self.intent_bridge.on_automation_event(automation_id, {...})

      # Atlas 侧事件产生点（project_open / tool_result / record_updated）
      # 在各自的采集/工具管线里调用：
      await self.intent_bridge.handle_atlas_event("project_open", payload)

  在挂接前，测试与调用方经 :meth:`handle_atlas_event` 直调（本波集成测试
  即如此），Automation 投影仍经 :meth:`create_automation_for_intent` 产出。
"""

from __future__ import annotations

import structlog
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from atlas.memory.unified_client import (
    RevisionConflict,
    UnifiedMemoryClient,
    UnifiedMemoryError,
)
from atlas.memory.unified_facade import UnifiedMemoryFacade

log = structlog.get_logger()

# create_reminder 判定「同源 Automation 已被取消」的两种 reason（见
# atlas.automation.reminders.create_reminder）：命中即说明该意图的 Automation
# 半边已经停用，意图必须随之终态化，避免「意图 ACTIVE、Automation 已停用」。
_INTENT_TERMINAL_REASONS = frozenset(
    {"source_reminder_cancelled", "automation_cancelled"})

#: automation_id 前缀（稳定绑定：um-intent-<intent_id>；ID_PATTERN 兼容 ——
#: intent_id 生成规则 "int-" + hex 与 [A-Za-z0-9_-]{1,100} 相容）
AUTOMATION_ID_PREFIX = "um-intent-"

#: 本波适配的 Atlas 事件集（与 MemoryOS intentions.ATLAS_EVENT_TYPES 同集；
#: 匹配器对事件类型开放 —— 这是适配集登记，不是校验边界）
ATLAS_EVENT_TYPES = ("project_open", "tool_result", "record_updated")

#: 触发 receipt kinds（回写 TRIGGERED 时附带给服务端的依据）
RECEIPT_AUTOMATION_EVENT = "automation_event"
RECEIPT_ATLAS_EVENT = "atlas_event"

#: intent cue 的事件种类（与 MemoryOS CUE_KINDS 同集）
CUE_KINDS = ("time", "event")


class IntentBridgeError(Exception):
    """IntentBridge 参数/形状错误（本地形状错误，先于 HTTP 传输）。"""


def automation_id_for_intent(intent_id: str) -> str:
    """intent_id → 绑定 automation_id（稳定映射，两仓库共享约定）。"""
    text = str(intent_id or "").strip()
    if not text:
        raise IntentBridgeError("intent_id 不能为空")
    return AUTOMATION_ID_PREFIX + text


def intent_id_from_automation(automation_id: str) -> str | None:
    """绑定 automation_id → intent_id；非本桥前缀的 automation → None
    （其他产品 Automation 与统一意图无关，绝不误伤）。"""
    text = str(automation_id or "").strip()
    if not text.startswith(AUTOMATION_ID_PREFIX):
        return None
    intent_id = text[len(AUTOMATION_ID_PREFIX):]
    return intent_id or None


def event_matches_cue(cue: Any, event_type: str, payload: Any = None) -> bool:
    """纯函数：事件意图 cue 对 Atlas 事件的匹配判据（T06.3 三类事件适配）。

    与 MemoryOS ``intentions.cue_match`` 同一语义（事件类型相等 + conditions
    子集相等；任一侧 list 语义 any-of）；类型不符 / 缺字段 → False（不抛错，
    engine 挂接点可安全批量调用）。event 的 Atlas 适配集：
    project_open / tool_result / record_updated。
    """
    if not isinstance(cue, dict) or str(cue.get("kind") or "") != "event":
        return False
    if str(cue.get("event_type") or "") != str(event_type or ""):
        return False
    payload = payload if isinstance(payload, dict) else {}
    conditions = cue.get("conditions")
    if not isinstance(conditions, dict):
        return True
    for key, wanted in conditions.items():
        got = payload.get(key)
        if isinstance(wanted, list):
            if got not in wanted:
                return False
        elif isinstance(got, list):
            if wanted not in got:
                return False
        elif got != wanted:
            return False
    return True


def projection_for_intent(intent: dict[str, Any], *,
                          event_inbox_dir: str | None = None) -> dict[str, Any]:
    """纯函数：统一意图 → Automation 产品记录（§4 冻结字段形状）。

    投影规则（cue/action → trigger/payload；T06.3「用现有 Automation trigger」）：

      * time cue（due_at）→ ``trigger.kind="date"``、``trigger.at=due_at``
        （引擎 date 触发一次性到期 fire）；
      * event cue → ``trigger.kind="event"``、``event_path=<事件收件箱目录>``
        （事件触发；真实送达路径是 :meth:`IntentBridge.handle_atlas_event`，
        引擎挂接前 event_path 只是结构合法的声明位 —— 偏差如实标注）；
      * 都没有 → 投影失败（无触发面，只能人工触发 —— 不为它造 scheduler）；
      * action → ``payload.kind="agent_turn"``，message 内嵌 intent_ref 与
        回写指令（执行侧经 transition 回写 RUNNING/COMPLETED，带依据）。

    返回 normalize_record 可直接消费的 dict（validate_record 合法性由单测
    经临时 TOML store 验证）。**不写 store** —— 本函数纯内存。
    """
    intent_id = str(intent.get("intent_id") or "").strip()
    if not intent_id:
        raise IntentBridgeError("投影需要 intent_id（unified_intents 行）")
    action = intent.get("action") if isinstance(intent.get("action"), dict) else {}
    cue = intent.get("cue") if isinstance(intent.get("cue"), dict) else None
    due_at = str(intent.get("due_at") or "").strip()
    cue_at = str((cue or {}).get("at") or "").strip()
    effective_due = due_at or (cue_at if (cue or {}).get("kind") == "time" else "")
    is_event_cue = bool(cue) and cue.get("kind") == "event"

    if not effective_due and not is_event_cue:
        raise IntentBridgeError(
            f"意图 {intent_id} 无 time cue（due_at）也无 event cue —— 无 Automation "
            "触发面可投影（不另造 scheduler；人工触发走 run-now，偏差留引擎侧）")

    intent_ref = f"intent:{intent_id}"
    automation_id = automation_id_for_intent(intent_id)
    message = (
        f"[unified intent {intent_ref}] "
        f"{action.get('message') or action.get('kind') or '执行意图动作'} "
        f"（action.kind={action.get('kind') or 'unknown'}；条件："
        f"{intent.get('condition') or '无'}）。这是统一意图的到期/事件触发投影 —— "
        "请记录执行 receipt 并经 POST /v1/unified/intents/{id}/transition 回写 "
        "RUNNING/COMPLETED（COMPLETED 必须带结果依据；调度器不改事实权威）。")

    if is_event_cue:
        trigger = {
            "kind": "event",
            "event_path": str(event_inbox_dir or "./unified-events"),
            "event_glob": str(cue.get("event_type") or ""),
            "event_debounce": 0.0,
        }
        trigger_basis = f"event:{cue.get('event_type')}"
    else:
        trigger = {"kind": "date", "at": effective_due}
        trigger_basis = f"date:{effective_due}"

    return {
        "id": automation_id,
        "name": f"统一意图 {intent_ref}（{action.get('kind') or 'action'}）",
        "enabled": True,
        "owner_agent_id": "",
        "trigger": trigger,
        "payload": {"kind": "agent_turn", "message": message,
                    "wake_mode": "now"},
        "delivery": {"mode": "none"},
        "policy": {"missed_run": "skip", "delete_after_run": False},
        "intent_projection": {
            "intent_ref": intent_ref,
            "intent_id": intent_id,
            "trigger_basis": trigger_basis,
            "cue": cue,
            "binding": "automation_id = um-intent-<intent_id>（双向可解析）",
        },
    }


# ------------------------------------------- 记忆记录 → 意图行（F3-B3 收口）

#: 用户直接来源的 chain key 前缀（T06.3：意图的 ACTIVE 授权只来自来源验证）
USER_SOURCE_CHAIN_PREFIX = "ATLAS_USER_MESSAGE:"

#: 证据来源事件 id 前缀（``atlas:<KIND>:<object_id>:<revision>:<op>``）
SOURCE_EVENT_PREFIX = "atlas:"


def user_source_ref_from_record(record: Mapping[str, Any]) -> str | None:
    """INTENT 记忆记录 → 用户直接来源引用（``ATLAS_USER_MESSAGE:<object_id>``）。

    **只认用户自己的发言**：证据链 ``content.evidence_chains.chain_keys`` 优先，
    退化到 ``source_refs[*].source_event_id`` 的
    ``atlas:<KIND>:<object_id>:<revision>:<op>`` 解析。派生摘要
    （``DERIVED:observer-…``）、工具结果与助手消息一律不采用 —— 意图行要有用户
    直接授权来源才可能 ACTIVE（§4 来源纪律 / T06.3）。取不到 → None（调用方
    如实跳过，不伪造授权来源）。
    """
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    source_events = metadata.get("source_events")
    authoritative_refs: set[str] = set()
    if isinstance(source_events, list):
        for event in source_events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("source_event_id") or "").strip()
            parts = event_id.split(":")
            if len(parts) == 5 and parts[0] == "atlas" \
                    and parts[1] == "ATLAS_USER_MESSAGE" and parts[2].strip():
                authoritative_refs.add(USER_SOURCE_CHAIN_PREFIX + parts[2].strip())
    if len(authoritative_refs) == 1:
        return next(iter(authoritative_refs))

    content = record.get("content")
    content = content if isinstance(content, dict) else {}
    chains = content.get("evidence_chains")
    chains = chains if isinstance(chains, dict) else {}
    candidates: list[Any] = list(chains.get("chain_keys") or [])
    for ref in record.get("source_refs") or []:
        candidates.append(ref.get("source_event_id") if isinstance(ref, dict) else ref)
    for item in candidates:
        text = str(item or "").strip()
        if text.startswith(USER_SOURCE_CHAIN_PREFIX):
            return text
        if text.startswith(SOURCE_EVENT_PREFIX + USER_SOURCE_CHAIN_PREFIX):
            parts = text.split(":")
            if len(parts) >= 4 and parts[2].strip():
                return USER_SOURCE_CHAIN_PREFIX + parts[2].strip()
    return None


def source_binding_from_record(record: Mapping[str, Any]) -> dict[str, str]:
    """Return only source identifiers projected from the true USER evidence."""
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    binding: dict[str, str] = {}
    run_id = metadata.get("request_run_id")
    if isinstance(run_id, str) and run_id.strip():
        binding["request_run_id"] = run_id.strip()
    source_ref = user_source_ref_from_record(record)
    if source_ref:
        binding["source_message_ref"] = source_ref
    return binding


def aware_iso(raw: Any) -> str:
    """带时区 ISO 8601 → 原文本；naive / 非法 → 空串。

    naive 时刻不假装绝对时间（§2 时间纪律）—— 宁可判"无到期时刻"也不替用户
    猜时区。
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return ""
    return text if parsed.tzinfo is not None else ""


def same_instant(left: Any, right: Any) -> bool:
    """两个 ISO 时刻是否同一瞬间（时区写法和字符串形式无关）；不可解析 → False。"""
    parsed: list[datetime] = []
    for raw in (left, right):
        text = str(raw or "").strip()
        if not text:
            return False
        try:
            value = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            return False
        if value.tzinfo is None:
            return False
        parsed.append(value)
    return parsed[0] == parsed[1]


def record_due_at(record: Mapping[str, Any]) -> str:
    """记录 → 带时区到期时刻（``valid_time.valid_from`` 优先，退化 title/value）。"""
    valid_time = record.get("valid_time")
    valid_time = valid_time if isinstance(valid_time, dict) else {}
    content = record.get("content")
    content = content if isinstance(content, dict) else {}
    for raw in (valid_time.get("valid_from"), content.get("title"),
                content.get("value")):
        due = aware_iso(raw)
        if due:
            return due
    return ""


def record_reminder_text(record: Mapping[str, Any]) -> str:
    """记录 → 提醒正文（``content`` 的 text/summary 优先，退化标题 → "提醒"）。"""
    content = record.get("content")
    content = content if isinstance(content, dict) else {}
    for key in ("text", "summary", "statement", "title"):
        value = content.get(key)
        if str(value or "").strip():
            return str(value).strip()
    return "提醒"


def intent_request_from_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """INTENT 记忆记录 → ``POST /v1/unified/intents`` 请求体；不合格 → None。

    资格（缺一不可，缺则**如实跳过**、不伪造意图行）：facet/``memory_type`` ==
    ``INTENT`` 且生命周期 ACTIVE；有用户直接来源引用；有**带时区**的绝对到期
    时刻。服务端仍会独立查证来源（VERIFIED → ACTIVE，否则 PROPOSED）—— 桥不
    代替服务端判定授权，只保证请求字段齐全。
    """
    facet = str(record.get("facet") or record.get("memory_type") or "").upper()
    if facet and facet != "INTENT":
        return None
    lifecycle = str(record.get("lifecycle") or record.get("status")
                    or "ACTIVE").upper()
    if lifecycle != "ACTIVE":
        return None
    user_source_ref = user_source_ref_from_record(record)
    if not user_source_ref:
        return None
    due = record_due_at(record)
    if not due:
        return None
    return {
        "user_source_ref": user_source_ref,
        "cue": {"kind": "time", "at": due},
        "action": {"kind": "remind", "message": record_reminder_text(record)},
        "due_at": due,
    }


#: engine 挂接说明（机器可读；测试断言其存在与锚点正确）
#:
#: F3-B2 起：**时间条件意图的真实建任务已落**（``persist_automation_for_intent``
#: 直接 store.put + engine.sync_automation，见下）。事件 cue 意图仍只产配置对象
#: （事件分发点未统一），故 ``wired`` 记 True 而 ``event_wired`` 记 False —— 不
#: 把"半个挂接"说成全部挂接。
ENGINE_WIRING = {
    "wired": True,
    "reason": "F3-B2：时间条件意图经 persist_automation_for_intent 真实写入 "
              "AutomationStore 并 sync 到既有 AutomationEngine（不另造 scheduler）；"
              "事件 cue 意图仍只产配置对象（事件分发点未统一），见 event_wired。",
    "event_wired": False,
    "anchors": [
        {"file": "core/atlas/automation/engine.py",
         "function": "AutomationEngine.start_async",
         "line": "attach_triggers 之后：self.intent_bridge = IntentBridge.from_config()"},
        {"file": "core/atlas/automation/triggers.py",
         "function": "EventTriggerManager._submit._fire",
         "line": "await self.intent_bridge.on_automation_event(automation_id, {...})"},
        {"file": "core/atlas/memory/intent_bridge.py",
         "function": "IntentBridge.handle_atlas_event",
         "line": "Atlas 事件产生点（采集/工具管线）直调直至统一事件分发点建立"},
        {"file": "core/atlas/memory/observer_drain.py",
         "function": "MemoryObserverDrain._persist_intents",
         "line": "ACK 后新 INTENT（带时间条件）→ intent_bridge.persist_automation_for_intent"},
    ],
    "store_write": "persist_automation_for_intent（时间 cue）经 reminders.create_reminder "
                   "真实写 automations.toml（AutomationStore）+ engine.sync_automation；"
                   "create_automation_for_intent 仍只产出配置对象（事件 cue 用）",
}


class IntentBridge:
    """统一意图 ↔ Automation 桥：投影、事件适配、触发回写、取消说明。

    用法（engine 侧挂接后的形状；挂接前 handle_atlas_event 直调）::

        bridge = IntentBridge.from_config()
        projection = bridge.create_automation_for_intent(intent)   # 配置对象
        await bridge.on_automation_event(automation_id, event)     # 引擎 fire 回写
        await bridge.handle_atlas_event("project_open", payload)   # 事件适配
        await bridge.cancel_intent(intent_id)                      # 取消 + 说明
    """

    def __init__(self, facade: UnifiedMemoryFacade | None = None,
                 client: UnifiedMemoryClient | None = None, *,
                 event_inbox_dir: str | None = None,
                 config: Any = None) -> None:
        if facade is None and client is None:
            raise IntentBridgeError(
                "IntentBridge 需要 facade 或 client 之一（不自行装配配置）")
        self._facade = facade
        self._client_override = client
        self._event_inbox_dir = event_inbox_dir
        self._config = config if config is not None else getattr(facade, "_config", None)

    @classmethod
    def from_config(cls, config: Any = None) -> IntentBridge:
        if config is None:
            from atlas.config import get_config

            config = get_config()
        return cls(facade=UnifiedMemoryFacade.from_config(config), config=config)

    @property
    def enabled(self) -> bool:
        return bool(self._facade.enabled) if self._facade is not None else True

    def client(self) -> UnifiedMemoryClient:
        if self._client_override is not None:
            return self._client_override
        assert self._facade is not None
        return self._facade.client()

    def _context(self, context: dict[str, Any] | None) -> dict[str, Any] | None:
        """请求 context：显式传入优先；缺省用 facade 配置绑定骨架，并在
        runtime_session_id 为空时生成桥侧会话 ID（服务端 §1 校验拒绝空会话）。

        client-only 桥（无 facade）没有配置绑定的主体 —— §1 纪律禁止本桥
        编造身份，必须由调用方显式传 context（缺 → IntentBridgeError）。
        """
        if context is not None:
            return context
        if self._facade is None:
            raise IntentBridgeError(
                "client-only IntentBridge 需要显式 context（§1：主体绑定来自"
                "服务配置，本桥不编造身份）")
        skeleton = self._facade.default_context()
        if not str(skeleton.get("runtime_session_id") or "").strip():
            skeleton["runtime_session_id"] = \
                "intent-bridge-" + uuid.uuid4().hex[:8]
        return skeleton

    # ------------------------------------------------------------------ 投影

    def create_automation_for_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        """意图 → Automation 配置对象 + 引擎侧调用说明（**不写 store**）。

        返回::

            {
              "automation": <§4 冻结字段记录（normalize_record 可直接消费）>,
              "intent_projection": {...},          # 绑定与 trigger 依据
              "instructions": {                    # 引擎侧两步（本桥不执行）
                "persist": "engine 侧 store.put(record) 或 engine.sync_automation(record)",
                "activate": "engine 侧按 enabled=True 建 DBOS schedule/date run",
                "wired": False, "note": ...},
            }

        投影失败（无触发面）→ IntentBridgeError；时间/事件解析错误在引擎侧
        validate_record 兜底（本桥只产结构）。
        """
        projection = projection_for_intent(intent,
                                           event_inbox_dir=self._event_inbox_dir)
        record = {key: value for key, value in projection.items()
                  if key != "intent_projection"}
        return {
            "automation": record,
            "intent_projection": projection["intent_projection"],
            "instructions": {
                "persist": ("store.put(record) 后 engine.sync_automation(record)"
                            "（或 run-phases 内既有的 automation CRUD 入口）；"
                            "本桥不写 data/automations.toml"),
                "activate": ("enabled=True 时由引擎建 DBOS schedule（date/"
                             "event）；EventTriggerManager.sync() 重建监听"),
                "wired": ENGINE_WIRING["wired"],
                "note": ENGINE_WIRING["reason"],
            },
        }

    # -------------------------------------------------------------- 真实建任务

    @staticmethod
    def _reminder_text(intent: dict[str, Any]) -> str:
        """意图 → 提醒正文（action.message 优先；退化到意图正文；再退化到 action.kind）。"""
        action = intent.get("action")
        action = action if isinstance(action, dict) else {}
        for key in ("message", "text", "summary", "title"):
            value = action.get(key)
            if str(value or "").strip():
                return str(value).strip()
        for key in ("text", "summary", "content", "statement"):
            value = intent.get(key)
            if str(value or "").strip():
                return str(value).strip()
        return str(action.get("kind") or "提醒").strip()

    @staticmethod
    def _time_due(intent: dict[str, Any]) -> str:
        """意图的时间触发面：due_at 优先，其次 time cue 的 at；无 → 空串。"""
        cue = intent.get("cue")
        cue = cue if isinstance(cue, dict) else {}
        direct = str(intent.get("due_at") or "").strip()
        if direct:
            return direct
        if str(cue.get("kind") or "") == "time":
            return str(cue.get("at") or "").strip()
        return ""

    async def persist_automation_for_intent(self, intent: dict[str, Any], *,
                                            engine: Any = None,
                                            now: Any = None) -> dict[str, Any]:
        """统一意图 → **真实** Automation（F3-B2 主链路；不另造 scheduler）。

        时间条件意图（``due_at`` 或 time cue）经
        :func:`atlas.automation.reminders.create_reminder` 真写
        ``data/automations.toml`` 并 ``engine.sync_automation`` 到既有
        AutomationEngine；automation_id 用稳定绑定
        ``um-intent-<intent_id>``（重放/双链路幂等，不产生第二条）。

        event cue 意图**不在此建**（事件分发点未统一）→ 返回
        ``{"created": False, "reason": "event_cue_not_wired"}``，其配置对象仍由
        :meth:`create_automation_for_intent` 产出（偏差如实登记在
        :data:`ENGINE_WIRING`）。
        """
        intent_id = str(intent.get("intent_id") or "").strip()
        if not intent_id:
            raise IntentBridgeError("持久化需要 intent_id（unified_intents 行）")
        lifecycle = str(intent.get("lifecycle") or "ACTIVE").upper()
        if lifecycle != "ACTIVE":
            return {"created": False, "reason": f"intent_{lifecycle.lower()}",
                    "intent_id": intent_id,
                    "automation_id": automation_id_for_intent(intent_id)}
        due = self._time_due(intent)
        if not due:
            cue = intent.get("cue")
            cue = cue if isinstance(cue, dict) else {}
            reason = ("event_cue_not_wired" if str(cue.get("kind") or "") == "event"
                      else "no_time_cue")
            return {"created": False, "reason": reason, "intent_id": intent_id,
                    "automation_id": automation_id_for_intent(intent_id)}
        from atlas.automation import reminders as reminder_service

        source_binding = intent.get("source_binding")
        source_binding = dict(source_binding) if isinstance(source_binding, dict) else {}
        source_binding["intent_id"] = intent_id
        result = await reminder_service.create_reminder(
            message=self._reminder_text(intent), due_at=due,
            automation_id=automation_id_for_intent(intent_id),
            source_binding=source_binding,
            now=now, engine=engine, config=self._config)
        result["intent_id"] = intent_id
        result["automation_id"] = (result.get("automation") or {}).get("id")
        automation = result.get("automation") or {}
        if (str(result.get("reason") or "") not in _INTENT_TERMINAL_REASONS
                and automation.get("id") and automation.get("enabled") is not False):
            # 落库后复查：意图可能在 drain 确认 ACTIVE 之后、Automation 落库
            # 之前被取消（此时取消侧找不到 Automation，什么也没停）。以 MemoryOS
            # 里持久的终态意图为墓碑，晚到的落库立即停用，保证取消后不再触发。
            lifecycle = await self._current_lifecycle(intent_id)
            if lifecycle in {"CANCELLED", "EXPIRED"}:
                cancelled = await reminder_service.cancel_reminder(
                    automation_id=str(automation["id"]),
                    now=now, engine=engine, config=self._config)
                result["created"] = False
                result["reason"] = f"intent_{lifecycle.lower()}_after_persist"
                if cancelled.get("automation"):
                    result["automation"] = cancelled["automation"]
                log.info("memory.intent_automation_disabled_late",
                         intent_id=intent_id, lifecycle=lifecycle)
                return result
        if str(result.get("reason") or "") in _INTENT_TERMINAL_REASONS:
            # 目标 Automation 在意图投影之前就已被取消（工具取消先于观察者
            # drain 落意图）→ 意图随之终态化，否则 MemoryOS 会留下「意图
            # ACTIVE、对应 Automation 已停用」的口径矛盾（F4-B §2.2
            # 「取消同步更新 intent」）。
            result["intent_terminalized"] = await self._terminalize_intent(
                intent_id, intent)
        return result

    async def _current_lifecycle(self, intent_id: str) -> str | None:
        """读 MemoryOS 里意图当前 lifecycle；读不到返回 None（不据此误停任务）。"""
        try:
            listing = await self.client().call(
                "GET", "/v1/unified/intents", params={"intent_id": intent_id})
        except Exception as exc:  # noqa: BLE001 — 复查尽力而为，不阻塞建任务
            log.warning("memory.intent_lifecycle_lookup_failed",
                        intent_id=intent_id, error=str(exc), exc_info=True)
            return None
        items = listing.get("items") if isinstance(listing, dict) else listing
        for row in items or []:
            if isinstance(row, dict) and str(row.get("intent_id") or "") == intent_id:
                return str(row.get("lifecycle") or "").upper() or None
        return None

    async def _terminalize_intent(self, intent_id: str,
                                  intent: Mapping[str, Any]) -> dict[str, Any]:
        """把意图转到 CANCELLED 终态（终态自环幂等，重放安全）。"""
        body: dict[str, Any] = {"transition": "CANCELLED"}
        revision = intent.get("revision")
        if revision is not None:
            body["expected_revision"] = int(revision)
        try:
            # 服务端 §1 要求请求携带统一 MemoryContext；与 ensure_intent_from_record
            # 同源取法（facade 配置绑定的骨架，桥不编造身份）。
            ctx = self._context(None)
        except IntentBridgeError as exc:
            log.warning("memory.intent_terminalize_failed", intent_id=intent_id,
                        error=str(exc))
            return {"terminalized": False, "error": str(exc)}
        if ctx is not None:
            body["context"] = ctx
        try:
            payload = await self.client().transition_intent(str(intent_id), body)
        except UnifiedMemoryError as exc:
            log.warning("memory.intent_terminalize_failed", intent_id=intent_id,
                        error=str(exc))
            return {"terminalized": False, "error": str(exc)}
        return {"terminalized": True,
                "lifecycle": (payload or {}).get("lifecycle"),
                "revision": (payload or {}).get("revision")}

    # ------------------------------------------ 记忆记录 → 意图行（F3-B3 收口）

    async def find_intent_for_record(self, record: Mapping[str, Any]
                                     ) -> dict[str, Any] | None:
        """按 source + due instant + unique action 在已存 intent 里查重。

        ``GET /v1/unified/intents`` 只支持 lifecycle / intent_id / automation_id /
        subject 过滤（无 user_source_ref）→ 拉 ACTIVE 后本地按来源引用 + 到期时刻
        精确比对：同来源同时刻 = 同一意图，重放不产生第二条意图行。不合格记录 →
        None（调用方退回 POST 路径）。
        """
        request = intent_request_from_record(record)
        if request is None:
            return None
        listing = await self.client().call(
            "GET", "/v1/unified/intents", params={"limit": 200})
        items = listing.get("items") if isinstance(listing, dict) else listing
        from atlas.automation.reminders import _same_action

        matches: list[dict[str, Any]] = []
        for row in items or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("user_source_ref") or "").strip() != request["user_source_ref"]:
                continue
            if not same_instant(self._time_due(row), request["due_at"]):
                continue
            existing_action = row.get("action")
            existing_action = existing_action if isinstance(existing_action, dict) else {}
            if _same_action(str(existing_action.get("message") or ""),
                            str((request.get("action") or {}).get("message") or "")):
                matches.append(row)
        if not matches:
            return None
        # 规范化（提交→交 等）会让「提交报告」与「交报告」同判，二者同源同时刻
        # 并存时（例如一条已取消、一条仍 ACTIVE）绝不能凭 created_at（秒精度，
        # 同秒并列）随便挑最新：先取正文归一后**完全相同**的，才退回等价写法。
        from atlas.automation.reminders import _core_text

        wanted = _core_text(str((request.get("action") or {}).get("message") or ""))
        exact = [row for row in matches
                 if _core_text(str((row.get("action") or {}).get("message") or ""))
                 == wanted]
        if exact:
            matches = exact
        # F4-B 去重契约（任务书 §2.1「同一个意图只产生一个 Automation 任务」
        # 「不得建出第二个」）：同一 (source, due, action) 命中多条时取**最新**
        # 一条（当前态）复用，绝不因歧义再建新行。listing 按 created_at 升序，
        # 末条即最新。歧义只记日志，不影响选择。
        if len(matches) > 1:
            log.warning(
                "memory.intent_bridge_ambiguous_match",
                user_source_ref=request["user_source_ref"],
                due_at=request["due_at"], match_count=len(matches),
                picked_intent_id=matches[-1].get("intent_id"),
            )
        return matches[-1]

    async def ensure_intent_from_record(self, record: Mapping[str, Any], *,
                                        context: dict[str, Any] | None = None
                                        ) -> dict[str, Any]:
        """INTENT 记忆记录 → **真实** ``unified_intents`` 行（F3-B3 收口；幂等）。

        链路：观察者形成带时间 cue 的用户意图记忆 → 本条投影成意图行（服务端查证
        ``user_source_ref`` → ACTIVE）→ :meth:`persist_automation_for_intent` 用其
        ``intent_id`` 建真实 Automation（``um-intent-<intent_id>``）。

        幂等：先 :meth:`find_intent_for_record` 查现有 ACTIVE 意图，命中即复用
        （``created`` False）；否则 POST 建立。不合格记录 → ``reason`` 说明后如实
        跳过 —— 不伪造意图行、不假装成功。
        """
        request = intent_request_from_record(record)
        if request is None:
            return {"created": False, "reason": "not_eligible", "intent_id": None,
                    "intent": None, "request": None}
        existing = await self.find_intent_for_record(record)
        binding = source_binding_from_record(record)
        if existing is not None:
            if str(existing.get("lifecycle") or "").upper() != "ACTIVE":
                return {"created": False, "reason": "existing_terminal_intent",
                        "intent_id": existing.get("intent_id"), "intent": existing,
                        "request": request, "source_binding": binding}
            return {"created": False, "reason": "already_exists",
                    "intent_id": existing.get("intent_id"), "intent": existing,
                    "request": request, "source_binding": binding}
        body: dict[str, Any] = dict(request)
        if (ctx := self._context(context)) is not None:
            body["context"] = ctx
        payload = await self.client().create_intent(body)
        return {"created": True, "reason": "created",
                "intent_id": payload.get("intent_id"), "intent": payload,
                "lifecycle": payload.get("lifecycle"), "request": request,
                "source_binding": binding}

    @staticmethod
    def persist_input_from_record(ensured: Mapping[str, Any]
                                  ) -> dict[str, Any] | None:
        """``ensure_intent_from_record`` 结果 → ``persist_automation_for_intent`` 输入。

        以服务端意图行为准（intent_id / cue / due_at / action），记录侧请求字段只
        补缺 —— 持久化不依赖服务端是否回显 cue/due_at（少一次字段回显就掉链的
        脆性）。无 intent_id → None（调用方如实跳过）。
        """
        intent_id = str(ensured.get("intent_id") or "").strip()
        if not intent_id:
            return None
        request = ensured.get("request")
        request = request if isinstance(request, dict) else {}
        row = ensured.get("intent")
        row = dict(row) if isinstance(row, dict) else {}
        lifecycle = str(ensured.get("lifecycle") or row.get("lifecycle") or "").upper()
        if lifecycle and lifecycle != "ACTIVE":
            return None
        row["intent_id"] = intent_id
        for key in ("cue", "due_at", "action"):
            if not row.get(key) and request.get(key):
                row[key] = request[key]
        source_binding = ensured.get("source_binding")
        if isinstance(source_binding, dict) and source_binding:
            row["source_binding"] = dict(source_binding)
        return row

    async def cancel_automation_for_intent(self, intent_id: str, *,
                                           engine: Any = None,
                                           now: Any = None) -> dict[str, Any]:
        """统一意图取消 → 对应 Automation 停用（保留记录，可审计）。"""
        from atlas.automation import reminders as reminder_service

        automation_id = automation_id_for_intent(intent_id)
        try:
            store = reminder_service._engine(engine).store
            matches = [record for record in store.list()
                       if str((record.get("source_binding") or {}).get("intent_id") or "")
                       == str(intent_id)]
            if len(matches) == 1:
                automation_id = str(matches[0].get("id") or automation_id)
        except Exception as exc:  # noqa: BLE001 — fall back to legacy stable ID lookup
            log.debug("intent_bridge.cancel_automation_for_intent_failed", error=str(exc), exc_info=True)
        result = await reminder_service.cancel_reminder(
            automation_id=automation_id,
            now=now, engine=engine)
        result["intent_id"] = str(intent_id)
        return result

    # ------------------------------------------------------------------ 触发回写

    async def on_automation_event(self, automation_id: str,
                                  event: dict[str, Any] | None = None, *,
                                  context: dict[str, Any] | None = None,
                                  engine: Any = None,
                                  ) -> dict[str, Any]:
        """Automation fire 回调 → 服务端 transition TRIGGERED（带触发 receipt）。

        引擎 date/event trigger 真实 fire 后的回写入口（挂接前由测试/调用方
        直调）：

          * automation_id 非 um-intent- 前缀 → 不属于统一意图，原样跳过
            （{"fired": False, "reason": "not_intent_automation"}）；
          * 意图不存在 / lifecycle 非 ACTIVE（已取消/过期/已触发）→ 不触发；
          * expected_revision 冲突（取消/延期与触发竞争）→ 不触发不重试
            （服务端 409，版本校验阻止重复 —— 竞争取消赢）；
          * 成功 → 服务端 lifecycle=TRIGGERED，receipt 记录 automation 与
            触发事件（触发器不改事实权威 —— 本方法不执行 action）。
        """
        intent_id = None
        try:
            from atlas.automation import reminders as reminder_service

            automation = reminder_service._engine(engine).store.get(automation_id)
            binding = (automation or {}).get("source_binding")
            bound_intent_id = binding.get("intent_id") if isinstance(binding, dict) else None
            if isinstance(bound_intent_id, str) and bound_intent_id.strip():
                intent_id = bound_intent_id.strip()
        except Exception as exc:  # noqa: BLE001 — stable legacy ID remains a fallback
            log.debug("intent_bridge.on_automation_event_failed", error=str(exc), exc_info=True)
        if intent_id is None:
            intent_id = intent_id_from_automation(automation_id)
        if intent_id is None:
            return {"fired": False, "reason": "not_intent_automation",
                    "automation_id": automation_id}
        client = self.client()
        try:
            listing = await client.call(
                "GET", "/v1/unified/intents",
                params={"intent_id": intent_id})
        except UnifiedMemoryError as exc:
            return {"fired": False, "reason": "lookup_failed",
                    "automation_id": automation_id, "error": str(exc)}
        items = listing.get("items") or []
        if not items:
            return {"fired": False, "reason": "intent_not_found",
                    "automation_id": automation_id, "intent_id": intent_id}
        intent = items[0]
        lifecycle = str(intent.get("lifecycle") or "")
        if lifecycle != "ACTIVE":
            # 取消/过期后的意图不触发（判据 test_cancelled_intent_does_not_trigger
            # 的桥侧半边）；已 TRIGGERED/RUNNING 不重复触发。
            return {"fired": False, "reason": f"intent_{lifecycle.lower()}",
                    "automation_id": automation_id, "intent_id": intent_id,
                    "lifecycle": lifecycle}
        receipt = {"kind": RECEIPT_AUTOMATION_EVENT,
                   "automation_id": automation_id,
                   "event": event or {}}
        body: dict[str, Any] = {
            "transition": "TRIGGERED",
            "expected_revision": int(intent.get("revision")),
            "receipt": receipt,
            "automation_id": automation_id,
        }
        if (ctx := self._context(context)) is not None:
            body["context"] = ctx
        try:
            payload = await client.transition_intent(intent_id, body)
        except RevisionConflict as exc:
            return {"fired": False, "reason": "revision_conflict",
                    "automation_id": automation_id, "intent_id": intent_id,
                    "detail": str(exc)}
        except UnifiedMemoryError as exc:
            return {"fired": False, "reason": "transition_failed",
                    "automation_id": automation_id, "intent_id": intent_id,
                    "detail": str(exc)}
        return {"fired": True, "automation_id": automation_id,
                "intent_id": intent_id, "lifecycle": payload.get("lifecycle"),
                "revision": payload.get("revision"), "receipt": receipt}

    # ------------------------------------------------------------------ 事件适配

    async def handle_atlas_event(self, event_type: str,
                                 payload: dict[str, Any] | None = None, *,
                                 context: dict[str, Any] | None = None,
                                 ) -> dict[str, Any]:
        """Atlas 事件 → cue 匹配 → 逐意图回写 TRIGGERED（T06.3 事件适配入口）。

        三类适配事件：project_open / tool_result / record_updated（匹配器对
        类型开放）。流程：拉 ACTIVE 意图（GET /v1/unified/intents）→
        :func:`event_matches_cue` 匹配 → 逐个 transition TRIGGERED（带
        atlas_event receipt；409 冲突即跳过 —— 版本校验阻止重复）。
        engine 未挂接前的直调入口（偏差见模块 docstring / ENGINE_WIRING）。
        """
        event_type = str(event_type or "").strip()
        if not event_type:
            raise IntentBridgeError("event_type 必填（适配集："
                                    f"{'/'.join(ATLAS_EVENT_TYPES)}）")
        client = self.client()
        try:
            listing = await client.call("GET", "/v1/unified/intents",
                                        params={"lifecycle": "ACTIVE"})
        except UnifiedMemoryError as exc:
            return {"event_type": event_type, "matched": [], "transitions": [],
                    "error": str(exc)}
        event = {"event_type": event_type, "payload": payload or {}}
        matched = [item for item in (listing.get("items") or [])
                   if event_matches_cue(item.get("cue"), event_type, payload)]
        transitions: list[dict[str, Any]] = []
        for intent in matched:
            intent_id = str(intent.get("intent_id"))
            receipt = {"kind": RECEIPT_ATLAS_EVENT,
                       "event_type": event_type, "payload": payload or {}}
            body: dict[str, Any] = {
                "transition": "TRIGGERED",
                "expected_revision": int(intent.get("revision")),
                "receipt": receipt,
            }
            if intent.get("automation_id"):
                body["automation_id"] = intent["automation_id"]
            if (ctx := self._context(context)) is not None:
                body["context"] = ctx
            try:
                result = await client.transition_intent(intent_id, body)
            except RevisionConflict as exc:
                transitions.append({"intent_id": intent_id, "fired": False,
                                    "reason": "revision_conflict",
                                    "detail": str(exc)})
                continue
            except UnifiedMemoryError as exc:
                transitions.append({"intent_id": intent_id, "fired": False,
                                    "reason": "transition_failed",
                                    "detail": str(exc)})
                continue
            transitions.append({"intent_id": intent_id, "fired": True,
                                "lifecycle": result.get("lifecycle"),
                                "revision": result.get("revision"),
                                "receipt": receipt})
        return {"event_type": event_type, "event": event, "matched": matched,
                "transitions": transitions}

    # ------------------------------------------------------------------ 取消

    async def cancel_intent(self, intent_id: str, *, context: dict[str, Any] | None = None,
                            engine: Any = None, now: Any = None,
                            ) -> dict[str, Any]:
        """取消意图 + 对应 Automation 停用。

        服务端 transition CANCELLED（终态自环幂等重放）；Automation 半边：
        **显式传 engine 时真取消**（``store`` 停用 + ``engine.cancel``，见
        :meth:`cancel_automation_for_intent`），未传 engine 时只返回取消说明
        （``wired=False``）—— 不隐式读写进程默认的 ``data/automations.toml``
        （生产数据边界：调用方要真取消就显式注入引擎）。
        """
        client = self.client()
        try:
            listing = await client.call("GET", "/v1/unified/intents",
                                        params={"intent_id": str(intent_id)})
        except UnifiedMemoryError as exc:
            raise IntentBridgeError(f"意图查询失败: {exc}") from exc
        items = listing.get("items") or []
        if not items:
            raise IntentBridgeError(f"意图不存在: {intent_id}")
        intent = items[0]
        automation_id = str(intent.get("automation_id")
                            or automation_id_for_intent(intent_id))
        body: dict[str, Any] = {"transition": "CANCELLED",
                                "expected_revision": int(intent.get("revision"))}
        if (ctx := self._context(context)) is not None:
            body["context"] = ctx
        try:
            payload = await client.transition_intent(str(intent_id), body)
            cancel_ok, cancel_error = True, None
        except UnifiedMemoryError as exc:
            payload, cancel_ok, cancel_error = None, False, str(exc)
        automation_cancel: dict[str, Any] = {
            "automation_id": automation_id,
            "instruction": ("engine.cancel(automation_id)（移除 DBOS "
                            "schedule/date run + dedup 活跃 run）；store 停用"
                            "由 reminders.cancel_reminder 执行"),
            "wired": False,
            "note": ENGINE_WIRING["reason"],
        }
        if engine is not None and cancel_ok:
            automation_cancel["result"] = await self.cancel_automation_for_intent(
                str(intent_id), engine=engine, now=now)
            automation_cancel["wired"] = bool(
                automation_cancel["result"].get("cancelled"))
        return {
            "intent_id": intent_id,
            "lifecycle": payload.get("lifecycle") if payload else None,
            "revision": payload.get("revision") if payload else None,
            "cancelled": cancel_ok,
            "cancel_error": cancel_error,
            "automation_cancel": automation_cancel,
        }

    # ------------------------------------------------------------------ 挂接说明

    @staticmethod
    def describe_engine_wiring() -> dict[str, Any]:
        """engine 挂接偏差说明（真挂接行未落 —— 任务书允许的分步方式）。"""
        return dict(ENGINE_WIRING)
