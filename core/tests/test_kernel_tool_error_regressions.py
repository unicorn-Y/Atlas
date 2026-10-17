from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace
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
    route = SimpleNamespace(provider="openai", wire_model="test", model="test", key="",
                            base_url="http://isolated.invalid", api_mode="chat_completions",
                            model_id="test")
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route), stream=lambda *_args, **_kwargs: iter(chunks),
    ))
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
    route = SimpleNamespace(provider="openai", wire_model="test", model="test", key="",
                            base_url="http://isolated.invalid", api_mode="chat_completions",
                            model_id="test")
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route), stream=lambda *_args, **_kwargs: iter(next(attempts)),
    ))
    text = []
    result = await complete_stream(agent, "test", [], [], max_retries=1, on_text=text.append)
    assert result.attempts == 1
    [call] = result.tool_calls
    assert call["id"] == "call-1" and call["name"] == "local_shell" and call["args"] == {}
    assert "not valid JSON" in call["arg_error"]
    assert result.text == "Hello "


def _model_call_fixture(streams):
    from unittest.mock import AsyncMock

    route = SimpleNamespace(provider="provider-a", wire_model="wire-a", model="wire-a", key="",
                            base_url="http://127.0.0.1", api_mode="chat_completions",
                            model_id="model-a")
    router = SimpleNamespace(resolve=AsyncMock(return_value=route), calls=0)

    def stream(*_args, **_kwargs):
        index = router.calls
        router.calls += 1
        item = streams[index]
        if isinstance(item, BaseException):
            raise item
        def chunks():
            for chunk in item:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk
        return chunks()

    router.stream = stream
    return SimpleNamespace(_model_router=router), router


def _finished(text="ok"):
    return [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]}]


def _http_error(status, message="provider error", headers=None):
    error = RuntimeError(message)
    error.response = SimpleNamespace(status_code=status, headers=headers or {})
    return error


@pytest.mark.asyncio
async def test_model_call_retries_one_connection_failure_on_the_same_model(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    agent, router = _model_call_fixture([RuntimeError("connection reset"), _finished()])
    result = await complete_stream(agent, "model-a", [], [], max_retries=20)
    assert result.model == "model-a" and result.attempts == 2
    assert router.calls == 2


@pytest.mark.asyncio
async def test_model_call_caps_503_at_three_requests_and_preserves_error_fields(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    agent, router = _model_call_fixture([_http_error(503, "upstream unavailable") for _ in range(3)])
    with pytest.raises(model_call.ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=20)
    assert router.calls == 3
    assert raised.value.model == "model-a" and raised.value.provider == "provider-a"
    assert raised.value.status == 503 and raised.value.attempts == 3
    assert "upstream unavailable" in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 409, 413, 422, 425, 501, 505])
async def test_permanent_model_errors_are_not_retried(monkeypatch, status):
    from atlas.kernel import model_call

    message = "connection timeout" if status in {400, 409, 422, 425, 501, 505} else "provider error"
    agent, router = _model_call_fixture([_http_error(status, message), _finished()])
    with pytest.raises(model_call.ModelCallError):
        await complete_stream(agent, "model-a", [], [], max_retries=2,
                              fallback_models=["model-b", "deepseek-v4.1-flash"])
    assert router.calls == 1
    assert [call.args[0] for call in agent._model_router.resolve.await_args_list] == ["model-a"]


@pytest.mark.asyncio
async def test_route_failure_reports_selected_model_without_sending_request():
    from atlas.kernel.model_call import ModelCallError

    router = SimpleNamespace(resolve=AsyncMock(side_effect=RuntimeError("unknown model")))
    agent = SimpleNamespace(_model_router=router)
    with pytest.raises(ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=2)
    assert raised.value.model == "model-a"
    assert raised.value.category == "model_not_found" and raised.value.attempts == 0


@pytest.mark.asyncio
async def test_route_authentication_failure_preserves_provider_and_status():
    from atlas.kernel.model_call import ModelCallError

    error = _http_error(401, "invalid credential")
    error.provider = "provider-a"
    router = SimpleNamespace(resolve=AsyncMock(side_effect=error))
    agent = SimpleNamespace(_model_router=router)
    with pytest.raises(ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=2)
    assert raised.value.model == "model-a" and raised.value.provider == "provider-a"
    assert raised.value.category == "authentication" and raised.value.status == 401
    assert raised.value.attempts == 0


@pytest.mark.asyncio
async def test_invalid_tool_call_index_is_not_retried(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    malformed = [{"choices": [{"delta": {"tool_calls": [{"index": "invalid"}]},
                               "finish_reason": None}]}]
    agent, router = _model_call_fixture([malformed, _finished()])
    with pytest.raises(model_call.ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=2)
    assert raised.value.category == "malformed_response"
    assert router.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [503, 529])
