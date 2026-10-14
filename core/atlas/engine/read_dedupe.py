"""Session-scoped deduplication for unchanged file reads."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_STATE_ATTR = "_atlas_read_dedupe_state"


def _state(runtime: Any) -> dict[str, Any]:
    with _LOCK:
        state = getattr(runtime, _STATE_ATTR, None)
        if not isinstance(state, dict):
            state = {"reads": {}, "by_call_id": {}, "reminders": {}}
            setattr(runtime, _STATE_ATTR, state)
        return state


def _read_paths(arguments: dict[str, Any], runtime: Any) -> list[Path]:
    raw_paths = arguments.get("paths")
    values = raw_paths if isinstance(raw_paths, list) else [arguments.get("path")]
    workspace = str(getattr(runtime, "workspace", "") or "")
    cwd = str(arguments.get("cwd") or workspace or os.getcwd())
    paths: list[Path] = []
    for raw in values:
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.is_absolute():
            path = Path(cwd) / path
        try:
            paths.append(path.resolve())
        except OSError:
            continue
    return paths


def _range(arguments: dict[str, Any]) -> tuple[Any, ...]:
    return (
        arguments.get("offset"),
        arguments.get("limit"),
        arguments.get("byte_offset"),
        arguments.get("byte_limit"),
        arguments.get("encoding", "utf-8"),
        bool(arguments.get("binary", False)),
    )


def _key(path: Path, read_range: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    return os.path.normcase(str(path)), read_range


def unchanged_read_result(
    runtime: Any,
    arguments: dict[str, Any],
    tool_call_id: str | None,
) -> str | None:
    """Return the unchanged-file stub only when every requested read is still present."""
    if not tool_call_id:
        return None
    paths = _read_paths(arguments, runtime)
    if not paths:
        return None
    state = _state(runtime)
    read_range = _range(arguments)
    with _LOCK:
        records = [state["reads"].get(_key(path, read_range)) for path in paths]
        if any(record is None for record in records):
            return None
        for path, record in zip(paths, records):
            try:
                current_mtime = path.stat().st_mtime_ns
            except OSError:
                return None
            if current_mtime != record["mtime_ns"]:
                return None
        labels = ", ".join(str(path) for path in paths)
        return f"文件自上次读取后未变化，内容见前文：{labels}"


def record_file_read(
    runtime: Any,
    arguments: dict[str, Any],
    tool_call_id: str | None,
    result: Any,
) -> None:
    """Remember successful reads, keyed by canonical path, range, and file mtime."""
    if not tool_call_id or not isinstance(result, str) or not result.strip():
        return
    lowered_result = result.casefold()
    if result.lstrip().startswith(("Error:", "PermissionError:", "FileNotFoundError:")):
        return
    if "full output saved to:" in lowered_result or "[truncated: tool response" in lowered_result:
        return
    paths = _read_paths(arguments, runtime)
    if not paths:
        return
    state = _state(runtime)
    read_range = _range(arguments)
    records: list[tuple[str, tuple[Any, ...]]] = []
    with _LOCK:
        for path in paths:
            if f"== {path}\nerror:".casefold() in lowered_result:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            key = _key(path, read_range)
            state["reads"][key] = {"mtime_ns": stat.st_mtime_ns, "tool_call_id": tool_call_id}
            state["reminders"].pop(str(path), None)
            records.append(key)
        if records:
            state["by_call_id"][tool_call_id] = records


def invalidate_read_dedupe(runtime: Any, tool_call_ids: Iterable[str]) -> None:
    """Forget dedupe entries whose source results were pruned, replaced, or compacted."""
    ids = {str(item) for item in tool_call_ids if item}
    if not ids:
        return
    state = _state(runtime)
    with _LOCK:
        for call_id in ids:
            for key in state["by_call_id"].pop(call_id, []):
                record = state["reads"].get(key)
                if record and record.get("tool_call_id") == call_id:
                    state["reminders"][key[0]] = {"path": key[0], "tool_call_id": call_id}
                    state["reads"].pop(key, None)


def post_compaction_read_paths(runtime: Any) -> list[str]:
    """List read-only paths whose original tool results no longer remain in history."""
    state = _state(runtime)
    with _LOCK:
        return [str(item["path"]) for item in state["reminders"].values()]
