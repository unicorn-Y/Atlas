"""Tests for cross-restart goal resumption.

Every case writes real rows through ``SessionDB`` and reads them back through
the same door production uses, so a schema change breaks these tests rather
than silently producing empty scans.
"""

from __future__ import annotations

import time

import pytest

from atlas.engine.goal_loop import (
    GOAL_META_PREFIX,
    resume_prompt,
    scan_resumable_goals,
    summarize,
)
from atlas.engine.goals import GoalManager, GoalState


@pytest.fixture()
def home(tmp_path):
    """A data root holding a real state.db, as production passes to GoalManager."""
    return tmp_path


def _persist(home, session_id: str, **state_kwargs) -> GoalState:
    """Write one goal row the way GoalManager does, then return it."""
    state = GoalState(goal=state_kwargs.pop("goal", "ship the feature"), **state_kwargs)
    home.joinpath("state.db").touch(exist_ok=True)
    from atlas.engine.state.atlas_state import SessionDB

    with SessionDB(db_path=home / "state.db") as db:
        db.set_meta(f"{GOAL_META_PREFIX}{session_id}", state.to_json())
    return state


def test_no_home_returns_nothing():
    assert scan_resumable_goals(None) == []


def test_missing_state_db_returns_nothing(tmp_path):
    assert scan_resumable_goals(tmp_path) == []


def test_active_goal_with_subgoals_is_resumable(home):
    _persist(home, "s1", subgoals=["design", "build", "verify"], completed_subgoals=[1])
    found = scan_resumable_goals(home)
    assert len(found) == 1
    assert found[0].session_id == "s1"
    assert found[0].remaining_subgoals == ("build", "verify")


def test_paused_goal_is_not_resumed(home):
    _persist(home, "s1", status="paused")
    assert scan_resumable_goals(home) == []


def test_done_goal_is_not_resumed(home):
    _persist(home, "s1", status="done")
    assert scan_resumable_goals(home) == []


def test_settombstone_status_cleared_is_skipped(home):
    """`/goal clear` writes a tombstone; it must never come back."""
    from atlas.engine.state.atlas_state import SessionDB

    home.joinpath("state.db").touch(exist_ok=True)
    with SessionDB(db_path=home / "state.db") as db:
        db.set_meta(f"{GOAL_META_PREFIX}s1", '{"goal": "", "status": "cleared"}')
    assert scan_resumable_goals(home) == []


def test_corrupt_row_is_skipped_without_raising(home):
    from atlas.engine.state.atlas_state import SessionDB

    home.joinpath("state.db").touch(exist_ok=True)
    with SessionDB(db_path=home / "state.db") as db:
        db.set_meta(f"{GOAL_META_PREFIX}s1", "{not json")
    assert scan_resumable_goals(home) == []


def test_future_wait_barrier_is_respected(home):
    _persist(home, "s1", waiting_until=time.time() + 3600)
    assert scan_resumable_goals(home) == []


def test_expired_wait_barrier_is_cleared_for_resume(home):
    _persist(home, "s1", waiting_until=time.time() - 10)
    found = scan_resumable_goals(home)
    assert len(found) == 1


def test_dead_pid_wait_does_not_block_resume(home):
    """A wait on a process that no longer exists must not strand the goal."""
    _persist(home, "s1", waiting_on_pid=999998)
    found = scan_resumable_goals(home)
    assert len(found) == 1


def test_live_pid_wait_blocks_resume(home):
    import os

    _persist(home, "s1", waiting_on_pid=os.getpid())
    assert scan_resumable_goals(home) == []


def test_all_subgoals_done_is_surfaced_not_resumed_silently(home):
    _persist(home, "s1", subgoals=["a", "b"], completed_subgoals=[1, 2])
    found = scan_resumable_goals(home)
    assert len(found) == 1
    assert found[0].remaining_subgoals == ()
    assert "never marked done" in found[0].reason


def test_multiple_sessions_sorted(home):
    _persist(home, "zeta")
    _persist(home, "alpha")
    assert [item.session_id for item in scan_resumable_goals(home)] == ["alpha", "zeta"]


def test_other_meta_prefixes_ignored(home):
    from atlas.engine.state.atlas_state import SessionDB

    home.joinpath("state.db").touch(exist_ok=True)
    with SessionDB(db_path=home / "state.db") as db:
        db.set_meta("loop:s1", "irrelevant")
    assert scan_resumable_goals(home) == []


def test_resume_prompt_names_first_remaining_subgoal(home):
    _persist(home, "s1", subgoals=["design", "build"], completed_subgoals=[1])
    goal = scan_resumable_goals(home)[0]
    prompt = resume_prompt(goal)
    assert "build" in prompt
    assert "design" not in prompt.split("Remaining milestones")[-1]
    assert "1/1000" in prompt or "used" in prompt


def test_resume_prompt_for_finished_subgoals_asks_for_verification(home):
    _persist(home, "s1", subgoals=["a"], completed_subgoals=[1])
    prompt = resume_prompt(scan_resumable_goals(home)[0])
    assert "Verify the goal is truly" in prompt


def test_resume_prompt_wraps_in_canonical_goal_kick(home):
    """A resumed goal must speak like a freshly `/goal`-ed one."""
    _persist(home, "s1", subgoals=["x"])
    prompt = resume_prompt(scan_resumable_goals(home)[0])
    assert "[Working toward this goal]" in prompt


def test_summarize_counts(home):
    _persist(home, "s1", subgoals=["a"])
    _persist(home, "s2", subgoals=["b"], completed_subgoals=[1], turns_used=7)
    stats = summarize(scan_resumable_goals(home))
    assert stats["resumable"] == 2
    assert stats["with_remaining_subgoals"] == 1
    assert stats["all_subgoals_done"] == 1
    assert stats["turns_used_total"] == 7
    assert stats["sessions"] == ["s1", "s2"]


def test_summarize_empty():
    assert summarize([])["resumable"] == 0


def test_real_goal_manager_roundtrip(tmp_path):
    """The scan must read what GoalManager itself wrote, not a hand-built shape."""
    manager = GoalManager("conv-1", home=tmp_path)
    manager.set("real goal")
    manager.add_subgoal("first")
    manager.add_subgoal("second")
    found = scan_resumable_goals(tmp_path)
    assert len(found) == 1
    assert found[0].goal == "real goal"
    assert found[0].remaining_subgoals == ("first", "second")


def test_cleared_goal_manager_leaves_nothing_resumable(tmp_path):
    manager = GoalManager("conv-1", home=tmp_path)
    manager.set("real goal")
    manager.clear()
    assert scan_resumable_goals(tmp_path) == []


def test_resumable_goal_to_dict_is_json_safe(home):
    import json

    _persist(home, "s1", subgoals=["a", "b"], completed_subgoals=[1])
    payload = json.dumps(scan_resumable_goals(home)[0].to_dict(), ensure_ascii=False)
    assert '"remaining_subgoals": ["b"]' in payload
