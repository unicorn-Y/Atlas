from __future__ import annotations

import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from atlas.agent import AgentOrchestrator, AgentRunContext, SYSTEM_PROMPT
from atlas.agent.prompt_caching import strip_anthropic_cache_control


class _ModelManager:
    current_model = "claude-sonnet-4"
    current_litellm_model = "anthropic/claude-sonnet-4"
    gateway_base_url = "https://api.anthropic.com/v1"

    def list_models(self):
        return [{
            "id": self.current_model,
            "provider": "anthropic",
            "litellm_model": self.current_litellm_model,
        }]


@pytest.mark.asyncio
async def test_agent_keeps_system_prefix_and_sorted_tools_stable_across_rounds(monkeypatch):
    import atlas.agent as agent_module

    calls = []
    toolset = [
        {"type": "function", "function": {"name": "z_tool", "parameters": {}}},
        {"type": "function", "function": {"name": "a_tool", "parameters": {}}},
    ]

    async def fake_completion(**kwargs):
        calls.append(copy.deepcopy(kwargs))

        async def stream():
            yield {"choices": [{"delta": {"content": "继续"}}], "usage": {
                "prompt_tokens": 20, "completion_tokens": 1,
                "prompt_tokens_details": {"cached_tokens": 12},
            }}

        return stream()

    monkeypatch.setattr(agent_module, "acompletion", fake_completion)
    monkeypatch.setattr(agent_module, "_CACHE_UNSUPPORTED_MODELS", set())
    agent = AgentOrchestrator(_ModelManager(), memory=None)
    agent._model_facing_tools = lambda: copy.deepcopy(toolset)
    runtime = AgentRunContext(model="claude-sonnet-4")
    state = {
        "messages": [SystemMessage(content=SYSTEM_PROMPT + "\nStable run rules."),
                     HumanMessage(content="请完成任务")],
        "pending_events": [], "tool_rounds": 0, "cancelled": False,
        "runtime": runtime,
    }

    for round_index in range(5):
        output = await agent._think_node(state)
        state["messages"].extend(output["messages"])
        state["messages"].append(HumanMessage(content=f"继续第 {round_index + 1} 步"))
        state["tool_rounds"] += 1

    prefixes = [
        strip_anthropic_cache_control(call["messages"][:1])
        for call in calls
    ]
    assert all(prefix == prefixes[0] for prefix in prefixes[1:])
    assert all([item["function"]["name"] for item in call["tools"]] == [
        "a_tool", "z_tool",
    ] for call in calls)
    usage_events = []
    while not runtime.event_queue.empty():
        event = runtime.event_queue.get_nowait()
        if event.get("type") == "run_usage":
            usage_events.append(event["usage"])
    assert len(usage_events) == 5
    assert all(event["cached_input_tokens"] == 12 for event in usage_events)
