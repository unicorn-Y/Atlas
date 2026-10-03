"""Pure guard-chain functions for the heartbeat runner.

Ported from OpenClaw (source freeze ``3e5560873a4``, read-only at
``D:\\Atlas-persistent-sources\\openclaw``):

- ``src/infra/heartbeat-active-hours.ts``      -> :func:`is_within_active_hours`
- ``src/infra/heartbeat-cooldown.ts``          -> :class:`CooldownTracker`
  (``shouldDeferWake`` / ``recordRunStart``, 30s min-spacing, 5-per-60s flood)
- ``src/infra/heartbeat-runner-execution.ts``  -> guard-chain order of
  :func:`should_defer_wake` (disabled -> quiet hours -> preflight -> busy ->
  cooldown, per r2 report section 1.3 / 1.9)
- ``src/infra/heartbeat-runner-prompt.ts``     -> :func:`is_effectively_empty`
  (``isHeartbeatContentEffectivelyEmpty`` preflight cheap-diff)
- ``src/infra/session-event-wake.ts``          -> retry/guard reason sets and
  the ``shouldRetain`` rule (:func:`should_retain_wake`)

Everything here is a pure function or a plain stateful value object with no
I/O, so each piece is independently unit-testable. Cooldown persistence is a
plain ``dict`` round-trip (``to_dict`` / ``from_dict``); the service owns the
json file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time as dt_time

# ---------------------------------------------------------------------------
# Ported constants (OpenClaw src/infra/heartbeat-cooldown.ts)
# ---------------------------------------------------------------------------
DEFAULT_MIN_WAKE_SPACING_S = 30.0  # DEFAULT_MIN_WAKE_SPACING_MS = 30_000
DEFAULT_FLOOD_WINDOW_S = 60.0  # DEFAULT_FLOOD_WINDOW_MS = 60_000
DEFAULT_FLOOD_THRESHOLD = 5  # DEFAULT_FLOOD_THRESHOLD = 5

# Wake intents, port of HeartbeatWakeIntent (heartbeat-wake-contracts.ts).
WAKE_INTENTS = ("scheduled", "task", "event", "immediate", "manual")

# Skips the wake bus retains and retries (session-event-wake.ts RETRY_REASONS).
RETRY_REASONS = frozenset(
    {
        "active-run",
        "requests-in-flight",
        "cron-in-progress",
        "preempted",
        "channel-not-ready",
    }
)
# Cooldown/guard skips produced by the runner itself (GUARD_REASONS).
GUARD_REASONS = frozenset({"not-due", "min-spacing", "flood"})

# Reasons a guard can defer with, in guard-chain order.
DEFER_REASONS = (
    "disabled",
    "quiet-hours",
    "empty-scratch",
    "no-pending-event",
    "requests-in-flight",
    "not-due",
    "min-spacing",
    "flood",
)


def is_retryable_reason(reason: str) -> bool:
    """True when the wake bus should retain and retry after this skip."""
    return reason in RETRY_REASONS


def should_retain_wake(intent: str, reason: str, *, has_tasks: bool = False) -> bool:
    """Port of session-event-wake.ts ``shouldRetain``.

    Retryable busy reasons always retain; cooldown/guard reasons only retain
    work that carries tasks or a non-schedule intent (a pure interval poll is
    event-free and simply waits for the next persisted cadence tick).
    """
    if reason in RETRY_REASONS:
        return True
    if reason in GUARD_REASONS and (has_tasks or intent in ("task", "event", "immediate")):
        return True
    return False


# ---------------------------------------------------------------------------
# Active hours (port of heartbeat-active-hours.ts)
# ---------------------------------------------------------------------------
# Times are HH:MM; the end side additionally accepts "24:00".
_ACTIVE_HOURS_RE = re.compile(
    r"^\s*(?P<sh>[01]\d|2[0-3]):(?P<sm>[0-5]\d)\s*-\s*"
    r"(?:(?P<eh>[01]\d|2[0-3]):(?P<em>[0-5]\d)|24:00)\s*$"
)


def is_within_active_hours(now_time: dt_time, active_hours: str | None) -> bool:
    """Return True when ``now_time`` falls inside the ``"HH:MM-HH:MM"`` window.

    Port semantics (heartbeat-active-hours.ts):
    - empty/None window = active all day;
    - unparseable config is permissive (True) so bad schedules never disable
      heartbeats;
    - ``start == end`` is a zero-width window -> never active;
    - ``start > end`` is a cross-midnight window;
    - the end boundary is exclusive (``23:00`` ends the ``09:00-23:00`` day),
      the start boundary inclusive.
    """
    raw = (active_hours or "").strip()
    if not raw:
        return True
    match = _ACTIVE_HOURS_RE.match(raw)
    if match is None:
        return True  # invalid config is permissive, never disabling
    start = int(match["sh"]) * 60 + int(match["sm"])
    end_raw = match["eh"]
    end = (int(end_raw) * 60 + int(match["em"])) if end_raw else 24 * 60
    if start == end:
        return False  # zero-width window is never active
    current = now_time.hour * 60 + now_time.minute
    if end > start:
        return start <= current < end
    return current >= start or current < end


# ---------------------------------------------------------------------------
# Preflight (port of isHeartbeatContentEffectivelyEmpty)
# ---------------------------------------------------------------------------
_HTML_COMMENT_START_RE = re.compile(r"^\s*<!--")
_HEADER_RE = re.compile(r"^#+(\s|$)")
_LIST_STUB_RE = re.compile(r"^[-*+]\s*(\[[\sXx]?\]\s*)?$")
_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*$")


def is_effectively_empty(content: str | None) -> bool:
    """True when monitor scratch has no actionable content.

    Scratch counts as effectively empty when it contains only whitespace,
    HTML comments, ATX headers, fence markers, or empty checklist stubs.
    A missing scratch (``None``) returns False so the model can still decide
    what to do on a first run; the skip only applies to a row that exists.
    """
    if not isinstance(content, str):
        return False
    in_comment = False
    for raw_line in content.split("\n"):
        line = raw_line
        while in_comment or _HTML_COMMENT_START_RE.match(line):
            search = line if in_comment else line.lstrip()
            end = search.find("-->")
            if end == -1:
                in_comment = True
                line = ""
                break
            in_comment = False
            line = search[end + 3 :]
        trimmed = line.strip()
        if (
            not trimmed
            or _HEADER_RE.match(trimmed)
            or _LIST_STUB_RE.match(trimmed)
            or _FENCE_RE.match(trimmed)
        ):
            continue
        return False
    return True


# ---------------------------------------------------------------------------
# Cooldown tracker (port of heartbeat-cooldown.ts)
# ---------------------------------------------------------------------------
@dataclass
class CooldownTracker:
    """Per-agent run bookkeeping: 30s min-spacing plus 5-per-60s flood guard.

    ``record_run_start`` is called only when a run is actually admitted, so a
    retryable skip (busy and friends) never consumes cooldown. The buffer is a
    ring of at most ``flood_threshold + 1`` entries, matching OpenClaw.
    """

    min_spacing_s: float = DEFAULT_MIN_WAKE_SPACING_S
    flood_window_s: float = DEFAULT_FLOOD_WINDOW_S
    flood_threshold: int = DEFAULT_FLOOD_THRESHOLD
    last_run_started_at: float | None = None
    recent_run_starts: list[float] = field(default_factory=list)

    def should_defer(
        self,
        *,
        intent: str,
        now: float,
        next_due: float | None = None,
        retained_work: bool = False,
    ) -> tuple[bool, str, float | None]:
        """Port of OpenClaw ``shouldDeferWake`` -> ``(deferred, reason, retry_at)``.

        - ``manual`` intent is fully exempt; ``immediate`` bypasses spacing and
          not-due but still passes the flood guard (system wake-now paths can
          form feedback loops too).
        - ``scheduled`` intent only checks not-due: a persisted monitor tick
          bypasses min-spacing by construction.
        - task/event intents respond before the first scheduled tick and defer
          on min-spacing afterwards; retained work bypasses the not-due gate.
        """
        if intent == "manual":
            return (False, "", None)

        flood = self._flood_defer(now)
        if flood[0]:
            return flood
        if intent == "immediate":
            return (False, "", None)

        if intent == "scheduled":
            if next_due is not None and now < next_due:
                return (True, "not-due", next_due)
            return (False, "", None)

        # An idle agent can respond to its first event before the first tick.
        if self.last_run_started_at is None:
            return (False, "", None)

        spacing_retry_at = self._spacing_retry_at(now)
        if intent != "task" and not retained_work and next_due is not None and now < next_due:
            retry_at = next_due
            if spacing_retry_at is not None:
                retry_at = min(next_due, spacing_retry_at)
            return (True, "not-due", retry_at)

        if spacing_retry_at is not None:
            return (True, "min-spacing", spacing_retry_at)
        return (False, "", None)

    def record_run_start(self, ts: float) -> None:
        """Admit a run start and keep the ring at ``threshold + 1`` entries."""
        self.recent_run_starts.append(ts)
        while len(self.recent_run_starts) > self.flood_threshold + 1:
            self.recent_run_starts.pop(0)
        self.last_run_started_at = ts

    # -- internals ---------------------------------------------------------

    def _spacing_retry_at(self, now: float) -> float | None:
        if self.last_run_started_at is None:
            return None
        retry_at = self.last_run_started_at + self.min_spacing_s
        return retry_at if now < retry_at else None

    def _flood_defer(self, now: float) -> tuple[bool, str, float | None]:
        if len(self.recent_run_starts) < self.flood_threshold:
            return (False, "", None)
        window_start = now - self.flood_window_s
        in_window = 0
        for ts in reversed(self.recent_run_starts):
            if ts < window_start:
                break
            in_window += 1
            if in_window == self.flood_threshold:
                # retryAtMs = threshold'th start + window + 1ms (port keeps +1).
                return (True, "flood", ts + self.flood_window_s + 0.001)
        return (False, "", None)

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "min_spacing_s": self.min_spacing_s,
            "flood_window_s": self.flood_window_s,
            "flood_threshold": self.flood_threshold,
            "last_run_started_at": self.last_run_started_at,
            "recent_run_starts": list(self.recent_run_starts),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "CooldownTracker":
        data = data or {}
        starts = [float(ts) for ts in (data.get("recent_run_starts") or [])]
        threshold = int(data.get("flood_threshold") or DEFAULT_FLOOD_THRESHOLD)
        tracker = cls(
            min_spacing_s=float(data.get("min_spacing_s") or DEFAULT_MIN_WAKE_SPACING_S),
            flood_window_s=float(data.get("flood_window_s") or DEFAULT_FLOOD_WINDOW_S),
            flood_threshold=threshold,
            last_run_started_at=(
                float(data["last_run_started_at"])
                if data.get("last_run_started_at") is not None
                else None
            ),
            recent_run_starts=starts[-(threshold + 1) :],
        )
        return tracker


# ---------------------------------------------------------------------------
# Guard chain (order per r2 report section 1.3 / integration-map section 2)
# ---------------------------------------------------------------------------
DeferDecision = tuple[bool, str]


def should_defer_wake(
    *,
    enabled: bool,
    active_hours_ok: bool,
    preflight_ok: bool,
    preflight_reason: str = "",
    busy: bool = False,
    cooldown: CooldownTracker | None = None,
    now: float = 0.0,
    intent: str = "scheduled",
    next_due: float | None = None,
    retained_work: bool = False,
) -> DeferDecision:
    """Evaluate the full guard chain: disabled -> quiet hours -> preflight ->
    busy -> cooldown. Returns ``(deferred, reason)`` with ``reason == ""``
    when the wake is admitted.

    - ``disabled``: heartbeat off for this agent (terminal).
    - ``quiet-hours``: outside active hours; applies to interval-style
      ``scheduled`` ticks only (task/event/manual wakes are not restricted,
      mirroring OpenClaw's cron-source bypass).
    - preflight: ``empty-scratch`` (scratch row exists but is effectively
      empty) or ``no-pending-event`` (event wake whose events were already
      consumed) - terminal skips that never burn the model.
    - busy: ``requests-in-flight`` (retryable; ``manual``/``immediate`` exempt).
    - cooldown: ``not-due`` / ``min-spacing`` / ``flood`` via the tracker.
    """
    if not enabled:
        return (True, "disabled")
    if not active_hours_ok and intent == "scheduled":
        return (True, "quiet-hours")
    if not preflight_ok:
        return (True, preflight_reason or "empty-scratch")
    if busy and intent not in ("manual", "immediate"):
        return (True, "requests-in-flight")
    if cooldown is not None:
        deferred, reason, _retry_at = cooldown.should_defer(
            intent=intent, now=now, next_due=next_due, retained_work=retained_work
        )
        if deferred:
            return (True, reason)
    return (False, "")


__all__ = [
    "DEFAULT_FLOOD_THRESHOLD",
    "DEFAULT_FLOOD_WINDOW_S",
    "DEFAULT_MIN_WAKE_SPACING_S",
    "DEFER_REASONS",
    "GUARD_REASONS",
    "RETRY_REASONS",
    "CooldownTracker",
    "DeferDecision",
    "WAKE_INTENTS",
    "is_effectively_empty",
    "is_retryable_reason",
    "is_within_active_hours",
    "should_defer_wake",
    "should_retain_wake",
]
