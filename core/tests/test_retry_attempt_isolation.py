from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from atlas.engine.kernel.model_call import complete_stream


pytestmark = pytest.mark.unit


def _chunk(text: str, *, finish_reason=None, tool_calls=None):
    delta = {"content": text}
    if tool_calls:
        delta["tool_calls"] = tool_calls
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


@pytest.mark.asyncio
async def test_failed_attempt_text_and_tool_fragments_do_not_enter_success_result(monkeypatch):
    attempts = []
    lifecycle = []
    streams = 0

    def stream(*_args, **_kwargs):
        nonlocal streams
        streams += 1
        if streams == 1:
            def old_then_disconnect():
                yield _chunk("OLD", tool_calls=[{
                    "index": 0,
                    "id": "failed-call",
                    "function": {"name": "delete_file", "arguments": '{"path":"secret.txt"'},
                }])
                raise httpx.ReadError("connection reset")

            return old_then_disconnect()
        return iter([_chunk("NEW", finish_reason="stop")])

    route = SimpleNamespace(
        provider="openai", wire_model="test", model="test", key="",
        base_url="http://isolated.invalid", api_mode="chat_completions", model_id="test",
    )
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route), stream=stream,
    ))

    async def no_retry_delay(_delay):
        return None

    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", no_retry_delay)
    result = await complete_stream(
        agent, "test", [{"role": "user", "content": "answer"}], [],
        max_retries=1, unbounded_connection_retries=False, on_attempt=attempts.append,
        on_event=lifecycle.append,
    )

    assert result.text == "NEW"
    assert result.tool_calls == []
    assert result.attempts == 2
    assert [item["ok"] for item in attempts] == [False, True]
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert [(item["type"], item["attempt"]) for item in lifecycle if item["type"].startswith("attempt_")] == [
        ("attempt_started", 1),
        ("attempt_discarded", 1),
        ("attempt_started", 2),
        ("attempt_committed", 2),
    ]


@pytest.mark.asyncio
async def test_cancelled_stream_discards_partial_attempt_before_propagating(monkeypatch):
    lifecycle = []
    cancel_event = asyncio.Event()
    route = SimpleNamespace(
        provider="openai", wire_model="test", model="test", key="",
        base_url="http://isolated.invalid", api_mode="chat_completions", model_id="test",
    )
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route),
        stream=lambda *_args, **_kwargs: iter([
            _chunk("OLD partial"),
            _chunk(" should never be read", finish_reason="stop"),
        ]),
    ))

    async def cancel_after_first_delta(_delta):
        cancel_event.set()

    with pytest.raises(asyncio.CancelledError):
        await complete_stream(
            agent, "test", [{"role": "user", "content": "answer"}], [],
            cancel_event=cancel_event,
            on_text=cancel_after_first_delta,
            on_event=lifecycle.append,
        )

    assert [item["type"] for item in lifecycle if item["type"].startswith("attempt_")] == [
        "attempt_started", "attempt_discarded",
    ]
    discarded = next(item for item in lifecycle if item["type"] == "attempt_discarded")
    assert discarded["category"] == "cancelled"
    assert discarded["retry"] is False
    assert discarded["partial_text"] == "OLD partial"
    assert discarded["attempt_id"] == next(
        item["attempt_id"] for item in lifecycle if item["type"] == "attempt_started"
    )


@pytest.mark.asyncio
async def test_consumer_timeout_does_not_retry_provider_or_commit_partial_text(monkeypatch):
    attempts = []
    lifecycle = []
    streams = 0

    def stream(*_args, **_kwargs):
        nonlocal streams
        streams += 1
        return iter([_chunk("partial", finish_reason="stop")])

    route = SimpleNamespace(
        provider="openai", wire_model="test", model="test", key="",
        base_url="http://isolated.invalid", api_mode="chat_completions", model_id="test",
    )
    agent = SimpleNamespace(_model_router=SimpleNamespace(
        resolve=AsyncMock(return_value=route), stream=stream,
    ))

    async def consumer_timeout(_delta):
        raise TimeoutError("renderer stopped accepting the stream")

    async def no_retry_delay(_delay):
        return None

    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", no_retry_delay)

    with pytest.raises(Exception) as raised:
        await complete_stream(
            agent, "test", [{"role": "user", "content": "answer"}], [],
            max_retries=2, unbounded_connection_retries=True,
            fallback_models=["fallback"],
            on_text=consumer_timeout, on_attempt=attempts.append, on_event=lifecycle.append,
        )

    assert streams == 1
    assert agent._model_router.resolve.await_count == 1
    assert getattr(raised.value, "category", None) == "consumer_callback"
    assert [item["ok"] for item in attempts] == [False]
    assert [item["type"] for item in lifecycle if item["type"].startswith("attempt_")] == [
        "attempt_started", "attempt_discarded",
    ]
    discarded = next(item for item in lifecycle if item["type"] == "attempt_discarded")
    assert discarded["category"] == "consumer_callback"
    assert discarded["retry"] is False
    assert discarded["partial_text"] == "partial"
