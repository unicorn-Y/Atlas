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

import uuid
from typing import Any

from atlas.memory.unified_client import (
    RevisionConflict,
    UnifiedMemoryClient,
    UnifiedMemoryError,
)
from atlas.memory.unified_facade import UnifiedMemoryFacade

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
                 event_inbox_dir: str | None = None) -> None:
        if facade is None and client is None:
            raise IntentBridgeError(
                "IntentBridge 需要 facade 或 client 之一（不自行装配配置）")
        self._facade = facade
        self._client_override = client
        self._event_inbox_dir = event_inbox_dir

    @classmethod
    def from_config(cls, config: Any = None) -> IntentBridge:
        return cls(facade=UnifiedMemoryFacade.from_config(config))

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
        due = self._time_due(intent)
        if not due:
            cue = intent.get("cue")
            cue = cue if isinstance(cue, dict) else {}
            reason = ("event_cue_not_wired" if str(cue.get("kind") or "") == "event"
                      else "no_time_cue")
            return {"created": False, "reason": reason, "intent_id": intent_id,
                    "automation_id": automation_id_for_intent(intent_id)}
        from atlas.automation import reminders as reminder_service

        result = await reminder_service.create_reminder(
            message=self._reminder_text(intent), due_at=due,
            automation_id=automation_id_for_intent(intent_id),
            now=now, engine=engine)
        result["intent_id"] = intent_id
        result["automation_id"] = (result.get("automation") or {}).get("id")
        return result

    async def cancel_automation_for_intent(self, intent_id: str, *,
                                           engine: Any = None,
                                           now: Any = None) -> dict[str, Any]:
        """统一意图取消 → 对应 Automation 停用（保留记录，可审计）。"""
        from atlas.automation import reminders as reminder_service

        result = await reminder_service.cancel_reminder(
            automation_id=automation_id_for_intent(intent_id),
            now=now, engine=engine)
        result["intent_id"] = str(intent_id)
        return result

    # ------------------------------------------------------------------ 触发回写

    async def on_automation_event(self, automation_id: str,
                                  event: dict[str, Any] | None = None, *,
                                  context: dict[str, Any] | None = None,
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
        if engine is not None:
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
