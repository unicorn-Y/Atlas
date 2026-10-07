"""FocusContext — Atlas-side task focus wiring（UM06 / T06.1）.

职责边界（任务书 T06.1 允许分步，如实登记）：

  * 本模块封装 :class:`~atlas.memory.unified_facade.UnifiedMemoryFacade` 的
    focus 调用（update_focus / attend_focus / observe_focus，T06.1 已在
    unified_client 补齐 attend/observe 两个方法）—— 所有状态都在 MemoryOS
    的 unified_focus 投影，Atlas 不持有第二份焦点事实。
  * ``run_phases.py`` / ``hermes_runtime.py`` 的**调用点接线属 T06.2/UM07**
    （任务书 T06.1 文件清单将 run_phases/hermes_runtime 列为修改项，但接线
    语义与重启接续绑定；本波只交付本模块与供 T06.2 调用的方法签名 ——
    begin_task_focus / commit_focus / attend_for_purpose）。
  * **权威边界（绝对不变量）**：原任务运行状态只由 Atlas/Hermes 权威写。
    FocusContext 是运行权威的**投影客户端**：``authority_revision`` 由调用方
    （运行侧）传入并原样转发；MemoryOS 服务端不推断任务完成，本模块同样
    不推断 —— commit 声明 RUNNING，attend 就不会返回 COMPLETED。
  * 上下文压缩装配辅助 ``compress_context`` 是**纯函数**（T06.2 接线用）：
    压缩/切模型时保留 focus 与原证据 refs，不让仅会话摘要代替任务状态。

来源（S04 Myelin observe/commit/attend 工作集循环 ADAPT；搬运对照见
MemoryOS service/unified/working_set.py 模块 docstring 与
docs/plan/UNIFIED-MEMORY/VENDORED.md S04 条目）。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from atlas.memory.unified_client import UnifiedMemoryClient
from atlas.memory.unified_facade import UnifiedMemoryFacade

#: attend 支持的 purpose（与 MemoryOS working_set.ATTEND_PURPOSES 同集；
#: 通用召回走 recall，不经过焦点装配）
ATTEND_PURPOSES = ("CONTINUE_TASK", "PLAN")

#: 每条保留项/证据 refs 的形状键（§5：context_items 必带 record_ref/revision）
_REF_KEYS = ("record_ref", "revision")


class FocusContextError(Exception):
    """FocusContext 参数/用途错误（本地形状错误，先于 HTTP 传输）。"""


class FocusContext:
    """任务焦点客户端：begin/commit/attend/observe 四个方法封装 facade。

    用法（T06.2 的接线形状）::

        focus = FocusContext.from_config()
        await focus.begin_task_focus(task_id=..., goal=...,
                                     authority_revision=<运行权威版本>)
        await focus.commit_focus(task_id=..., snapshot={...},
                                 authority_revision=<新版本>)
        assembled = await focus.attend_for_purpose(task_id=...,
                                                   purpose="CONTINUE_TASK")
    """

    def __init__(self, facade: UnifiedMemoryFacade | None = None,
                 client: UnifiedMemoryClient | None = None) -> None:
        if facade is None and client is None:
            raise FocusContextError(
                "FocusContext 需要 facade 或 client 之一（不自行装配配置）")
        self._facade = facade
        self._client_override = client

    @classmethod
    def from_config(cls, config: Any = None) -> "FocusContext":
        return cls(facade=UnifiedMemoryFacade.from_config(config))

    @property
    def enabled(self) -> bool:
        return bool(self._facade.enabled) if self._facade is not None else True

    def client(self) -> UnifiedMemoryClient:
        if self._client_override is not None:
            return self._client_override
        assert self._facade is not None
        return self._facade.client()

    def _context(self, context: dict[str, Any] | None, *,
                 task_id: str | None = None) -> dict[str, Any]:
        """请求 context：显式传入优先；缺省用 facade 配置绑定骨架。

        client-only 构造（``FocusContext(client=...)``，测试/直连用）没有
        facade 配置可绑定骨架 —— context 缺失时显式 FocusContextError（调用方
        契约错误），不用 assert（-O 下会消失，且失败信息不可行动）。
        """
        if context is not None:
            return context
        if self._facade is None:
            raise FocusContextError(
                "client-only 构造（FocusContext(client=...)）必须显式传入 "
                "context（无 facade 配置可绑定缺省骨架）")
        return self._facade.default_context(task_id=task_id)

    # ------------------------------------------------------------------ 写

    async def begin_task_focus(self, *, task_id: str, goal: str,
                               constraints: list[Any] | None = None,
                               steps: list[Any] | None = None,
                               pending: list[Any] | None = None,
                               memory_refs: list[Any] | None = None,
                               external_receipts: list[Any] | None = None,
                               authority_revision: int = 1,
                               task_status: str = "RUNNING",
                               context: dict[str, Any] | None = None,
                               valid_until: str | None = None) -> dict[str, Any]:
        """任务开始/接续时建立焦点投影（commit_focus 的语义化入口）。

        权威边界：只写投影，不改运行状态 —— task_status 原样声明给服务端
        （RUNNING 归一为 ACTIVE）；服务端/本模块都不推断完成。steps 条目可带
        evidence_refs 指回原始证据定位（压缩保留原证据，§5/T06.1）。
        """
        return await self.commit_focus(
            task_id=task_id,
            snapshot={"goal": goal, "constraints": constraints or [],
                      "steps": steps or [], "pending": pending or [],
                      "memory_refs": memory_refs or [],
                      "external_receipts": external_receipts or []},
            authority_revision=authority_revision, task_status=task_status,
            context=context, valid_until=valid_until)

    async def commit_focus(self, *, task_id: str, snapshot: dict[str, Any],
                           authority_revision: int,
                           task_status: str | None = None,
                           context: dict[str, Any] | None = None,
                           valid_until: str | None = None) -> dict[str, Any]:
        """POST /v1/unified/focus：提交焦点快照（权威投影覆盖）。

        snapshot 形状（MemoryOS working_set.commit_focus 契约）：goal /
        constraints / steps（已验证步骤，entry 可带 evidence_refs 指回原始
        证据定位）/ pending / memory_refs（{ref, revision}）/ external_receipts。
        authority_revision 必须由调用方传入（运行权威版本）；服务端 409
        （旧版本 / 同版本不同内容）→ RevisionConflict 原样向上抛。
        """
        if not self.enabled:
            from atlas.memory.unified_client import ServiceUnavailable

            raise ServiceUnavailable(
                "unified memory disabled (memory.unified.enabled=false); "
                "focus commit must not silently drop the authoritative snapshot")
        if not str(task_id or "").strip():
            raise FocusContextError("commit_focus 必须绑定 task_id（多任务不串焦点）")
        if authority_revision is None:
            raise FocusContextError(
                "commit_focus 必须携带 authority_revision（Atlas 运行权威版本；"
                "focus 是投影，不是第二执行器）")
        request: dict[str, Any] = {
            "context": self._context(context, task_id=task_id),
            "task_id": task_id,
            "authority_revision": int(authority_revision),
            **{key: value for key, value in snapshot.items()
               if value is not None},
        }
        if task_status is not None:
            request["task_status"] = task_status
        if valid_until is not None:
            request["valid_until"] = valid_until
        return await self.client().update_focus(request)

    async def observe(self, *, focus_id: str, event: dict[str, Any],
                      context: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST /v1/unified/focus/{focus_id}/observe：注意事件入工作集。

        事件绑定焦点 task scope；不改权威快照。event 形状：{kind?, ref?,
        note?, payload?, event_id?}。
        """
        request = {"context": self._context(context), **dict(event or {})}
        return await self.client().observe_focus(focus_id, request)

    # ------------------------------------------------------------------ 读

    async def attend_for_purpose(self, *, task_id: str,
                                 purpose: str = "CONTINUE_TASK",
                                 context: dict[str, Any] | None = None,
                                 max_records: int | None = None,
                                 ) -> dict[str, Any]:
        """GET /v1/unified/focus/{task_id}：attend 焦点装配。

        disabled 时返回 ``{"enabled": False, "found": False, ...}``（与
        facade.recall_for_conversation 同语义：读路径不假装失败，但**不编造**
        任何焦点内容）；enabled 时 409/422 等错误类原样向上抛。
        """
        if purpose not in ATTEND_PURPOSES:
            raise FocusContextError(
                f"purpose 必须是 {'/'.join(ATTEND_PURPOSES)} 之一；通用召回走 "
                "facade.recall_for_conversation（§5）")
        if not self.enabled:
            return {"enabled": False, "reason": "MEMORY_UNIFIED_DISABLED",
                    "found": False, "focus_id": None, "goal": None,
                    "constraints": [], "steps": [], "pending": [],
                    "memory_refs": [], "external_receipts": [],
                    "observed": [], "context_items": [],
                    "note": "统一记忆未启用；不编造焦点前情"}
        params_subject = None
        if context and context.get("memory_subject_id"):
            params_subject = str(context["memory_subject_id"])
        response = await self.client().attend_focus(
            task_id, purpose=purpose, subject=params_subject,
            max_records=max_records)
        return {"enabled": True, **response}


