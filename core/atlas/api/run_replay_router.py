"""HTTP surface for run replay and resumable execution checkpoints.

Two reads and one resume, backed by two different stores that already exist:

* **replay** reads the append-only run archive
  (``data/logs/runs/<date>/<run_id>.jsonl``) through the read-only
  :mod:`atlas.run_replay` toolkit. Nothing is re-executed: the timeline is
  reconstructed from the recorded events only.
* **checkpoints** read ``data/run_checkpoints.db`` (see
  :mod:`atlas.run_checkpoints`): the durable *position* record the kernel
  writes at every phase transition and every completed tool call.
* **resume** delegates to :func:`atlas.api.run_drive.resume_run_after_restart`,
  which is the existing restart-recovery path. This router never re-implements
  continuation, so a resumed run has exactly the same tools, permissions and
  hooks as the original turn.

Resume is explicit about what it will *not* do. A tool call whose result was
lost is never replayed here: the kernel's repair marks it unknown, and this
endpoint returns the checkpoint digest (``unsafe_tools`` and the per-call
``replay_safe`` flags) so the caller can see which side effects may already
have happened before deciding to continue.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.runtime import MAX_RESUME_ATTEMPTS
from atlas.run_checkpoints import (
    checkpoint_overview,
    list_checkpoints,
    summarize_checkpoints,
)
from atlas.run_replay import (
    RunNotFoundError,
    list_runs,
    load_run,
    replay,
    summarize,
)

router = APIRouter()

#: Same shape the archive writer enforces (``atlas/logs.py``); a run id is never
#: an arbitrary path fragment.
_RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

#: Statuses from which there is nothing left to continue (``RunState.status``).
#: ``failed`` is deliberately absent: that is exactly the state the shutdown
#: leaves an interrupted run in, so a failed run is the main thing to resume.
#: A finished (``completed``) or user-aborted (``cancelled``) run has no open
#: position to continue, and re-entering the executor for it would spend a whole
#: extra model turn on work the caller already has.
_NOT_RESUMABLE = frozenset({"completed", "cancelled"})


def _check_run_id(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id or ""):
        raise HTTPException(status_code=400, detail="无效的运行 ID")
    return run_id


# -- replay ----------------------------------------------------------------


@router.get("/api/run-replay")
async def list_replay_runs(limit: int = 50) -> dict[str, Any]:
    """Inventory of runs that have an archive on disk, newest first."""
    # Reading the archive directory touches the filesystem; keep it off the event
    # loop the way every other blocking call in this package is kept off it.
    rows = await asyncio.to_thread(list_runs, limit=max(1, min(500, limit)))
    return {
        "items": [
            {
                "run_id": info.id,
                "path": info.path,
                "files": list(info.files),
                "size_bytes": info.size,
                "event_count": info.event_count,
                "bad_lines": info.bad_lines,
                "session_id": info.session_id,
                "status": info.status,
                "start_time": info.start_time,
                "end_time": info.end_time,
                "duration_ms": info.duration_ms,
            }
            for info in rows
        ],
        "count": len(rows),
    }


@router.get("/api/run-replay/{run_id}")
async def get_run_replay(run_id: str, timeline_limit: int = 500) -> dict[str, Any]:
    """Read one run's recorded timeline back. No model call, no tool call.

    Returns the ordered timeline (``run_start`` / ``run_phase`` / ``model_call``
    / ``tool_call`` / ``tool_result`` / ``error`` / ``run_end``) plus the
    duration/token/cost digest, so a replay can be inspected without loading
    the run's session.
    """
    _check_run_id(run_id)
    try:
        run = await asyncio.to_thread(load_run, run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="运行归档不存在") from exc
    items = await asyncio.to_thread(replay, run)
    keep = max(0, min(2000, timeline_limit))
    return {
        "run_id": run.id,
        "files": list(run.paths),
        "status": run.status,
        "terminal_status": run.terminal_status,
        "model": run.model,
        "session_id": run.session_id,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "duration_ms": run.duration_ms,
        "cost_usd": run.cost_usd,
        "bad_lines": run.bad_lines,
        "truncated": run.truncated,
        "summary": summarize(run),
        "timeline_count": len(items),
        "timeline_truncated": len(items) > keep,
        "timeline": [
            {
                "index": item.index,
                "kind": item.kind,
                "timestamp": item.timestamp,
                "label": item.label,
                "detail": item.detail,
                "elapsed_ms": item.elapsed_ms,
                "tool_name": item.tool_name,
                "tool_call_id": item.tool_call_id,
                "is_error": item.is_error,
            }
            for item in items[:keep]
        ],
    }


# -- checkpoints -----------------------------------------------------------


@router.get("/api/run-checkpoints")
async def list_checkpointed_runs(limit: int = 50) -> dict[str, Any]:
    """Runs with durable checkpoints, newest activity first (counts only)."""
    return {"items": await asyncio.to_thread(checkpoint_overview, limit=limit)}


@router.get("/api/run-checkpoints/{run_id}")
async def get_run_checkpoints(run_id: str, limit: int = 500) -> dict[str, Any]:
    """The raw boundary rows plus the resume-oriented digest for one run."""
    _check_run_id(run_id)
    items = await asyncio.to_thread(list_checkpoints, run_id, limit=limit)
    return {
        "run_id": run_id,
        "count": len(items),
        "digest": await asyncio.to_thread(summarize_checkpoints, run_id),
        "checkpoints": items,
    }


# -- resume ----------------------------------------------------------------


@router.post("/api/run-checkpoints/{run_id}/resume")
async def resume_run(
    run_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Continue an interrupted run from its last durable checkpoint.

    Completed tool calls are not repeated: the resume re-enters the normal
    execution path with the continuation instruction, and the kernel's per-turn
    repair marks any call whose result was lost as *unknown* rather than
    re-running it. ``skipped`` names the reason when the run cannot be taken
    over; ``unsafe_tools`` names the calls whose side effects may already have
    happened and which therefore must not be repeated blindly.

    Two things this endpoint deliberately does *not* decide for the caller:

    * A run that was ``waiting`` on an approval/plan/input when the process died
      comes back as ``failed`` and its question is gone, so an explicit resume
      continues without that answer. The automatic boot recovery refuses such a
      run (``RuntimeManager._resumable``), because continuing it unprompted would
      answer the user's question for them; here the caller has asked for it by
      name, which is taken as the answer being "go ahead".
    * The caller's own retries are not counted against ``MAX_RESUME_ATTEMPTS``.
      That budget exists to stop a *crash loop* from re-running the same work on
      every boot, and only the boot path spends it; an explicit request is a
      decision, not a loop. No attempt of either kind replays a tool.
    """
    _check_run_id(run_id)
    digest = await asyncio.to_thread(summarize_checkpoints, run_id)
    from atlas.api.run_drive import resume_run_after_restart

    manager = services.runtime_mgr
    run = manager.runs.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="找不到这次运行的运行态；进程重启后的运行态保存在 runtime_runs 中，若已被清理则无法续跑。",
        )

    before = run.status
    reason = _skip_reason(run, manager)
    warnings = _resume_warnings(run)
    if reason is None and not await resume_run_after_restart(run, manager=manager):
        # resume_run_after_restart logs the precise reason; mirror it in a code
        # the caller can branch on instead of parsing a log line.
        reason = _skip_reason(run, manager, after_attempt=True)
    if reason is not None:
        return {
            "run_id": run_id,
            "resumed": False,
            "skipped": reason,
            "status_before": before,
            "status": run.status,
            "warnings": warnings,
            "digest": digest,
            "notice": _SKIP_NOTICE.get(reason, _SKIP_NOTICE["unknown"]),
        }

    return {
        "run_id": run_id,
        "resumed": True,
        "skipped": None,
        "status_before": before,
        "status": run.status,
        "resume_attempt": run.resume_attempts,
        "warnings": warnings,
        "digest": digest,
        "notice": (
            "已从中断处续跑：已完成的工具调用不会重做。"
            + (
                f"以下有副作用的调用未自动重放，请确认其实际状态：{', '.join(digest['unsafe_tools'])}。"
                if digest.get("unsafe_tools")
                else ""
            )
        ),
    }


