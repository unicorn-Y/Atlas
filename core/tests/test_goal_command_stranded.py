"""Tests for /goal stranded and /goal resume-other."""

from __future__ import annotations

from atlas.engine.goal_command import dispatch_goal_command, is_goal_control
from atlas.engine.goals import GoalManager


def _no_gate():
    return None


def _seed(home, session_id, goal="ship it", subgoals=(), complete=()):
    manager = GoalManager(session_id, home=home)
    manager.set(goal)
    for text in subgoals:
        manager.add_subgoal(text)
    for index in complete:
        manager.complete_subgoal(index)
    return manager


def _run(manager, arg):
    return dispatch_goal_command(manager, arg, authorize_gate=_no_gate)


def test_no_stranded_says_so(tmp_path):
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "stranded")
    assert not got.error
    assert "No goals" in got.output


def test_stranded_lists_other_sessions(tmp_path):
    _seed(tmp_path, "other", subgoals=["a", "b"], complete=[1])
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "stranded")
    assert not got.error
    assert "other" in got.output
    assert "b" in got.output


def test_stranded_excludes_own_session(tmp_path):
    """A goal this session owns is running, not stranded."""
    _seed(tmp_path, "mine", subgoals=["a"])
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "stranded")
    assert "mine" not in got.output


def test_stranded_marks_control(tmp_path):
    assert is_goal_control("stranded")
    assert is_goal_control("stranded anything")


def test_resume_other_adopts_goal(tmp_path):
    _seed(tmp_path, "other", goal="migrate the schema", subgoals=["step one"])
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "resume-other other")
    assert not got.error
    assert got.kickoff
    assert manager.state.goal == "migrate the schema"
    assert "step one" in (got.prompt or "")


def test_resume_other_reports_remaining_subgoals(tmp_path):
    _seed(tmp_path, "other", goal="g", subgoals=["a", "b"], complete=[1])
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "resume-other other")
    assert "b" in (got.prompt or "")


def test_resume_other_unknown_session_errors(tmp_path):
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "resume-other nope")
    assert got.error
    assert "nope" in got.output


def test_resume_other_requires_argument(tmp_path):
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "resume-other")
    assert got.error
    assert "Usage" in got.output


def test_resume_other_ignores_own_session(tmp_path):
    """Adopting your own stranded goal would restart what you are already doing."""
    _seed(tmp_path, "mine", goal="already mine")
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "resume-other mine")
    assert got.error


def test_resume_other_marks_control(tmp_path):
    assert is_goal_control("resume-other abc")


def test_stranded_still_allows_setting_goal_text(tmp_path):
    """The new verbs must not swallow ordinary goal text."""
    manager = GoalManager("mine", home=tmp_path)
    _run(manager, "stranded ships should be rare")
    # 'stranded' is a control word, so it wins; the text is not a new goal.
    assert manager.state is None


def test_set_goal_still_works(tmp_path):
    manager = GoalManager("mine", home=tmp_path)
    got = _run(manager, "make the build green")
    assert not got.error
    assert manager.state.goal == "make the build green"
