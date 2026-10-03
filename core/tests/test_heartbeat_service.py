"""Full-flow HeartbeatService tests with a fake host (no real model)."""

from __future__ import annotations

import asyncio
import time

import pytest

from atlas.heartbeat import (
    DEFAULT_HEARTBEAT_PROMPT,
    HeartbeatService,
    resolve_delivery_target,
    session_key,
)

FAST_BUS = {"coalesce_s": 0.03, "retry_s": 0.05, "idle_retry_s": 0.1}


def local_noon_epoch(hour: int = 12) -> float:
    """Epoch for the local wall clock at ``hour``:00 today (tz-robust)."""
    return time.mktime((2026, 1, 15, hour, 0, 0, 0, 0, -1))


class FakeHost:
    """HeartbeatHost fake: injectable clock, scripted replies."""

    def __init__(self, now: float = 1_000_000.0):
        self._now = now
        self.default_config = {
            "enabled": True,
            "interval_minutes": 30,
            "active_hours": "",
            "prompt": "",
            "delivery": "owner",
            "isolated_session": True,
        }
        self.configs: dict[str, dict] = {}
        self.busy_agents: set[str] = set()
        self.turns: list[tuple[str, str, str]] = []
        self.replies: dict[str, object] = {}
        self.deliveries: list[tuple[str, str, str]] = []

    # HeartbeatHost protocol -------------------------------------------------
    def get_heartbeat_config(self, agent_id: str) -> dict:
        return dict(self.configs.get(agent_id, self.default_config))

    def is_agent_busy(self, agent_id: str) -> bool:
        return agent_id in self.busy_agents

    async def dispatch_heartbeat_turn(self, agent_id: str, prompt: str, session_key: str):
        self.turns.append((agent_id, prompt, session_key))
        reply = self.replies.get(agent_id, "NO_REPLY")
        if callable(reply):
            reply = reply(agent_id, prompt)
        return reply

    def deliver(self, agent_id: str, text: str, target: str) -> None:
        self.deliveries.append((agent_id, text, target))

    def now(self) -> float:
        return self._now

    # helpers ---------------------------------------------------------------
    def advance(self, seconds: float) -> None:
        self._now += seconds

    def turn_count(self) -> int:
        return len(self.turns)


@pytest.fixture
def host() -> FakeHost:
    return FakeHost()


@pytest.fixture
async def service(host, tmp_path):
    svc = HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)
    yield svc
    await svc.aclose()


def restart(host: FakeHost, tmp_path) -> HeartbeatService:
    """Simulate a process restart: fresh service, same persistence root."""
    return HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)


# ---------------------------------------------------------------------------
# Guard wiring through tick()
# ---------------------------------------------------------------------------
class TestGuardWiring:
    async def test_disabled_agent_skips_without_model(self, host, service):
        host.default_config["enabled"] = False
        result = await service.tick("agent-a")
        assert (result.status, result.reason) == ("skipped", "disabled")
        assert host.turn_count() == 0

    async def test_quiet_hours_skip(self, host, service):
        host.default_config["active_hours"] = "00:30-01:00"
        host.advance(local_noon_epoch() - host.now())  # local noon: outside window
        result = await service.tick("agent-a")
        assert (result.status, result.reason) == ("skipped", "quiet-hours")
        assert host.turn_count() == 0

    async def test_active_hours_pass_inside_window(self, host, service):
        host.default_config["active_hours"] = "09:00-23:00"
        host.advance(local_noon_epoch() - host.now())
        result = await service.tick("agent-a")
        assert result.status == "ran"

    async def test_busy_scheduled_poll_waits_for_next_tick(self, host, service):
        host.busy_agents.add("agent-a")
        result = await service.tick("agent-a")
        assert (result.status, result.reason) == ("skipped", "requests-in-flight")
        assert host.turn_count() == 0

    async def test_not_due_second_tick_skips(self, host, service):
        assert await service.tick("agent-a") is not None
        result = await service.tick("agent-a")
        assert (result.status, result.reason) == ("skipped", "not-due")
        assert host.turn_count() == 1

    async def test_empty_scratch_is_terminal_skip(self, host, service, tmp_path):
        service.set_scratch("agent-a", "## nothing to do\n- [ ]\n```\n```")
        result = await service.tick("agent-a")
        assert (result.status, result.reason) == ("skipped", "empty-scratch")
        assert host.turn_count() == 0

    async def test_missing_scratch_proceeds_first_run(self, host, service):
        assert service.scratch("agent-a") is None
        result = await service.tick("agent-a")
        assert result.status == "ran"
        assert host.turn_count() == 1

    async def test_manual_wake_bypasses_busy_and_cooldown(self, host, service):
        host.busy_agents.add("agent-a")
        result = await service.request_wake(
            "agent-a", intent="manual", source="manual", reason="manual"
        )
        assert result.status == "ran"
        assert host.turn_count() == 1


