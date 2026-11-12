"""Small message-identity sanitizers needed by the Atlas SessionDB port."""

from __future__ import annotations

import re
from typing import Any

_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')


def _sanitize_surrogates(text: str) -> str:
    return text if text.isascii() else _SURROGATE_RE.sub('\ufffd', text)


def _tc_field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _expand_tool_id_variants(values: tuple[Any, ...]) -> frozenset[str]:
    """Return every wire spelling of a tool-call identifier and its aliases."""
    variants: set[str] = set()
    for raw in values:
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            variants.add(value)
            variants.update(part for part in (item.strip() for item in value.split("|")) if part)
    return frozenset(variants)


def tool_call_id_variants(tool_call: Any) -> frozenset[str]:
    """Return all pairing-id variants carried by a tool-call entry."""
    return _expand_tool_id_variants(
        tuple(_tc_field(tool_call, key) for key in ("call_id", "id", "response_item_id"))
    )


def tool_result_id_variants(tool_call_id: Any) -> frozenset[str]:
    """Return all matching variants for a role=tool ``tool_call_id``."""
    return _expand_tool_id_variants((tool_call_id,))


def coalesce_tool_call_id(tool_call: Any) -> str:
    for raw in (_tc_field(tool_call, "call_id"), _tc_field(tool_call, "id")):
        value = raw.strip() if isinstance(raw, str) else ""
        if value:
            return value.split("|", 1)[0].strip() or value
    return ""


