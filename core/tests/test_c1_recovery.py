import pytest

from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import DropMidStream, Error, Hang, Text


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
    assert "recovered answer" in events[-1]["result"]["final_response"]
    assert len(requests) >= 2
    if isinstance(fault, (Text, DropMidStream)):
        assert any(event["type"] == "run.recovery.notice" for event in events)


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
    calls = {call["id"] for row in messages for call in row.get("tool_calls", [])}
    results = {row["tool_call_id"] for row in messages if row["role"] == "tool"}
    assert calls <= results
    assert any("read the fixture" in str(row.get("content", "")) for row in messages)
    assert events[-1]["result"]["final_response"] == "resumed"
