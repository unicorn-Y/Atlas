"""Guard-chain unit tests: active hours, defer reasons, cooldown, retention."""

from __future__ import annotations

from datetime import time

from atlas.heartbeat.guards import (
    DEFAULT_FLOOD_THRESHOLD,
    DEFAULT_MIN_WAKE_SPACING_S,
    CooldownTracker,
    is_effectively_empty,
    is_retryable_reason,
    is_within_active_hours,
    should_defer_wake,
    should_retain_wake,
)

NOON = time(12, 0)


def make_chain(**overrides):
    """Guard-chain input defaults: enabled, all day, preflight ok, idle."""
    base = dict(
        enabled=True,
        active_hours_ok=True,
        preflight_ok=True,
        preflight_reason="",
        busy=False,
        cooldown=CooldownTracker(),
        now=1000.0,
        intent="scheduled",
        next_due=None,
        retained_work=False,
    )
    base.update(overrides)
    return base


def _retry_at(chain: dict) -> float | None:
    _deferred, _reason, retry_at = chain["cooldown"].should_defer(
        intent=chain["intent"],
        now=chain["now"],
        next_due=chain["next_due"],
        retained_work=chain["retained_work"],
    )
    return retry_at


# ---------------------------------------------------------------------------
# is_within_active_hours
# ---------------------------------------------------------------------------
class TestActiveHours:
    def test_empty_window_is_always_active(self):
        assert is_within_active_hours(time(3, 17), "")
        assert is_within_active_hours(time(23, 59), None)
        assert is_within_active_hours(time(0, 0), "   ")

    def test_normal_window_boundaries(self):
        window = "09:00-23:00"
        assert is_within_active_hours(time(9, 0), window)  # start inclusive
        assert is_within_active_hours(time(12, 0), window)
        assert is_within_active_hours(time(22, 59), window)
        assert not is_within_active_hours(time(23, 0), window)  # end exclusive
        assert not is_within_active_hours(time(8, 59), window)
        assert not is_within_active_hours(time(0, 0), window)

    def test_cross_midnight_window(self):
        window = "22:00-06:00"
        assert is_within_active_hours(time(22, 0), window)
        assert is_within_active_hours(time(23, 30), window)
        assert is_within_active_hours(time(0, 0), window)
        assert is_within_active_hours(time(5, 59), window)
        assert not is_within_active_hours(time(6, 0), window)  # end exclusive
        assert not is_within_active_hours(time(12, 0), window)
        assert not is_within_active_hours(time(21, 59), window)

    def test_zero_width_window_is_never_active(self):
        for now in (time(9, 0), time(0, 0), time(23, 59)):
            assert not is_within_active_hours(now, "09:00-09:00")

    def test_end_2400_covers_full_day(self):
        assert is_within_active_hours(time(0, 0), "00:00-24:00")
        assert is_within_active_hours(time(23, 59), "00:00-24:00")

    def test_invalid_config_is_permissive(self):
        # Bad schedules never disable heartbeats (OpenClaw port).
        for bad in ("garbage", "9:00-23:00", "25:00-26:00", "09:00", "09:00-23:00-24:00"):
            assert is_within_active_hours(NOON, bad)


