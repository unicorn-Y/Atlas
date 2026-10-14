"""Small message-identity sanitizers needed by the Atlas SessionDB port."""

from __future__ import annotations

import re
from typing import Any

_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')


def _sanitize_surrogates(text: str) -> str:
    return text if text.isascii() else _SURROGATE_RE.sub('\ufffd', text)


def _tc_field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def coalesce_tool_call_id(tool_call: Any) -> str:
    for raw in (_tc_field(tool_call, "call_id"), _tc_field(tool_call, "id")):
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            return value.split("|", 1)[0].strip() or value
    return ""


