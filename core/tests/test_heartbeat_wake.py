"""WakeBus tests: coalescing, priority, concurrency cap, retain/retry."""

from __future__ import annotations

import asyncio
import time

import pytest

from atlas.heartbeat.wake import (
    ScheduledTask,
    WakeBus,
    WakeRequest,
    WakeResult,
    wake_priority,
)

FAST = dict(coalesce_s=0.03, retry_s=0.05, idle_retry_s=0.1)


def req(agent_id: str = "agent-a", **overrides) -> WakeRequest:
    base = dict(intent="event", source="exec-event", reason="event")
    base.update(overrides)
    return WakeRequest(agent_id=agent_id, **base)


class RecordingHandler:
    """Async handler recording calls; scripted results per call index."""

    def __init__(self, results=None, gate: asyncio.Event | None = None):
        self.calls: list[WakeRequest] = []
        self.results = list(results or [])
        self.gate = gate
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, request: WakeRequest):
        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.results:
                outcome = self.results.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
            return WakeResult.ran()
        finally:
            self.in_flight -= 1


async def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached in time")


@pytest.fixture
async def buses():
    created: list[WakeBus] = []

    def make(handler, **overrides):
        bus = WakeBus(handler, **{**FAST, **overrides})
        created.append(bus)
        return bus

    yield make
    for bus in created:
        await bus.close()


# ---------------------------------------------------------------------------
class TestCoalesce:
    async def test_same_target_merges_into_single_dispatch(self, buses):
        handler = RecordingHandler()
        # Wide window: immune to OS timer slack between the two requests.
        bus = buses(handler, coalesce_s=0.4)
        bus.request(req(intent="scheduled", reason="interval"))
        bus.request(req(intent="task", source="cron", reason="task"))
        await wait_until(lambda: len(handler.calls) == 1)
        await asyncio.sleep(0.1)
        # One guarded turn absorbs the coincident scheduled tick.
        assert len(handler.calls) == 1
        assert handler.calls[0].intent == "task"  # higher-priority intent kept

    async def test_merge_keeps_earliest_ready_time(self, buses):
        handler = RecordingHandler()
        bus = buses(handler)
        bus.request(req(), coalesce_s=0.2)
        await asyncio.sleep(0.01)
        bus.request(req(), coalesce_s=0.02)
        started = time.monotonic()
        await wait_until(lambda: len(handler.calls) == 1)
        # The later, shorter window must not be stretched by the earlier one.
        assert time.monotonic() - started < 0.19

    async def test_manual_bypasses_not_before_of_merged_wake(self, buses):
        handler = RecordingHandler(results=[WakeResult.ran()])
        bus = buses(handler)
        blocked = req(intent="scheduled", reason="interval")
        bus.request(blocked)
        # Pretend a guard pushed the scheduled wake into the future.
        group = bus._pending[bus.target_key(blocked)]
        group.slots["scheduled"].not_before = time.monotonic() + 5
        bus.request(req(intent="manual", source="manual", reason="manual"))
        await wait_until(lambda: len(handler.calls) == 1)
        assert handler.calls[0].intent == "manual"


class TestPriority:
    async def test_priorities(self):
        assert wake_priority("manual") == 3
        assert wake_priority("immediate") == 3
        assert wake_priority("task") == 2
        assert wake_priority("event") == 2
        assert wake_priority("scheduled") == 1
        assert wake_priority(source="interval") == 1
        assert wake_priority(source="retry") == 0
        assert wake_priority(reason="retry") == 0

    async def test_higher_priority_target_dispatches_first(self, buses):
        handler = RecordingHandler(gate=asyncio.Event())
        bus = buses(handler, max_active=1)
        bus.request(req("low-agent", intent="scheduled", reason="interval"))
        await asyncio.sleep(0.05)  # let the coalesce window elapse
        bus.request(req("high-agent", intent="manual", reason="manual"))
        await asyncio.sleep(0.05)
        assert handler.calls[0].agent_id == "low-agent"  # admitted first (only candidate)
        bus._wakeup.set()
        # Now both cannot run (cap 1, one in flight); release and let the
        # queue order the rest: high-agent before any other low priority.
        handler.gate.set()
        bus.request(req("other-agent", intent="scheduled", reason="interval"))
        await wait_until(lambda: len(handler.calls) >= 2)
        assert handler.calls[1].agent_id == "high-agent"

    async def test_merge_keeps_higher_priority_intent(self, buses):
        handler = RecordingHandler()
        bus = buses(handler, coalesce_s=0.4)
        bus.request(req(intent="scheduled", reason="interval"))
        bus.request(req(intent="immediate", source="restart-sentinel", reason="restart"))
        await wait_until(lambda: len(handler.calls) == 1)
        assert handler.calls[0].intent == "immediate"


