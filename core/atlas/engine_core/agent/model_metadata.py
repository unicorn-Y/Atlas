"""Small, dependency-free rough request token estimator used by Atlas."""

from __future__ import annotations

import json
import re
from typing import Any

CHARS_PER_TOKEN = 4
_CJK_DENSE_RE = re.compile(r"[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")
_IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})


def estimate_tokens_rough(text: str) -> int:
    """Estimate tokens using the upstream CJK-aware, UTF-8 byte heuristic."""
    if not text:
        return 0
    text = str(text)
    if text.isascii():
        return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
    stripped = _CJK_DENSE_RE.sub("", text)
    dense = len(text) - len(stripped)
    return dense + (len(stripped.encode("utf-8", "replace")) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _wire_message_shadow(message: Any) -> Any:
    if not isinstance(message, dict):
        return message
    shadow: dict[str, Any] = {}
    for key, value in message.items():
        if key.startswith("_") or key in {"reasoning_details", "encrypted_content"}:
            continue
        if key == "reasoning" and message.get("reasoning_content"):
            continue
        if key == "content" and isinstance(value, list):
            shadow[key] = [
                {"type": part.get("type"), "image": "[stripped]"}
                if isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES else part
                for part in value
            ]
        elif key == "content" and isinstance(value, dict) and value.get("_multimodal"):
            shadow[key] = value.get("text_summary", "")
        elif key == "encrypted_content":
            shadow[key] = ""
        else:
            shadow[key] = value
    return shadow


def estimate_request_tokens_rough(
    messages: list[dict[str, Any]], *, system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate request text and schema size without counting encoded image bytes."""
    material = [system_prompt] if system_prompt else []
    material.extend(str(_wire_message_shadow(item)) for item in messages or [])
    if tools:
        material.extend(str(item) for item in tools)
    return estimate_tokens_rough("\n".join(material))


