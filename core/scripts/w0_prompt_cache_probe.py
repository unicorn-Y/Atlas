"""Small offline proof for the W0-1 prompt-cache request wiring."""

from __future__ import annotations

import json

from atlas.kernel.prompt import build_prompt
from atlas.kernel.model_call import _stable_tool_definitions, _wire_messages
from atlas.agent.prompt_cache_boundary import find_stable_prefix
from atlas.agent.prompt_caching import build_prompt_cache_plan
from atlas.models.router import RouteSpec, _anthropic_payload, _openai_payload


def main() -> None:
    tools = [
        {"type": "function", "function": {"name": "z_tool", "parameters": {"type": "object", "properties": {"z": {"type": "string"}, "a": {"type": "integer"}}}}},
        {"type": "function", "function": {"name": "a_tool", "parameters": {"type": "object", "properties": {}}}},
    ]
    requests = [
        build_prompt(identity="Atlas identity", tool_policy="Use declared tools", goal=f"round {n}")
        for n in (1, 2)
    ]
    stable = requests[0].stable_prefix.encode("utf-8")
    assert all(item.messages[0]["content"].encode("utf-8").startswith(stable) for item in requests)

    openai = RouteSpec(provider="deepseek", api_mode="openai", model="deepseek-chat", base_url="https://example.invalid/v1")
    stable_tools = _stable_tool_definitions(tools)
    openai_payloads = [_openai_payload(openai, _wire_messages(item.messages), {"tools": stable_tools}) for item in requests]
    openai_tools = [json.dumps(item["tools"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in openai_payloads]
    assert openai_tools[0] == openai_tools[1]
    assert all("cache_control" not in json.dumps(item) for item in openai_payloads)

    anthropic = RouteSpec(provider="anthropic", api_mode="anthropic_messages", model="claude-sonnet", base_url="https://example.invalid")
    api_messages = _wire_messages(requests[0].messages)
    cache_plan = build_prompt_cache_plan(
        api_messages, stable_tools, native_anthropic=True,
        static_system_prefix=find_stable_prefix(api_messages[0]["content"]),
        direct_native_tool_cache=True,
    )
    anthropic_payload = _anthropic_payload(anthropic, cache_plan.messages, {"tools": cache_plan.tools})
    assert any(isinstance(block.get("cache_control"), dict) for block in anthropic_payload.get("system", []))
    assert any(isinstance(tool.get("cache_control"), dict) for tool in anthropic_payload.get("tools", []))
    print("W0-1 OK: dynamic system tail follows an identical stable prefix; OpenAI tools serialize identically without markers; Anthropic system/tools carry cache_control.")


if __name__ == "__main__":
    main()
