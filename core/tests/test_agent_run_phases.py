"""H2 lane tests: single execution path, injection budget, router wiring.

Covers the H2.2 ``run()`` phase split (``RunRequest``/``RunCallbacks`` adapter,
event-driven cancel pump) and the H2.3 memory-injection stopgap, plus the H4
wiring of every auxiliary model call in ``atlas.agent`` through
``atlas.models.router``.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.agent import AgentOrchestrator
from atlas.agent.run_phases import (
    RunCallbacks,
    RunRequest,
    _phase_plan,
    _RunState,
)

from atlas.models.router import CompletionResult


def _stream_types(events: list[dict[str, Any]]) -> list[str]:
    """Event types restricted to the conversation stream.

    A run emits two kinds of event. *Stream* events are the conversation
    protocol the UI renders turn by turn (``chunk``/``tool_call``/
    ``tool_result``/``approval_required``/``error``/``done``/``cancelled``).
    *Notification* events describe the run around that stream —
    ``context_sources`` (what was injected, run_phases.py:1088),
    ``run.recovery.notice``, ``plan_updated``, ``run_status``, ``run_usage``,
    ``session.title``, ``goal_evaluated``, ``run_verify_nudge``.

    The cancel tests below are about cancel semantics, so they assert on the
    stream only. Pinning the full event list made them fail whenever a
    notification was added — three separate times so far — which is noise, not
    a regression. Stream ordering is still asserted exactly.
    """
    stream = {"chunk", "tool_call", "tool_result", "approval_required",
              "error", "done", "cancelled"}
    return [e["type"] for e in events if e["type"] in stream]


def _memory_stub() -> AsyncMock:
    memory = AsyncMock()
    memory.get_conversation_messages.return_value = []
    memory.get_agent_context_with_trace.return_value = {
        "memories": [], "knowledge_trace": {"decisions": [], "query_terms": []},
    }
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


async def test_closing_run_closes_nested_execution_in_same_task(monkeypatch) -> None:
    from contextvars import ContextVar

    marker = ContextVar("test_execution_scope", default="outside")
    closed = []

    async def fake_execute(agent, request, callbacks):
        token = marker.set("inside")
        try:
            yield {"type": "error", "error": "missing credentials"}
            await asyncio.sleep(60)
        finally:
            marker.reset(token)
            closed.append(True)

    monkeypatch.setattr("atlas.agent.execute_run", fake_execute)
    events = _orchestrator().run("hello", "conversation")
    assert (await anext(events))["type"] == "error"
    await events.aclose()
    assert closed == [True]
    assert marker.get() == "outside"


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

    monkeypatch.setattr("atlas.agent.run_phases._engine_turn", fail_turn)

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
    """Cancellation must be woken by the cancel Event itself, never a timer.

    Contract (H3.5): a ``atlas-cancel-watcher`` task parks on the cancel
    Event and feeds ``_CANCEL_REQUESTED`` into the event queue, so the pump
    — blocked on ``queue.get()`` — wakes the moment the event is set. The
    retired implementation had no watcher and polled the queue with
    ``wait_for(..., timeout=0.2)``, so it only noticed a cancel on a tick.

    Detector design — structural, not wall-clock (a wall-clock bound cannot
    do this job: a poll tick landing right after ``set()`` notices within
    ~0ms, so no bound reliably separates polling from a healthy wake, and
    the pre-turn pipeline (``_phase_context`` session-sync disk I/O)
    legitimately costs 0.15–0.35s under parallel test load, swamping any
    tight bound). Detection instead:
      1. a spy on ``asyncio.Event.wait`` proves the watcher parks on THIS
         cancel event exactly once — a timer-polling watcher re-enters
         ``wait`` on every tick, and a retired pump (no watcher) never
         parks at all;
      2. within two ``asyncio.sleep(0)`` loop passes after ``cancel.set()``
         — wall-clock free — the watcher task is already done: its wake was
         scheduled by the event itself, which a >=0.2s timer could not have
         delivered yet;
      3. the generous ``elapsed < 1.0s`` bound is an anti-hang guard for
         the sentinel path only (event fired but sentinel lost), NOT the
         polling detector — a 0.2s poll would also pass it, which is why
         (1) and (2) carry the contract.
    The clock starts only once the watcher is parked, so the machine-speed
    dependent startup pipeline stays out of every measurement.
    """
    agent = _orchestrator()
    stop_hooks: list[dict[str, Any]] = []
    agent.hooks.register("agent_stop", lambda **payload: stop_hooks.append(payload))

    async def slow_turn(_agent, _state):
        await asyncio.sleep(30)
        return {"messages": [], "pending_events": [], "runtime": _state.runtime}

    monkeypatch.setattr("atlas.agent.run_phases._engine_turn", slow_turn)
    cancel = asyncio.Event()

    watcher_waits: list[str] = []
    real_event_wait = asyncio.Event.wait

    async def spy_event_wait(self: asyncio.Event) -> bool:
        task = asyncio.current_task()
        name = task.get_name() if task is not None else ""
        if self is cancel and name.startswith("atlas-cancel-watcher"):
            watcher_waits.append(name)
        return await real_event_wait(self)

    monkeypatch.setattr(asyncio.Event, "wait", spy_event_wait)

    async def collect() -> list[dict[str, Any]]:
        return [event async for event in agent.run("hello", "conv-1", cancel_event=cancel)]

    run_task = asyncio.create_task(collect())
    try:
        # Wait until the watcher is actually parked on the event so the wake
        # clock below contains no startup-pipeline noise.
        watcher: asyncio.Task[None] | None = None
        deadline = time.monotonic() + 10
        while watcher is None or not watcher_waits:
            assert time.monotonic() < deadline, (
                "atlas-cancel-watcher never parked on the cancel event — "
                "cancel wake is not event-driven (retired 0.2s poll?)"
            )
            await asyncio.sleep(0.005)
            for task in asyncio.all_tasks():
                if task.get_name().startswith("atlas-cancel-watcher"):
                    watcher = task

        assert watcher_waits == [watcher.get_name()], (
            f"watcher parked {len(watcher_waits)}x before cancel — polling"
        )
        started = time.monotonic()
        cancel.set()
        # Two loop passes, no wall clock involved: pass 1 resumes the watcher
        # (it enqueues the sentinel and finishes), pass 2 is slack. A timer
        # driven wake (>=0.2s) could not have fired in these microsecond
        # scale passes.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert watcher.done(), (
            "cancel watcher did not wake from the event within one loop pass "
            "— its wake is timer-driven (polling regression)"
        )
        events = await asyncio.wait_for(run_task, timeout=10)
        elapsed = time.monotonic() - started
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)

    assert _stream_types(events) == ["cancelled"]
    assert len(watcher_waits) == 1, (
        "cancel watcher re-entered Event.wait — it polls on a timer instead "
        "of sleeping on the event (retired 0.2s poll behavior)"
    )
    # Anti-hang guard only: a 0.2s poll would also pass this; the structural
    # assertions above are what fails a polling implementation.
    assert elapsed < 1.0, f"cancel wake took {elapsed:.3f}s — sentinel path hung?"
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

    monkeypatch.setattr("atlas.agent.run_phases._engine_turn", instant_turn)
    cancel = asyncio.Event()
    events = [event async for event in agent.run("hello", "conv-1", cancel_event=cancel)]
    assert _stream_types(events) == ["chunk", "done"]
    await asyncio.sleep(0)
    watchers = [task for task in asyncio.all_tasks()
                if task.get_name().startswith("atlas-cancel-watcher")]
    assert watchers == [], "cancel watcher leaked past the run"


# -- H10.2-DEFECT-2: a terminal engine-turn failure is never a success --------


class _ScriptedAtlasRuntime:
    """AtlasRuntime double yielding pre-scripted events, incl. atlas.result."""

    result: dict[str, Any] = {}

    def __init__(self, *, data_dir, model_manager, **_kwargs) -> None:
        self.event_queue = asyncio.Queue()

    async def run_turn(self, **_kwargs):
        yield {"type": "run.recovery.notice", "data": {"message": "provider hard-failed"}}
        yield {"type": "atlas.result", "result": dict(self.result)}


async def _events_for_scripted_result(monkeypatch, result: dict[str, Any]) -> list[dict]:
    monkeypatch.setattr(
        "atlas.engine.AtlasRuntime",
        type("_Runtime", (_ScriptedAtlasRuntime,), {"result": result}),
    )
    agent = _orchestrator()
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


# -- planner resilience: a plan is an optimization, never a turn killer ------


async def test_plan_phase_degrades_instead_of_aborting_when_plan_creation_fails() -> None:
    """A failed plan must NOT end the turn (symmetric with verify/goal-eval).

    ``_verify_plan`` and ``_evaluate_goal`` log a warning and keep going; a
    plan-creation failure used to set ``state.abort = True`` and kill the whole
    user request. The planner is an optimization, so it degrades to "no plan".
    """
    agent = _orchestrator()
    agent._model_router, _ = _router_stub(text="sorry, no json here")

    # second attempt also fails -> the phase must still not abort
    request = RunRequest(message="first do a then do b", conversation_id="conv-1")
    state = _RunState(request=request, callbacks=RunCallbacks(), message=request.message)
    state.litellm_model = "openai/test-model"
    state.runtime = None

    events = [event async for event in _phase_plan(agent, state)]

    assert state.abort is False, "planner failure must never abort the turn"
    assert state.plan is None
    assert state.plan_resumed is False
    assert all(event["type"] != "error" for event in events), (
        "a degraded plan must not surface as a run error"
    )
    skipped = [e for e in events if e["type"] == "run.recovery.notice"]
    assert len(skipped) == 1
    assert "message" in skipped[0]["data"]


async def test_plan_phase_retries_once_before_degrading() -> None:
    """One bad completion is retried; the retry's JSON is used as the plan."""
    agent = _orchestrator()
    good = json.dumps({
        "goal": "ship", "subtasks": [{"id": "a", "title": "t", "verification": "v"}],
    })
    agent._model_router = SimpleNamespace(
        complete_for=AsyncMock(side_effect=[
            CompletionResult(text="not a json object at all"),
            CompletionResult(text=good),
        ]),
    )

    plan = await agent._create_plan("do it", "openai/test-model")

    assert plan.goal == "ship"
    assert agent._model_router.complete_for.await_count == 2


async def test_plan_parse_stages_name_the_real_culprit() -> None:
    """``_json_object`` is shared; each caller must label its own stage."""
    from atlas.agent import AgentOrchestrator as Orchestrator

    with pytest.raises(ValueError, match="Plan verifier response"):
        Orchestrator._json_object("no json", "Plan verifier")
    with pytest.raises(ValueError, match="Goal evaluator response"):
        Orchestrator._json_object("no json", "Goal evaluator")
    with pytest.raises(ValueError, match="Planner response"):
        Orchestrator._json_object("no json", "Planner")
