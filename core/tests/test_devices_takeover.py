"""TakeoverStateMachine tests — transition matrix, invariants, feed, handoff cards."""
from __future__ import annotations

from typing import Any

import pytest

from atlas.devices.takeover import (
    AGENT,
    FREE,
    HUMAN,
    ObservationRequiredError,
    TakeoverError,
    TakeoverStateMachine,
)


class FakeClock:
    def __init__(self, start: float = 500.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def machine(clock: FakeClock) -> TakeoverStateMachine:
    return TakeoverStateMachine(device_id="self", clock=clock)


# ---------------------------------------------------------------------------
# Transition matrix
# ---------------------------------------------------------------------------
def test_initial_state_is_free(machine: TakeoverStateMachine) -> None:
    snap = machine.snapshot()
    assert snap["state"] == FREE
    assert snap["holder"] is None
    assert snap["needs_observation"] is False


def test_free_grants_user_and_agent(machine: TakeoverStateMachine) -> None:
    snap = machine.request("agent:coder")
    assert snap["state"] == AGENT
    assert snap["holder"] == "agent:coder"
    assert snap["needs_observation"] is True  # first action must observe
    machine.observe("agent:coder")
    assert machine.release("agent:coder")["state"] == FREE

    snap = machine.request("user")
    assert snap["state"] == HUMAN
    assert snap["holder"] == "user"
    assert snap["needs_observation"] is True


def test_agent_denied_while_human_holds(machine: TakeoverStateMachine) -> None:
    machine.request("user")
    with pytest.raises(TakeoverError):
        machine.request("agent:coder")
    assert machine.state == HUMAN
    denied = [e for e in machine.activity() if e["action"] == "control_denied"]
    assert len(denied) == 1
    assert denied[0]["actor"] == "agent:coder"


def test_agent_denied_while_other_agent_holds(machine: TakeoverStateMachine) -> None:
    machine.request("agent:coder")
    with pytest.raises(TakeoverError):
        machine.request("agent:writer")
    assert machine.state == AGENT
    assert machine.holder == "agent:coder"


def test_human_preempts_agent_and_it_is_recorded(machine: TakeoverStateMachine) -> None:
    machine.request("agent:coder")
    snap = machine.request("user", note="鼠标拿回来了")
    assert snap["state"] == HUMAN
    assert snap["holder"] == "user"
    assert snap["needs_observation"] is True
    events = machine.activity()
    assert any(e["action"] == "control_changed" and "agent:coder" in e["detail"] and "抢占" in e["detail"]
               for e in events)


def test_holder_reassert_changes_nothing(machine: TakeoverStateMachine) -> None:
    machine.request("user")
    machine.observe("user")
    assert machine.needs_observation is False
    snap = machine.request("user")  # re-assert: no control change
    assert snap["state"] == HUMAN
    assert snap["needs_observation"] is False  # flag untouched by re-assert

    machine.release("user")
    machine.request("agent:coder")
    machine.observe("agent:coder")
    snap = machine.request("agent:coder")
    assert snap["state"] == AGENT
    assert snap["needs_observation"] is False


def test_release_matrix(machine: TakeoverStateMachine) -> None:
    with pytest.raises(TakeoverError):  # nothing to release on FREE
        machine.release("user")
    machine.request("agent:coder")
    with pytest.raises(TakeoverError):  # non-holder cannot release
        machine.release("user")
    assert machine.state == AGENT
    snap = machine.release("agent:coder")
    assert snap["state"] == FREE
    assert snap["holder"] is None
    assert snap["needs_observation"] is True  # release is a control change too
    with pytest.raises(TakeoverError):
        machine.request("")  # empty actor rejected


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------
def test_needs_observation_gates_input_actions(machine: TakeoverStateMachine) -> None:
    machine.request("agent:coder")
    with pytest.raises(ObservationRequiredError):
        machine.assert_can_act("agent:coder")  # blocked: change happened, no screenshot yet
    machine.observe("agent:coder")
    machine.assert_can_act("agent:coder")  # fresh observation clears the gate
    machine.request("user")  # control change re-arms the gate
    with pytest.raises(ObservationRequiredError):
        machine.assert_can_act("agent:coder")


def test_observation_is_never_blocked_by_takeover(machine: TakeoverStateMachine) -> None:
    # Observe is legal in FREE, HUMAN and AGENT alike (agent keeps its eyes).
    machine.observe("agent:coder")
    machine.request("user")
    machine.observe("agent:coder")
    with pytest.raises(TakeoverError):  # the request itself is denied…
        machine.request("agent:coder")
    machine.observe("agent:coder")  # …but looking at the screen never is.


def test_no_auto_takeover_without_calls(machine: TakeoverStateMachine, clock: FakeClock) -> None:
    machine.request("user")
    before = machine.activity()
    clock.advance(3600)  # an hour passes; nothing may move by itself
    snap = machine.snapshot()
    assert snap["state"] == HUMAN
    assert snap["holder"] == "user"
    assert machine.activity() == before  # no hidden timers, no phantom events


# ---------------------------------------------------------------------------
# Activity feed (ring buffer)
# ---------------------------------------------------------------------------
def test_activity_event_shape_and_order(machine: TakeoverStateMachine) -> None:
    machine.request("user")
    machine.record_action("agent:coder", "click", "ref=e4")
    events = machine.activity()
    assert [e["action"] for e in events] == ["control_changed", "action:click"]
    for event in events:
        assert set(event) == {"ts", "seq", "actor", "action", "detail"}
        assert isinstance(event["ts"], float) and isinstance(event["seq"], int)
    assert events[-1]["detail"] == "ref=e4"


def test_activity_ring_buffer_is_bounded(clock: FakeClock) -> None:
    machine = TakeoverStateMachine(device_id="self", clock=clock, activity_capacity=3)
    for _ in range(5):
        machine.request("user")
        machine.release("user")
    events = machine.activity()
    assert len(events) == 3
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)  # oldest-first, newest kept


