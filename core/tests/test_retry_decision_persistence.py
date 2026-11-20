import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fakes.fake_llm_provider import DropMidStream, FakeLLMServer, Text, write_atlas_home
from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.test_engine_model_wiring import _ProviderKeyManager


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _runtime_for(tmp_path, monkeypatch, fake, conversation_id):
    home = tmp_path / "engine"
    write_atlas_home(home, fake.base_url)
    monkeypatch.setenv("HERMES_HOME", str(home))
    manager = _ProviderKeyManager(fake.base_url, current="fake-model")
    manager._models = [{
        "id": "fake-model", "provider": "atlas-fixture", "atlas_provider": "atlas-fixture",
        "litellm_model": "openai/fake-model", "native_model": "fake-model",
        "max_output_tokens": 256,
    }]
    manager._find_model = lambda _model: manager._models[0]
    mcp = MagicMock()
    mcp.get_tools_for_llm.return_value = []
    mcp.list_tools.return_value = []
    mcp.tool_count = 0
    local = LocalExecutionRuntime()
    agent = AgentOrchestrator(manager, MagicMock(), mcp_client=mcp, local_execution=local)
    context = AgentRunContext(
        cancel_event=asyncio.Event(), run_id=f"run-{conversation_id}",
        conversation_id=conversation_id, workspace=str(tmp_path), permission_mode="full_access",
    )
    runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
    return runtime, agent, context, local


async def _run(runtime, agent, context, conversation_id, workspace):
    return [event async for event in runtime.run_turn(
        message="exercise durable retry decision", conversation_id=conversation_id,
        workspace=str(workspace), history=[], atlas_agent=agent, atlas_context=context,
    )]


def _attempt_events(runtime, conversation_id):
    from hermes_state import SessionDB

    with SessionDB(db_path=runtime.home / "state.db") as db:
        return [
            item for item in db.list_session_events(conversation_id, after_seq=0, limit=1000)
            if item.get("event_type") == "model/attempt"
        ]


async def _cleanup(runtime, local):
    await runtime.aclose()
    await local.shutdown()


async def test_retry_decision_and_budget_are_durable_before_second_request(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "2")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())
    runtime_ref = {}
    observed_before_second = []

    def responder(_request):
        runtime = runtime_ref["runtime"]
        if len(observed_before_second) == 0:
            observed_before_second.append(None)
            return DropMidStream("OLD answer", after_chars=3)
        observed_before_second[0] = _attempt_events(runtime, "retry-before-second")
        return Text("NEW answer")

    with FakeLLMServer(responder) as fake:
        runtime, agent, context, local = _runtime_for(
            tmp_path, monkeypatch, fake, "retry-before-second",
        )
        runtime_ref["runtime"] = runtime
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        try:
            events = await _run(runtime, agent, context, "retry-before-second", tmp_path)
            attempts = _attempt_events(runtime, "retry-before-second")
            assert len(fake.main_requests()) == 2
            assert observed_before_second[0], "retry decision was not durable before request 2"
            discarded = next(
                item["payload"] for item in observed_before_second[0]
                if item["payload"].get("status") == "discarded"
            )
            assert discarded["retry"] is True
            assert discarded["retry_kind"] == "connection"
            assert discarded["retry_delay_s"] >= 0
            assert discarded["retry_budget_attempts_used_after_decision"] == 1
            assert discarded["retry_budget_attempts_remaining"] == 1
            assert discarded["retry_budget_wait_s_used_after_decision"] == pytest.approx(
                discarded["retry_delay_s"], abs=0.001,
            )
            persisted_discarded = next(
                item["payload"] for item in attempts
                if item["payload"].get("status") == "discarded"
            )
            assert persisted_discarded == discarded
            result = next(event["result"] for event in events if event["type"] == "atlas.result")
            assert result["final_response"] == "NEW answer"
        finally:
            await _cleanup(runtime, local)


async def test_retry_budget_exhaustion_is_persisted_and_sends_no_second_request(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "0")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())
    with FakeLLMServer([DropMidStream("OLD answer", after_chars=3)]) as fake:
        runtime, agent, context, local = _runtime_for(
            tmp_path, monkeypatch, fake, "retry-budget-exhausted",
        )
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        try:
            events = await _run(runtime, agent, context, "retry-budget-exhausted", tmp_path)
            attempts = _attempt_events(runtime, "retry-budget-exhausted")
            assert len(fake.main_requests()) == 1
            discarded = next(
                item["payload"] for item in attempts
                if item["payload"].get("status") == "discarded"
            )
            assert discarded["retry"] is False
            assert discarded["retry_denied_reason"] == "attempt_budget_exhausted"
            assert discarded["retry_budget_attempts_used_after_decision"] == 0
            assert discarded["retry_budget_attempts_remaining"] == 0
            assert not any(
                event.get("type") == "atlas.result"
                and event.get("result", {}).get("final_response") == "NEW answer"
                for event in events
            )
        finally:
            await _cleanup(runtime, local)


async def test_retry_audit_write_failure_fails_closed_before_second_request(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "2")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())
    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3), Text("NEW answer"),
    ]) as fake:
        runtime, agent, context, local = _runtime_for(
            tmp_path, monkeypatch, fake, "retry-audit-write-failure",
        )
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])

        from atlas.engine.session_sync import append_session_event as append_original

        def fail_discarded_audit(_home, _conversation_id, event_type, payload):
            if event_type == "model/attempt" and payload.get("status") == "discarded":
                raise OSError("fixture audit write failure")
            return append_original(_home, _conversation_id, event_type, payload)

        monkeypatch.setattr("atlas.engine.session_sync.append_session_event", fail_discarded_audit)
        try:
            events = await _run(runtime, agent, context, "retry-audit-write-failure", tmp_path)
            assert len(fake.main_requests()) == 1
            assert not any(
                event.get("type") == "atlas.result"
                and event.get("result", {}).get("final_response") == "NEW answer"
                for event in events
            )
            assert any(event.get("type") == "error" for event in events)
        finally:
            await _cleanup(runtime, local)
