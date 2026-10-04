"""Heartbeat service - per-agent heartbeat state machine for Atlas.

Ports the OpenClaw heartbeat runner semantics (source freeze ``3e5560873a4``;
see ``docs/research/2026-10-03-persistent-atlas/lanes/r2-openclaw-heartbeat-cron.md``):

- guards: disabled -> quiet hours -> preflight (empty scratch / consumed
  events) -> busy -> cooldown (:mod:`atlas.heartbeat.guards`);
- no-change contract: ``heartbeat_respond`` structured reply preferred, legacy
  ``NO_REPLY`` / ``HEARTBEAT_OK`` text accepted (:mod:`atlas.heartbeat.outcome`);
- wake bus: per-target slots, 250ms coalescing, priorities, concurrency cap,
  retain/retry (:mod:`atlas.heartbeat.wake`);
- isolated heartbeat session key ``agent:<id>:heartbeat``;
- delivery targets ``owner | none | <channel:target>``.

**The tick is driven exclusively by the automation engine**
(``payload.kind == "heartbeat"`` -> ``HeartbeatService.tick(agent_id, reason)``,
the W3<->W4 seam) **and by tests**. This module deliberately owns no resident
timer - cadence lives with the engine, guards live here, matching OpenClaw's
"cron holds the beat, the runner holds the guards" split.

All platform capabilities are injected through :class:`HeartbeatHost`; nothing
from other lanes (persistent_agents / automation / channels / server) is
imported here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Protocol, runtime_checkable

from .guards import (
    GUARD_REASONS,
    CooldownTracker,
    is_effectively_empty,
    is_within_active_hours,
    should_defer_wake,
)
from .outcome import (
    SILENT_REPLY_TOKEN,
    HeartbeatOutcome,
    parse_outcome,
)
from .wake import WakeBus, WakeRequest, WakeResult

DEFAULT_INTERVAL_MINUTES = 30.0
DEFAULT_HEARTBEAT_ROOT = Path("data") / "heartbeat"
STATE_FILENAME = "state.json"

# Transcript markers distinguishing internal wake kinds (port of
# INTERNAL_WAKE_TRANSCRIPT_PROMPTS, Atlas naming).
WAKE_MARKER_HEARTBEAT = "[Atlas heartbeat poll]"
WAKE_MARKER_EVENT = "[Atlas event wake]"
WAKE_MARKER_TASK = "[Atlas scheduled task]"

# Default heartbeat prompt (port of heartbeat.ts HEARTBEAT_PROMPT).
HEARTBEAT_CONTEXT_PROMPT = (
    "Follow the heartbeat monitor scratch context when provided. "
    "Recurring work belongs in automations, not heartbeat scratch; "
    "do not infer or repeat old tasks from prior chats."
)
DEFAULT_HEARTBEAT_PROMPT = (
    f"{HEARTBEAT_CONTEXT_PROMPT} If nothing needs attention, reply {SILENT_REPLY_TOKEN}."
)
# Response contract appended to every heartbeat prompt (port of
# HEARTBEAT_RESPONSE_TOOL_PROMPT incl. the text-fallback instructions).
HEARTBEAT_RESPONSE_INSTRUCTIONS = (
    "Use heartbeat_respond to report the wake outcome: reply with a single JSON "
    'object {"outcome": "no_change|progress|done|blocked|needs_attention", '
    '"notify": true|false, "summary": "...", "next_check": "<optional suggested '
    'interval>", "scratch": "<optional COMPLETE replacement scratch text>"}. '
    "Set notify=false when nothing needs the user's attention. Scratch is "
    "monitor prose only, replaced wholesale when provided."
)
HEARTBEAT_FALLBACK_INSTRUCTIONS = (
    f"If the structured reply is not available, reply {SILENT_REPLY_TOKEN} when "
    "nothing needs the user's attention; when the user should be interrupted, "
    "reply with only the alert text instead of a prose report."
)


@runtime_checkable
class HeartbeatHost(Protocol):
    """Platform ports the heartbeat service needs. Tests inject fakes; the
    production host is wired by the integration owner (Wave 2)."""

    def get_heartbeat_config(self, agent_id: str) -> dict:
        """integration-map section 3 heartbeat fields: enabled,
        interval_minutes, active_hours, prompt, delivery, isolated_session."""
        ...

    def is_agent_busy(self, agent_id: str) -> bool: ...

    def dispatch_heartbeat_turn(
        self, agent_id: str, prompt: str, session_key: str
    ) -> str | dict | Awaitable[str | dict]:
        """Run one model turn for the heartbeat; sync or async, fakeable."""
        ...

    def deliver(self, agent_id: str, text: str, target: str) -> None:
        """Deliver a notification. ``target`` is ``"owner"`` or the raw
        ``<channel:target>`` string; ``"none"`` never reaches here."""
        ...

    def now(self) -> float:
        """Wall clock, injectable for tests (epoch seconds)."""
        ...


def session_key(agent_id: str, *, isolated: bool = True) -> str:
    """Heartbeat session key: ``agent:<id>:heartbeat`` (isolated) or
    ``agent:<id>:main``.

    Wave2 convergence note: W1 owns the canonical
    ``agent:<id>:[channel:[account]:]kind:peer`` ``session_key()`` in
    ``atlas.persistent_agents``; this local copy intentionally uses the same
    format and must be replaced by the W1 implementation once that module
    lands (W3 must not import not-yet-landed lane modules).
    """
    return f"agent:{agent_id}:heartbeat" if isolated else f"agent:{agent_id}:main"


def resolve_delivery_target(delivery: str | None) -> str | None:
    """``owner`` -> ``"owner"`` (default), ``none`` -> ``None`` (never deliver),
    anything else (``<channel:target>``) passes through verbatim."""
    raw = (delivery or "").strip()
    if not raw:
        return "owner"
    if raw.lower() == "none":
        return None
    return raw


@dataclass
class TickResult:
    """Result of one guarded heartbeat tick (port of HeartbeatRunResult)."""

    status: str  # ran | skipped | failed
    reason: str = ""
    retry_at: float | None = None
    outcome: HeartbeatOutcome | None = None
    delivered: bool = False
    duration_s: float = 0.0


def _default_config() -> dict:
    return {
        "enabled": False,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "active_hours": "",
        "prompt": "",
        "delivery": "owner",
        "isolated_session": True,
    }


class HeartbeatService:
    """Per-agent heartbeat state: guards, turn dispatch, settlement,
    scratch/cooldown persistence and wake-bus integration."""

    def __init__(
        self,
        host: HeartbeatHost,
        *,
        root: str | os.PathLike[str] | None = None,
        wake_bus: WakeBus | None = None,
        clock: Any = None,
        bus_options: dict | None = None,
    ) -> None:
        self._host = host
        self._root = Path(root) if root is not None else DEFAULT_HEARTBEAT_ROOT
        self._clock = clock if clock is not None else host.now
        self._state: dict[str, dict[str, Any]] = {}
        self._cooldowns: dict[str, CooldownTracker] = {}
        self._events: dict[str, list[str]] = {}
        self._wake_bus = wake_bus if wake_bus is not None else self._make_bus(bus_options or {})
        self._load()

    # -- public surface ----------------------------------------------------

    @property
    def wake_bus(self) -> WakeBus:
        return self._wake_bus

    def session_key(self, agent_id: str) -> str:
        cfg = self._resolve_config(agent_id)
        return session_key(agent_id, isolated=cfg["isolated_session"])

    def next_due_at(self, agent_id: str) -> float | None:
        """Next due epoch for the interval cadence (None = due immediately,
        disabled agent, or no cadence). The engine uses this to time ticks;
        overdue gaps are never replayed slot-by-slot - one tick is one
        catch-up run, aligned with r2 section 2.5."""
        cfg = self._resolve_config(agent_id)
        if not cfg["enabled"]:
            return None
        last_run_at = self._state.get(agent_id, {}).get("last_run_at")
        if last_run_at is None:
            return None
        return float(last_run_at) + cfg["interval_minutes"] * 60.0

    def is_overdue(self, agent_id: str) -> bool:
        due = self.next_due_at(agent_id)
        return due is not None and self._clock() >= due

    def scratch(self, agent_id: str) -> str | None:
        value = self._state.get(agent_id, {}).get("scratch")
        return value if isinstance(value, str) else None

    def last_outcome(self, agent_id: str) -> dict | None:
        value = self._state.get(agent_id, {}).get("last_outcome")
        return value if isinstance(value, dict) else None

    def cooldown(self, agent_id: str) -> CooldownTracker:
        return self._cooldowns.setdefault(agent_id, CooldownTracker())

    def push_event(self, agent_id: str, text: str = "") -> None:
        """Queue a process-completion / external event for this agent."""
        self._events.setdefault(agent_id, []).append(text)

    def set_scratch(self, agent_id: str, scratch: str | None) -> None:
        state = self._state.setdefault(agent_id, {})
        state["scratch"] = scratch
        self._save()

    async def tick(self, agent_id: str, reason: str = "schedule") -> TickResult:
        """Run one guarded heartbeat tick. Only the automation engine
        (payload.kind == "heartbeat") and tests call this."""
        intent = "scheduled" if reason in ("schedule", "interval", "catch-up") else "event"
        return await self._run_tick(agent_id, reason=reason, intent=intent)

    async def handle_wake(self, request: WakeRequest) -> WakeResult:
        """Wake-bus handler: guarded tick converted to a bus result. Public so
        a custom bus can be wired from outside."""
        tick = await self._run_tick(
            request.agent_id,
            reason=request.reason,
            intent=request.intent,
            retained_work=request.retained_work,
        )
        if tick.status == "ran":
            return WakeResult.ran(tick.duration_s)
        if tick.status == "failed":
            return WakeResult.failed(tick.reason)
        retry_delay_s = None
        if tick.retry_at is not None:
            # Cooldown deadlines live in the host clock; the bus schedules on
            # its own real-time clock, so hand it a wall delay.
            retry_delay_s = max(0.0, tick.retry_at - self._clock())
        return WakeResult.skipped(tick.reason, retry_at=tick.retry_at, retry_delay_s=retry_delay_s)

    async def request_wake(
        self,
        agent_id: str,
        *,
        intent: str = "event",
        source: str = "exec-event",
        reason: str = "event",
        timeout: float | None = None,
    ) -> WakeResult:
        """Enqueue a wake on the bus and await its settlement."""
        return await self._wake_bus.request_wait(
            WakeRequest(agent_id=agent_id, intent=intent, source=source, reason=reason),
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._wake_bus.close()

    # -- tick internals ----------------------------------------------------

    async def _run_tick(
        self,
        agent_id: str,
        *,
        reason: str,
        intent: str,
        retained_work: bool = False,
    ) -> TickResult:
        cfg = self._resolve_config(agent_id)
        now = self._clock()
        started_at = now
        cooldown = self.cooldown(agent_id)
        scratch = self.scratch(agent_id)
        next_due = self.next_due_at(agent_id) if intent == "scheduled" else None

        preflight_ok, preflight_reason = self._preflight(agent_id, scratch, intent)
        active_hours_ok = is_within_active_hours(
            datetime.fromtimestamp(now).time(), cfg["active_hours"]
        )
        deferred, guard_reason = should_defer_wake(
            enabled=cfg["enabled"],
            active_hours_ok=active_hours_ok,
            preflight_ok=preflight_ok,
            preflight_reason=preflight_reason,
            busy=self._host.is_agent_busy(agent_id),
            cooldown=cooldown,
            now=now,
            intent=intent,
            next_due=next_due,
            retained_work=retained_work,
        )
        if deferred:
            retry_at = None
            if guard_reason in GUARD_REASONS:
                _d, _r, retry_at = cooldown.should_defer(
                    intent=intent, now=now, next_due=next_due, retained_work=retained_work
                )
            return TickResult(status="skipped", reason=guard_reason, retry_at=retry_at)

        # Admitted: only now does the run consume cooldown bookkeeping, so a
        # retryable skip above never burns the 30s spacing or the flood
        # window (r2 section 1.3 RETRY_REASONS semantics).
        cooldown.record_run_start(now)
        prompt = self._build_prompt(cfg, scratch, reason=reason, intent=intent)
        skey = self.session_key(agent_id)
        try:
            raw = self._host.dispatch_heartbeat_turn(agent_id, prompt, skey)
            if asyncio.isfuture(raw) or asyncio.iscoroutine(raw):
                raw = await raw
        except Exception as exc:
            logging.getLogger(__name__).exception("Heartbeat tick failed")
            self._save()
            return TickResult(status="failed", reason=str(exc) or exc.__class__.__name__)

        duration_s = max(0.0, self._clock() - started_at)
        outcome = parse_outcome(raw)

        if outcome.scratch is not None:
            self._state.setdefault(agent_id, {})["scratch"] = outcome.scratch
        if intent == "event":
            self._events.pop(agent_id, None)  # events are consumed by the turn

        delivered = False
        if not outcome.silent:
            target = resolve_delivery_target(cfg["delivery"])
            body = outcome.notification_body()
            if target is not None and body:
                self._host.deliver(agent_id, body, target)
                delivered = True

        self._persist_run(agent_id, outcome, now, duration_s)
        return TickResult(
            status="ran",
            outcome=outcome,
            delivered=delivered,
            duration_s=duration_s,
        )

    def _preflight(self, agent_id: str, scratch: str | None, intent: str) -> tuple[bool, str]:
        """Port of resolveHeartbeatPreflight: terminal skips before the model
        is ever invoked. A missing scratch row proceeds (first run); a row
        that exists but is effectively empty skips; an event wake whose
        events were already consumed skips."""
        has_event = bool(self._events.get(agent_id))
        if intent == "event" and not has_event:
            return (False, "no-pending-event")
        if scratch is not None and is_effectively_empty(scratch) and not has_event:
            return (False, "empty-scratch")
        return (True, "")

    def _resolve_config(self, agent_id: str) -> dict:
        raw = self._host.get_heartbeat_config(agent_id) or {}
        cfg = _default_config()
        cfg.update(raw)
        try:
            cfg["interval_minutes"] = float(cfg["interval_minutes"])
        except (TypeError, ValueError):
            cfg["interval_minutes"] = DEFAULT_INTERVAL_MINUTES
        if cfg["interval_minutes"] <= 0:
            cfg["interval_minutes"] = DEFAULT_INTERVAL_MINUTES
        cfg["enabled"] = bool(cfg["enabled"])
        cfg["isolated_session"] = bool(cfg.get("isolated_session", True))
        cfg["active_hours"] = str(cfg.get("active_hours") or "")
        cfg["prompt"] = str(cfg.get("prompt") or "")
        cfg["delivery"] = str(cfg.get("delivery") or "owner")
        return cfg

    def _build_prompt(self, cfg: dict, scratch: str | None, *, reason: str, intent: str) -> str:
        base = cfg["prompt"].strip() or DEFAULT_HEARTBEAT_PROMPT
        marker = (
            WAKE_MARKER_TASK if intent == "task" else
            WAKE_MARKER_EVENT if intent == "event" else
            WAKE_MARKER_HEARTBEAT
        )
        parts = [base, f"{marker} source={reason} intent={intent}"]
        parts.append("# Heartbeat monitor scratch\n" + (scratch if scratch else "(empty)"))
        parts.append(HEARTBEAT_RESPONSE_INSTRUCTIONS)
        parts.append(HEARTBEAT_FALLBACK_INSTRUCTIONS)
        return "\n\n".join(parts)

    def _persist_run(
        self,
        agent_id: str,
        outcome: HeartbeatOutcome,
        now: float,
        duration_s: float,
    ) -> None:
        state = self._state.setdefault(agent_id, {})
        state["last_run_at"] = now
        state["cooldown"] = self.cooldown(agent_id).to_dict()
        state["last_duration_s"] = duration_s
        # Outcome memory, not replay: no_change never overwrites the last
        # meaningful outcome (port of heartbeat-outcome-store.ts semantics).
        if outcome.stored:
            state["last_outcome"] = {
                "outcome": outcome.outcome,
                "summary": outcome.summary,
                "notify": outcome.notify,
                "at": now,
            }
        self._save()

    # -- persistence ---------------------------------------------------------

    def _make_bus(self, options: dict) -> WakeBus:
        # The bus keeps its own real-time scheduling clock (asyncio timers are
        # real); handler-side cooldown deadlines cross as wall delays.
        return WakeBus(self.handle_wake, **options)

    def _state_path(self) -> Path:
        return self._root / STATE_FILENAME

    def _load(self) -> None:
        path = self._state_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        agents = raw.get("agents")
        if not isinstance(agents, dict):
            return
        for agent_id, entry in agents.items():
            if not isinstance(entry, dict):
                continue
            self._state[agent_id] = {
                "scratch": entry.get("scratch"),
                "last_outcome": (
                    entry["last_outcome"] if isinstance(entry.get("last_outcome"), dict) else None
                ),
                "last_run_at": entry.get("last_run_at"),
                "last_duration_s": entry.get("last_duration_s"),
            }
            self._cooldowns[agent_id] = CooldownTracker.from_dict(entry.get("cooldown"))

    def _save(self) -> None:
        payload = {
            "version": 1,
            "agents": {
                agent_id: {
                    "scratch": entry.get("scratch"),
                    "last_outcome": entry.get("last_outcome"),
                    "last_run_at": entry.get("last_run_at"),
                    "last_duration_s": entry.get("last_duration_s"),
                    "cooldown": self.cooldown(agent_id).to_dict(),
                }
                for agent_id, entry in self._state.items()
            },
        }
        self._root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self._state_path())
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


__all__ = [
    "DEFAULT_HEARTBEAT_PROMPT",
    "DEFAULT_HEARTBEAT_ROOT",
    "DEFAULT_INTERVAL_MINUTES",
    "HEARTBEAT_FALLBACK_INSTRUCTIONS",
    "HEARTBEAT_RESPONSE_INSTRUCTIONS",
    "HeartbeatHost",
    "HeartbeatService",
    "TickResult",
    "resolve_delivery_target",
    "session_key",
]