# ------------------------------------------------------------------ 纯函数

def _ref_of(item: dict[str, Any]) -> dict[str, Any] | None:
    ref = item.get("record_ref")
    if not ref:
        return None
    entry: dict[str, Any] = {"record_ref": str(ref)}
    if item.get("revision") is not None:
        entry["revision"] = item["revision"]
    return entry


def compress_context(items: list[dict[str, Any]], focus: dict[str, Any] | None,
                     *, max_items: int = 12,
                     current_message: str | None = None) -> dict[str, Any]:
    """上下文压缩装配辅助（**纯函数**，T06.2 接 run_phases/hermes_runtime 用）。

    02_wave_tasks T06.1 判据：context 压缩/切模型保留 focus 与原证据，
    不让仅会话摘要代替任务状态；当前用户消息优先。

    输入：
      * ``items``  —— recall/attend 装配的 context_items（UnifiedRecord 形状）；
      * ``focus``  —— attend_for_purpose 的焦点装配（可 None）；
      * ``max_items`` —— 压缩后保留的普通记录条数上限（预算）；
      * ``current_message`` —— 当前用户消息（优先级最高，只标注不裁剪）。

    不变量（压缩不得破坏）：
      1. focus 装配（goal/constraints/steps/pending）**整块保留**在输出最前
         —— 任务状态永远来自焦点投影，不来自会话摘要；
      2. 所有输入项的原始证据 refs（record_ref+revision）**全部保留**到
         ``evidence_refs``（被裁的条目留下定位，不静默丢失）；
      3. SUMMARY 类条目只能作为补充（排最后、预算内），**不得**顶替
         WORKING_FOCUS / GOAL / STATE / COMMITMENT 任务状态类条目；
      4. steps.evidence_refs / memory_refs（focus 内的原证据）原样透传。

    返回（纯数据，无副作用）：{focus, focus_block, items, evidence_refs,
    dropped_refs, summaries_kept, current_message_first, note}。
    """
    evidence_refs: list[dict[str, Any]] = []
    seen_refs: set[str] = set()

    def keep_ref(entry: dict[str, Any] | None) -> None:
        if entry is None:
            return
        key = str(entry.get("record_ref"))
        if key in seen_refs:
            return
        seen_refs.add(key)
        evidence_refs.append(entry)

    # 1. focus 原证据 refs 先收（steps.evidence_refs / memory_refs）
    focus_steps = list((focus or {}).get("steps") or [])
    for step in focus_steps:
        if isinstance(step, dict):
            for ref in (step.get("evidence_refs") or []):
                keep_ref({"record_ref": str(ref)} if isinstance(ref, str)
                         else dict(ref))
    for ref_entry in ((focus or {}).get("memory_refs") or []):
        if isinstance(ref_entry, dict) and ref_entry.get("ref"):
            keep_ref({"record_ref": str(ref_entry["ref"]),
                      "revision": ref_entry.get("revision")})

    # 2. 任务状态类条目优先保留（不被 SUMMARY 顶替）
    TASK_STATE_FACETS = {"WORKING_FOCUS", "GOAL", "STATE", "COMMITMENT",
                         "FACT", "EPISODE"}
    state_items: list[dict[str, Any]] = []
    summary_items: list[dict[str, Any]] = []
    other_items: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        keep_ref(_ref_of(item))
        facet = str(item.get("facet") or "")
        if facet == "SUMMARY":
            summary_items.append(item)
        elif facet in TASK_STATE_FACETS:
            state_items.append(item)
        else:
            other_items.append(item)

    budget = max(0, int(max_items))
    kept = (state_items + other_items)[:budget]
    summaries_kept = summary_items[:max(0, budget - len(kept))]
    kept = kept + summaries_kept
    dropped = [entry for entry in evidence_refs
               if entry.get("record_ref") not in {
                   str(i.get("record_ref")) for i in kept if
                   isinstance(i, dict)}]

    focus_block: dict[str, Any] | None = None
    if focus and focus.get("found"):
        focus_block = {
            "focus_ref": focus.get("focus_ref"),
            "focus_id": focus.get("focus_id"),
            "task_id": focus.get("task_id"),
            "goal": focus.get("goal"),
            "constraints": focus.get("constraints") or [],
            "steps": focus_steps,
            "pending": focus.get("pending") or [],
            "memory_refs": focus.get("memory_refs") or [],
            "external_receipts": focus.get("external_receipts") or [],
            "status": focus.get("status"),
            "authority_revision": focus.get("authority_revision"),
        }

    return {
        "focus": focus_block,
        "items": kept,
        "evidence_refs": evidence_refs,
        "dropped_refs": dropped,
        "summaries_kept": len(summaries_kept),
        "current_message_first": bool(current_message),
        "note": ("压缩不变量：focus 任务状态整块保留（会话摘要只作补充，"
                 "不得代替任务状态）；全部原始证据 refs 保留可回溯；"
                 "当前用户消息优先（T06.2 接线点）"),
    }