# ---------------------------------------------------------------------------
# Guard chain: one test per defer reason, in chain order
# ---------------------------------------------------------------------------
class TestGuardChain:
    def test_admitted_when_all_guards_pass(self):
        assert should_defer_wake(**make_chain()) == (False, "")

    def test_disabled(self):
        assert should_defer_wake(**make_chain(enabled=False)) == (True, "disabled")

    def test_quiet_hours_for_scheduled(self):
        chain = make_chain(active_hours_ok=False, intent="scheduled")
        assert should_defer_wake(**chain) == (True, "quiet-hours")

    def test_quiet_hours_bypassed_for_event_and_manual(self):
        for intent in ("event", "task", "manual", "immediate"):
            chain = make_chain(active_hours_ok=False, intent=intent)
            assert should_defer_wake(**chain) == (False, "")

    def test_preflight_empty_scratch(self):
        chain = make_chain(preflight_ok=False, preflight_reason="empty-scratch")
        assert should_defer_wake(**chain) == (True, "empty-scratch")

    def test_preflight_no_pending_event(self):
        chain = make_chain(preflight_ok=False, preflight_reason="no-pending-event")
        assert should_defer_wake(**chain) == (True, "no-pending-event")

    def test_preflight_reason_defaults_when_missing(self):
        chain = make_chain(preflight_ok=False)
        assert should_defer_wake(**chain) == (True, "empty-scratch")

    def test_busy_requests_in_flight(self):
        assert should_defer_wake(**make_chain(busy=True, intent="event")) == (
            True,
            "requests-in-flight",
        )

    def test_busy_exempt_for_manual_and_immediate(self):
        for intent in ("manual", "immediate"):
            assert should_defer_wake(**make_chain(busy=True, intent=intent)) == (False, "")

    def test_cooldown_not_due_for_scheduled(self):
        chain = make_chain(next_due=1100.0, now=1000.0, intent="scheduled")
        assert should_defer_wake(**chain) == (True, "not-due")

    def test_cooldown_min_spacing_for_event(self):
        cooldown = CooldownTracker(last_run_started_at=990.0)
        chain = make_chain(cooldown=cooldown, now=1000.0, intent="event", next_due=None)
        assert should_defer_wake(**chain) == (True, "min-spacing")

    def test_event_wake_before_due_defers_not_due_with_spacing_floor(self):
        # Port: an event wake before the next due slot defers as "not-due",
        # retryAt = min(nextDue, lastRun + 30s).
        cooldown = CooldownTracker(last_run_started_at=990.0)
        chain = make_chain(cooldown=cooldown, now=1000.0, intent="event", next_due=1200.0)
        assert should_defer_wake(**chain) == (True, "not-due")
        assert _retry_at(chain) == 1020.0

    def test_cooldown_flood(self):
        cooldown = CooldownTracker(
            recent_run_starts=[950.0, 960.0, 970.0, 980.0, 990.0]
        )
        chain = make_chain(cooldown=cooldown, now=1000.0, intent="event")
        assert should_defer_wake(**chain) == (True, "flood")

    def test_chain_order_preflight_before_busy(self):
        # Empty scratch wins over busy: terminal skip, never queued behind work.
        chain = make_chain(preflight_ok=False, preflight_reason="empty-scratch", busy=True)
        assert should_defer_wake(**chain) == (True, "empty-scratch")

    def test_chain_order_busy_before_cooldown(self):
        cooldown = CooldownTracker(last_run_started_at=999.0)
        chain = make_chain(busy=True, cooldown=cooldown, now=1000.0, intent="event")
        assert should_defer_wake(**chain) == (True, "requests-in-flight")


