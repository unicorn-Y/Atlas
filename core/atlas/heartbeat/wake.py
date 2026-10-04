"""Asyncio wake bus - port of OpenClaw ``src/infra/session-event-wake.ts``.

All heartbeat wake categories converge here. Per-target (agent) there is one
``WakeGroup`` with three slots (``task`` / ``scheduled`` / ``event``); wakes
arriving inside the coalesce window merge, keeping the higher-priority intent
(``manual``/``immediate`` > ``task``/``event`` > ``scheduled``/``interval`` >
``retry``). At most ``MAX_ACTIVE_TARGETS`` targets dispatch concurrently. A
wake whose handler skip is retainable (retryable busy reasons, or cooldown
guard reasons carrying task/event/immediate work) is re-enqueued by the bus
and retried - the caller's future only settles when the wake finally runs,
skips terminally, or fails.

Times come from an injectable clock (``now_fn``) so tests can use fast real
time or a fake clock; the service shares its host clock with the bus so
cooldown ``retry_at`` values line up.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from .guards import GUARD_REASONS, RETRY_REASONS

SLOTS = ("task", "scheduled", "event")

# Ported constants (session-event-wake.ts).
COALESCE_S = 0.25  # COALESCE_MS = 250
RETRY_S = 1.0  # RETRY_MS = 1_000
IDLE_RETRY_S = 60.0  # SESSION_EVENT_IDLE_RETRY_MS = 60_000
MAX_ACTIVE_TARGETS = 4  # MAX_ACTIVE_TARGETS = 4


def wake_priority(intent: str = "", source: str = "", reason: str = "") -> int:
    """Port of the bus ``priority()``: manual/immediate=3 > task/event=2 >
    scheduled/interval=1 > retry=0."""
    if intent in ("manual", "immediate"):
        return 3
    if source == "retry" or reason == "retry":
        return 0
    if intent == "scheduled" or source == "interval" or reason == "interval":
        return 1
    return 2


@dataclass(frozen=True)
class ScheduledTask:
    """Cron-owned work carried into a guarded heartbeat turn."""

    task_id: str
    name: str = ""
    prompt: str = ""


@dataclass(frozen=True)
class WakeRequest:
    """One wake request (port of HeartbeatWakeRequest)."""

    agent_id: str
    intent: str = "scheduled"  # scheduled | task | event | immediate | manual
    source: str = "interval"
    reason: str = "interval"
    session_key: str = ""
    tasks: tuple[ScheduledTask, ...] = ()
    # Set by the bus when re-enqueueing retained work after a guard deferral.
    retained_work: bool = False

    @property
    def priority(self) -> int:
        return wake_priority(self.intent, self.source, self.reason)


@dataclass
class WakeResult:
    """Handler outcome (port of HeartbeatRunResult)."""

    status: str  # ran | skipped | failed
    reason: str = ""
    # Retry deadline in the HANDLER's clock (e.g. host epoch). The bus
    # converts it to a wall delay via ``retry_delay_s`` when provided.
    retry_at: float | None = None
    # Wall-clock delay before the retained wake is retried. Takes precedence.
    retry_delay_s: float | None = None
    duration_s: float = 0.0
    # A pure monitor poll the handler chose not to retain (waits for the next
    # persisted cadence tick instead of retrying behind busy work).
    terminal_poll: bool = False

    @classmethod
    def ran(cls, duration_s: float = 0.0) -> "WakeResult":
        return cls(status="ran", duration_s=duration_s)

    @classmethod
    def skipped(
        cls,
        reason: str,
        retry_at: float | None = None,
        *,
        retry_delay_s: float | None = None,
        terminal_poll: bool = False,
    ) -> "WakeResult":
        return cls(
            status="skipped",
            reason=reason,
            retry_at=retry_at,
            retry_delay_s=retry_delay_s,
            terminal_poll=terminal_poll,
        )

    @classmethod
    def failed(cls, reason: str) -> "WakeResult":
        return cls(status="failed", reason=reason)


Handler = Callable[[WakeRequest], Any]


@dataclass
class _PendingWake:
    request: WakeRequest
    sequence: int
    requested_at: float
    ready_at: float
    not_before: float
    retained_work: bool = False
    settlements: list = field(default_factory=list)

    @property
    def priority(self) -> int:
        return self.request.priority


@dataclass
class _Group:
    slots: dict[str, _PendingWake] = field(default_factory=dict)
    blocked_until: float = 0.0


def _slot_for(intent: str) -> str:
    if intent == "task":
        return "task"
    if intent == "scheduled":
        return "scheduled"
    return "event"


def _merge_tasks(left: tuple[ScheduledTask, ...], right: tuple[ScheduledTask, ...]) -> tuple:
    merged = {task.task_id: task for task in (*left, *right)}
    return tuple(sorted(merged.values(), key=lambda task: task.task_id))


def _merge(previous: _PendingWake, next: _PendingWake) -> _PendingWake:
    """Port of the bus ``merge()``: keep the higher-priority intent, merge
    tasks by id, earliest ready time, latest not-before (manual bypasses)."""
    if (previous.request.intent == "task") != (next.request.intent == "task"):
        preferred = previous if previous.request.intent == "task" else next
    elif next.priority > previous.priority or (
        next.priority == previous.priority and next.requested_at >= previous.requested_at
    ):
        preferred = next
    else:
        preferred = previous
    other = next if preferred is previous else previous

    bypass = preferred.request.intent in ("manual", "immediate") and not preferred.retained_work
    # A scheduled reason must not discard the event's guard-retry semantics.
    intent = (
        other.request.intent
        if preferred.request.intent == "scheduled"
        else preferred.request.intent
    )
    request = replace(
        preferred.request,
        intent=intent,
        tasks=_merge_tasks(previous.request.tasks, next.request.tasks),
    )
    return _PendingWake(
        request=request,
        sequence=min(previous.sequence, next.sequence),
        requested_at=(
            preferred.requested_at
            if bypass
            else min(previous.requested_at, next.requested_at)
        ),
        ready_at=min(previous.ready_at, next.ready_at),
        not_before=0.0 if bypass else max(previous.not_before, next.not_before),
        retained_work=(previous.retained_work or next.retained_work) and not bypass,
        settlements=[s for s in (*previous.settlements, *next.settlements) if s is not None],
    )


class WakeBus:
    """Per-target wake queue with coalescing, priorities, a concurrency cap
    and retain/retry semantics."""

    def __init__(
        self,
        handler: Handler,
        *,
        now_fn: Callable[[], float] = time.monotonic,
        coalesce_s: float = COALESCE_S,
        retry_s: float = RETRY_S,
        idle_retry_s: float = IDLE_RETRY_S,
        max_active: int = MAX_ACTIVE_TARGETS,
    ) -> None:
        self._handler = handler
        # Scheduling clock: must advance in real time (asyncio timers are
        # real); handler clocks (host epoch) only enter via retry delays.
        self._now = now_fn
        self._coalesce_s = coalesce_s
        self._retry_s = retry_s
        self._idle_retry_s = idle_retry_s
        self._max_active = max(1, int(max_active))
        self._pending: dict[str, _Group] = {}
        self._active: dict[str, asyncio.Task] = {}
        self._sequence = 0
        self._wakeup = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None
        self._closed = False

    # -- public API --------------------------------------------------------

    @staticmethod
    def target_key(request: WakeRequest) -> str:
        """Per-target key. Heartbeat targets are per-agent; the isolated
        heartbeat session is derived from the agent, so the agent id is the
        coalescing target (OpenClaw keys ``agentId::sessionKey``)."""
        return request.agent_id or "::"

    def request(self, req: WakeRequest, *, coalesce_s: float | None = None) -> str:
        """Fire-and-forget enqueue."""
        key = self._enqueue(req, coalesce_s=coalesce_s, settlement=None)
        self._ensure_loop()
        return key

    async def request_wait(
        self,
        req: WakeRequest,
        *,
        coalesce_s: float | None = None,
        timeout: float | None = None,
    ) -> WakeResult:
        """Enqueue and await the final settlement of this wake."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[WakeResult] = loop.create_future()
        self._enqueue(req, coalesce_s=coalesce_s, settlement=future)
        self._ensure_loop()
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout)

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def pending_count(self) -> int:
        return sum(len(group.slots) for group in self._pending.values())

    async def close(self) -> None:
        """Stop the loop, cancel in-flight dispatches and settle waiters."""
        self._closed = True
        self._wakeup.set()
        loop_task = self._loop_task
        if loop_task is not None:
            await asyncio.gather(loop_task, return_exceptions=True)
        for task in list(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()
        for group in self._pending.values():
            for wake in group.slots.values():
                self._settle(wake, WakeResult.skipped("handler-unavailable"))
        self._pending.clear()

    # -- internals ---------------------------------------------------------

    def _enqueue(
        self,
        req: WakeRequest,
        *,
        coalesce_s: float | None,
        settlement: asyncio.Future | None,
    ) -> str:
        now = self._now()
        self._sequence += 1
        pending = _PendingWake(
            request=req,
            sequence=self._sequence,
            requested_at=now,
            ready_at=now + (self._coalesce_s if coalesce_s is None else coalesce_s),
            not_before=0.0,
            settlements=[settlement] if settlement is not None else [],
        )
        key = self.target_key(req)
        group = self._pending.setdefault(key, _Group())
        slot = _slot_for(req.intent)
        existing = group.slots.get(slot)
        group.slots[slot] = _merge(existing, pending) if existing is not None else pending
        self._wakeup.set()
        return key

    def _ensure_loop(self) -> None:
        if self._closed:
            return
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while not self._closed:
            self._admit(self._now())
            self._wakeup.clear()
            delay = self._next_delay(self._now())
            if delay is None:
                return
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=max(0.0, delay))
            except (asyncio.TimeoutError, TimeoutError):
                pass

    def _ready_slots(self, group: _Group, now: float) -> dict[str, _PendingWake]:
        picked: dict[str, _PendingWake] = {}
        for slot in SLOTS:
            wake = group.slots.get(slot)
            if wake is not None and wake.not_before <= now and wake.ready_at <= now:
                picked[slot] = wake
        return picked

    def _admit(self, now: float) -> None:
        candidates: list[tuple[str, _Group, dict[str, _PendingWake]]] = []
        for key, group in self._pending.items():
            if key in self._active or group.blocked_until > now:
                continue
            picked = self._ready_slots(group, now)
            if picked:
                candidates.append((key, group, picked))
        # Highest priority first; ties break on earliest request.
        candidates.sort(
            key=lambda item: (
                -max(wake.priority for wake in item[2].values()),
                min(wake.requested_at for wake in item[2].values()),
            )
        )
        for key, group, picked in candidates:
            if len(self._active) >= self._max_active:
                break
            wakes = self._compose_wakes(picked)
            for slot, wake in picked.items():
                if group.slots.get(slot) is wake:
                    del group.slots[slot]
            if not group.slots:
                self._pending.pop(key, None)
            task = asyncio.get_running_loop().create_task(self._dispatch(key, wakes))
            self._active[key] = task

    def _compose_wakes(self, picked: dict[str, _PendingWake]) -> list[_PendingWake]:
        """Port of takeReady composition: a task turn absorbs a coincident
        scheduled tick (the task prompt includes monitor scratch); an event
        absorbs a coincident scheduled tick; ordering prefers retained work."""
        task = picked.get("task")
        scheduled = picked.get("scheduled")
        event = picked.get("event")
        wakes: list[_PendingWake] = []
        if task is not None:
            wakes.append(_merge(scheduled, task) if scheduled is not None else task)
            if event is not None:
                wakes.append(event)
        elif event is not None:
            wakes.append(_merge(scheduled, event) if scheduled is not None else event)
        elif scheduled is not None:
            wakes.append(scheduled)
        wakes.sort(key=lambda wake: (0 if wake.retained_work else 1, wake.requested_at))
        return wakes

    async def _dispatch(self, key: str, wakes: list[_PendingWake]) -> None:
        try:
            for wake in wakes:
                try:
                    result = await self._invoke(wake.request)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # a thrown handler retries (port)
                    logging.getLogger(__name__).exception("Heartbeat wake handler failed")
                    self._retry(wake, WakeResult.skipped(f"handler-error: {exc}"))
                    continue
                if (
                    result.status == "skipped"
                    and not result.terminal_poll
                    and self._should_retain(wake, result)
                ):
                    self._retry(wake, result)
                else:
                    self._settle(wake, result)
        except asyncio.CancelledError:
            raise
        finally:
            self._active.pop(key, None)
            self._wakeup.set()
            self._ensure_loop()

    async def _invoke(self, request: WakeRequest) -> WakeResult:
        started = self._now()
        outcome = self._handler(request)
        if asyncio.isfuture(outcome) or asyncio.iscoroutine(outcome):
            outcome = await outcome
        if isinstance(outcome, WakeResult):
            return outcome
        if isinstance(outcome, tuple):  # (status, reason) convenience
            status, reason = (outcome + ("",))[:2]
            return WakeResult(status=status, reason=reason)
        return WakeResult.ran(duration_s=self._now() - started)

    def _should_retain(self, wake: _PendingWake, result: WakeResult) -> bool:
        if result.reason in RETRY_REASONS:
            return True
        return result.reason in GUARD_REASONS and (
            bool(wake.request.tasks)
            or wake.request.intent in ("task", "event", "immediate")
        )

    def _retry(self, wake: _PendingWake, result: WakeResult) -> None:
        """Port of the bus ``retry()``: guard-reason and idle-grace skips get
        a not-before deadline with retainedWork; other retryable skips block
        the whole target until the deadline."""
        now = self._now()
        idle_grace = result.reason in ("preempted", "channel-not-ready") or (
            result.reason in ("requests-in-flight", "active-run")
            and wake.request.intent in ("scheduled", "task")
        )
        guard = idle_grace or result.reason in GUARD_REASONS
        if result.retry_delay_s is not None:
            delay = max(0.0, result.retry_delay_s)
        elif result.retry_at is not None:  # same-clock fallback
            delay = max(0.0, result.retry_at - now)
        elif idle_grace:
            delay = self._idle_retry_s
        else:
            delay = self._retry_s
        deadline = now + delay
        request = replace(wake.request, retained_work=True) if guard else wake.request
        requeued = _PendingWake(
            request=request,
            sequence=wake.sequence,
            requested_at=wake.requested_at,
            ready_at=now,
            not_before=deadline if guard else 0.0,
            retained_work=True if guard else wake.retained_work,
            settlements=wake.settlements,
        )
        key = self.target_key(wake.request)
        group = self._pending.setdefault(key, _Group())
        slot = _slot_for(requeued.request.intent)
        existing = group.slots.get(slot)
        group.slots[slot] = _merge(existing, requeued) if existing is not None else requeued
        if not guard:
            group.blocked_until = max(group.blocked_until, deadline)
        self._wakeup.set()

    def _settle(self, wake: _PendingWake, result: WakeResult) -> None:
        for future in wake.settlements:
            if future is not None and not future.done():
                future.set_result(result)
        wake.settlements = []

    def _next_delay(self, now: float) -> float | None:
        if self._closed:
            return None
        if len(self._active) >= self._max_active:
            # A finishing dispatch sets the wakeup and restarts the loop.
            return None
        earliest: float | None = None
        for key, group in self._pending.items():
            if key in self._active:
                continue
            slot_times = [max(wake.ready_at, wake.not_before) for wake in group.slots.values()]
            if not slot_times:
                continue
            # blocked_until gates the whole target: it can only postpone the
            # earliest slot, never advance it (0 = not blocked).
            candidate = max(group.blocked_until, min(slot_times))
            earliest = candidate if earliest is None else min(earliest, candidate)
        if earliest is None:
            return None
        return max(0.0, earliest - now)


__all__ = [
    "COALESCE_S",
    "IDLE_RETRY_S",
    "MAX_ACTIVE_TARGETS",
    "RETRY_S",
    "SLOTS",
    "Handler",
    "ScheduledTask",
    "WakeBus",
    "WakeRequest",
    "WakeResult",
    "wake_priority",
]