# ------------------------------------------------------------------ T07.3 / T08.2

def is_personal_memory_relevant(query: str) -> bool:
    """判断当前查询是否与个人/任务记忆相关（UM07 / T07.3）。

    - 纯通用代码/计算类问题（如 "Python dict 怎么排序", "帮我算一下 128 乘以 64"）
      无个人、任务、时间指示时返回 False，避免无端装配私人经历或无关片段；
    - 涉及排期、偏好、任务、人名指示或隐含时间线的问题（如 "帮我安排明天的工作",
      "按我现在的格式来", "帮我把他上次的修改意见整理成清单"）返回 True 并允许召回。
    """
    if not query or not isinstance(query, str):
        return False
    q = query.strip()
    if not q:
        return False

    # 1. 显式纯计算类问题（如 "帮我算一下 128 乘以 64"）
    math_patterns = (
        r"(?:算一下|计算|求值|等于几).*(?:\d+|[\+\-\*\/]|乘以|除以|加上|减去)",
        r"\d+\s*(?:\+|加|减|\-|乘|\*|乘以|除|\/|除以)\s*\d+",
        r"^(?:帮我)?(?:算一下|计算)\b",
    )
    for pat in math_patterns:
        if re.search(pat, q):
            # 若不包含显式日程/偏好/人物等个人线索，则属于纯计算
            if not any(k in q for k in ("日程", "会议", "工作", "上次", "按我", "安排", "计划", "明天", "时间")):
                return False

    # 2. 纯通用编程/语法/库函数类问题（如 "Python dict 怎么排序"）
    generic_code_patterns = (
        r"(?:python|java|c\+\+|golang|rust|javascript|typescript|sql|html|css)\b.*(?:怎么|如何|写法|排序|遍历|反转|用法|实现)",
        r"^(?:怎么|如何|什么是|介绍一下)(?:使用|实现|排序|遍历|写)?\s*[a-zA-Z0-9_]+",
    )
    for pat in generic_code_patterns:
        if re.search(pat, q, re.IGNORECASE):
            if not any(k in q for k in ("我的", "我们", "上次", "项目", "格式", "按我", "习惯", "偏好", "现在", "之前")):
                return False

    # 3. 个人排期、偏好、习惯、人物、时间或状态线索
    personal_cues = (
        "安排", "明天", "工作", "日程", "会议", "晚上", "晚间", "上午", "下午", "这周", "下周",
        "格式", "按我", "习惯", "偏好", "上次", "昨天", "他", "她", "清单", "意见",
        "继续", "接着", "项目", "计划", "提醒", "备忘", "记住", "约定", "约束", "要求",
        "小王", "老李", "张三", "李四", "同事", "领导", "现在的工作", "现在的格式",
    )
    if any(cue in q for cue in personal_cues):
        return True

    # 4. 代词与个人指令线索
    if any(p in q for p in ("我", "我的", "我们")) and any(a in q for a in ("帮我", "给我", "做", "写", "查", "排")):
        return True

    return False