def test_activity_limit_tail(clock: FakeClock) -> None:
    machine = TakeoverStateMachine(device_id="self", clock=clock)
    machine.request("user")
    machine.release("user")
    machine.request("agent:coder")
    tail = machine.activity(limit=2)
    assert len(tail) == 2
    assert tail[-1]["action"] == "control_changed"
    assert tail[-1]["actor"] == "agent:coder"


# ---------------------------------------------------------------------------
# Handoff cards
# ---------------------------------------------------------------------------
def test_handoff_card_lifecycle(machine: TakeoverStateMachine) -> None:
    before = machine.snapshot()["state"]
    card = machine.open_handoff("需要人工确认登录验证码")
    assert card["status"] == "PENDING"
    assert card["note"] == "需要人工确认登录验证码"
    assert machine.snapshot()["state"] == before  # opening a card never moves control

    resolved = machine.resolve_handoff(card["card_id"], "done")
    assert resolved["status"] == "done"
    assert resolved["resolved_ts"] is not None
    with pytest.raises(TakeoverError) as twice:  # terminal: no second resolution
        machine.resolve_handoff(card["card_id"], "give_up")
    assert twice.value.status_code == 409


def test_handoff_give_up_and_filters(machine: TakeoverStateMachine) -> None:
    done = machine.open_handoff("卡片一")
    stuck = machine.open_handoff("卡片二")
    machine.resolve_handoff(done["card_id"], "done")
    machine.resolve_handoff(stuck["card_id"], "give_up")
    assert machine.handoff_cards(status="PENDING") == []
    assert {c["status"] for c in machine.handoff_cards()} == {"done", "give_up"}
    with pytest.raises(TakeoverError) as unknown:
        machine.resolve_handoff("handoff-9999", "done")
    assert unknown.value.status_code == 404
    with pytest.raises(TakeoverError) as bad_resolution:
        machine.resolve_handoff(done["card_id"], "open_panel")
    assert bad_resolution.value.status_code == 422


def test_snapshot_includes_pending_count(clock: FakeClock) -> None:
    machine = TakeoverStateMachine(device_id="self", clock=clock)
    machine.open_handoff("一")
    machine.open_handoff("二")
    card = machine.open_handoff("三")
    machine.resolve_handoff(card["card_id"], "give_up")
    snap: dict[str, Any] = machine.snapshot()
    assert snap["pending_handoff"] == 2
