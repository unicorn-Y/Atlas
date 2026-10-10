# Ported from deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c: packages/core/session/src/repair.ts (MIT)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/session/turn.rs (Apache-2.0)
# SPDX-License-Identifier: MIT AND Apache-2.0
"""Repair unpaired model tool calls without replaying uncertain side effects."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


def _metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


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
                    if row.get("event") == "tool_start" and row.get("tool_call_id"):
                        result.add(str(row["tool_call_id"]))
        except OSError:
            continue
    return result


def repair_unpaired_tool_calls(
    messages: Iterable[dict[str, Any]], *, started_ids: set[str] | None = None,
    run_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Append one synthetic result per open call and return its recovery receipt.

    Calls with no durable ``tool_start`` are safe to retry. Once dispatch began,
    the side effect may have happened and the model must inspect current state.
    """
    repaired = copy.deepcopy(list(messages))
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
    receipts: list[dict[str, str]] = []
    for call_id, (name, _index) in pending.items():
        outcome = "unknown" if call_id in started else "not_started"
        detail = (
            "The previous turn stopped after this tool call began. Its outcome is unknown; "
            "inspect the current state before deciding what to do next."
            if outcome == "unknown" else
            "The previous turn stopped before this tool call started. It is safe to retry."
        )
        repaired.append({
            "role": "tool", "tool_call_id": call_id, "name": name,
            "content": detail, "is_error": True, "repair_state": outcome,
            "kernel_run_id": run_id or "",
        })
        receipts.append({"tool_call_id": call_id, "name": name, "state": outcome})
    return repaired, receipts
