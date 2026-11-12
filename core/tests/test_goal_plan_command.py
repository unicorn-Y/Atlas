"""/goal plan: inspect and override the decomposition gate."""

from __future__ import annotations

import pytest

from atlas.engine import goals
from atlas.engine.goal_command import dispatch_goal_command


@pytest.fixture()
def manager(tmp_path):
    return goals.GoalManager("plan-cmd", home=tmp_path)


def run(manager, arg):
    return dispatch_goal_command(manager, arg, authorize_gate=lambda: None)


def test_plan_without_a_goal_is_an_error(manager):
    result = run(manager, "plan")
    assert result.error is True
    assert "set a goal first" in result.output


def test_plan_reports_pending_planning_turn(manager):
    manager.set("ship the release")
    result = run(manager, "plan")
    assert result.error is False
    assert "required" in result.output
    assert "planning turn" in result.output


def test_plan_off_disables_the_gate(manager):
    manager.set("a single lookup")
    result = run(manager, "plan off")
    assert "Plan gate off" in result.output
    assert manager.state.decomposition_required is False
    assert manager.state.needs_plan() is False


def test_plan_on_restores_the_gate(manager):
    manager.set("ship the release")
    run(manager, "plan off")
    result = run(manager, "plan on")
    assert "Plan gate on" in result.output
    assert manager.state.decomposition_required is True
    assert manager.state.needs_plan() is True


def test_plan_off_is_refused_once_milestones_exist(manager):
    manager.set("ship the release")
    manager.add_subgoal("write the notes")
    result = run(manager, "plan off")
    assert "only applies" in result.output
    assert manager.state.decomposition_required is True


def test_plan_lists_milestones_with_progress(manager):
    manager.set("ship the release")
    manager.add_subgoal("write the notes")
    manager.add_subgoal("tag the build")
    manager.complete_subgoal(1)
    result = run(manager, "plan")
    assert "1/2 complete" in result.output
    assert "[x] 1. write the notes" in result.output
    assert "[ ] 2. tag the build" in result.output
    assert "planning turn" not in result.output


def test_plan_shows_gate_off_with_no_milestones(manager):
    manager.set("a single lookup")
    manager.state.decomposition_required = False
    result = run(manager, "plan")
    assert "off" in result.output
    assert "gate is off" in result.output


def test_plan_off_is_persisted(manager, tmp_path):
    manager.set("a single lookup")
    run(manager, "plan off")
    reloaded = goals.GoalManager("plan-cmd", home=tmp_path)
    assert reloaded.state.decomposition_required is False
    assert reloaded.state.needs_plan() is False