async def test_long_retry_after_on_server_errors_stops_without_waiting(monkeypatch, status):
    from atlas.kernel import model_call

    wait = AsyncMock()
    monkeypatch.setattr(model_call, "_wait_for_retry", wait)
    agent, router = _model_call_fixture([_http_error(status, headers={"Retry-After": "30"}), _finished()])
    with pytest.raises(model_call.ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=2)
    assert router.calls == 1 and wait.await_count == 0
    assert raised.value.retry_after_s == 30


@pytest.mark.asyncio
async def test_error_card_detail_keeps_response_reason_and_redacts_secrets():
    from atlas.kernel import model_call

    error = _http_error(503, "HTTP 503")
    error.response.text = '{"error":{"message":"upstream maintenance","api_key":"superSecretToken123"}}'
    detail = model_call._safe_error_detail(error)
    assert "upstream maintenance" in detail
    assert "superSecretToken123" not in detail


def test_httpx_stream_error_captures_only_bounded_response_body():
    import httpx
    from atlas.models.router import _ERROR_BODY_MAX_BYTES, _raise_for_status_with_body

    body = b'{"error":"upstream maintenance"}' + (b"x" * (_ERROR_BODY_MAX_BYTES * 2))
    response = httpx.Response(503, request=httpx.Request("POST", "https://example.invalid"),
                              stream=httpx.ByteStream(body))
    with pytest.raises(httpx.HTTPStatusError) as raised:
        _raise_for_status_with_body(response)
    captured = raised.value._atlas_response_body
    assert "upstream maintenance" in captured
    assert len(captured.encode("utf-8")) <= _ERROR_BODY_MAX_BYTES
    from atlas.kernel.model_call import _safe_error_detail, classify_error
    assert classify_error(raised.value) == ("provider", True, 503)
    assert "upstream maintenance" in _safe_error_detail(raised.value)


@pytest.mark.asyncio
async def test_empty_model_selection_fails_without_resolving_a_route():
    from atlas.kernel.model_call import ModelCallError

    router = SimpleNamespace(resolve=AsyncMock())
    with pytest.raises(ModelCallError) as raised:
        await complete_stream(SimpleNamespace(_model_router=router), "", [], [])
    assert raised.value.category == "route" and raised.value.model == ""
    assert raised.value.attempts == 0 and router.resolve.await_count == 0


@pytest.mark.asyncio
async def test_rate_limit_retry_respects_retry_after_cutoff(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    small, small_router = _model_call_fixture([
        _http_error(429, headers={"Retry-After": "2", "x-request-id": "provider-req-1"}), _finished(),
    ])
    result = await complete_stream(small, "model-a", [], [], max_retries=2)
    assert result.attempts == 2 and small_router.calls == 2

    large, large_router = _model_call_fixture([_http_error(429, headers={
        "Retry-After": "16", "x-request-id": "provider-req-16",
    }), _finished()])
    with pytest.raises(model_call.ModelCallError) as raised:
        await complete_stream(large, "model-a", [], [], max_retries=2)
    assert large_router.calls == 1
    assert raised.value.retry_after_s == 16
    assert raised.value.request_id == "provider-req-16"


@pytest.mark.asyncio
async def test_partial_stream_failure_is_not_reissued(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    partial = [{"choices": [{"delta": {"content": "seen"}, "finish_reason": None}]},
               RuntimeError("connection reset")]
    agent, router = _model_call_fixture([partial, _finished("duplicate")])
    received = []
    with pytest.raises(model_call.ModelCallError) as raised:
        await complete_stream(agent, "model-a", [], [], max_retries=2, on_text=received.append)
    assert router.calls == 1 and "".join(received) == "seen"
    assert raised.value.attempts == 1


@pytest.mark.asyncio
async def test_tool_delta_failure_is_not_reissued(monkeypatch):
    from atlas.kernel import model_call

    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())
    partial = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1",
        "function": {"name": "write_file", "arguments": "{\"path\":"}}]}, "finish_reason": None}]},
        RuntimeError("connection reset")]
    agent, router = _model_call_fixture([partial, _finished()])
    with pytest.raises(model_call.ModelCallError):
        await complete_stream(agent, "model-a", [], [], max_retries=2)
    assert router.calls == 1


@pytest.mark.asyncio
async def test_cancel_interrupts_retry_wait():
    from atlas.kernel.model_call import _wait_for_retry

    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await _wait_for_retry(15, cancel)


@pytest.mark.asyncio
async def test_auxiliary_router_does_not_try_fallback_or_implicit_models():
    from atlas.models.router import ModelRouter

    route = object()
    router = SimpleNamespace(
        resolve=AsyncMock(return_value=route), complete=AsyncMock(return_value="ok"),
    )
    result = await ModelRouter.complete_for(router, "model-a", "memory", [], fallbacks=["model-b"])
    assert result == "ok"
    assert [call.args[0] for call in router.resolve.await_args_list] == ["model-a"]


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

