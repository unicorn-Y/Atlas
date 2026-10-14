from __future__ import annotations

import asyncio

import pytest

from atlas.models.router import ModelRouter, RouteSpec


@pytest.mark.parametrize(
    ("purpose", "wire_model", "kwargs", "expected_timeout", "expected_extra_body"),
    [
        ("memory_library", "gemini-3.8-flash", {}, 120.0, {"reasoning_effort": "low"}),
        ("memory_library", "gemini-3.8-flash", {}, 120.0, {"reasoning_effort": "low"}),
        (
            "memory_library", "gemini-3.8-flash", {"timeout": 17.0}, 17.0,
            {"reasoning_effort": "low"},
        ),
        (
            "memory_library",
            "gemini-3.8-flash",
            {"extra_body": {"trace_id": "keep", "reasoning_effort": "medium"}},
            120.0,
            {"trace_id": "keep", "reasoning_effort": "medium"},
        ),
        ("model_test", "test-model", {}, None, None),
        ("model_test", "test-model", {"extra_body": {"trace_id": "keep"}}, None, {"trace_id": "keep"}),
        ("memory_library", "other-model", {}, 120.0, None),
        (
            "memory_library", "other-model", {"extra_body": {"trace_id": "keep"}},
            120.0, {"trace_id": "keep"},
        ),
    ],
)
def test_model_router_applies_memory_timeouts_only(
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    wire_model: str,
    kwargs: dict[str, object],
    expected_timeout: float | None,
    expected_extra_body: dict[str, object] | None,
) -> None:
    import agent.auxiliary_client as auxiliary_client

    calls: list[dict[str, object]] = []

    def fake_call_llm(**call_kwargs: object) -> dict[str, object]:
        calls.append(call_kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(auxiliary_client, "call_llm", fake_call_llm)
    router = ModelRouter(object())
    route = RouteSpec(
        provider="test-provider", api_mode="chat_completions", model="test-model",
        base_url="https://example.invalid/v1", purpose=purpose,
        wire_model=wire_model, model_id="test-model",
    )

    asyncio.run(router.complete(route, [{"role": "user", "content": "hello"}], **kwargs))

    assert len(calls) == 1
    assert calls[0].get("timeout") == expected_timeout
    assert calls[0].get("extra_body") == expected_extra_body
