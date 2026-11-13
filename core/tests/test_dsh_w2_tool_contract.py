"""W2 contracts for typed tool stages and registered output schemas."""

import pytest

from atlas.engine.kernel.tools import (
    ToolDecision,
    ToolDecisionKind,
    ToolScheduler,
)
from atlas.engine.tools.registry import ToolRegistry

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_scheduler_runs_typed_pre_post_and_result_stages_in_order():
    stages = []

    async def dispatch(call_id, name, args):
        stages.append("execute")
        return {"value": args["value"]}

    def pre(call_id, name, args):
        stages.append("pre_execute")
        return ToolDecision.replace({**args, "value": args["value"] + 1})

    def post(call_id, name, args, output):
        stages.append("post_execute")
        return ToolDecision.replace({**output, "value": output["value"] + 1})

    def result(call_id, name, args, output):
        stages.append("result")
        return ToolDecision()

    scheduler = ToolScheduler(
        dispatch, pre_execute=pre, post_execute=post, result_stage=result,
    )
    receipt = await scheduler.execute({
        "id": "c1", "function": {"name": "inspect", "arguments": {"value": 1}},
    })

    assert stages == ["pre_execute", "execute", "post_execute", "result"]
    assert receipt.output == {"value": 3}
    assert receipt.receipt.state == "completed"


@pytest.mark.asyncio
async def test_pre_execute_deny_skips_execution_and_returns_typed_denial():
    calls = []
    scheduler = ToolScheduler(
        lambda *_: calls.append("execute"),
        pre_execute=lambda *_: ToolDecision.deny("policy declined"),
    )

    result = await scheduler.execute({
        "id": "c2", "function": {"name": "write", "arguments": {}},
    })

    assert calls == []
    assert result.receipt.state == "denied"
    assert result.output["outcome"] == "denied"
    assert ToolDecisionKind.DENY.value == "deny"


def test_registry_validates_declared_output_schema_and_exposes_presentation_contract():
    registry = ToolRegistry()
    registry.register(
        "w2_contract_probe", "w2", {"parameters": {"type": "object"}},
        lambda _args: "valid", output_schema={"type": "string", "minLength": 3},
        render="markdown", presentation_meta={"icon": "check"},
    )
    try:
        assert registry.dispatch("w2_contract_probe", {}) == "valid"
        contract = registry.get_output_contract("w2_contract_probe")
        assert contract.schema["minLength"] == 3
        assert contract.render == "markdown"
        assert contract.presentation_meta == {"icon": "check"}
    finally:
        registry.deregister("w2_contract_probe")


def test_registry_rejects_handler_output_that_violates_declared_schema():
    registry = ToolRegistry()
    registry.register(
        "w2_invalid_probe", "w2", {"parameters": {"type": "object"}},
        lambda _args: "x", output_schema={"type": "string", "minLength": 3},
    )
    try:
        result = registry.dispatch("w2_invalid_probe", {})
        assert isinstance(result, str)
        assert "tool_output_schema" in result, repr(result)
    finally:
        registry.deregister("w2_invalid_probe")


def test_registry_assigns_a_compatibility_output_contract_to_legacy_tools():
    registry = ToolRegistry()
    registry.register(
        "w2_legacy_probe", "w2", {"parameters": {"type": "object"}},
        lambda _args: "ok",
    )
    try:
        contract = registry.get_output_contract("w2_legacy_probe")
        assert contract is not None
        assert contract.render == "text"
        assert contract.presentation_meta == {}
        assert registry.dispatch("w2_legacy_probe", {}) == "ok"
    finally:
        registry.deregister("w2_legacy_probe")
