"""Tests for draft_contract — the /goal draft path that used to AttributeError."""

from __future__ import annotations

from atlas.engine.goal_command import dispatch_goal_command
from atlas.engine.goals import GoalContract, draft_contract


def _no_gate():
    return None


def test_draft_parses_json_object():
    def complete(_prompt):
        return ('{"outcome": "the build is green", "verification": "pytest -q exits 0", '
                '"constraints": "do not change public API", "boundaries": "", '
                '"stop_when": "a dependency must be upgraded"}')

    contract = draft_contract("make the build green", complete=complete)
    assert isinstance(contract, GoalContract)
    assert contract.outcome == "the build is green"
    assert contract.verification == "pytest -q exits 0"
    assert contract.boundaries == ""
    assert contract.stop_when == "a dependency must be upgraded"


def test_draft_tolerates_prose_around_json():
    def complete(_prompt):
        return 'Sure, here you go:\n{"outcome": "done thing"}\nHope that helps.'

    contract = draft_contract("do the thing", complete=complete)
    assert contract is not None
    assert contract.outcome == "done thing"


def test_draft_returns_none_without_json():
    contract = draft_contract("do it", complete=lambda _p: "I cannot help with that.")
    assert contract is None


def test_draft_returns_none_on_malformed_json():
    contract = draft_contract("do it", complete=lambda _p: '{"outcome": "x",}')
    assert contract is None


def test_draft_returns_none_when_all_fields_empty():
    """An all-empty contract is not a contract; caller must fall back."""
    contract = draft_contract("do it", complete=lambda _p: '{"outcome": "", "verification": ""}')
    assert contract is None


def test_draft_returns_none_on_empty_goal():
    contract = draft_contract("   ", complete=lambda _p: '{"outcome": "x"}')
    assert contract is None


def test_draft_swallows_model_errors():
    def boom(_prompt):
        raise RuntimeError("model down")

    assert draft_contract("do it", complete=boom) is None


def test_draft_returns_none_when_json_is_not_object():
    assert draft_contract("do it", complete=lambda _p: '["a", "b"]') is None


def test_draft_prompt_includes_goal_and_fields():
    seen = {}

    def complete(prompt):
        seen["prompt"] = prompt
        return '{"outcome": "x"}'

    draft_contract("ship the release", complete=complete)
    prompt = seen["prompt"]
    assert "ship the release" in prompt
    for field in ("outcome", "verification", "constraints", "boundaries", "stop_when"):
        assert field in prompt


def test_draft_does_not_invent_requirements_note():
    """The prompt must tell the model to leave unknown fields empty."""
    seen = {}
    draft_contract("vague ask", complete=lambda p: seen.setdefault("p", p) and '{"outcome": "x"}')
    assert "empty string" in seen["p"]


def test_goal_draft_command_reaches_draft_contract(tmp_path, monkeypatch):
    """/goal draft must actually call drafting, not fall into the except branch."""
    import atlas.engine.goals as goals_module

    called = {}

    def fake_draft(goal, **_kwargs):
        called["goal"] = goal
        return GoalContract(outcome="a drafted outcome")

    monkeypatch.setattr(goals_module, "draft_contract", fake_draft)

    from atlas.engine.goals import GoalManager

    manager = GoalManager("s1", home=tmp_path)
    got = dispatch_goal_command(manager, "draft make it fast", authorize_gate=_no_gate)
    assert not got.error
    assert called["goal"] == "make it fast"
    assert "a drafted outcome" in got.output
    assert manager.state.has_contract()