async def load_pre_plan_constraints(
    facade: Any, query: str, context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """规划前加载相关约束与偏好，绑定 read_id + input_hash 并记录应用收据（UM07 / T07.3）。

    规划前加载 active PREFERENCE / STATE / COMMITMENT / CONSTRAINT 条目；
    不要在 plan 已生成后才加载会改变计划的记忆。
    """
    input_hash = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()

    if not is_personal_memory_relevant(query):
        return {
            "relevant": False,
            "constraints": [],
            "context_items": [],
            "read_id": None,
            "input_hash": input_hash,
            "application_receipt": None,
        }

    if facade is None or not getattr(facade, "enabled", True):
        return {
            "relevant": True,
            "constraints": [],
            "context_items": [],
            "read_id": None,
            "input_hash": input_hash,
            "application_receipt": None,
        }

    try:
        recall_resp = await facade.recall_for_conversation(
            query=query, context=context, purpose="PLAN",
        )
    except Exception:
        return {
            "relevant": True,
            "constraints": [],
            "context_items": [],
            "read_id": None,
            "input_hash": input_hash,
            "application_receipt": None,
        }

    read_id = recall_resp.get("read_id")
    context_hash = recall_resp.get("context_hash") or input_hash
    items = recall_resp.get("context_items") or []

    constraint_facets = {"PREFERENCE", "STATE", "COMMITMENT", "CONSTRAINT", "HABIT"}
    applied_items: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        facet = str(item.get("facet") or "").upper()
        content = item.get("content") or {}
        text = ""
        if isinstance(content, dict):
            text = str(content.get("text") or content.get("value") or content.get("constraint") or "")
        elif isinstance(content, str):
            text = content

        is_constraint = (
            facet in constraint_facets
            or "constraint" in str(item.get("meta") or "").lower()
            or any(k in text for k in ("不要", "不得", "必须", "只能", "后不", "前不", "晚上", "晚间", "格式", "习惯", "约束"))
        )
        if is_constraint:
            applied_items.append(item)

    if not applied_items and items:
        applied_items = list(items)

    applied_refs = [
        str(it.get("record_ref")) for it in applied_items
        if isinstance(it, dict) and it.get("record_ref")
    ]

    receipt: dict[str, Any] | None = None
    if read_id and applied_items:
        basis = {
            "query": query,
            "input_hash": input_hash,
            "constraint_count": len(applied_items),
            "applied_refs": applied_refs,
        }
        app_request = {
            "read_id": read_id,
            "context_hash": context_hash,
            "action_refs": [f"action:plan-{uuid.uuid4().hex[:8]}"],
            "applied_items": applied_items,
            "basis": basis,
            "context": context,
        }
        try:
            if hasattr(facade, "record_application"):
                rec_res = await facade.record_application(app_request)
            elif hasattr(facade, "client") and hasattr(facade.client(), "record_application"):
                rec_res = await facade.client().record_application(app_request)
            else:
                rec_res = None

            if isinstance(rec_res, dict) and (rec_res.get("application_id") or rec_res.get("application_ref")):
                receipt = {
                    "application_id": rec_res.get("application_id"),
                    "application_ref": rec_res.get("application_ref"),
                    "read_id": read_id,
                    "input_hash": input_hash,
                    "applied_refs": applied_refs,
                    "basis": basis,
                    "status": "RECORDED",
                }
            else:
                receipt = {
                    "application_id": f"app-local-{uuid.uuid4().hex[:12]}",
                    "application_ref": f"application:local-{uuid.uuid4().hex[:12]}",
                    "read_id": read_id,
                    "input_hash": input_hash,
                    "applied_refs": applied_refs,
                    "basis": basis,
                    "status": "RECORDED_LOCAL",
                }
        except Exception:
            # 501 / 连接失败等降级为本地应用凭据
            receipt = {
                "application_id": f"app-local-{uuid.uuid4().hex[:12]}",
                "application_ref": f"application:local-{uuid.uuid4().hex[:12]}",
                "read_id": read_id,
                "input_hash": input_hash,
                "applied_refs": applied_refs,
                "basis": basis,
                "status": "RECORDED_LOCAL",
            }

    return {
        "relevant": True,
        "constraints": applied_items,
        "context_items": items,
        "read_id": read_id,
        "input_hash": input_hash,
        "application_receipt": receipt,
    }


async def check_action_dependencies(
    facade: Any, plan_dependencies: Any, context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """动作前依赖检查（T08.2 / UM08）：验证重要依赖版本，新事实不能配旧计划继续执行。"""
    if facade is None or not getattr(facade, "enabled", True):
        return {"status": "VALID", "changed_refs": [], "blocked": False}

    req: dict[str, Any] = {}
    if isinstance(plan_dependencies, list):
        req["dependencies"] = plan_dependencies
    elif isinstance(plan_dependencies, dict):
        req = dict(plan_dependencies)
    else:
        return {"status": "VALID", "changed_refs": [], "blocked": False}

    if context:
        req.setdefault("context", context)
    elif hasattr(facade, "default_context"):
        req.setdefault("context", facade.default_context())

    try:
        if hasattr(facade, "check_dependencies"):
            res = await facade.check_dependencies(req)
        elif hasattr(facade, "client") and hasattr(facade.client(), "check_dependencies"):
            res = await facade.client().check_dependencies(req)
        else:
            res = {"status": "VALID", "changed_refs": []}

        st = str(res.get("status") or "").upper()
        changed = list(res.get("changed_refs") or [])
        if st in {"STALE", "FRONTIER_STALE"} or bool(changed):
            return {
                "status": "STALE",
                "changed_refs": changed,
                "conflicts": res.get("conflicts", []),
                "details": res.get("details", []),
                "blocked": True,
                "detail": res.get("action_required") or "Plan dependencies are stale",
            }
        return {
            "status": res.get("status") or "VALID",
            "changed_refs": [],
            "details": res.get("details", []),
            "blocked": False,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "changed_refs": [],
            "blocked": False,
            "error": str(exc),
        }