# ---------------------------------------------------------------------------
# No-change contract
# ---------------------------------------------------------------------------
class TestNoChangeContract:
    async def test_no_change_silent_zero_deliveries(self, host, service):
        host.replies["agent-a"] = "NO_REPLY"
        result = await service.tick("agent-a")
        assert result.status == "ran"
        assert result.outcome.is_no_change
        assert host.deliveries == []
        assert service.last_outcome("agent-a") is None  # never stored

    async def test_no_change_does_not_overwrite_last_outcome(self, host, service):
        host.replies["agent-a"] = "Disk almost full on db-1"
        first = await service.tick("agent-a")
        assert first.delivered
        stored = service.last_outcome("agent-a")
        assert stored["outcome"] == "needs_attention"

        host.replies["agent-a"] = "NO_REPLY"
        host.advance(3600)
        await service.tick("agent-a")
        assert service.last_outcome("agent-a") == stored  # memory, not replay

    async def test_structured_notify_false_is_silent(self, host, service):
        host.replies["agent-a"] = {
            "outcome": "done",
            "notify": False,
            "summary": "backup finished",
        }
        result = await service.tick("agent-a")
        assert result.status == "ran"
        assert host.deliveries == []
        assert service.last_outcome("agent-a")["outcome"] == "done"

    async def test_hearbeat_ok_ack_is_silent(self, host, service):
        host.replies["agent-a"] = "HEARTBEAT_OK"
        result = await service.tick("agent-a")
        assert result.status == "ran"
        assert host.deliveries == []


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
class TestDelivery:
    async def test_legacy_alert_delivers_to_owner(self, host, service):
        host.replies["agent-a"] = "Disk almost full on db-1"
        result = await service.tick("agent-a")
        assert result.delivered
        assert host.deliveries == [("agent-a", "Disk almost full on db-1", "owner")]

    async def test_structured_notification_text_wins(self, host, service):
        host.replies["agent-a"] = {
            "outcome": "needs_attention",
            "notify": True,
            "summary": "long prose report",
            "notificationText": "short pager text",
        }
        result = await service.tick("agent-a")
        assert host.deliveries == [("agent-a", "short pager text", "owner")]

    async def test_delivery_none_never_delivers(self, host, service):
        host.default_config["delivery"] = "none"
        host.replies["agent-a"] = "urgent alert"
        result = await service.tick("agent-a")
        assert result.status == "ran"
        assert host.deliveries == []

    async def test_delivery_channel_target_passthrough(self, host, service):
        host.default_config["delivery"] = "telegram:12345"
        host.replies["agent-a"] = "deploy done, docs updated"
        await service.tick("agent-a")
        assert host.deliveries == [("agent-a", "deploy done, docs updated", "telegram:12345")]

    async def test_resolve_delivery_target(self):
        assert resolve_delivery_target("owner") == "owner"
        assert resolve_delivery_target(None) == "owner"
        assert resolve_delivery_target("") == "owner"
        assert resolve_delivery_target("none") is None
        assert resolve_delivery_target("slack:C123:thread") == "slack:C123:thread"