# ---------------------------------------------------------------------------
# CooldownTracker
# ---------------------------------------------------------------------------
class TestCooldownTracker:
    def test_min_spacing_30s(self):
        tracker = CooldownTracker()
        tracker.record_run_start(1000.0)
        deferred, reason, retry_at = tracker.should_defer(intent="event", now=1020.0)
        assert (deferred, reason) == (True, "min-spacing")
        assert retry_at == 1000.0 + DEFAULT_MIN_WAKE_SPACING_S

        deferred, reason, _ = tracker.should_defer(intent="event", now=1030.0)
        assert (deferred, reason) == (False, "")

    def test_scheduled_bypasses_min_spacing(self):
        # Persisted monitor ticks are due-by-construction: a due scheduled
        # tick is admitted even though the last run was 5s ago.
        tracker = CooldownTracker()
        tracker.record_run_start(1000.0)
        deferred, reason, _ = tracker.should_defer(
            intent="scheduled", now=1005.0, next_due=1005.0
        )
        assert (deferred, reason) == (False, "")

    def test_first_event_before_first_tick_is_allowed(self):
        tracker = CooldownTracker()
        deferred, reason, retry_at = tracker.should_defer(intent="event", now=500.0)
        assert (deferred, reason, retry_at) == (False, "", None)

    def test_task_intent_skips_not_due_gate(self):
        tracker = CooldownTracker(last_run_started_at=1000.0)
        deferred, reason, _ = tracker.should_defer(
            intent="task", now=1005.0, next_due=2000.0
        )
        # Within spacing -> still deferred, but as min-spacing (task bypasses
        # the not-due gate so cron tasks are never dropped on cadence).
        assert (deferred, reason) == (True, "min-spacing")

    def test_retained_work_bypasses_not_due_gate(self):
        tracker = CooldownTracker(last_run_started_at=1000.0)
        deferred, reason, retry_at = tracker.should_defer(
            intent="event", now=1005.0, next_due=2000.0, retained_work=True
        )
        assert (deferred, reason) == (True, "min-spacing")
        assert retry_at == 1030.0

    def test_flood_five_runs_in_60s(self):
        tracker = CooldownTracker()
        for i in range(5):
            tracker.record_run_start(1000.0 + i)
        deferred, reason, retry_at = tracker.should_defer(intent="event", now=1004.0)
        assert (deferred, reason) == (True, "flood")
        # retryAt = threshold'th (oldest counted) in-window start + 60s (+1ms port grace)
        assert retry_at == 1000.0 + 60.0 + 0.001

    def test_flood_expires_after_window_slides(self):
        tracker = CooldownTracker()
        for i in range(5):
            tracker.record_run_start(1000.0 + i)
        assert tracker.should_defer(intent="event", now=1004.0)[0] is True
        # 61s after the last start nothing is in the window anymore.
        deferred, reason, _ = tracker.should_defer(intent="event", now=1065.0)
        assert (deferred, reason) == (False, "")

    def test_flood_applies_to_immediate_but_not_manual(self):
        tracker = CooldownTracker()
        for i in range(5):
            tracker.record_run_start(1000.0 + i)
        assert tracker.should_defer(intent="immediate", now=1004.0)[1] == "flood"
        assert tracker.should_defer(intent="manual", now=1004.0) == (False, "", None)

    def test_record_run_start_keeps_threshold_plus_one_ring(self):
        tracker = CooldownTracker()
        for i in range(20):
            tracker.record_run_start(float(i))
        assert len(tracker.recent_run_starts) == DEFAULT_FLOOD_THRESHOLD + 1
        assert tracker.recent_run_starts[-1] == 19.0
        assert tracker.last_run_started_at == 19.0

    def test_deferred_skip_does_not_consume_cooldown(self):
        tracker = CooldownTracker()
        tracker.record_run_start(1000.0)
        before = (tracker.last_run_started_at, list(tracker.recent_run_starts))
        # Repeated deferred evaluations must be side-effect free.
        for now in (1005.0, 1010.0, 1020.0):
            assert tracker.should_defer(intent="event", now=now)[0] is True
        assert (tracker.last_run_started_at, tracker.recent_run_starts) == before

    def test_persistence_roundtrip(self):
        tracker = CooldownTracker(last_run_started_at=42.0, recent_run_starts=[40.0, 41.0, 42.0])
        restored = CooldownTracker.from_dict(tracker.to_dict())
        assert restored.to_dict() == tracker.to_dict()
        deferred, reason, retry_at = restored.should_defer(intent="event", now=50.0)
        assert (deferred, reason, retry_at) == (True, "min-spacing", 72.0)

    def test_from_dict_tolerates_missing_and_trims_ring(self):
        empty = CooldownTracker.from_dict(None)
        assert empty.last_run_started_at is None
        assert empty.recent_run_starts == []
        bloated = CooldownTracker.from_dict(
            {"recent_run_starts": list(range(50)), "last_run_started_at": 49}
        )
        assert len(bloated.recent_run_starts) == DEFAULT_FLOOD_THRESHOLD + 1


# ---------------------------------------------------------------------------
# Retention rules (wake bus contract)
# ---------------------------------------------------------------------------
class TestRetention:
    def test_retryable_reasons_retain(self):
        for reason in ("active-run", "requests-in-flight", "cron-in-progress",
                       "preempted", "channel-not-ready"):
            assert is_retryable_reason(reason)
            assert should_retain_wake("scheduled", reason)

    def test_guard_reasons_retain_only_non_poll_work(self):
        for reason in ("not-due", "min-spacing", "flood"):
            assert not should_retain_wake("scheduled", reason)
            assert not should_retain_wake("scheduled", reason, has_tasks=False)
            assert should_retain_wake("scheduled", reason, has_tasks=True)
            for intent in ("task", "event", "immediate"):
                assert should_retain_wake(intent, reason)

    def test_unknown_reasons_are_terminal(self):
        assert not is_retryable_reason("quiet-hours")
        assert not should_retain_wake("event", "quiet-hours")


# ---------------------------------------------------------------------------
# Preflight cheap-diff
# ---------------------------------------------------------------------------
class TestEffectivelyEmpty:
    def test_missing_scratch_is_not_empty(self):
        assert not is_effectively_empty(None)
        assert not is_effectively_empty(123)  # type: ignore[arg-type]

    def test_scaffolding_only_is_empty(self):
        assert is_effectively_empty("")
        assert is_effectively_empty("\n\n  \n")
        assert is_effectively_empty("## Heading\n### Sub")
        assert is_effectively_empty("```markdown\n```")
        assert is_effectively_empty("- [ ]\n- \n* ")
        assert is_effectively_empty("<!-- pending check -->")
        assert is_effectively_empty("## Title\n<!-- note\nspans lines -->\n- [ ]")

    def test_real_content_is_not_empty(self):
        assert not is_effectively_empty("check deploy status")
        assert not is_effectively_empty("- [ ] ship the release")
        assert not is_effectively_empty("## Heading\nreal note")
