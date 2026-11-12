"""Introspection provider: persistent goals and the decomposition gate.

A goal outlives the run that created it. Its state lives in
``state_meta['goal:<session_id>']``, its history in
``state_meta['goal-events:<session_id>']``, and the driver that advances it only
exists while a process is running. So the two questions a session actually has
about goals cannot be answered from source or from the REST list:

* **Is anything stranded?** A goal whose owning process exited mid-flight is
  resumed by the startup sweep, but nothing surfaces *which* ones are waiting, so
  "why did this stop" has no answer at all.
* **Why did the last turn not do work?** A fresh goal spends its first turns on
  decomposition by design. From outside, a planning turn is indistinguishable
  from an execution turn that accomplished nothing.

This provider answers both, read-only. It is deliberately separate from
``/api/goals``: that endpoint is the *scheduled-goal* surface and only knows goals
that have a scheduler task row, while a goal started with ``/goal`` in a chat
session has none. Reading the same DB the driver reads is the only way to see
those.

Every method tolerates a missing database, an unreadable row and a malformed
event log — an introspection query that 500s on one corrupt goal tells you
nothing about the other forty.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _home() -> Any:
    """The engine data root — the same directory ``GoalManager`` is given.

    Imported lazily and read fresh, because ``atlas.config.DATA_ROOT`` is
    patched by tests and by ``ATLAS_DATA_DIR``; a captured constant would answer
    for the wrong install.
    """
    from atlas.config import DATA_ROOT

    return DATA_ROOT / "engine"


def _stranded(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.engine.goal_loop import scan_resumable_goals, summarize

    home = _home()
    try:
        goals = scan_resumable_goals(home)
    except Exception as exc:  # noqa: BLE001 - a scan failure is an answer, not a 500
        return {"resumable": 0, "goals": [], "error": f"{type(exc).__name__}: {exc}"}
    search = str(args.get("search") or "").strip().lower()
    if search:
        goals = [g for g in goals if search in g.goal.lower() or search in g.session_id.lower()]
    summary = summarize(goals)
    summary["home"] = str(home)
    summary["goals"] = [g.to_dict() for g in goals]
    return summary


def _state(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.engine.state.atlas_state import SessionDB

    session_id = str(args["session_id"]).strip()
    path = _home() / "state.db"
    if not path.exists():
        return {"session_id": session_id, "exists": False, "note": "引擎还没有 state.db。"}
    try:
        with SessionDB(db_path=path) as db:
            raw = db.get_meta(f"goal:{session_id}")
    except Exception as exc:  # noqa: BLE001
        return {"session_id": session_id, "error": f"{type(exc).__name__}: {exc}"}
    if not raw:
        return {"session_id": session_id, "exists": False}

    from atlas.engine.goals import MAX_PLAN_ATTEMPTS, GoalState

    try:
        state = GoalState.from_json(raw)
    except Exception as exc:  # noqa: BLE001
        return {"session_id": session_id, "exists": True, "error": f"unreadable goal row: {exc}"}

    remaining = [
        text for index, text in enumerate(state.subgoals, 1)
        if index not in set(state.completed_subgoals)
    ]
    return {
        "session_id": session_id,
        "exists": True,
        "goal": state.goal,
        "status": state.status,
        "turns_used": state.turns_used,
        "max_turns": state.max_turns,
        "subgoals": list(state.subgoals),
        "completed_subgoals": list(state.completed_subgoals),
        "done_count": len([i for i in state.completed_subgoals if 1 <= i <= len(state.subgoals)]),
        "remaining_subgoals": remaining,
        "last_verdict": state.last_verdict,
        "last_reason": state.last_reason,
        "waiting": state.is_waiting() if callable(getattr(state, "is_waiting", None)) else False,
        "plan": {
            "decomposition_required": state.decomposition_required,
            "plan_attempts": state.plan_attempts,
            "max_plan_attempts": MAX_PLAN_ATTEMPTS,
            "needs_plan": state.needs_plan(),
        },
    }


def _history(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.engine.session_sync import goal_events

    session_id = str(args["session_id"]).strip()
    try:
        events = goal_events(_home(), session_id)
    except Exception as exc:  # noqa: BLE001
        return {"session_id": session_id, "count": 0, "events": [], "error": f"{type(exc).__name__}: {exc}"}
    wanted = str(args.get("event") or "").strip()
    if wanted:
        events = [e for e in events if e.get("event") == wanted]
    try:
        limit = max(1, min(int(args.get("limit") or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    planning = [e for e in events if e.get("event") == "goal.planning_turn"]
    return {
        "session_id": session_id,
        "count": len(events),
        "planning_turns": len(planning),
        "events": events[-limit:],
    }


def _gate(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """The decomposition gate itself: what it enforces and what it costs."""
    from atlas.engine.goals import MAX_PLAN_ATTEMPTS, _PLAN_REQUIREMENT

    return {
        "max_plan_attempts": MAX_PLAN_ATTEMPTS,
        "requirement_prompt": _PLAN_REQUIREMENT,
        "events": ["goal.planning_turn"],
        "note": (
            "新目标的前 MAX_PLAN_ATTEMPTS 轮只允许拆解里程碑，之后无论有没有拆解都继续执行；"
            "这一限制只用于避免目标卡在规划里，不会暂停目标。"
        ),
    }


PROVIDER = Provider(
    id="goals",
    title="持续目标",
    summary="跨轮持续的目标：哪些在重启后还没续上、某个目标的里程碑与拆解闸门状态、以及它的推进记录。",
    methods=(
        Method(
            name="stranded",
            summary="重启后仍可继续的目标（含里程碑剩余情况），可按目标或会话过滤。",
            input_schema=object_schema(
                {"search": {"type": "string", "description": "在目标文本或会话 id 里做子串过滤。"}}
            ),
            run=_stranded,
        ),
        Method(
            name="state",
            summary="一个目标的完整状态：里程碑完成情况、轮次预算、拆解闸门。",
            input_schema=object_schema(
                {"session_id": {"type": "string", "description": "目标所属会话 id。"}},
                required=("session_id",),
            ),
            run=_state,
        ),
        Method(
            name="history",
            summary="一个目标的推进记录，含规划轮次数；可按事件名过滤。",
            input_schema=object_schema(
                {
                    "session_id": {"type": "string", "description": "目标所属会话 id。"},
                    "event": {"type": "string", "description": "只看某一种事件，例如 goal.evaluated。"},
                    "limit": {"type": "integer", "description": "最多返回多少条，默认 50，上限 200。"},
                },
                required=("session_id",),
            ),
            run=_history,
        ),
        Method(
            name="gate",
            summary="拆解闸门的规则本身：允许几次规划轮、提示词原文。",
            input_schema=object_schema(),
            run=_gate,
        ),
    ),
)
