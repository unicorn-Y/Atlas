"""Provider usage first, model-aware token estimates otherwise."""

from __future__ import annotations

import json
from typing import Any


def _usage_input_tokens(usage: Any) -> int | None:
    if usage is None:
        return None
    for name in ("input_tokens", "prompt_tokens"):
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def estimate_tokens(
    value: str | list[dict[str, Any]] | dict[str, Any],
    *,
    model: str = "",
    system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate tokens with tiktoken; fall back to Hermes' CJK-aware request estimator."""
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model) if model else tiktoken.get_encoding("cl100k_base")
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        if isinstance(value, str):
            material = value
        else:
            material = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if system_prompt:
            material = system_prompt + "\n" + material
        if tools:
            material += "\n" + json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        return len(encoding.encode(material))
    except (ImportError, ValueError, TypeError):
        pass

    from agent.model_metadata import estimate_request_tokens_rough

    if isinstance(value, str):
        messages = [{"role": "user", "content": value}]
    elif isinstance(value, dict):
        messages = [value]
    else:
        messages = value
    return estimate_request_tokens_rough(messages, system_prompt=system_prompt, tools=tools)


def count_tokens(
    value: str | list[dict[str, Any]] | dict[str, Any],
    *,
    model: str = "",
    usage: Any = None,
    system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Return provider-reported input usage when present, otherwise an actual tokenizer estimate."""
    reported = _usage_input_tokens(usage)
    if reported is not None:
        return reported
    return estimate_tokens(value, model=model, system_prompt=system_prompt, tools=tools)
