import pytest

from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import DropMidStream, Error, Hang, Text


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [
    Error(429, "scripted rate limit", retry_after=0.01),
    Error(500, "scripted server error"),
    Hang(seconds=0.05),
    Text(""),
    Text("partial answer", finish_reason="length"),
    DropMidStream("broken stream to continue", after_chars=8),
])
async def test_atlas_recovers_provider_fault_and_finishes(tmp_path, monkeypatch, fault):
    events, requests, _ = await run_script(tmp_path, monkeypatch, [fault, Text("recovered answer")], hermes_config="api_max_retries: 3")
    result = next((event for event in events if event.get("type") == "atlas.result"), None)
    assert result is not None, [
        {"type": event.get("type"), "error": event.get("error"), "status": event.get("status")}
        for event in events
    ]
    assert "recovered answer" in result["result"]["final_response"]
    assert len(requests) >= 2
    if isinstance(fault, (Text, DropMidStream)):
        assert any(event["type"] in {"run.recovery.notice", "message.rollback"} for event in events)
    if isinstance(fault, DropMidStream):
        assert any(event["type"] == "message.rollback" for event in events)
        assert any(event["type"] == "model_attempt_committed" for event in events)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_repairs_missing_tool_result_and_keeps_completed_history(tmp_path, monkeypatch):
    history = [
        {"role": "user", "content": "read the fixture"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "lost-result", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
        ]},
    ]
    events, requests, _ = await run_script(tmp_path, monkeypatch, [Text("resumed")], history=history)
    messages = requests[0]["messages"]
    from atlas.engine.state.atlas_state import SessionDB
    with SessionDB(db_path=tmp_path / "engine" / "state.db") as db:
        persisted = db.get_messages_as_conversation("review-session")
    calls = {call["id"] for row in messages for call in row.get("tool_calls", [])}
    results = {row["tool_call_id"] for row in messages if row["role"] == "tool"}
    assert calls <= results
    assert any("read the fixture" in str(row.get("content", "")) for row in messages), (
        [
            {"role": row.get("role"), "content": row.get("content"),
             "tool_call_ids": [call.get("id") for call in row.get("tool_calls", [])],
             "tool_call_id": row.get("tool_call_id")}
            for row in messages
        ],
        [
            {"role": row.get("role"), "content": row.get("content"),
             "metadata": row.get("metadata")}
            for row in persisted
        ],
    )
    assert any(row.get("role") == "user" and row.get("content") == "read the fixture"
               for row in persisted)
    assert any(row.get("role") == "tool" and row.get("tool_call_id") == "lost-result"
               and (row.get("repair_state") == "unknown"
                    or (row.get("display_metadata") or {}).get("repair_state") == "unknown")
               for row in persisted), persisted
    result = next((event for event in events if event.get("type") == "atlas.result"), None)
    assert result is not None, [
        {"type": event.get("type"), "error": event.get("error"), "status": event.get("status")}
        for event in events
    ]
    assert result["result"]["final_response"] == "resumed"
