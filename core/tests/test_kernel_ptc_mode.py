"""Focused tests for the opt-in PTC tool transport."""

import asyncio
from types import SimpleNamespace

import pytest

from atlas.engine.kernel.loop import AtlasKernel, _final_model_tools, _tools_for_mode
from atlas.engine.kernel.request_envelope import request_envelope

pytestmark = pytest.mark.unit


def _execute_code_schema():
    return {"type": "function", "function": {
        "name": "execute_code", "description": "Execute code",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
    }}


def test_ptc_mode_replaces_execute_code_with_single_run_code_transport():
    schemas = [_execute_code_schema(), {"type": "function", "function": {"name": "read_file"}}]

    assert _tools_for_mode(schemas, "native") is schemas
    ptc_schemas = _tools_for_mode(schemas, "ptc")
    assert [schema["function"]["name"] for schema in ptc_schemas] == ["run_code"]
    assert ptc_schemas[0]["function"]["description"].startswith("Execute a Python program")


def test_ptc_mode_fails_closed_without_execute_code_and_for_unknown_modes():
    with pytest.raises(RuntimeError, match="requires execute_code"):
        _tools_for_mode([], "ptc")
    with pytest.raises(ValueError, match="unsupported tool mode"):
        _tools_for_mode([], "unexpected")


def test_ptc_final_model_request_envelope_contains_only_run_code():
    class Plan:
        def filter_tools(self, tools, *, read_only_names):
            assert read_only_names == ("build_repo_map", "concludeTurn")
            return tools

    tools = _final_model_tools(
        [_execute_code_schema(), {"type": "function", "function": {"name": "read_file"}}],
        Plan(), "ptc",
    )
    envelope = request_envelope([{"role": "user", "content": "do work"}], tools)

    assert envelope["tool_names"] == ["run_code"]


@pytest.mark.asyncio
async def test_ptc_dispatch_blocks_direct_tools_and_logs_each_nested_call(tmp_path):
    calls = []

    class Agent:
        def _model_facing_tools(self):
            return [_execute_code_schema()]

        async def execute_code(self, code, **kwargs):
            calls.append((code, kwargs))
            assert all(
                schema["function"]["name"] != "execute_code"
                for schema in kwargs["tool_catalog"]
            )
            nested_code = await kwargs["tool_dispatch"]("execute_code", {"code": "again"}, "isolated")
            assert nested_code["outcome"] == "denied"
            child_result = await kwargs["tool_dispatch"]("clock.curr_time", {}, "isolated")
            assert child_result["outcome"] == "completed"
            return {"exit_code": 0, "steps": [{"tool": "clock.curr_time"}]}

    runtime = SimpleNamespace(
        tool_mode="ptc", tool_allow=["execute_code", "clock.curr_time"], tool_deny=[],
        run_id="ptc-run", conversation_id="ptc-session", read_only=True,
    )
    kernel = AtlasKernel(data_dir=tmp_path)
    events = asyncio.Queue()

    direct = await kernel._dispatch(Agent(), runtime, "direct-1", "clock.curr_time", {}, events)
    assert direct["outcome"] == "denied"
    assert "Use run_code" in direct["content"]
    assert calls == []

    result = await kernel._dispatch(
        Agent(), runtime, "outer-1", "run_code", {"code": "print('ok')"}, events,
    )
    assert result["outcome"] == "completed"
    assert calls[0][0] == "print('ok')"
    assert calls[0][1]["tool_allow"] == runtime.tool_allow

    child_events = []
    while not events.empty():
        child_events.append(events.get_nowait())
    assert [event["type"] for event in child_events] == [
        "tool_call", "tool_result", "tool_call", "tool_result",
    ]
    assert child_events[0]["name"] == child_events[1]["name"] == "execute_code"
    assert child_events[1]["output"]["outcome"] == "denied"
    assert child_events[2]["name"] == child_events[3]["name"] == "clock.curr_time"
