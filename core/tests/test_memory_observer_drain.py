from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from atlas.memory.observer_drain import MemoryObserverDrain


@dataclass
class _Batch:
    batch_id: str
    payload: dict[str, Any] | None


class _Observer:
    def __init__(self, sessions: list[str], batches: list[_Batch | None]) -> None:
        self.sessions = sessions
        self.batches = batches
        self.resumed: list[tuple[str, bool]] = []
        self.acked: list[str] = []
        self.persisted_end_sessions: set[str] = set()

    def pending_sessions(self) -> list[str]:
        return self.sessions

    def mark_session_ended(self, session_id: str) -> None:
        self.persisted_end_sessions.add(session_id)

    async def resume(self, session_id: str, *, context=None, session_ended=False):
        self.resumed.append((
            session_id, session_ended or session_id in self.persisted_end_sessions,
        ))
        return self.batches.pop(0)

    async def ack_batch(self, batch_id: str):
        self.acked.append(batch_id)
        return self.batches.pop(0)


class _Facade:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def default_context(self, **kwargs):
        return kwargs

    async def observe_batch(self, payload):
        self.calls.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _ack(payload: dict[str, Any]) -> dict[str, Any]:
    observations = payload["observations"]
    return {
        "accepted": len(observations),
        "receipts": [
            {"source_event_id": item["source_event_id"]} for item in observations
        ],
    }


@pytest.mark.asyncio
async def test_session_switch_ends_previous_session_only() -> None:
    observer = _Observer([], [None])
    drain = MemoryObserverDrain(observer, _Facade([]))

    drain.note_session_started("session-a")
    drain.note_session_started("session-a")
    assert drain.end_sessions == set()
    drain.note_session_started("session-b")
    assert drain.end_sessions == {"session-a"}
    assert observer.persisted_end_sessions == {"session-a"}

    await drain.drain_once()

    assert observer.resumed == [("session-a", True)]
    assert drain.end_sessions == set()


@pytest.mark.asyncio
async def test_end_signal_survives_drain_delay_and_observer_restart() -> None:
    observer = _Observer([], [None])
    drain = MemoryObserverDrain(observer, _Facade([]))
    drain.note_session_started("session-a")
    drain.end_active_session()

    # A newly restored observer sees the same durable session flush flag after
    # its capture source receives ACK and becomes visible in pending_sessions.
    restarted = _Observer(["session-a"], [None])
    restarted.persisted_end_sessions = set(observer.persisted_end_sessions)
    await MemoryObserverDrain(restarted, _Facade([])).drain_once()

    assert restarted.persisted_end_sessions == {"session-a"}
    assert restarted.resumed == [("session-a", True)]


@pytest.mark.asyncio
async def test_payloadless_batch_skips_http_but_is_acked() -> None:
    observer = _Observer(["session-a"], [_Batch("empty", None)])
    facade = _Facade([])

    await MemoryObserverDrain(observer, facade).drain_once()

    assert facade.calls == []
    assert observer.acked == ["empty"]


@pytest.mark.asyncio
async def test_http_ack_must_cover_every_derived_observation() -> None:
    payload = {"observations": [
        {"source_event_id": "derived-1"}, {"source_event_id": "derived-2"},
    ]}
    observer = _Observer(["session-a"], [_Batch("batch-a", payload)])
    facade = _Facade([{"accepted": 2, "receipts": [
        {"source_event_id": "derived-1"}, {"source_event_id": "wrong-id"},
    ]}])

    await MemoryObserverDrain(observer, facade).drain_once()

    assert facade.calls == [payload]
    assert observer.acked == []


@pytest.mark.asyncio
async def test_http_failure_keeps_model_result_pending_for_next_tick() -> None:
    payload = {"observations": [{"source_event_id": "derived-1"}]}
    pending = _Batch("batch-a", payload)
    observer = _Observer(["session-a"], [pending])
    facade = _Facade([RuntimeError("offline"), _ack(payload)])
    drain = MemoryObserverDrain(observer, facade)

    await drain.drain_once()
    assert observer.acked == []

    observer.sessions = ["session-a"]
    observer.batches = [pending]
    await drain.drain_once()

    assert facade.calls == [payload, payload]
    assert observer.acked == ["batch-a"]


@pytest.mark.asyncio
async def test_ack_drains_next_batch_only_after_previous_http_success() -> None:
    first = {"observations": [{"source_event_id": "derived-1"}]}
    second = {"observations": [{"source_event_id": "derived-2"}]}
    observer = _Observer(
        ["session-a"], [_Batch("batch-a", first), _Batch("batch-b", second), None],
    )
    facade = _Facade([_ack(first), _ack(second)])

    await MemoryObserverDrain(observer, facade).drain_once()

    assert observer.acked == ["batch-a", "batch-b"]
    assert facade.calls == [first, second]
