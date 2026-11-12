"""The planning-turn flag the driver records and the UI displays."""

from __future__ import annotations

import pytest

from atlas.engine.goals import MAX_PLAN_ATTEMPTS, GoalManager


def _judge(goal, response, state):
    return ("continue", "still working")


@pytest.fixture()
def manager(tmp_path):
    return GoalManager("plan-event", home=tmp_path)


def test_first_turn_is_flagged_as_planning(manager):
    manager.set("refactor the scheduler")
    decision = manager.evaluate_after_turn("looked around", judge=_judge)
    assert decision["planning_turn"] is True
    assert decision["plan_attempts"] == 1
    assert decision["max_plan_attempts"] == MAX_PLAN_ATTEMPTS
    assert decision["milestones"] == 0
    assert "PLAN REQUIRED" in decision["continuation_prompt"]


def test_expiring_flag_warns_on_last_planning_turn(manager):
    manager.set("refactor the scheduler")
    first = manager.evaluate_after_turn("turn one", judge=_judge)
    assert first["planning_turn"] is True
    remaining_before = MAX_PLAN_ATTEMPTS - first["plan_attempts"]
    assert first["plan_gate_expiring"] is (remaining_before <= 1)


def test_gate_expires_and_turns_become_execution(manager):
    manager.set("refactor the scheduler")
    for _ in range(MAX_PLAN_ATTEMPTS):
        decision = manager.evaluate_after_turn("no plan yet", judge=_judge)
        assert decision["planning_turn"] is True
    exhausted = manager.evaluate_after_turn("still no plan", judge=_judge)
    assert exhausted["planning_turn"] is False
    assert "PLAN REQUIRED" not in (exhausted["continuation_prompt"] or "")
    # The goal must stay active: the gate bounds planning, it never pauses.
    assert manager.state.status == "active"


def test_planning_a_goal_clears_the_flag(manager):
    manager.set("refactor the scheduler")
    assert manager.evaluate_after_turn("turn one", judge=_judge)["planning_turn"] is True
    manager.add_subgoal("milestone one")
    manager.add_subgoal("milestone two")
    decision = manager.evaluate_after_turn("did milestone one", judge=_judge)
    assert decision["planning_turn"] is False
    assert decision["milestones"] == 2
    assert "milestone one" in decision["continuation_prompt"]


def test_gate_off_never_flags_planning(tmp_path):
    manager = GoalManager("plan-event-off", home=tmp_path)
    manager.set("a quick lookup")
    manager.state.decomposition_required = False
    manager._save()
    decision = manager.evaluate_after_turn("done looking", judge=_judge)
    assert decision["planning_turn"] is False
    assert decision["plan_attempts"] == 0


def test_inactive_goal_reports_no_planning(tmp_path):
    manager = GoalManager("plan-event-none", home=tmp_path)
    decision = manager.evaluate_after_turn("nothing", judge=_judge)
    assert decision.get("planning_turn") is not True
