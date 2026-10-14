from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atlas.kernel.model_call import complete_stream
from atlas.kernel.stuck import StuckDetector
from atlas.agent.enrichment import AtlasToolBridge, CodeActRuntime
from atlas.tools.local_execution import LocalExecutionRuntime


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 2, 7, 19])
async def test_stream_preserves_tool_arguments_and_repeated_characters(monkeypatch, size):
    arguments = {
        "command": "taskkill /?",
        "code": "import json\nitems = ['bookkeeper', 'taskkill']\nfor item in items:\n"
                "    print(json.dumps({'text': item}, ensure_ascii=False))\nresult = {'items': items}\n",
        "nested": {"items": [{"value": "bookkeeper"}]},
    }
    wire = json.dumps(arguments)
    pieces = [wire[index:index + size] for index in range(0, len(wire), size)]
    chunks = []
    for index, piece in enumerate(pieces):
        chunks.append({"choices": [{"delta": {"tool_calls": [{
            "index": 0,
            "id": "call-1" if index == 0 else "",
            "function": {"name": "local_shell" if index == 0 else "", "arguments": piece},
        }], "reasoning_content": " "}, "finish_reason": None}]})
    chunks.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    auxiliary = ModuleType("agent.auxiliary_client")
    auxiliary.call_llm = lambda **kwargs: iter(chunks)
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary)
    route = SimpleNamespace(provider="openai", wire_model="test", model="test", key="",
                            base_url="http://isolated.invalid", api_mode="chat_completions",
                            model_id="test")
    agent = SimpleNamespace(_model_router=SimpleNamespace(resolve=AsyncMock(return_value=route)))
    events = []
    result = await complete_stream(agent, "test", [], [], max_retries=0, on_event=events.append)
    assert result.tool_calls == [{"id": "call-1", "name": "local_shell", "args": arguments}]
    assert "".join(event["arguments"] for event in events if event["type"] == "tool_call_delta") == wire
    assert "".join(event["delta"] for event in events if event["type"] == "reasoning_delta") == " " * len(pieces)
    local = LocalExecutionRuntime()
    try:
        executed = await CodeActRuntime(AtlasToolBridge(local=local), timeout=10).execute(
            result.tool_calls[0]["args"]["code"],
        )
        assert executed["exit_code"] == 0, executed["stderr"]
        assert executed["result"] == {"items": ["bookkeeper", "taskkill"]}
    finally:
        await local.shutdown()


def test_repeated_errors_ignore_execution_identity_in_text():
    detector = StuckDetector()
    for index in range(3):
        detector.observe_tool("local_shell", {"command": "taskill /?"}, {
            "is_error": True,
            "content": [{"type": "text", "text": "'taskill' is not recognized.\nFull output: D:/logs/run-"
                        + str(index) + ".log\nProcess: process-" + str(index) + " (failed)"}],
            "data": {"execution_id": str(index), "pid": index, "duration_seconds": index,
                     "output": "'taskill' is not recognized.", "output_ref": str(index)},
        })
    decision = detector.check()
    assert decision is not None
    assert decision.reason == "repeated_errors"


def test_changed_arguments_and_distinct_errors_are_not_a_repeat_loop():
    detector = StuckDetector()
    for index in range(3):
        detector.observe_tool("local_shell", {"command": str(index)}, {
            "is_error": True, "content": "error", "data": {"execution_id": str(index)},
        })
    assert detector.check() is None
    detector = StuckDetector()
    for index in range(3):
        detector.observe_tool("local_shell", {"command": "same"}, {
            "is_error": True, "content": "error " + str(index),
        })
    assert detector.check() is None


def test_repeated_error_halts_only_after_corrective_nudge_is_ignored():
    detector = StuckDetector()
    for index in range(3):
        detector.observe_tool("local_shell", {"command": "same"}, {
            "is_error": True, "content": "error", "data": {"execution_id": str(index)},
        })
    assert detector.check().action == "nudge"
    assert detector.check() is None
    detector.observe_tool("local_shell", {"command": "same"}, {
        "is_error": True, "content": "error", "data": {"execution_id": "next"},
    })
    assert detector.check().action == "halt"


