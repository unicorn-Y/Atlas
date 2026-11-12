"""Durable transcript projections used by SessionDB rewind and replay."""

from __future__ import annotations

from typing import Any

_EPHEMERAL_SCAFFOLDING_FLAGS = (
    "_empty_recovery_synthetic", "_empty_terminal_sentinel", "_thinking_prefill",
    "_verification_stop_synthetic", "_pre_verify_synthetic", "_kanban_stop_synthetic",
    "_dropped_toolcall_nudge",
)


def _is_ephemeral_scaffolding(msg: Any) -> bool:
    return isinstance(msg, dict) and any(msg.get(flag) for flag in _EPHEMERAL_SCAFFOLDING_FLAGS)


def _durable_content(content: Any) -> Any:
    if isinstance(content, dict) and content.get("_multimodal") is True and isinstance(content.get("content"), list):
        if content.get("text_summary"):
            return str(content["text_summary"])
        parts = [str(p.get("text", "")) for p in content.get("content", [])
                 if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(parts) if parts else "[multimodal tool result]"
    if not isinstance(content, list):
        return content
    text = [str(part.get("text", "")) if part.get("type") == "text" else "[screenshot]"
            for part in content if isinstance(part, dict)
            and (part.get("type") == "text" or part.get("type") in {"image", "image_url", "input_image"})]
    return "\n".join(text) if text else None


