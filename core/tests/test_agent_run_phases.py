"""H2 lane tests: single execution path, injection budget, router wiring.

Covers the H2.2 ``run()`` phase split (``RunRequest``/``RunCallbacks`` adapter,
event-driven cancel pump) and the H2.3 memory-injection stopgap, plus the H4
wiring of every auxiliary model call in ``atlas.agent`` through
``atlas.models.router``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import SystemMessage

from atlas.agent import AgentOrchestrator
from atlas.agent.injection_budget import (
    InjectionBlock,
    fit_injection_blocks,
    injection_budget_tokens,
)
from atlas.agent.run_phases import (
    RunCallbacks,
    RunRequest,
    _phase_context,
    _build_messages,
    _RunState,
)
from atlas.config import AtlasConfig
from atlas.models.router import CompletionResult
from atlas.models.tokens import estimate_tokens

ADVISORY_PREFIXES = (
    "Active user context ", "Knowledge retrieval explanation ",
    "Historical failure reflections ", "Approved goal experiences ",
    "Consolidated goal knowledge ", "Approved consolidated knowledge insights ",
)


def _memory_stub() -> AsyncMock:
    memory = AsyncMock()
    memory.get_conversation_messages.return_value = []
    memory.get_agent_context_with_trace.return_value = {
        "memories": [], "knowledge_trace": {"decisions": [], "query_terms": []},
    }
    memory.retrieve_agent_reflections.return_value = []
    memory.retrieve_approved_goal_experiences.return_value = []
    memory.retrieve_approved_goal_knowledge.return_value = []
    memory.apply_knowledge_consolidated_insights.return_value = []
    memory.extract_conversation_candidates.return_value = []
    memory.save_message.return_value = "message-1"
    return memory


def _orchestrator(memory: Any | None = None) -> AgentOrchestrator:
    model_mgr = MagicMock()
    model_mgr.current_model = "test-model"
    model_mgr.current_litellm_model = "openai/test-model"
    model_mgr.list_models.return_value = [
        {"id": "test-model", "litellm_model": "openai/test-model"},
    ]
    return AgentOrchestrator(model_mgr, memory or _memory_stub(), MagicMock())


# -- H2.2: run() adapter packs RunRequest/RunCallbacks -----------------------


async def test_run_kwargs_pack_request_and_callbacks(monkeypatch) -> None:
    agent = _orchestrator()
    captured: dict[str, Any] = {}

    async def fake_execute_run(orch, request, callbacks):
        captured["orch"] = orch
        captured["request"] = request
        captured["callbacks"] = callbacks
        yield {"type": "done", "message_id": "m1", "model": "test-model"}

    monkeypatch.setattr("atlas.agent.execute_run", fake_execute_run)
    cancel = asyncio.Event()
    events = [event async for event in agent.run(
        "hello", "conv-1", model="test-model", cancel_event=cancel,
        permission_mode="ask_writes", mode="plan", worker=True,
        run_id="run-9", force_plan=True,
    )]

    assert [event["type"] for event in events] == ["done"]
    assert captured["orch"] is agent
    request, callbacks = captured["request"], captured["callbacks"]
    assert request.message == "hello"
    assert request.conversation_id == "conv-1"
    assert request.model == "test-model"
    assert request.permission_mode == "ask_writes"
    assert request.mode == "plan"
    assert request.worker is True
    assert request.run_id == "run-9"
    assert request.force_plan is True
    assert callbacks.cancel_event is cancel
    # defaults survive the packing
    assert request.read_only is False
    assert callbacks.approval_callback is None


async def test_context_phase_closes_unexpected_memories_coroutine(monkeypatch) -> None:
    from atlas.engine import session_sync

    async def unexpected_memories():
        return []

    memories = unexpected_memories()
    memory = AsyncMock()
    memory.get_agent_context_with_trace.return_value = {"memories": memories}
    memory.apply_knowledge_consolidated_insights.return_value = []
    memory.retrieve_agent_reflections.return_value = []
    memory.retrieve_approved_goal_experiences.return_value = []
    monkeypatch.setattr(session_sync, "read_session_messages", lambda *_args, **_kwargs: [])

    agent = SimpleNamespace(_memory=memory)
    state = _RunState(
        request=RunRequest(message="hello", conversation_id="conversation"),
        callbacks=RunCallbacks(),
        message="hello",
        runtime=SimpleNamespace(),
    )
    events = [event async for event in _phase_context(agent, state)]

    assert events and events[0]["type"] == "error"
    assert "must be a list" in events[0]["detail"]
    assert state.abort is True
    assert inspect.getcoroutinestate(memories) == inspect.CORO_CLOSED


async def test_unknown_model_still_yields_single_error_event() -> None:
    agent = _orchestrator()
    events = [event async for event in agent.run(
        "hello", "conv-1", model="no-such-model",
    )]
    assert events == [{
        "type": "error", "category": "model",
        "detail": "Model selection failed: Unknown model: no-such-model",
    }]


async def test_blocked_prompt_hook_persists_reason_and_stops_before_turn(
    monkeypatch, tmp_path,
) -> None:
    import atlas.config as config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    memory = _memory_stub()
    agent = _orchestrator(memory)

    def fail_turn(*_args, **_kwargs):
        raise AssertionError("engine turn must not start for a blocked prompt")

    monkeypatch.setattr("atlas.agent.run_phases._hermes_turn", fail_turn)

    async def blocked_hook(_event, payload):
        return {"blocked": True, "reason": "不行"}

    events = [event async for event in agent.run(
        "hello", "conv-1", user_hook_callback=blocked_hook,
    )]
    assert [event["type"] for event in events] == ["chunk", "done"]
    assert events[0] == {"type": "chunk", "content": "不行"}
    from atlas.engine.session_sync import read_session_all_messages

    messages = read_session_all_messages(tmp_path / "engine", "conv-1")
    assert len(messages) == 1
    assert events[1]["message_id"] == messages[0]["id"]
    assert messages[0]["role"] == "assistant" and messages[0]["content"] == "不行"
    assert messages[0]["metadata"]["hook"] == "UserPromptSubmit"
    memory.save_message.assert_not_awaited()


# -- H2.2/H3.5: event-driven cancel pump -------------------------------------


async def test_cancel_event_ends_run_promptly_without_polling(monkeypatch) -> None:
    agent = _orchestrator()
    stop_hooks: list[dict[str, Any]] = []
    agent.hooks.register("agent_stop", lambda **payload: stop_hooks.append(payload))

    async def slow_turn(_agent, _state):
        await asyncio.sleep(30)
        return {"messages": [], "pending_events": [], "runtime": _state.runtime}

    monkeypatch.setattr("atlas.agent.run_phases._hermes_turn", slow_turn)
    cancel = asyncio.Event()

    async def set_cancel_later() -> None:
        await asyncio.sleep(0.01)
        cancel.set()

    primer = asyncio.create_task(set_cancel_later())
    started = time.monotonic()
    events = [event async for event in agent.run("hello", "conv-1", cancel_event=cancel)]
    elapsed = time.monotonic() - started
    await primer

    assert [event["type"] for event in events] == ["cancelled"]
    # The event-driven watcher fires immediately; the retired implementation
    # could only notice a cancel on a 0.2s wait_for timeout.
    assert elapsed < 0.15, f"cancel took {elapsed:.3f}s — pump is polling again"
    assert len(stop_hooks) == 1, "agent_stop hook must run exactly once"


async def test_cancel_watcher_is_cleaned_up_after_done(monkeypatch) -> None:
    from atlas.agent.run_phases import _EVENT_STREAM_DONE

    agent = _orchestrator()

    async def instant_turn(_agent, state):
        try:
            await state.runtime.event_queue.put({"type": "chunk", "content": "hi"})
            return {"messages": [], "pending_events": [], "runtime": state.runtime}
        finally:
            state.runtime.event_queue.put_nowait(_EVENT_STREAM_DONE)

    monkeypatch.setattr("atlas.agent.run_phases._hermes_turn", instant_turn)
    agent._reflection = SimpleNamespace(reflect=AsyncMock(return_value=None))
    cancel = asyncio.Event()
    events = [event async for event in agent.run("hello", "conv-1", cancel_event=cancel)]
    assert [event["type"] for event in events] == ["chunk", "done"]
    await asyncio.sleep(0)
    watchers = [task for task in asyncio.all_tasks()
                if task.get_name().startswith("atlas-cancel-watcher")]
    assert watchers == [], "cancel watcher leaked past the run"


# -- H10.2-DEFECT-2: a terminal engine-turn failure is never a success --------


class _ScriptedHermesRuntime:
    """HermesRuntime double yielding pre-scripted events, incl. hermes.result."""

    result: dict[str, Any] = {}

    def __init__(self, *, data_dir, model_manager, **_kwargs) -> None:
        self.event_queue = asyncio.Queue()

    async def run_turn(self, **_kwargs):
        yield {"type": "run.recovery.notice", "data": {"message": "provider hard-failed"}}
        yield {"type": "hermes.result", "result": dict(self.result)}


async def _events_for_scripted_result(monkeypatch, result: dict[str, Any]) -> list[dict]:
    monkeypatch.setattr(
        "atlas.engine.HermesRuntime",
        type("_Runtime", (_ScriptedHermesRuntime,), {"result": result}),
    )
    agent = _orchestrator()
    agent._reflection = SimpleNamespace(reflect=AsyncMock(return_value=None))
    return [event async for event in agent.run("hello", "conv-fail")]


async def test_terminal_failed_turn_yields_error_and_never_done(monkeypatch) -> None:
    """A 404-style terminal provider failure must end the run as failed (H10.2-2).

    Hermes returns a result dict (empty response, null usage) even when the
    provider rejected the request with no retryable path; reporting that as
    `done` made `atlas run` exit 0 with no output.
    """
    events = await _events_for_scripted_result(monkeypatch, {
        "final_response": "", "messages": [], "api_calls": 1,
        "completed": False, "failed": True,
        "error": 'HTTP 404: Model "openai/deepseek-v4.1-flash" is not supported',
        "failure_reason": "model_not_found", "failure_retryable": False,
    })

    error = next(event for event in events if event["type"] == "error")
    assert error["category"] == "model"
    assert "404" in error["detail"]
    assert [event["type"] for event in events][-1] != "done"
    assert "done" not in [event["type"] for event in events]


async def test_failed_turn_without_error_detail_still_fails(monkeypatch) -> None:
    events = await _events_for_scripted_result(monkeypatch, {
        "final_response": "", "messages": [], "failed": True, "completed": False,
    })

    error = next(event for event in events if event["type"] == "error")
    assert error["category"] == "model"
    assert error["detail"]
    assert "done" not in [event["type"] for event in events]


async def test_interrupted_turn_is_not_reported_as_failure(monkeypatch) -> None:
    """The cancel path owns interrupts; a `failed` interrupt verdict stays out."""
    events = await _events_for_scripted_result(monkeypatch, {
        "final_response": "", "messages": [], "failed": True, "interrupted": True,
        "completed": False, "error": "user interrupt",
    })

    assert "error" not in [event["type"] for event in events]
    assert events[-1]["type"] == "done"


async def test_successful_turn_still_ends_in_done(monkeypatch) -> None:
    events = await _events_for_scripted_result(monkeypatch, {
        "final_response": "完成", "messages": [{"role": "assistant", "content": "完成"}],
        "completed": True, "failed": False, "api_calls": 1,
    })

    assert "error" not in [event["type"] for event in events]
    assert events[-1]["type"] == "done"


# -- H2.3: injection budget ---------------------------------------------------


def _big_state() -> tuple[Any, _RunState]:
    agent = _orchestrator()
    memories = [
        {"key": f"fact:{index}", "value": "很长的记忆内容"} for index in range(40)
    ]
    reflections = [
        {"summary": f"reflection {index}", "resolution_hint": "提示内容"}
        for index in range(40)
    ]
    state = _RunState(
        request=RunRequest(message="目标", conversation_id="conv-1"),
        callbacks=RunCallbacks(),
        message="目标",
    )
    state.selected_config = {"context_window": 2000}
    state.context = {
        "memories": memories,
        "knowledge_trace": {"decisions": [], "query_terms": []},
    }
    state.reflections = reflections
    state.goal_experiences = []
    state.consolidated_goal_knowledge = []
    state.consolidated_insights = []
    return agent, state


def test_injection_budget_under_cap_keeps_everything() -> None:
    agent, state = _big_state()
    state.selected_config = {"context_window": 10_000_000}
    result = asyncio.run(_build_messages(agent, state))
    advisory = [
        item for item in result
        if isinstance(item, SystemMessage)
        and any(str(item.content).startswith(prefix) for prefix in ADVISORY_PREFIXES)
    ]
    assert len(advisory) == 2  # memories + reflections, nothing dropped
    injected = sum(estimate_tokens(str(item.content)) for item in advisory)
    budget = injection_budget_tokens(
        lambda: AtlasConfig(), state.selected_config,
    )
    assert injected <= budget, "nothing should be dropped while under the cap"


def test_injection_budget_caps_total_and_keeps_relevance_order() -> None:
    agent, state = _big_state()
    result = asyncio.run(_build_messages(agent, state))
    budget = injection_budget_tokens(lambda: AtlasConfig(), state.selected_config)
    advisory = [
        str(item.content) for item in result
        if isinstance(item, SystemMessage)
        and any(str(item.content).startswith(prefix) for prefix in ADVISORY_PREFIXES)
    ]
    injected = sum(estimate_tokens(text) for text in advisory)
    assert injected <= budget, (
        f"advisory injection {injected} exceeds budget {budget}"
    )
    # The most relevant head is kept; the unbounded tail is gone. Blocks are
    # filled in assembly order, so a starved later block is dropped entirely.
    memories_text = next(
        text for text in advisory if text.startswith("Active user context")
    )
    assert '"key": "fact:0"' in memories_text
    assert '"key": "fact:39"' not in memories_text
    reflections_text = next(
        (text for text in advisory if text.startswith("Historical failure reflections")),
        None,
    )
    assert reflections_text is None or "reflection 39" not in reflections_text


def test_injection_budget_ratio_config_scales_budget() -> None:
    config = AtlasConfig({"agent": {"memory_injection": {"max_context_ratio": 0.5}}})
    assert injection_budget_tokens(lambda: config, {"context_window": 1000}) == 500
    assert injection_budget_tokens(lambda: config, {"context_window": 0}) == 100_000
    broken = AtlasConfig({"agent": {"memory_injection": {"max_context_ratio": 7}}})
    assert injection_budget_tokens(lambda: broken, {"context_window": 1000}) == 50


def test_fit_blocks_drops_block_that_cannot_fit_and_keeps_prefix_order() -> None:
    blocks = [
        InjectionBlock("first", [{"id": index} for index in range(10)],
                       render=lambda items: json.dumps(items)),
        InjectionBlock("second", [{"id": "only"}], render=lambda items: json.dumps(items)),
    ]
    kept = fit_injection_blocks(blocks, budget_tokens=25, estimate=lambda text: len(text))
    # '[{"id": 0}, {"id": 1}]' renders to 22 chars; the third item overflows 25.
    assert kept[0] == [{"id": 0}, {"id": 1}]
    assert kept[1] == []  # no budget left; an empty block is never injected


# -- H4: auxiliary completions route through the shared router ----------------


def _router_stub(text: str = "{}") -> tuple[SimpleNamespace, AsyncMock]:
    complete_for = AsyncMock(return_value=CompletionResult(text=text))
    return SimpleNamespace(complete_for=complete_for), complete_for


async def test_create_plan_routes_planning_purpose_through_router() -> None:
    agent = _orchestrator()
    agent._model_router, complete_for = _router_stub(text=json.dumps({
        "goal": "ship", "subtasks": [{"id": "a", "title": "t", "verification": "v"}],
    }))
    plan = await agent._create_plan("do it", "openai/test-model")
    assert plan.goal == "ship"
    args = complete_for.call_args.args
    assert args[0] == "openai/test-model" and args[1] == "planning"
    assert complete_for.call_args.kwargs == {"max_tokens": 1200}


async def test_verify_plan_and_goal_evaluation_route_reflection_purpose() -> None:
    from atlas.agent.planning import PlanSubtask, TaskPlan

    agent = _orchestrator()
    agent._model_router, complete_for = _router_stub(text=json.dumps(
        {"results": [{"id": "a", "completed": True, "evidence": "done"}]},
    ))
    plan = TaskPlan("goal", [PlanSubtask("a", "t", "v")])
    results = await agent._verify_plan(plan, "final", "openai/test-model")
    assert results[0]["completed"] is True
    assert complete_for.call_args.args[1] == "reflection"
    assert complete_for.call_args.kwargs["max_tokens"] == 1200

    plan.subtasks[0].status = "completed"
    agent._model_router, complete_for = _router_stub(text=json.dumps({
        "satisfied": True, "evidence": "tests pass", "reason": "verified",
    }))
    evaluation = await agent._evaluate_goal("goal", plan, "final", "openai/test-model")
    assert evaluation["satisfied"] is True
    assert complete_for.call_args.args[1] == "reflection"
    assert complete_for.call_args.kwargs["max_tokens"] == 1200


async def test_moa_summary_routes_through_router() -> None:
    agent = _orchestrator()
    agent._model_router, complete_for = _router_stub(text="汇总完成")
    summary = await agent._summarize_parallel_results([
        {"index": 1, "title": "t", "status": "completed", "summary": "s",
         "changed_files": ["a.py"]},
    ])
    assert summary == "汇总完成"
    assert complete_for.call_args.args[0] == "test-model"
    assert complete_for.call_args.args[1] == "moa"
    assert complete_for.call_args.kwargs == {"max_tokens": 600}
