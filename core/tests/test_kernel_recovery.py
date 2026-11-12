from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from atlas.engine.kernel.model_call import ModelCallError, complete_stream
from atlas.engine.kernel.repair import repair_unpaired_tool_calls, started_call_ids


def call_group(*ids):
    return {"role": "assistant", "content": "Checking", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "local_shell", "arguments": "{}"}}
        for call_id in ids
    ]}


def result(call_id, content="completed"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_recovery_pairs_parallel_results_before_the_new_user_without_mutation():
    history = [call_group("a", "b"), {"role": "user", "content": "Continue"}]
    original = copy.deepcopy(history)
    repaired, receipts = repair_unpaired_tool_calls(history, started_ids={"a", "b"})
    assert [m["role"] for m in repaired] == ["assistant", "tool", "tool", "user"]
    assert [m["tool_call_id"] for m in repaired[1:3]] == ["a", "b"]
    assert [r["state"] for r in receipts] == ["unknown", "unknown"]
    assert history == original
    again, receipts = repair_unpaired_tool_calls(repaired, started_ids={"a", "b"})
    assert again == repaired
    assert receipts == []


def test_missing_dispatch_evidence_never_promises_a_safe_retry():
    repaired, receipts = repair_unpaired_tool_calls([call_group("a")])
    assert receipts[0]["state"] == "unknown"
    assert "safe to retry" not in repaired[-1]["content"].lower()


def test_recovery_keeps_real_result_and_fills_only_missing_parallel_result():
    repaired, receipts = repair_unpaired_tool_calls([
        call_group("a", "b"), result("b", "real output"),
        {"role": "user", "content": "Continue"},
    ])
    assert [m["role"] for m in repaired] == ["assistant", "tool", "tool", "user"]
    assert repaired[2] == result("b", "real output")
    assert [r["tool_call_id"] for r in receipts] == ["a"]


@pytest.mark.parametrize("key", ["display_metadata", "metadata"])
def test_dispatch_evidence_survives_both_session_metadata_formats(tmp_path, key):
    folder = tmp_path / "runs" / "2026-10-18"
    folder.mkdir(parents=True)
    (folder / "prior.jsonl").write_text(
        '\n'.join(['{"event":"tool_start","tool_call_id":"a"}',
                   'null', '[]', '{"partial":',
                   '{"event":"tool_start","tool_call_id":"b"}']), encoding="utf-8",
    )
    assert started_call_ids([{key: {"kernel_run_id": "prior"}}], tmp_path) == {"a", "b"}


def test_already_persisted_misordered_results_are_repaired_without_new_receipts():
    history = [call_group("a", "b"), {"role": "user", "content": "Continue"},
               result("b"), result("a")]
    repaired, receipts = repair_unpaired_tool_calls(history)
    assert [m["role"] for m in repaired] == ["assistant", "tool", "tool", "user"]
    assert [m["tool_call_id"] for m in repaired[1:3]] == ["a", "b"]
    assert receipts == []


def test_legacy_unsafe_recovery_receipts_are_conservative_in_model_view():
    legacy = {**result("a", "The previous turn stopped. It is safe to retry."),
              "display_metadata": {"repair_state": "not_started"}}
    repaired, receipts = repair_unpaired_tool_calls([call_group("a"), legacy])
    assert "safe to retry" not in repaired[1]["content"].lower()
    assert repaired[1]["repair_state"] == "unknown"
    assert legacy["display_metadata"]["repair_state"] == "not_started"
    assert receipts == []


@pytest.mark.parametrize("history", [
    [result("orphan")],
    [call_group("a"), result("a"), result("a", "conflicting output")],
    [call_group("a", "a"), result("a")],
])
def test_ambiguous_tool_histories_fail_locally(history):
    from atlas.engine.kernel.repair import normalize_tool_results

    with pytest.raises(ValueError):
        normalize_tool_results(history)


def test_sequential_rounds_can_reuse_a_provider_tool_id():
    from atlas.engine.kernel.repair import normalize_tool_results

    history = [call_group("a"), result("a", "first"),
               {"role": "user", "content": "Next"}, call_group("a"), result("a", "second")]
    assert normalize_tool_results(history) == history


@pytest.mark.integration
def test_reused_call_id_recovery_persists_current_unknown_result(tmp_path):
    from atlas.engine.session_sync import append_session_message, read_session_model_messages
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "engine"
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("reused", "api_server")
    history = [call_group("a"), result("a", "old successful write"),
               {"role": "user", "content": "Next"}, call_group("a")]
    for message in history:
        append_session_message(home, "reused", message["role"], message["content"],
                               {k: v for k, v in message.items() if k not in {"role", "content"}})
    repaired, receipts = repair_unpaired_tool_calls(history, started_ids={"a"})
    for receipt in receipts:
        append_session_message(home, "reused", "tool", receipt["content"], {
            "tool_call_id": receipt["tool_call_id"], "repair_state": receipt["state"],
        })
    tools = [m for m in read_session_model_messages(home, "reused") if m["role"] == "tool"]
    assert tools[0]["content"] == "old successful write"
    assert tools[1]["content"] == repaired[-1]["content"] == receipts[0]["content"]
    assert "unknown" in tools[1]["content"].lower()
    assert tools[1]["display_metadata"]["repair_state"] == "unknown"


@pytest.mark.parametrize("text", [
    '{"api_key": "other-secret", "password": "hunter2", "access_token": "token-value"}',
    "{'api_key': 'other-secret', 'password': 'hunter2', 'access_token': 'token-value'}",
    "https://example.invalid/?api_key=other-secret&password=hunter2&access_token=token-value",
    "x" * 1480 + '{"password": "hunter2"}',
])
def test_error_details_redact_quoted_fields_and_query_values_before_truncation(text):
    from atlas.engine.kernel.model_call import _provider_error_detail

    detail = _provider_error_detail(ValueError(text))
    assert all(secret not in detail for secret in ("other-secret", "hunter2", "token-value"))
    assert len(detail) <= 1500


@pytest.mark.integration
def test_session_projection_repairs_persisted_history_and_preserves_raw_rows(tmp_path):
    from atlas.engine.session_sync import append_session_message, read_session_model_messages
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "engine"
    with SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("recovered", "api_server")
    for message in [call_group("a", "b"), {"role": "user", "content": "Continue"},
                    result("a"), result("b")]:
        append_session_message(home, "recovered", message["role"], message["content"],
                               {k: v for k, v in message.items() if k not in {"role", "content"}})
    with SessionDB(db_path=home / "state.db") as db:
        before = db.get_messages("recovered")
    projection = read_session_model_messages(home, "recovered")
    assert [m["role"] for m in projection] == ["assistant", "tool", "tool", "user"]
    assert len({m["message_uid"] for m in projection}) == 4
    with SessionDB(db_path=home / "state.db") as db:
        assert db.get_messages("recovered") == before


def routed_agent(stream):
    route = SimpleNamespace(provider="openai", wire_model="test", model="test",
                            key="secret-route-key",
                            base_url="https://provider.invalid/v1", api_mode="chat_completions",
                            model_id="test")
    return SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route), stream=stream,
    ))


