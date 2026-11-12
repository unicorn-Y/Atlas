from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

from atlas.agent.tool_catalog import model_facing_tools
from atlas.engine.kernel.context import ContextManager, estimate_tokens
from atlas.engine.kernel.loop import AtlasKernel


def test_compact_in_place_reduces_long_history_and_keeps_work_state_and_recent_turns():
    history = [{"role": "system", "content": "system"}]
    for index in range(40):
        history.extend([
            {"role": "user", "content": f"turn {index} " + ("verbose request " * 50)},
            {"role": "assistant", "content": f"response {index} " + ("verbose response " * 50)},
        ])

    async def summarize(_messages, prompt):
        assert "Goal" in prompt and "Open items" in prompt and "Key files" in prompt
        return (
            "Goal: finish the current task\nConstraints: keep scope\nDecisions: use helper\n"
            "Completed: inspected history\nOpen items: verify integration\n"
            "Key files: core/atlas/kernel/context.py\nUnverified assumptions: none"
        )

    compacted = asyncio.run(ContextManager().compact_in_place(
        history, summarize=summarize, budget_tokens=10_000, keep_recent_turns=2,
    ))
    assert estimate_tokens(compacted) < estimate_tokens(history) * 0.5
    summary = compacted[1]["content"]
    assert all(label in summary for label in ("Goal:", "Open items:", "Key files:"))
    assert [message["content"] for message in compacted[-4:]] == [
        history[-4]["content"], history[-3]["content"], history[-2]["content"], history[-1]["content"],
    ]


def test_phase_boundary_is_evaluated_once_and_tool_is_model_facing():
    manager = ContextManager()
    assert manager.should_compact_at_phase_boundary("plan:1", token_count=100, budget_tokens=80)
    assert not manager.should_compact_at_phase_boundary("plan:1", token_count=10, budget_tokens=80)
    agent = SimpleNamespace(
        _mcp=None, _custom_tools=None, _local_execution=None, _computer_use=None,
        _web=None, _projects=None, _skills=None, _memory=None, _delegation=None,
    )
    tools = {item["function"]["name"]: item for item in model_facing_tools(agent)}
    assert "compact_context" in tools
    assert "same context window" in tools["compact_context"]["function"]["description"]


def test_compact_context_dispatch_replaces_shared_history_and_emits_event():
    history = [{"role": "system", "content": "system"}]
    for index in range(40):
        call_id = f"call-{index}"
        history.extend([
            {"role": "user", "content": f"turn {index} " + ("verbose request " * 50)},
            {"role": "assistant", "content": f"response {index} " + ("verbose response " * 50),
             "tool_calls": [{"id": call_id, "type": "function", "function": {
                 "name": "lookup", "arguments": "{}",
             }}]},
            {"role": "tool", "tool_call_id": call_id, "content": f"result {index} " + ("verbose result " * 50)},
        ])
    original = history
    recent_turns = copy.deepcopy(history[-6:])
    before_tokens = estimate_tokens(history)
    manager = ContextManager()
    callback_calls = []

    async def summarize(_messages, prompt):
        assert "Goal" in prompt and "Open items" in prompt
        return "Goal: finish task\nOpen items: verify integration"

    async def compact_callback():
        callback_calls.append(True)
        compacted = await manager.compact_in_place(
            history, summarize=summarize, budget_tokens=10_000, keep_recent_turns=2,
        )
        history[:] = compacted
        return {
            "method": "in_place", "before_tokens": before_tokens,
            "after_tokens": estimate_tokens(history), "budget_tokens": 10_000,
        }

    runtime = SimpleNamespace(compact_in_place_callback=compact_callback)
    event_queue = asyncio.Queue()
    result = asyncio.run(AtlasKernel.__new__(AtlasKernel)._dispatch(
        SimpleNamespace(), runtime, "compact", "compact_context", {}, event_queue,
    ))

    assert callback_calls == [True]
    assert history is original
    assert result["outcome"] == "completed"
    assert result["data"]["after_tokens"] <= result["data"]["before_tokens"] * 0.5
    assert history[-6:] == recent_turns
    assert "Goal:" in history[1]["content"] and "Open items:" in history[1]["content"]
    event = event_queue.get_nowait()
    assert event == {"type": "context.compacted.in_place", "data": result["data"]}


def test_exit_plan_mode_triggers_phase_boundary_evaluation_once():
    calls = []
    events = []

    async def phase_callback(boundary_id):
        calls.append(boundary_id)
        return {"boundary": boundary_id}

    runtime = SimpleNamespace(
        phase_boundary_callback=phase_callback,
        plan_approval_callback=lambda plan: True,
        plan_state={"goal": "g", "subtasks": []},
        dynamic_plan_mode=True,
    )

    async def run():
        queue = asyncio.Queue()
        result = await AtlasKernel.__new__(AtlasKernel)._dispatch(
            SimpleNamespace(), runtime, "exit", "ExitPlanMode", {"summary": "ok"}, queue,
        )
        while not queue.empty():
            events.append(queue.get_nowait())
        return result

    first = asyncio.run(run())
    second = asyncio.run(run())

    assert first["outcome"] == "completed"
    assert second["outcome"] == "completed"
    assert calls == ["plan:1", "plan:2"]
    assert runtime.dynamic_plan_mode is False
    assert [event["type"] for event in events] == ["plan_mode_changed", "plan_mode_changed"]
