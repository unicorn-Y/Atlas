"""Small offline proof for W0-2 provider-specific reasoning replay."""

from __future__ import annotations

from atlas.kernel.model_call import _wire_messages
from atlas.models.router import RouteSpec, _anthropic_payload, _openai_payload


def main() -> None:
    signed_thinking = {
        "type": "thinking", "thinking": "inspect the tool result", "signature": "sig-exact-abc",
    }
    history = [{
        "role": "assistant", "content": "", "reasoning_content": "deepseek thought verbatim",
        "reasoning_details": [signed_thinking],
        "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
    }, {"role": "tool", "tool_call_id": "call-1", "content": "file contents"}]
    wire_history = _wire_messages(history)
    assert wire_history[0]["reasoning_content"] == "deepseek thought verbatim"
    deepseek = RouteSpec(provider="deepseek", api_mode="openai", model="deepseek-v4", base_url="https://example.invalid/v1")
    next_request = _openai_payload(deepseek, wire_history, {"tools": [], "reasoning_config": {"effort": "ultra"}})
    assert next_request["messages"][0]["reasoning_content"] == "deepseek thought verbatim"
    assert next_request["thinking"] == {"type": "enabled"}
    assert next_request["reasoning_effort"] == "max"

    unsupported = RouteSpec(provider="openai", api_mode="openai", model="gpt-4.1", base_url="https://example.invalid/v1")
    assert "reasoning_content" not in _openai_payload(unsupported, wire_history, {}).get("messages", [{}])[0]

    anthropic = RouteSpec(provider="anthropic", api_mode="anthropic_messages", model="claude-sonnet", base_url="https://example.invalid")
    anthropic_request = _anthropic_payload(anthropic, wire_history, {
        "max_tokens": 2048, "reasoning_config": {"effort": "high"},
    })
    replayed = next(block for block in anthropic_request["messages"][0]["content"] if block.get("type") == "thinking")
    assert replayed == signed_thinking
    assert anthropic_request["thinking"]["budget_tokens"] == 2047
    print("W0-2 OK: DeepSeek tool-followup echoes reasoning_content and clamps effort; unsupported OpenAI drops it; Anthropic replays signed thinking and respects max_tokens-1.")


if __name__ == "__main__":
    main()