# ---------------------------------------------------------------------------
# Event wakes through the bus
# ---------------------------------------------------------------------------
class TestEventWakes:
    async def test_event_wake_delivers_exactly_once(self, host, service):
        host.replies["agent-a"] = "Deploy finished, one warning"
        service.push_event("agent-a", "exec finished")
        result = await asyncio.wait_for(service.request_wake("agent-a"), timeout=2)
        assert result.status == "ran"
        assert host.turn_count() == 1
        assert len(host.deliveries) == 1

    async def test_event_consumed_then_no_pending_event(self, host, service):
        service.push_event("agent-a", "exec finished")
        first = await service.tick("agent-a", reason="exec-event")
        assert first.status == "ran"
        second = await service.tick("agent-a", reason="exec-event")
        assert (second.status, second.reason) == ("skipped", "no-pending-event")
        assert host.turn_count() == 1

    async def test_min_spacing_after_run_defers_event(self, host, service):
        await service.tick("agent-a")  # run at t0
        t0 = host.now()
        service.push_event("agent-a", "later event")
        host.advance(10)
        deferred = await service.tick("agent-a", reason="exec-event")
        assert (deferred.status, deferred.reason) == ("skipped", "min-spacing")
        assert deferred.retry_at == pytest.approx(t0 + 30.0)
        assert host.turn_count() == 1  # no model burn for the deferred wake
        host.advance(21)  # past the spacing deadline
        admitted = await service.tick("agent-a", reason="exec-event")
        assert admitted.status == "ran"
        assert host.turn_count() == 2

    async def test_busy_deferred_by_bus_then_retry_succeeds(self, host, service):
        host.replies["agent-a"] = "one build failed"
        service.push_event("agent-a", "exec finished")
        host.busy_agents.add("agent-a")
        pending = asyncio.create_task(service.request_wake("agent-a"))
        await asyncio.sleep(0.06)
        assert host.turn_count() == 0  # busy guard: no model call
        host.busy_agents.clear()
        result = await asyncio.wait_for(pending, timeout=3)
        assert result.status == "ran"
        assert host.turn_count() == 1
        assert len(host.deliveries) == 1


# ---------------------------------------------------------------------------
# Prompt assembly and session isolation
# ---------------------------------------------------------------------------
class TestPromptAndSession:
    async def test_isolated_session_key(self, host, service):
        await service.tick("agent-a")
        assert host.turns[0][2] == "agent:agent-a:heartbeat"
        assert session_key("agent-a") == "agent:agent-a:heartbeat"

    async def test_non_isolated_uses_main_session(self, host, service):
        host.default_config["isolated_session"] = False
        await service.tick("agent-a")
        assert host.turns[0][2] == "agent:agent-a:main"

    async def test_prompt_carries_scratch_and_contract(self, host, service):
        service.set_scratch("agent-a", "watch the deploy rollout")
        await service.tick("agent-a")
        prompt = host.turns[0][1]
        assert "watch the deploy rollout" in prompt
        assert "heartbeat_respond" in prompt
        assert "NO_REPLY" in prompt  # legacy fallback instructions
        assert "no_change" in prompt  # outcome enum contract

    async def test_custom_prompt_used_as_base(self, host, service):
        host.default_config["prompt"] = "Check the release board."
        await service.tick("agent-a")
        assert host.turns[0][1].startswith("Check the release board.")

    async def test_scratch_replacement_applies_to_next_turn(self, host, service):
        host.replies["agent-a"] = {
            "outcome": "progress",
            "notify": False,
            "summary": "watching",
            "scratch": "next: verify rollout finished",
        }
        await service.tick("agent-a")
        assert service.scratch("agent-a") == "next: verify rollout finished"

        host.advance(3600)
        host.replies["agent-a"] = "NO_REPLY"
        await service.tick("agent-a")
        assert "verify rollout finished" in host.turns[1][1]


