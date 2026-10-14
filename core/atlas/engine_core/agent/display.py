"""Browser argument redaction retained from Hermes' display seam (MIT)."""
from __future__ import annotations

from typing import Any

from atlas.engine_core.agent.redact import redact_sensitive_text


def redact_browser_typed_text_for_display(value: Any, typed_text: Any) -> Any:
    needle = "" if typed_text is None else str(typed_text)
    redacted = redact_sensitive_text(needle, force=True) if needle else needle
    if redacted == needle:
        return value
    if isinstance(value, str):
        return value.replace(needle, redacted)
    if isinstance(value, dict):
        return {key: redact_browser_typed_text_for_display(item, typed_text) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_browser_typed_text_for_display(item, typed_text) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_browser_typed_text_for_display(item, typed_text) for item in value)
    return value


def redact_tool_args_for_display(tool_name: str, args: dict | None) -> dict | None:
    if not isinstance(args, dict):
        return args
    if tool_name == "browser_type" and isinstance(args.get("text"), str):
        return {**args, "text": redact_sensitive_text(args["text"], force=True)}
    return args


