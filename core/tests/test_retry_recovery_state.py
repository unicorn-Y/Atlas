import asyncio
from unittest.mock import AsyncMock

import pytest

from tests.fakes.fake_llm_provider import DropMidStream, FakeLLMServer, Hang, Text
from tests.test_retry_decision_persistence import (
    _attempt_events, _cleanup, _run, _runtime_for,
)
from atlas.engine.session_sync import classify_retry_recovery


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_reopened_session_records_started_discarded_started_committed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "2")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())
    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3), Text("NEW answer"),
    ]) as fake:
        runtime, agent, context, local = _runtime_for(
            tmp_path, monkeypatch, fake, "retry-recovery-settled",
        )
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        try:
            events = await _run(runtime, agent, context, "retry-recovery-settled", tmp_path)
            attempts = _attempt_events(runtime, "retry-recovery-settled")
            assert [item["payload"]["status"] for item in attempts] == [
                "started", "discarded", "started", "committed",
            ]
            assert len(fake.main_requests()) == 2
            assert next(event for event in events if event["type"] == "atlas.result")
        finally:
            await _cleanup(runtime, local)


async def test_reopened_session_classifies_started_retry_as_unknown_without_replaying(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "2")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())
    conversation_id = "retry-recovery-unknown"
    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3), Hang(seconds=30), Text("must not replay"),
    ]) as fake:
        runtime, agent, context, local = _runtime_for(
            tmp_path, monkeypatch, fake, conversation_id,
        )
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        turn = asyncio.create_task(_run(runtime, agent, context, conversation_id, tmp_path))
        try:
            await asyncio.to_thread(fake.wait_for_requests, 2, timeout=10)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(turn, timeout=5)
            attempts = _attempt_events(runtime, conversation_id)
            assert [item["payload"]["status"] for item in attempts] == [
                "started", "discarded", "started", "discarded",
            ]
            assert attempts[-1]["payload"]["category"] == "cancelled"
            from atlas.engine import session_sync

            recovery = session_sync.classify_retry_recovery(
                attempts, run_id=context.run_id,
            )
            assert recovery["state"] == "outcome_unknown"
            assert recovery["attempt_id"] == attempts[-1]["payload"]["attempt_id"]
            assert recovery["outcome_reason"] == "cancelled_locally"
            assert recovery["attempt_status"] == "discarded"
            assert recovery["retry_budget_attempts_remaining"] == 1
            assert len(fake.main_requests()) == 2
        finally:
            if not turn.done():
                turn.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(turn, timeout=5)
            await _cleanup(runtime, local)


async def test_retry_recovery_classifier_keeps_unknown_status_unsettled():
    recovery = classify_retry_recovery([{
        "seq": 10, "event_type": "model/attempt",
        "payload": {"run_id": "run-1", "attempt_id": "attempt-x", "attempt": 1,
                    "status": "future-status"},
    }], run_id="run-1")

    assert recovery["state"] == "state_unknown"
    assert recovery["attempt_status"] == "future-status"