# ---------------------------------------------------------------------------
# Restart continuation
# ---------------------------------------------------------------------------
class TestRestart:
    async def test_cooldown_survives_restart(self, host, service, tmp_path):
        await service.tick("agent-a")  # run at t0, persisted
        await service.aclose()

        revived = restart(host, tmp_path)
        assert revived.cooldown("agent-a").last_run_started_at == pytest.approx(host.now())
        service_2 = revived
        service_2.push_event("agent-a", "event right after restart")
        host.advance(10)
        deferred = await service_2.tick("agent-a", reason="exec-event")
        assert (deferred.status, deferred.reason) == ("skipped", "min-spacing")
        host.advance(21)
        admitted = await service_2.tick("agent-a", reason="exec-event")
        assert admitted.status == "ran"
        await service_2.aclose()

    async def test_overdue_catchup_runs_exactly_once(self, host, service, tmp_path):
        await service.tick("agent-a")  # t0
        await service.aclose()
        turns_before = host.turn_count()

        host.advance(3 * 3600)  # 6 intervals missed while down
        revived = restart(host, tmp_path)
        assert revived.is_overdue("agent-a")
        first = await revived.tick("agent-a", reason="schedule")  # single catch-up
        assert first.status == "ran"
        assert host.turn_count() == turns_before + 1

        # No slot-by-slot replay: the next tick is a fresh interval away.
        assert not revived.is_overdue("agent-a")
        second = await revived.tick("agent-a", reason="schedule")
        assert (second.status, second.reason) == ("skipped", "not-due")
        assert host.turn_count() == turns_before + 1
        await revived.aclose()

    async def test_scratch_and_outcome_survive_restart(self, host, service, tmp_path):
        host.replies["agent-a"] = {
            "outcome": "blocked",
            "notify": False,
            "summary": "waiting for CI",
            "scratch": "blocked: ci red",
        }
        await service.tick("agent-a")
        await service.aclose()

        revived = restart(host, tmp_path)
        assert revived.scratch("agent-a") == "blocked: ci red"
        assert revived.last_outcome("agent-a")["outcome"] == "blocked"
        assert revived.last_outcome("agent-a")["summary"] == "waiting for CI"
        await revived.aclose()


# ---------------------------------------------------------------------------
# Persistence round trip
# ---------------------------------------------------------------------------
class TestPersistence:
    async def test_state_file_roundtrip(self, host, tmp_path):
        svc = HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)
        host.replies["agent-a"] = "NO_REPLY"
        await svc.tick("agent-a")
        state_path = tmp_path / "state.json"
        assert state_path.exists()
        raw = state_path.read_text(encoding="utf-8")
        assert "agent-a" in raw
        await svc.aclose()

        revived = HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)
        assert revived.next_due_at("agent-a") == pytest.approx(host.now() + 30 * 60)
        assert revived.cooldown("agent-a").recent_run_starts == [pytest.approx(host.now())]
        await revived.aclose()

    async def test_corrupt_state_file_tolerated(self, host, tmp_path):
        (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
        svc = HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)
        assert svc.scratch("agent-a") is None
        result = await svc.tick("agent-a")
        assert result.status == "ran"
        await svc.aclose()

    async def test_multiple_agents_isolated_entries(self, host, tmp_path):
        svc = HeartbeatService(host, root=tmp_path, bus_options=FAST_BUS)
        host.replies["a"] = "alert for a"
        host.replies["b"] = "NO_REPLY"
        await svc.tick("a")
        host.advance(60)
        await svc.tick("b")
        assert svc.last_outcome("a")["summary"] == "alert for a"
        assert svc.last_outcome("b") is None
        await svc.aclose()


# ---------------------------------------------------------------------------
# Engine seam
# ---------------------------------------------------------------------------
class TestEngineSeam:
    async def test_next_due_and_overdue(self, host, service):
        assert service.next_due_at("agent-a") is None  # never ran -> due now
        assert not service.is_overdue("agent-a")
        t0 = host.now()
        await service.tick("agent-a")
        assert service.next_due_at("agent-a") == pytest.approx(t0 + 30 * 60)
        assert not service.is_overdue("agent-a")
        host.advance(30 * 60 + 1)
        assert service.is_overdue("agent-a")

    async def test_disabled_agent_has_no_cadence(self, host, service):
        host.default_config["enabled"] = False
        assert service.next_due_at("agent-a") is None
        assert not service.is_overdue("agent-a")


# ---------------------------------------------------------------------------
# Default prompt constant (ported shape)
# ---------------------------------------------------------------------------
def test_default_prompt_mentions_silent_token():
    assert "NO_REPLY" in DEFAULT_HEARTBEAT_PROMPT
    assert "heartbeat" in DEFAULT_HEARTBEAT_PROMPT.lower()


def test_session_key_format_matches_w1_convention():
    # integration-map section 3: agent:<id>:[channel:[account]:]kind:peer
    assert session_key("architect") == "agent:architect:heartbeat"
    assert session_key("architect", isolated=False) == "agent:architect:main"
