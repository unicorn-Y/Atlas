"""Validated, source-linked patches for Markdown memory consolidation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_ACTIONS = {"add", "update", "supersede", "retract", "keep"}
_SECTIONS = {"现在状态", "定下的决定", "没做完", "来龙去脉"}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_plan(raw: str, allowed_refs: set[str]) -> list[dict[str, Any]]:
    """Parse a strict model plan and reject unknown sources or unsafe fields."""
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"actions"} or not isinstance(value["actions"], list):
        raise ValueError("proposal must contain only an actions array")
    actions = []
    for item in value["actions"]:
        if not isinstance(item, dict) or item.get("action") not in _ACTIONS:
            raise ValueError("proposal action is invalid")
        required = {"action", "target_id", "old_text_hash", "source_refs", "fields", "reason"}
        if set(item) != required:
            raise ValueError("proposal action fields do not match schema")
        refs, fields = item["source_refs"], item["fields"]
        if not isinstance(refs, list) or not refs or any(ref not in allowed_refs for ref in refs):
            raise ValueError("proposal contains an unknown source reference")
        if not isinstance(fields, dict) or any(key not in {"section", "text"} for key in fields):
            raise ValueError("proposal fields are invalid")
        if item["action"] in {"add", "update", "supersede"}:
            if set(fields) != {"section", "text"} or fields.get("section") not in _SECTIONS or not isinstance(fields.get("text"), str):
                raise ValueError("proposal text or section is invalid")
        elif fields and (fields.get("section") not in _SECTIONS or not isinstance(fields.get("text", ""), str)):
            raise ValueError("proposal text or section is invalid")
        if item["action"] in {"update", "supersede", "retract"} and (not item["target_id"] or not item["old_text_hash"]):
            raise ValueError("mutating action needs target id and old text hash")
        if item["action"] == "add" and (item["target_id"] or item["old_text_hash"]):
            raise ValueError("add action cannot target an existing claim")
        if not isinstance(item["reason"], str):
            raise ValueError("proposal reason must be text")
        actions.append(item)
    return actions


def entry_metadata(entry: Any) -> Mapping[str, Any]:
    metadata = getattr(entry, "extra_metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}