@pytest.mark.asyncio
async def test_writes_work_without_workspace_and_utf8_pages_never_split(tmp_path):
    runtime = LocalExecutionRuntime()
    target = tmp_path / "written.txt"
    result = await runtime.call_tool("local_file", {
        "action": "write", "path": str(target), "cwd": str(tmp_path), "content": "test",
    })
    assert not result["is_error"]
    assert target.read_text() == "test"
    result = await runtime.call_tool("local_file", {
        "action": "write", "path": str(tmp_path), "content": "x", "_atlas_workspace": str(tmp_path),
    })
    assert result["is_error"]  # the workspace root itself stays protected
    chinese = tmp_path / "zh.txt"
    chinese.write_bytes("你好世界".encode("utf-8"))
    result = await runtime.call_tool("local_file", {
        "action": "read", "path": str(chinese), "byte_offset": 0, "byte_limit": 4,
    })
    assert not result["is_error"]
    assert "你" in str(result) and "\ufffd" not in str(result)
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_incomplete_arguments_become_a_call_error_without_a_retry(monkeypatch):
    """FEEL-1: a broken call is answered on its own; the response is not thrown away."""
    def chunk(text, arguments, finished=False):
        return {"choices": [{"delta": {"content": text, "tool_calls": [{
            "index": 0, "id": "call-1", "function": {"name": "local_shell", "arguments": arguments},
        }]}, "finish_reason": "tool_calls" if finished else None}]}

    attempts = iter([
        [chunk("Hello ", '{"command":', True)],
        [chunk("Hello world", '{"command":"taskkill /?"}', True)],
    ])
    auxiliary = ModuleType("agent.auxiliary_client")
    auxiliary.call_llm = lambda **kwargs: iter(next(attempts))
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary)
    route = SimpleNamespace(provider="openai", wire_model="test", model="test", key="",
                            base_url="http://isolated.invalid", api_mode="chat_completions",
                            model_id="test")
    agent = SimpleNamespace(_model_router=SimpleNamespace(resolve=AsyncMock(return_value=route)))
    text = []
    result = await complete_stream(agent, "test", [], [], max_retries=1, on_text=text.append)
    assert result.attempts == 1
    [call] = result.tool_calls
    assert call["id"] == "call-1" and call["name"] == "local_shell" and call["args"] == {}
    assert "not valid JSON" in call["arg_error"]
    assert result.text == "Hello "


def test_tool_call_arguments_repair_only_closed_objects():
    from atlas.kernel.model_call import _ToolDelta, _tool_calls

    calls = _tool_calls({
        0: _ToolDelta("a", "write", '{"path": "y", "content": "ok",}'),
        1: _ToolDelta("b", "write", '{"path": "y", "content": "half a fi'),
    })
    assert calls[0]["args"] == {"path": "y", "content": "ok"} and calls[0]["args_repaired"]
    assert calls[1]["args"] == {} and "arg_error" in calls[1]
    [cut] = _tool_calls({0: _ToolDelta("c", "write", '{"path": "y"}')}, truncated=True)
    assert cut["args"] == {"path": "y"}  # complete JSON is kept even when the output hit the limit
    [cut] = _tool_calls({0: _ToolDelta("c", "write", '{"path": "y", "con')}, truncated=True)
    assert "output length limit" in cut["arg_error"]


def test_overlap_merge_preserves_boundary_character_repetition():
    from atlas.kernel.model_call import _overlap_merge

    assert _overlap_merge("asci", "i") == "ascii"
    assert _overlap_merge("fast", "train") == "fasttrain"
    assert _overlap_merge('foo"', '"bar') == 'foo""bar'
    assert _overlap_merge("a=", "=b") == "a==b"
    assert _overlap_merge("Hello world from the stream", "from the stream and more") == "Hello world from the stream and more"


def test_classify_error_extracts_http_429_from_upstream_message():
    from atlas.kernel.model_call import classify_error

    exc = RuntimeError("ModelCallError: Upstream API error (HTTP 429)")
    category, retryable, status = classify_error(exc)
    assert category == "rate_limit"
    assert retryable is True
    assert status == 429

