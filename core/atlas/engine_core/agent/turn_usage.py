"""Atlas auxiliary model usage rows."""

from __future__ import annotations

import uuid
from typing import Any, Callable


def new_usage_request_id() -> str:
    return uuid.uuid4().hex


def report_auxiliary_usage(
    callback: Callable[[dict[str, Any]], Any] | None, response: Any, *,
    purpose: str, model: str, provider: str, api_mode: str, wire_model: str,
    request_id: str,
) -> tuple[dict[str, Any], Any] | None:
    """Build Atlas's durable usage shape and return its scoped observer result."""
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if usage is None:
        return None
    get = usage.get if isinstance(usage, dict) else lambda key, default=None: getattr(usage, key, default)
    raw_input = get("input_tokens", get("prompt_tokens", get("input", None)))
    raw_output = get("output_tokens", get("completion_tokens", get("output", None)))
    try:
        input_tokens = max(0, int(raw_input)) if raw_input is not None else None
    except (TypeError, ValueError, OverflowError):
        input_tokens = None
    try:
        output_tokens = max(0, int(raw_output)) if raw_output is not None else None
    except (TypeError, ValueError, OverflowError):
        output_tokens = None
    row = {
        "request_id": request_id, "purpose": purpose, "model": model,
        "provider": provider, "api_mode": api_mode, "wire_model": wire_model,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "context_tokens": input_tokens, "usage_available": input_tokens is not None or output_tokens is not None,
    }
    for key, value in (usage.items() if isinstance(usage, dict) else vars(usage).items()):
        if key not in row and isinstance(value, (str, int, float, bool)):
            row[key] = value
    return row, callback(row) if callback is not None else None