class TestConcurrencyCap:
    async def test_at_most_max_active_targets(self, buses):
        handler = RecordingHandler(gate=asyncio.Event())
        bus = buses(handler, max_active=4)
        for i in range(7):
            bus.request(req(f"agent-{i}"))
        await wait_until(lambda: handler.in_flight > 0)
        await asyncio.sleep(0.1)
        assert handler.max_in_flight == 4
        assert bus.active_count == 4
        assert bus.pending_count == 3

        handler.gate.set()
        await wait_until(lambda: len(handler.calls) == 7)
        assert handler.max_in_flight == 4

    async def test_fifth_target_waits_beyond_cap(self, buses):
        handler = RecordingHandler(gate=asyncio.Event())
        bus = buses(handler, max_active=4)
        for i in range(5):
            bus.request(req(f"agent-{i}"))
        await asyncio.sleep(0.08)
        assert len(handler.calls) == 4
        handler.gate.set()
        await wait_until(lambda: len(handler.calls) == 5)


class TestRetainRetry:
    async def test_retryable_busy_skip_is_retained_and_retried(self, buses):
        handler = RecordingHandler(
            results=[WakeResult.skipped("requests-in-flight"), WakeResult.ran()]
        )
        bus = buses(handler)
        result = await bus.request_wait(req())
        assert result.status == "ran"
        assert len(handler.calls) == 2
        # A plain busy retry is not guard-retained (no not-due bypass marker).
        assert handler.calls[1].retained_work is False

    async def test_guard_reason_retained_for_event_intent(self, buses):
        retry_at = time.monotonic() + 0.08
        handler = RecordingHandler(
            results=[WakeResult.skipped("min-spacing", retry_at=retry_at), WakeResult.ran()]
        )
        bus = buses(handler, retry_s=10.0)  # retry_at must win over retry_s
        result = await bus.request_wait(req(intent="event"))
        assert result.status == "ran"
        assert len(handler.calls) == 2

    async def test_guard_reason_not_retained_for_pure_scheduled_poll(self, buses):
        handler = RecordingHandler(results=[WakeResult.skipped("not-due")])
        bus = buses(handler)
        result = await bus.request_wait(req(intent="scheduled", reason="interval"))
        assert result.status == "skipped"
        assert result.reason == "not-due"
        assert len(handler.calls) == 1  # waits for the next cadence tick

    async def test_terminal_poll_flag_settles_without_retry(self, buses):
        handler = RecordingHandler(
            results=[WakeResult.skipped("requests-in-flight", terminal_poll=True)]
        )
        bus = buses(handler)
        result = await bus.request_wait(req(intent="scheduled", reason="interval"))
        assert result.status == "skipped"
        await asyncio.sleep(0.15)
        assert len(handler.calls) == 1  # event-free poll waits for next tick

    async def test_terminal_reason_settles_without_retry(self, buses):
        handler = RecordingHandler(results=[WakeResult.skipped("empty-scratch")])
        bus = buses(handler)
        result = await bus.request_wait(req())
        assert (result.status, result.reason) == ("skipped", "empty-scratch")
        await asyncio.sleep(0.1)
        assert len(handler.calls) == 1

    async def test_busy_retry_uses_idle_grace_for_scheduled(self, buses):
        handler = RecordingHandler(
            results=[WakeResult.skipped("requests-in-flight"), WakeResult.ran()]
        )
        bus = buses(handler, retry_s=0.01, idle_retry_s=0.12)
        started = time.monotonic()
        await bus.request_wait(req(intent="scheduled", reason="interval"))
        # scheduled intents take the 60s-style idle grace, not the 1s retry.
        assert time.monotonic() - started >= 0.1

    async def test_tasks_merged_by_id_across_coalesce(self, buses):
        handler = RecordingHandler()
        bus = buses(handler)
        bus.request(req(intent="task", source="cron", reason="task",
                       tasks=(ScheduledTask("job-2", "Second", "b"),)))
        await asyncio.sleep(0.005)
        bus.request(req(intent="task", source="cron", reason="task",
                       tasks=(ScheduledTask("job-1", "First", "a"),)))
        await wait_until(lambda: len(handler.calls) == 1)
        assert [task.task_id for task in handler.calls[0].tasks] == ["job-1", "job-2"]


class TestLifecycle:
    async def test_handler_exception_retries_then_settles(self, buses):
        handler = RecordingHandler(results=[RuntimeError("boom"), WakeResult.ran()])
        bus = buses(handler)
        result = await bus.request_wait(req())
        assert result.status == "ran"
        assert len(handler.calls) == 2

    async def test_close_settles_pending_waiters(self):
        handler = RecordingHandler(gate=asyncio.Event())
        bus = WakeBus(handler, **FAST)
        pending = asyncio.create_task(bus.request_wait(req()))
        await asyncio.sleep(0.005)
        await bus.close()
        result = await pending
        assert (result.status, result.reason) == ("skipped", "handler-unavailable")

    async def test_failed_result_settles_without_retry(self, buses):
        handler = RecordingHandler(results=[WakeResult.failed("model-down")])
        bus = buses(handler)
        result = await bus.request_wait(req())
        assert (result.status, result.reason) == ("failed", "model-down")
        await asyncio.sleep(0.1)
        assert len(handler.calls) == 1
