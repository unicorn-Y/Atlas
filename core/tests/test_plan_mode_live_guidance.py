"""Plan mode guidance must reach the model for the *live* mode, not the start mode.

``system_prompt`` is assembled once before the turn loop, and ``PlanMode`` is
constructed after it. A model that calls ``EnterPlanMode`` mid-run therefore got
the read-only tool restriction with none of the instruction text explaining what
to do instead — the run was restricted but unguided. Two separate flags made it
worse: the tool gate read ``dynamic_plan_mode`` while the prompt builder read
``mode``.

The turn loop now rebuilds the plan guidance from the live mode on every prompt
assembly, and both entry points switch the same ``PlanMode`` instance rather than
a per-call copy of the run context.
"""

from __future__ import annotations

import copy

import pytest

from atlas.engine.kernel.plan import PlanMode

pytestmark = pytest.mark.unit


class _RunContext:
    """Stand-in for AgentRunContext: exposes exactly what PlanMode touches."""

    __slots__ = ("mode", "dynamic_plan_mode", "plan_mode", "plan_state")

    def __init__(self) -> None:
        self.mode = "act"
        self.dynamic_plan_mode = False
        self.plan_mode = None
        self.plan_state = None


def _plan(run: _RunContext) -> PlanMode:
    return PlanMode(run, {}, plan_update_callback=lambda snapshot: None)


def test_live_mode_is_read_from_the_shared_run_context_not_the_copy():
    run = _RunContext()
    plan = _plan(run)
    # This mirrors what the kernel does: tool handlers get a shallow copy, with
    # the PlanMode instance attached so both sides read the same live object.
    proxy = copy.copy(run)
    proxy.plan_mode = plan

    assert plan.active is False

    proxy.plan_mode.enter()

    # The original run context is the one the prompt builder reads.
    assert run.mode == "plan"
    assert plan.active is True


def test_writing_the_copy_alone_would_be_invisible_to_the_prompt_builder():
    """Pins *why* the tool handler must not write ``runtime.mode`` directly."""
    run = _RunContext()
    proxy = copy.copy(run)

    proxy.mode = "plan"

    assert run.mode == "act"


def test_plan_guidance_text_is_non_empty_only_when_active():
    run = _RunContext()
    plan = _plan(run)

    assert plan.prompt() == ""

    plan.enter()

    guidance = plan.prompt()
    assert "Plan mode" in guidance
    assert "read-only" in guidance


def test_enter_and_approve_round_trip_switches_the_live_mode():
    run = _RunContext()
    plan = _plan(run)

    plan.enter()
    assert run.mode == "plan"

    plan.approve(user_approved=True)
    assert run.mode == "act"


def test_approval_without_user_authorisation_is_refused():
    run = _RunContext()
    plan = _plan(run)
    plan.enter()

    with pytest.raises(PermissionError):
        plan.approve(user_approved=False)

    # A refused approval must leave plan mode in place.
    assert run.mode == "plan"


def test_tool_filter_restricts_to_read_only_while_active():
    run = _RunContext()
    plan = _plan(run)
    tools = [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "write_file"}},
    ]

    assert [tool["function"]["name"] for tool in plan.filter_tools(tools)] == [
        "read_file", "write_file",
    ]

    plan.enter()

    assert [tool["function"]["name"] for tool in plan.filter_tools(tools)] == ["read_file"]
