"""Resume active goals across process restarts.

``GoalManager`` persists each session's goal as ``state_meta['goal:<session_id>']``.
The in-run driver (``run_drive._execute_run``) keeps a goal advancing while its
own process lives, but nothing re-reads those rows on startup — so a goal that
was mid-flight when Atlas exited is never resumed, even though its state,
subgoals and turn budget are all on disk.

This module is that startup sweep. It reports goals it can prove are resumable
without guessing: a goal qualifies only when its status is ``active`` and it is
not parked on a wait barrier whose owner is gone. It never marks a goal done
and never spends a turn; it only hands back what the driver needs to continue.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.engine.goals import GoalState

log = logging.getLogger(__name__)

GOAL_META_PREFIX = "goal:"


@dataclass(frozen=True)
class ResumableGoal:
    """One persisted goal that survived a restart and can be continued."""

    session_id: str
    goal: str
    status: str
    turns_used: int
    max_turns: int
    remaining_subgoals: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "turns_used": self.turns_used,
            "max_turns": self.max_turns,
            "remaining_subgoals": list(self.remaining_subgoals),
            "reason": self.reason,
        }


def _pid_alive_windows(pid: int) -> bool:
    """Liveness via ``OpenProcess``, never via a signal.

    ``os.kill(pid, 0)`` is not a portable probe: on Windows CPython does not
    implement the ``sig=0`` no-op POSIX defines, so probing a live pid can
    terminate it instead of merely observing it. That makes it unusable for the
    job this function has — checking whether a *wait barrier* still has an owner.
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        # No such process, or one we may not query. Either way we cannot prove it
        # is waiting, and a barrier nobody can verify must not strand the goal.
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """True when ``pid`` is a live process, probed without sending it a signal."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return _pid_alive_windows(pid)
        except Exception:
            log.debug("goal_loop.pid_probe_failed", extra={"pid": pid}, exc_info=True)
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_still_valid(state: GoalState, *, now: float) -> bool:
    """True when the recorded wait barrier still has a live owner."""
    if state.waiting_until and now < state.waiting_until:
        return True
    if state.waiting_on_pid and _pid_alive(state.waiting_on_pid):
        return True
    # A delegation wait is not something this module can verify from disk; treat
    # it as spent rather than block the goal forever on a counter no process owns.
    return False


def _decode(session_id: str, raw: str) -> GoalState | None:
    """Parse one persisted goal row, or None when it is unusable."""
    try:
        state = GoalState.from_json(raw)
    except (ValueError, TypeError, KeyError):
        log.warning("goal_loop.unreadable_state", extra={"session_id": session_id})
        return None
    if not state.goal:
        return None
    return state


def scan_resumable_goals(
    home: str | Path | None, *, now: float | None = None,
) -> list[ResumableGoal]:
    """Return every persisted goal that is still worth continuing.

    ``home`` is the directory holding ``state.db`` — the same value
    ``GoalManager`` receives, so callers must pass what they already pass there
    (the engine data root), never a guess.
    """
    if home is None:
        return []
    import time as _time

    moment = _time.time() if now is None else float(now)
    path = Path(home).expanduser().resolve() / "state.db"
    if not path.exists():
        return []

    from atlas.engine.state.atlas_state import SessionDB

    try:
        with SessionDB(db_path=path) as db:
            rows = db.list_meta_prefix(GOAL_META_PREFIX)
    except Exception:
        log.exception("goal_loop.scan_failed")
        return []

    found: list[ResumableGoal] = []
    for key, raw in rows:
        session_id = str(key)[len(GOAL_META_PREFIX):]
        if not session_id or not isinstance(raw, str):
            continue
        state = _decode(session_id, raw)
        if state is None or state.status != "active":
            continue
        if _wait_still_valid(state, now=moment):
            continue
        done = set(state.completed_subgoals)
        remaining = tuple(
            text for index, text in enumerate(state.subgoals, 1) if index not in done
        )
        if state.subgoals and not remaining:
            # Every milestone is ticked but the goal was never closed out. That is
            # a judgement call for the driver, not a silent resume — surface it.
            found.append(ResumableGoal(
                session_id=session_id, goal=state.goal, status=state.status,
                turns_used=state.turns_used, max_turns=state.max_turns,
                remaining_subgoals=(),
                reason="all subgoals complete but goal never marked done",
            ))
            continue
        found.append(ResumableGoal(
            session_id=session_id, goal=state.goal, status=state.status,
            turns_used=state.turns_used, max_turns=state.max_turns,
            remaining_subgoals=remaining,
            reason="active goal interrupted by restart",
        ))

    found.sort(key=lambda item: (item.session_id,))
    return found


def resume_prompt(goal: ResumableGoal) -> str:
    """Continuation prompt for one resumable goal, built from persisted state."""
    from atlas.engine.goals import goal_kick_prompt

    lines = [
        "[Resuming a goal that was interrupted by a restart]",
        goal.goal,
    ]
    if goal.remaining_subgoals:
        lines.append("\nRemaining milestones (persisted):")
        lines.extend(f"- [ ] {text}" for text in goal.remaining_subgoals)
        lines.append(f"\nStart at: {goal.remaining_subgoals[0]}")
    else:
        lines.append("\nEvery milestone is already marked complete. Verify the goal is truly "
                     "achieved, then close it; if it is not, add the missing milestones first.")
    lines.append(
        f"\nTurn budget: {goal.turns_used}/{goal.max_turns} used. "
        "Continue until the goal is complete or you are blocked."
    )
    # Reuse the canonical kick prompt so a resumed goal speaks exactly like a
    # freshly `/goal`-ed one; do not fork a second prompt dialect.
    return goal_kick_prompt("\n".join(lines))


def summarize(goals: Iterable[ResumableGoal]) -> dict[str, Any]:
    """One-line health view for the console/CLI: how many goals are stranded."""
    items = list(goals)
    return {
        "resumable": len(items),
        "sessions": [item.session_id for item in items],
        "with_remaining_subgoals": sum(1 for item in items if item.remaining_subgoals),
        "all_subgoals_done": sum(1 for item in items if not item.remaining_subgoals),
        "turns_used_total": sum(item.turns_used for item in items),
    }


def pid_alive(pid: int) -> bool:
    """Public alias for :func:`_pid_alive`.

    Exported because the same dangerous ``os.kill(pid, 0)`` liveness probe used to
    live in ``GoalManager.is_waiting``; anything that needs to test a PID without
    disturbing it should come here instead of reaching for ``os.kill``.
    """
    return _pid_alive(pid)


__all__ = [
    "GOAL_META_PREFIX",
    "ResumableGoal",
    "pid_alive",
    "resume_prompt",
    "scan_resumable_goals",
    "summarize",
]
