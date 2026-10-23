# Ported from deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c: packages/core/session/src/repair.ts (MIT)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/session/turn.rs (Apache-2.0)
# SPDX-License-Identifier: MIT AND Apache-2.0
"""Repair unpaired model tool calls without replaying uncertain side effects."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


class ToolHistoryError(ValueError):
    """Canonical history cannot be paired without guessing or losing evidence."""


def _metadata(message: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in ("display_metadata", "metadata"):
        metadata = message.get(key)
        if isinstance(metadata, dict):
            values.update(metadata)
    return values


def _calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    values = message.get("tool_calls") or _metadata(message).get("tool_calls") or []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _call_id(call: dict[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    return str(call.get("id") or call.get("tool_call_id") or function.get("id") or "")


def _call_name(call: dict[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    return str(call.get("name") or function.get("name") or "unknown")


def _message_call_id(message: dict[str, Any]) -> str:
    return str(message.get("tool_call_id") or _metadata(message).get("tool_call_id") or "")


def started_call_ids(messages: Iterable[dict[str, Any]], log_root: str | Path) -> set[str]:
    """Find tool starts for prior run IDs stored with their assistant call group."""
    root = Path(log_root)
    run_ids = {
        str(_metadata(message).get("kernel_run_id"))
        for message in messages
        if _metadata(message).get("kernel_run_id")
    }
    if not run_ids or not root.exists():
        return set()
    result: set[str] = set()
    for path in root.glob("runs/*/*.jsonl"):
        if path.stem not in run_ids:
            continue
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if (isinstance(row, dict) and row.get("event") == "tool_start"
                            and row.get("tool_call_id")):
                        result.add(str(row["tool_call_id"]))
        except (OSError, UnicodeError):
            continue
    return result


def normalize_tool_results(
    messages: Iterable[dict[str, Any]], *, require_complete: bool = True,
    drop_orphan_results: bool = False,
) -> list[dict[str, Any]]:
    """Build a provider view, keeping results next to their owning call group.

    Durable chronology and message identities stay untouched. Call IDs may be
    reused in later completed rounds, but ambiguous or orphan results fail closed.
    Missing results are allowed only while loading history for recovery.
    """
    history = copy.deepcopy(list(messages))
    owners: dict[str, int] = {}
    groups: dict[int, list[str]] = {}
    results: dict[tuple[int, str], dict[str, Any]] = {}
    for index, message in enumerate(history):
        if message.get("role") == "assistant" and _calls(message):
            ids = [_call_id(call) for call in _calls(message)]
            if not all(ids) or len(set(ids)) != len(ids):
                raise ToolHistoryError("Invalid tool history: missing or duplicate tool call ID")
            for call_id in ids:
                previous = owners.get(call_id)
                if previous is not None and (previous, call_id) not in results:
                    raise ToolHistoryError("Invalid tool history: overlapping tool call ID")
                owners[call_id] = index
            groups[index] = ids
        elif message.get("role") in {"tool", "tool_result"}:
            call_id = _message_call_id(message)
            owner = owners.get(call_id)
            if owner is None:
                if drop_orphan_results:
                    continue
                raise ToolHistoryError("Invalid tool history: orphan tool result")
            identity = (owner, call_id)
            if identity in results:
                if drop_orphan_results:
                    continue
                raise ToolHistoryError("Invalid tool history: duplicate tool result")
            message["role"] = "tool"
            message["tool_call_id"] = call_id
            if (message.get("repair_state") or _metadata(message).get("repair_state")) == "not_started":
                # Older recovery code mistook lost provenance for proof of no
                # dispatch. Correct the provider view without rewriting the audit.
                message["repair_state"] = "unknown"
                message["content"] = (
                    "The previous turn stopped without a confirmed result for this tool call. "
                    "Its outcome is unknown; inspect the current state before deciding what to do next."
                )
                for key in ("metadata", "display_metadata"):
                    if isinstance(message.get(key), dict):
                        message[key]["repair_state"] = "unknown"
            results[identity] = message
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(history):
        if message.get("role") in {"tool", "tool_result"}:
            continue
        normalized.append(message)
        for call_id in groups.get(index, []):
            result = results.get((index, call_id))
            if result is not None:
                normalized.append(result)
            elif require_complete:
                raise ToolHistoryError("Invalid tool history: missing tool result")
    return normalized


def repair_unpaired_tool_calls(
    messages: Iterable[dict[str, Any]], *, started_ids: set[str] | None = None,
    run_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Pair existing results and fill missing results without replaying tools.

    Absence of a dispatch record is not proof a tool never ran: a crash can lose
    the receipt. Unknown outcomes must be inspected before any decision to retry.
    """
    # A corrupt result row is not allowed to poison the entire conversation.
    # Remove only results that cannot be safely attached to a call (or that
    # repeat an already accepted result), while preserving every valid call
    # and result.  These rows are excluded from the provider projection; the
    # durable transcript remains available for diagnosis.
    source = copy.deepcopy(list(messages))
    pending_calls: set[str] = set()
    repaired_source: list[dict[str, Any]] = []
    receipts: list[dict[str, str]] = []
    for message in source:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            calls = _calls(message)
            ids = [_call_id(call) for call in calls]
            if calls and (not all(ids) or len(set(ids)) != len(ids)):
                raise ToolHistoryError("Invalid tool history: missing or duplicate tool call ID")
            pending_calls.update(ids)
            repaired_source.append(message)
            continue
        if message.get("role") in {"tool", "tool_result"}:
            call_id = _message_call_id(message)
            if not call_id or call_id not in pending_calls:
                receipts.append({
                    "tool_call_id": call_id,
                    "name": str(message.get("tool_name") or message.get("name") or "unknown"),
                    "state": "orphan_result_dropped",
                    "content": "Dropped an orphan or duplicate tool result from the model history.",
                })
                continue
            pending_calls.remove(call_id)
        repaired_source.append(message)
    repaired = normalize_tool_results(repaired_source, require_complete=False)
    started = started_ids or set()
    pending: dict[str, tuple[str, int]] = {}
    for index, message in enumerate(repaired):
        if not isinstance(message, dict):
            continue
        if message.get("role") in {"tool", "tool_result"}:
            pending.pop(_message_call_id(message), None)
        for call in _calls(message):
            call_id = _call_id(call)
            if call_id:
                pending[call_id] = (_call_name(call), index)
    for call_id, (name, _index) in pending.items():
        outcome = "unknown"
        detail = (
            "The previous turn stopped after this tool call began. Its outcome is unknown; "
            "inspect the current state before deciding what to do next."
            if call_id in started else
            "The previous turn stopped without a durable result for this tool call. "
            "Its outcome is unknown; inspect the current state before deciding what to do next."
        )
        repaired.append({
            "role": "tool", "tool_call_id": call_id, "name": name,
            "content": detail, "is_error": True, "repair_state": outcome,
            "kernel_run_id": run_id or "",
        })
        receipts.append({"tool_call_id": call_id, "name": name, "state": outcome, "content": detail})
    return normalize_tool_results(repaired), receipts
