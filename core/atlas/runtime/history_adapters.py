"""Read-only JSONL transcript adapters for Pi, Hermes, and Atlas CLI exports."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

MAX_JSONL_BYTES = 32 * 1024 * 1024
MAX_JSONL_RECORDS = 50_000
ADAPTERS: dict[str, dict[str, str]] = {
    "pi": {"role": "message.role", "content": "message.content", "timestamp": "timestamp", "id": "message.id"},
    "hermes": {"role": "role", "content": "content", "timestamp": "timestamp", "id": "id"},
    "atlas-cli": {"role": "role", "content": "content", "timestamp": "", "id": "id"},
}
FORMATS = tuple(ADAPTERS)


def _path_value(row: Mapping[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split(".") if path else ():
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, Mapping):
        if value.get("type") in {"text", "input_text", "output_text"}:
            return _text(value.get("text"))
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
        if "content" in value:
            return _text(value["content"])
    return ""


def _flatten_paths(value: Any, prefix: str = "", depth: int = 0) -> set[str]:
    if depth >= 3 or not isinstance(value, Mapping):
        return set()
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path)
        if isinstance(child, Mapping):
            paths.update(_flatten_paths(child, path, depth + 1))
    return paths


def _detect(rows: list[dict[str, Any]]) -> str:
    for row in rows[:20]:
        kind = str(row.get("type") or "").casefold()
        if kind in {"start", "input", "text_delta", "final", "end"} and "session_id" in row:
            return "atlas-cli"
        if kind == "message" and isinstance(row.get("message"), dict):
            msg = row["message"]
            if msg.get("role") in {"user", "assistant"}:
                return "pi"
        if row.get("role") in {"user", "assistant"}:
            return "hermes"
        data = row.get("data")
        if isinstance(data, dict) and data.get("role") in {"user", "assistant"}:
            return "hermes"
    return ""


def _parse_atlas_cli(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue
        session = sessions.setdefault(session_id, {"messages": [], "deltas": []})
        kind = row.get("type")
        if kind == "input" and isinstance(row.get("text"), str):
            session["messages"].append({"role": "user", "content": row["text"], "id": f"{session_id}:input"})
        elif kind == "final" and isinstance(row.get("text"), str):
            session["messages"].append({"role": "assistant", "content": row["text"], "id": f"{session_id}:final"})
    return [message for session in sessions.values() for message in session["messages"]]


def inspect_jsonl(content: str, requested_format: str = "auto") -> dict[str, Any]:
    """Parse a bounded transcript, suggest mappings, and return a safe preview."""
    encoded = content.encode("utf-8", errors="replace")
    if len(encoded) > MAX_JSONL_BYTES:
        raise ValueError(f"JSONL 文件超过 {MAX_JSONL_BYTES // (1024 * 1024)} MiB 上限")
    source_rows: list[dict[str, Any]] = []
    errors = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        if len(source_rows) + errors >= MAX_JSONL_RECORDS:
            raise ValueError(f"JSONL 行数超过 {MAX_JSONL_RECORDS} 行上限")
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors += 1
            continue
        if isinstance(row, dict):
            source_rows.append(row)
    detected = _detect(source_rows)
    fmt = detected if requested_format == "auto" else requested_format
    if fmt not in FORMATS:
        raise ValueError("format 必须为 auto、pi、hermes 或 atlas-cli")
    if fmt == "atlas-cli":
        messages = _parse_atlas_cli(source_rows)
        paths = {"role", "content", "id"}
        mapping = ADAPTERS[fmt]
    else:
        all_paths = set().union(*(_flatten_paths(row) for row in source_rows[:200])) if source_rows else set()
        paths = all_paths
        if fmt == "pi":
            mapping = ADAPTERS[fmt]
        elif fmt == "hermes":
            nested = "data." if "data.role" in paths else ""
            mapping = {"role": f"{nested}role", "content": f"{nested}content", "timestamp": f"{nested}timestamp", "id": f"{nested}id"}
        else:
            mapping = ADAPTERS[fmt]
        messages = []
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "format": fmt, "detected_format": detected or None,
        "available_fields": sorted(paths), "mapping": mapping,
        "record_count": len(source_rows), "invalid_lines": errors,
        "file_key": digest, "messages": messages,
        "rows": source_rows if fmt != "atlas-cli" else [],
    }


def normalize_jsonl_messages(
    content: str, fmt: str, mapping: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    parsed = inspect_jsonl(content, fmt)
    if fmt == "atlas-cli":
        rows = parsed["messages"]
        effective = {"role": "role", "content": "content", "timestamp": "", "id": "id"}
    else:
        rows = parsed["rows"]
        effective = dict(parsed["mapping"])
        if mapping:
            effective.update({key: str(value) for key, value in mapping.items() if key in effective})
    occurrences: Counter[str] = Counter()
    result: list[dict[str, str]] = []
    file_key = parsed["file_key"]
    for row in rows:
        role = _path_value(row, effective.get("role", ""))
        if role not in {"user", "assistant"}:
            continue
        content_text = _text(_path_value(row, effective.get("content", ""))).strip()
        if not content_text:
            continue
        timestamp = _path_value(row, effective.get("timestamp", "")) if effective.get("timestamp") else ""
        source_id = _path_value(row, effective.get("id", "")) if effective.get("id") else ""
        basis = str(source_id or f"{role}\0{timestamp or ''}\0{content_text}")
        ordinal = occurrences[basis]
        occurrences[basis] += 1
        message_key = hashlib.sha256(f"{file_key}\0{basis}\0{ordinal}".encode("utf-8", errors="replace")).hexdigest()
        message = {"role": str(role), "content": content_text, "external_message_key": message_key}
        if timestamp:
            message["timestamp"] = str(timestamp)
        result.append(message)
    return result