@pytest.mark.asyncio
async def test_model_boundary_repairs_existing_results_before_transport():
    offered = []

    def stream(_route, messages, **_kwargs):
        offered.extend(messages)
        return iter([{"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}])

    response = await complete_stream(routed_agent(stream), "test", [
        call_group("a"), {"role": "user", "content": "Continue"}, result("a"),
    ], [], max_retries=0)
    assert response.text == "OK"
    assert [m["role"] for m in offered] == ["assistant", "tool", "user"]


@pytest.mark.asyncio
async def test_incomplete_history_is_rejected_before_transport():
    def stream(*_args, **_kwargs):
        pytest.fail("Invalid history must not reach the provider")

    with pytest.raises(ModelCallError, match="tool") as caught:
        await complete_stream(routed_agent(stream), "test", [call_group("a")], [], max_retries=0)
    assert caught.value.category == "invalid_history"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_http_error_keeps_bounded_redacted_provider_reason_and_request_id():
    def stream(*_args, **_kwargs):
        request = httpx.Request("POST", "https://provider.invalid/v1")
        response = httpx.Response(400, request=request,
                                  headers={"x-request-id": "request-123"}, json={"error": {
                                      "message": "No tool output found; secret-route-key "
                                                 "sk-testcredential123456 "
                                                 "Authorization: Bearer abcdefghijk " + "x" * 3000,
                                      "type": "invalid_request_error",
                                  }})
        response.raise_for_status()

    attempts = []
    with pytest.raises(ModelCallError) as caught:
        await complete_stream(routed_agent(stream), "test", [{"role": "user", "content": "Hi"}],
                              [], max_retries=0, on_attempt=attempts.append)
    detail = str(caught.value)
    assert "No tool output found" in detail
    assert "request-123" in detail
    assert "secret-route-key" not in detail
    assert "sk-testcredential123456" not in detail
    assert "abcdefghijk" not in detail
    assert len(detail) <= 1600
    assert caught.value.status == 400
    assert caught.value.category == "invalid_request"
    assert attempts[0]["detail"] == detail
