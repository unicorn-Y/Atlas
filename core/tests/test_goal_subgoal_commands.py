from atlas.engine_core.goal_command import dispatch_goal_command
from atlas.engine_core.goals import GoalManager


def test_subgoal_command_add_edit_remove_and_clear(tmp_path):
    manager = GoalManager("subgoal-test", home=tmp_path)
    manager.set("Ship the feature")
    authorize = lambda: None

    assert "saved" in dispatch_goal_command(manager, "subgoal add first", authorize_gate=authorize).output
    assert "saved" in dispatch_goal_command(manager, "subgoal add second", authorize_gate=authorize).output
    manager.complete_subgoal(2)
    assert "Updated" in dispatch_goal_command(manager, "subgoal edit 2 revised", authorize_gate=authorize).output
    assert manager.state.subgoals == ["first", "revised"]
    assert manager.state.completed_subgoals == [2]
    assert "Removed" in dispatch_goal_command(manager, "subgoal remove 1", authorize_gate=authorize).output
    assert manager.state.subgoals == ["revised"]
    assert manager.state.completed_subgoals == [1]
    assert "Cleared 1" in dispatch_goal_command(manager, "subgoal clear", authorize_gate=authorize).output
    assert manager.state.subgoals == []
    assert manager.state.completed_subgoals == []
