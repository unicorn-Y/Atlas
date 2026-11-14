import pytest

from atlas.agent import AgentRunContext


@pytest.mark.unit
def test_agent_run_context_defaults_to_native_tool_mode():
    assert AgentRunContext().tool_mode == "native"


@pytest.mark.unit
def test_agent_run_context_accepts_ptc_tool_mode():
    assert AgentRunContext(tool_mode="ptc").tool_mode == "ptc"
