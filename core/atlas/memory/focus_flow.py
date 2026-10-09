"""Run-side focus flow（UM06 / T06.2）：重启接续版本语义 + 副作用收据快照。

:mod:`atlas.agent.run_phases` 的接线辅助 —— 本模块只做 focus 投影的数据编排，
不碰聊天事件流；所有状态都在 MemoryOS ``unified_focus`` 投影，本模块不持有
第二份焦点事实。

版本语义（重启续接，任务书 T06.2）：

  * MemoryOS 服务端是**权威投影**；Atlas 运行侧不持久化版本号 —— 每次运行
    begin 时先 ``attend`` 回读服务端 ``authority_revision``，再以 ``old+1``
    提交，run 内单调递增（finalize 再 +1）。
  * 旧版本 / 同版本异内容提交会被服务端 409 ``FOCUS_REVISION_CONFLICT`` 拒绝
    （§6）；本链路重启后先回读再提交，因此**正常续接路径不再触发 409**
    （409 竞争已在 T06.1 服务端语义测试覆盖）。
  * 并发竞争（同任务两个运行同时续接，attend→commit 之间被抢先）：按「回读
    服务端最新版本重试一次；仍冲突则本运行降级为不写焦点」处理 —— 焦点是
    投影不是执行器，任何 focus 失败都绝不打断聊天主流程。

副作用对账（重跑前检查）：begin 回读的 UNKNOWN 外部收据先经
:func:`atlas.memory.reconcile.reconcile_unknown_receipt`（确定性文件存在性
检查；真实 API/窗口检查留偏差）更新状态，再随快照重提交 —— 不重复调用具有
副作用的工具。

已验证步骤的证据边界：finalize 步骤只来自**真实工具收据**（T02.2 capture 的
TOOL_RESULT 观察引用 ``atlas:ATLAS_TOOL_OBSERVATION:{tool_call_id}:2:UPSERT``，
同一套稳定 ID 体系）；助手「完成」文本不产生已验证步骤，``task_status`` 恒为
RUNNING（服务端不推断完成）。
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any

import structlog

from atlas.memory.context import FocusContext, compress_context
from atlas.memory.reconcile import reconcile_focus_receipts
from atlas.memory.unified_client import RevisionConflict

log = structlog.get_logger()


# ------------------------------------------------------------------ 装配单例
# 与 memory.capture.get_capture_service 同一模式：进程级惰性装配一次；
# disabled（memory.unified.enabled=false）→ None，接线点必须容忍 None。

class _FocusRuntime:
    """FocusContext + 配置绑定 facade（context 骨架从这里来）。"""

    def __init__(self) -> None:
        from atlas.memory.unified_facade import UnifiedMemoryFacade

        self.facade = UnifiedMemoryFacade.from_config()
        self.focus = FocusContext(facade=self.facade)

    def context(self, *, task_id: str, session_id: str) -> dict[str, Any]:
        """MemoryContext 骨架：task_id 绑定任务本体；会话 ID 只作溯源。"""
        return self.facade.default_context(
            task_id=task_id, runtime_session_id=str(session_id or ""))


_focus_runtime: _FocusRuntime | None = None
_focus_configured = False
_focus_lock = threading.Lock()


def get_focus_context() -> _FocusRuntime | None:
    """接线点取用入口；未组装时按全局配置惰性组装一次。disabled → None。"""
    global _focus_runtime, _focus_configured
    if _focus_runtime is not None or _focus_configured:
        return _focus_runtime
    with _focus_lock:
        if _focus_runtime is not None or _focus_configured:
            return _focus_runtime
        _focus_configured = True
        from atlas.config import get_config

        cfg = get_config()
        if not cfg.get("memory.unified.enabled"):
            return None
        _focus_runtime = _FocusRuntime()
        return _focus_runtime


def reset_focus_context() -> None:
    """丢弃进程级单例（测试隔离用）。"""
    global _focus_runtime, _focus_configured
    with _focus_lock:
        _focus_runtime = None
        _focus_configured = False


# ------------------------------------------------------------------ 小工具

def _carried(payload: dict[str, Any] | None) -> dict[str, list[Any]]:
    """attend 回读 → 可携带的任务状态节。

    过期焦点按服务端 attend 语义装配节已清空（found=True + expired=True），
    这里以 ``expired`` 为准整体置空 —— 过期工作集按正常新任务处理。
    """
    payload = payload or {}
    if not payload.get("found") or payload.get("expired"):
        return {"constraints": [], "steps": [], "pending": [],
                "memory_refs": [], "external_receipts": []}
    return {
        "constraints": list(payload.get("constraints") or []),
        "steps": list(payload.get("steps") or []),
        "pending": list(payload.get("pending") or []),
        "memory_refs": list(payload.get("memory_refs") or []),
        "external_receipts": list(payload.get("external_receipts") or []),
    }


def _merge_by_call_id(carried: list[Any], new: list[Any]) -> list[Any]:
    """按 tool_call_id 去重合并（并发竞争重试时服务端可能已含本次收据）。"""
    seen = {str(entry.get("tool_call_id")) for entry in carried
            if isinstance(entry, dict) and entry.get("tool_call_id")}
    return carried + [entry for entry in new
                      if str(entry.get("tool_call_id", "")) not in seen]


def _receipt_evidence(tool_call_id: str) -> str:
    """T02.2 capture 的 TOOL_RESULT 观察引用（§2 source_event_id 定位）。"""
    return f"atlas:ATLAS_TOOL_OBSERVATION:{tool_call_id}:2:UPSERT"


def _receipt_path(text: str) -> str | None:
    """从真实工具输出提取受影响路径（保守：完整 dict 输出且带 path 字段）。

    提取不到不造路径 —— 对账时该收据按「无定位」保持 UNKNOWN（不伪造检查）。
    """
    raw = str(text or "").strip()
    if not raw.startswith("{"):
        return None
    try:
        data = ast.literal_eval(raw)
    except (ValueError, SyntaxError, MemoryError):
        return None
    if isinstance(data, dict):
        path = data.get("path")
        if isinstance(path, str) and path.strip():
            return path.strip()
    return None


def _entries_from_receipts(
    tool_receipts: list[dict[str, Any]] | None, session_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """真实工具收据 → (已验证步骤, 待解决条目, 外部收据条目)。

    无稳定 tool_call_id 的收据不进快照（不伪造对象 ID，§2）。
    """
    steps: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for receipt in tool_receipts or []:
        call_id = str(receipt.get("tool_call_id") or "").strip()
        if not call_id:
            continue
        name = str(receipt.get("tool") or "tool")
        evidence = _receipt_evidence(call_id)
        path = _receipt_path(receipt.get("text") or "")
        entry: dict[str, Any] = {
            "tool": name, "tool_call_id": call_id,
            "evidence_refs": [evidence],
            "evidence_locator": f"{session_id}/{call_id}",
        }
        if path:
            entry["path"] = path
        if receipt.get("is_error"):
            pending.append({**entry, "item": f"工具 {name} 执行失败（结果未验证）",
                            "status": "FAILED"})
        else:
            steps.append({**entry, "item": f"工具 {name} 执行成功（真实收据）",
                          "status": "OK"})
        receipts.append({"tool": name, "tool_call_id": call_id,
                         "status": "FAILED" if receipt.get("is_error") else "OK",
                         "ref_locator": f"{session_id}/{call_id}",
                         **({"path": path} if path else {})})
    return steps, pending, receipts


# ------------------------------------------------------------------ begin

async def begin_run_focus(
    *, task_id: str, message: str, workspace: str | None = None,
    session_id: str = "",
) -> tuple[dict[str, Any], int] | None:
    """运行开始：attend 回读旧权威版本 → 对账 UNKNOWN 收据 → old+1 重提交。

    返回 ``(焦点装配载荷, 本次运行的权威版本)``；disabled / 服务不可达 /
    版本冲突降级 → ``None``（本运行无焦点，聊天主流程不受影响）。
    载荷里 ``goal`` 已更新为当前用户消息（当前消息优先），``reconciled``
    记录本次对账计数。
    """
    runtime = get_focus_context()
    if runtime is None or not str(task_id or "").strip():
        return None
    try:
        attend = await runtime.focus.attend_for_purpose(
            task_id=task_id, purpose="CONTINUE_TASK")
    except Exception as exc:  # noqa: BLE001 — focus 失败绝不打断聊天
        log.debug("focus.attend_failed", task_id=task_id, error=str(exc), exc_info=True)
        return None
    if not attend.get("enabled"):
        return None
    carried = _carried(attend)
    reconciled = reconcile_focus_receipts(
        {"external_receipts": carried["external_receipts"],
         "pending": carried["pending"]},
        base_dir=Path(workspace) if workspace else None)
    carried["external_receipts"] = reconciled["receipts"]
    carried["pending"] = reconciled["pending"]
    prior_revision = (
        int(attend.get("authority_revision") or 0)
        if attend.get("found") else 0)
    revision = prior_revision + 1
    context = runtime.context(task_id=task_id, session_id=session_id)

    async def _commit(rev: int, sections: dict[str, list[Any]]) -> None:
        await runtime.focus.begin_task_focus(
            task_id=task_id, goal=message,
            constraints=sections["constraints"], steps=sections["steps"],
            pending=sections["pending"], memory_refs=sections["memory_refs"],
            external_receipts=sections["external_receipts"],
            authority_revision=rev, task_status="RUNNING", context=context)

    try:
        await _commit(revision, carried)
    except RevisionConflict:
        # 并发竞争：服务端是权威 —— 回读最新版本重试一次；再冲突则降级。
        try:
            attend = await runtime.focus.attend_for_purpose(
                task_id=task_id, purpose="CONTINUE_TASK")
            fresh = _carried(attend)
            revision = int(attend.get("authority_revision") or prior_revision) + 1
            fresh["steps"] = _merge_by_call_id(fresh["steps"], carried["steps"])
            await _commit(revision, fresh)
        except Exception as exc:  # noqa: BLE001
            log.debug("focus.begin_conflict_degraded",
                      task_id=task_id, error=str(exc), exc_info=True)
            return None
    except Exception as exc:  # noqa: BLE001 — 服务不可达等：本运行无焦点
        log.debug("focus.begin_failed", task_id=task_id, error=str(exc), exc_info=True)
        return None
    payload = {
        # 携带对账后的节：finalize 重提交以这里为 carried 基线（对账结果不回退）。
        **attend,
        "goal": message,
        "external_receipts": reconciled["receipts"],
        "pending": reconciled["pending"],
        "authority_revision": revision,
        "reconciled": {"resolved": int(reconciled["resolved"]),
                       "unresolved": int(reconciled["unresolved"])},
    }
    log.info("focus.begin", task_id=task_id, revision=revision,
             prior_revision=prior_revision, carried_steps=len(carried["steps"]))
    return payload, revision


# ------------------------------------------------------------------ 装配

def focus_context_block(
    prior: dict[str, Any] | None, *, mode: str = "act",
    current_message: str = "", memories: list[Any] | None = None,
) -> dict[str, Any] | None:
    """attend 回读 → 注入模型的焦点装配块（只附加，不覆盖现有上下文）。

    ``compress_context`` 不变量（T06.1）：focus 整块保留、原证据 refs 全部
    可回溯、当前用户消息优先。``mode="plan"`` 时清空 transient 注意事件环
    （与 MemoryOS attend purpose=PLAN 语义等价：计划只看已提交状态）。
    无焦点（found=False）→ ``None``（正常新任务不编前情）。
    """
    if not prior or not prior.get("found"):
        return None
    payload = dict(prior)
    if mode == "plan":
        payload["observed"] = []
    try:
        block = compress_context(list(memories or []), payload,
                                 current_message=current_message)
    except Exception as exc:  # noqa: BLE001 — 装配失败按无焦点处理
        log.debug("focus.block_failed", error=str(exc), exc_info=True)
        return None
    focus_part = block.get("focus")
    if not focus_part:
        return None
    return {
        "focus": focus_part,
        "evidence_refs": block.get("evidence_refs") or [],
        "current_message_first": True,
        "note": ("焦点装配为补充上下文：当前用户消息优先，旧装配不覆盖新要求；"
                 "收据状态 OK / 已验证的步骤不得重复执行"),
    }


# ------------------------------------------------------------------ finalize

async def commit_finalize_focus(
    *, task_id: str, message: str, prior: dict[str, Any] | None = None,
    revision: int = 0, tool_receipts: list[dict[str, Any]] | None = None,
    session_id: str = "",
) -> int:
    """finalize：真实工具收据进焦点快照（已验证步骤 / FAILED 进 pending）。

    ``task_status`` 恒为 RUNNING —— 服务端不推断完成，助手自报完成不是验证。
    返回提交后的权威版本（失败降级返回原 ``revision``，调用方零处理）。
    """
    runtime = get_focus_context()
    if runtime is None or not revision or not str(task_id or "").strip():
        return int(revision or 0)
    carried = _carried(prior)
    new_steps, new_pending, new_receipts = _entries_from_receipts(
        tool_receipts, session_id)
    context = runtime.context(task_id=task_id, session_id=session_id)

    async def _commit(rev: int, sections: dict[str, list[Any]]) -> None:
        await runtime.focus.commit_focus(
            task_id=task_id,
            snapshot={"goal": message,
                      "constraints": sections["constraints"],
                      "steps": sections["steps"],
                      "pending": sections["pending"],
                      "memory_refs": sections["memory_refs"],
                      "external_receipts": sections["external_receipts"]},
            authority_revision=rev, task_status="RUNNING", context=context)

    revision_sections = {
        "constraints": carried["constraints"],
        "steps": _merge_by_call_id(carried["steps"], new_steps),
        "pending": _merge_by_call_id(carried["pending"], new_pending),
        "memory_refs": carried["memory_refs"],
        "external_receipts": carried["external_receipts"] + new_receipts,
    }
    new_revision = int(revision) + 1
    try:
        await _commit(new_revision, revision_sections)
    except RevisionConflict:
        # 并发竞争：回读最新权威版本重试一次（收据按 tool_call_id 去重）。
        try:
            attend = await runtime.focus.attend_for_purpose(
                task_id=task_id, purpose="CONTINUE_TASK")
            fresh = _carried(attend)
            new_revision = int(attend.get("authority_revision") or revision) + 1
            await _commit(new_revision, {
                "constraints": fresh["constraints"],
                "steps": _merge_by_call_id(fresh["steps"], new_steps),
                "pending": _merge_by_call_id(fresh["pending"], new_pending),
                "memory_refs": fresh["memory_refs"],
                "external_receipts": fresh["external_receipts"] + new_receipts,
            })
        except Exception as exc:  # noqa: BLE001
            log.debug("focus.finalize_conflict_degraded",
                      task_id=task_id, error=str(exc), exc_info=True)
            return int(revision)
    except Exception as exc:  # noqa: BLE001 — 服务不可达：本轮快照丢弃，不打断收尾
        log.debug("focus.finalize_failed", task_id=task_id, error=str(exc), exc_info=True)
        return int(revision)
    log.info("focus.finalize", task_id=task_id, revision=new_revision,
             verified_steps=len(new_steps), failed_pending=len(new_pending))
    return new_revision