def _resume_warnings(run: Any) -> list[str]:
    """Where this explicit resume goes further than the automatic boot path.

    Both differences are deliberate, and both are things the caller should know
    rather than discover: neither one replays a tool call, but the first drops a
    question that was never answered and the second overrides the crash-loop
    budget. An empty list means the two paths would have agreed.
    """
    out: list[str] = []
    if run.waiting_for:
        out.append(
            f"这次运行中断时正在等待用户回答（{run.waiting_for}），该问题已经失效；"
            "续跑会按“继续”处理。"
        )
    if run.resume_attempts >= MAX_RESUME_ATTEMPTS:
        out.append(
            f"这次运行已经自动续跑过 {run.resume_attempts} 次（上限 {MAX_RESUME_ATTEMPTS}），"
            "本次是显式续跑，不占用该上限。"
        )
    return out


def _skip_reason(run: Any, manager: Any, *, after_attempt: bool = False) -> str | None:
    """Which guard in ``resume_run_after_restart`` would refuse this run.

    Mirrors that function's conditions in the same order; it exists only so the
    HTTP answer carries a stable code, never to make a different decision.

    The first four codes are decided *before* any work starts. ``finished`` is
    the one condition this router adds on purpose: a run that already reached a
    final status (completed / cancelled) has nothing left to continue, and
    re-entering the executor for it would spend a whole extra model turn on a
    finished task. ``failed`` is *not* such a status -- it is what the shutdown
    leaves an interrupted run in, so it is the main thing this endpoint resumes.
    Continuing a finished run on purpose is a new turn, which the caller starts
    through the normal chat endpoint.
    """
    active = manager.runs.get(run.run_id)
    if active is not None and active.task is not None and not active.task.done():
        return "already_active"
    if not (run.conversation_id or "").strip():
        return "no_conversation"
    if run.executor != "atlas":
        return "not_atlas_executor"
    if not after_attempt and run.status in _NOT_RESUMABLE:
        return "finished"
    # The last refusal (`rules_need_trust`) is only visible from inside
    # resume_run_after_restart, which emits its own notice; anything else that
    # leaves the run untaken is reported as unknown rather than guessed at.
    return None if not after_attempt else "unknown"


_SKIP_NOTICE = {
    "finished": (
        "这次运行已经正常结束（completed/cancelled），没有中断点可续跑。"
        "检查点可直接读取以免重跑；要继续做事请新开一轮对话。"
    ),
    "already_active": "这次运行正在执行中，无需续跑。",
    "no_conversation": "这次运行没有会话，无法重建上下文，因此不会续跑。",
    "not_atlas_executor": "这次运行不是由 Atlas 执行器驱动的，续跑会跑错循环，因此不会续跑。",
    "rules_need_trust": (
        "工作区规则文件需要你重新确认信任后才能继续；请重新发送这条消息。"
    ),
    "unknown": (
        "这次运行没有被续跑（原因见 skipped）。已完成并写入检查点的工具调用"
        "不会被重做；未拿到结果的调用也不会被静默重放。"
    ),
}
