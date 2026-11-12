"""The decomposition gate: a fresh goal must plan before it implements, but never forever."""

from __future__ import annotations

import pytest

from atlas.engine.goals import (
    MAX_PLAN_ATTEMPTS,
    GoalManager,
    GoalState,
    goal_kick_prompt,
)


@pytest.fixture()
def manager(tmp_path):
    return GoalManager("gate-session", home=tmp_path)


def test_fresh_goal_requires_plan(manager):
    manager.set("ship the release")
    assert manager.state.needs_plan() is True


def test_goal_with_subgoals_does_not_require_plan(manager):
    manager.set("ship the release")
    manager.add_subgoal("write the notes")
    assert manager.state.needs_plan() is False


def test_empty_goal_text_never_requires_plan():
    assert GoalState(goal="   ").needs_plan() is False


def test_gate_can_be_switched_off(manager):
    manager.set("a one-line lookup")
    manager.state.decomposition_required = False
    assert manager.state.needs_plan() is False


def test_gate_is_bounded_and_gives_up(manager):
    """A model that never decomposes must not trap the goal in planning forever."""
    manager.set("ship the release")
    assert manager.state.needs_plan() is True

    for _ in range(MAX_PLAN_ATTEMPTS):
        manager.next_continuation_prompt()

    assert manager.state.plan_attempts >= MAX_PLAN_ATTEMPTS
    assert manager.state.needs_plan() is False, "plan gate must expire, not loop forever"
    # And the goal is still active — expiring the gate must not pause or fail it.
    assert manager.state.status == "active"
    assert manager.is_active() is True


def test_saving_a_subgoal_clears_the_gate_immediately(manager):
    manager.set("ship the release")
    manager.next_continuation_prompt()
    assert manager.state.plan_attempts == 1
    manager.add_subgoal("write the notes")
    assert manager.state.needs_plan() is False


def test_continuation_prompt_carries_the_requirement(manager):
    manager.set("ship the release")
    prompt = manager.next_continuation_prompt()
    assert "PLAN REQUIRED" in prompt
    assert "goal_subgoal" in prompt
    assert prompt.startswith("[Working toward this goal]")


def test_last_planning_turn_warns_about_expiry(manager):
    manager.set("ship the release")
    first = manager.next_continuation_prompt()
    assert "last planning turn" not in first
    second = manager.next_continuation_prompt()
    assert "last planning turn" in second


def test_non_planning_continuation_is_unchanged(manager):
    manager.set("ship the release")
    manager.add_subgoal("write the notes")
    prompt = manager.next_continuation_prompt()
    assert "PLAN REQUIRED" not in prompt
    assert "write the notes" in prompt
    assert manager.state.plan_attempts == 0, "no planning turns are consumed once planned"


def test_plan_attempts_survive_a_restart(manager, tmp_path):
    manager.set("ship the release")
    manager.next_continuation_prompt()
    reloaded = GoalManager("gate-session", home=tmp_path)
    assert reloaded.state.plan_attempts == 1
    assert reloaded.state.needs_plan() is True


def test_old_state_rows_without_new_fields_load():
    """Forward compatibility: rows written before this feature must still load."""
    import json

    legacy = json.loads(GoalState(goal="legacy goal").to_json())
    legacy.pop("plan_attempts")
    legacy.pop("decomposition_required")
    raw = json.dumps(legacy)
    assert "plan_attempts" not in raw and "decomposition_required" not in raw
    parsed = GoalState.from_json(raw)
    assert parsed.decomposition_required is True
    assert parsed.plan_attempts == 0


def test_kick_prompt_require_plan_flag():
    plain = goal_kick_prompt("do the thing")
    assert "PLAN REQUIRED" not in plain
    gated = goal_kick_prompt("do the thing", require_plan=True)
    assert "PLAN REQUIRED" in gated
    assert plain.startswith(gated.split("\n\nPLAN REQUIRED")[0][:40])
