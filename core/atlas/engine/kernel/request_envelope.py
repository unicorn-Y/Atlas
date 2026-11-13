"""Safe request-envelope metadata for kernel diagnostics."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def request_envelope(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe a provider request without copying private prompt contents to logs."""
    payload = {"messages": messages, "tools": tools}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str,
                         separators=(",", ":")).encode("utf-8")
    return {
        "request_sha256": hashlib.sha256(encoded).hexdigest(),
        "message_count": len(messages),
        "roles": [str(item.get("role") or "unknown") for item in messages],
        "message_chars": [len(str(item.get("content") or "")) for item in messages],
        "tool_names": sorted(
            str((item.get("function") or item).get("name") or "")
            for item in tools if (item.get("function") or item).get("name")
        ),
    }


def tool_pool_change_message(previous: set[str], current: set[str]) -> str | None:
    """Build a model-visible notice when the dispatched tool pool changes."""
    added = sorted(current - previous)
    removed = sorted(previous - current)
    if not added and not removed:
        return None
    parts = ["Tool availability changed."]
    if added:
        parts.append("Added: " + ", ".join(added) + ".")
    if removed:
        parts.append("Removed: " + ", ".join(removed) + ".")
    return " ".join(parts)
