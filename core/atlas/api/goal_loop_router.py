"""Read and resume goals that are still active on disk.

A goal is written by ``GoalManager`` into ``state_meta['goal:<session>']`` and
kept advancing by the in-run driver. Nothing survives a restart, so a goal that
was mid-flight when Atlas exited is invisible: the row is still there, but no
process is working on it. These endpoints surface those rows and hand the caller
what it needs to continue one without guessing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.config import DATA_ROOT
from atlas.engine.goal_loop import (
    resume_prompt,
    scan_resumable_goals,
    summarize,
)
from atlas.engine.goals import GoalManager

log = logging.getLogger(__name__)

router = APIRouter(tags=["goals"])


def _engine_home():
    """The directory holding ``state.db``, matching what the driver passes."""
    return DATA_ROOT / "engine"


class ResumePayload(BaseModel):
    # Explicit acknowledgement: continuing a goal spends turns, so a bare GET
    # must never trigger it.
    session_id: str = Field(min_length=1, max_length=200)


@router.get("/api/engine-goals/stranded")
async def list_stranded_goals() -> dict[str, Any]:
    """Every persisted engine goal that no process is currently advancing.

    Deliberately not under ``/api/goals``: that namespace belongs to the
    scheduler's goal tasks. These are the session goals ``GoalManager`` writes
    into ``state_meta``, a different object with a different lifetime.
    """
    goals = await asyncio.to_thread(scan_resumable_goals, _engine_home())
    return {
        "goals": [goal.to_dict() for goal in goals],
        "summary": summarize(goals),
    }


@router.post("/api/engine-goals/resume")
async def resume_stranded_goal(payload: ResumePayload) -> dict[str, Any]:
    """Return the continuation prompt for one stranded goal.

    This does not run the turn itself — the caller owns execution and its
    cancellation — it only proves the goal still exists and is still resumable,
    then hands back the prompt the driver should send.
    """
    home = _engine_home()
    goals = await asyncio.to_thread(scan_resumable_goals, home)
    match = next((item for item in goals if item.session_id == payload.session_id), None)
    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"没有可恢复的目标：{payload.session_id!r} 不在可恢复列表中。",
        )
    manager = GoalManager(payload.session_id, home=home)
    if not manager.is_active():
        raise HTTPException(
            status_code=409,
            detail=f"目标 {payload.session_id!r} 当前不是活动状态，未恢复。",
        )
    return {
        "session_id": match.session_id,
        "goal": match.goal,
        "remaining_subgoals": list(match.remaining_subgoals),
        "reason": match.reason,
        "continuation_prompt": resume_prompt(match),
    }
