"""Validation for the agent-to-renderer structured component protocol."""

from __future__ import annotations

import json
from typing import Any

_KINDS = {"progress", "table", "metrics", "buttons"}
_STATUSES = {"pending", "active", "done", "error"}


def normalize_component_args(args: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Validate and bound one push_component request before it becomes a UI event."""
    title = args.get("title")
    kind = args.get("kind")
    payload = args.get("data")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("Component title must contain 1–120 characters.")
    if kind not in _KINDS or not isinstance(payload, dict):
        raise ValueError("Component kind and data object are required.")
    if len(json.dumps(payload, ensure_ascii=False)) > 24000:
        raise ValueError("Structured component data is limited to 24000 characters.")

    if kind == "progress":
        steps = payload.get("steps")
        if not isinstance(steps, list) or len(steps) > 40 or any(
            not isinstance(step, dict) or not isinstance(step.get("label"), str)
            or len(step["label"]) > 200 or step.get("status") not in _STATUSES
            for step in steps
        ):
            raise ValueError("Progress components require up to 40 {label,status} steps.")
    elif kind == "table":
        columns, rows = payload.get("columns"), payload.get("rows")
        if not isinstance(columns, list) or not 1 <= len(columns) <= 20 or any(
            not isinstance(column, str) or len(column) > 100 for column in columns
        ) or not isinstance(rows, list) or len(rows) > 200 or any(
            not isinstance(row, (list, dict)) for row in rows
        ):
            raise ValueError("Table components require 1–20 string columns and at most 200 array/object rows.")
    elif kind == "metrics":
        metrics = payload.get("metrics")
        if not isinstance(metrics, list) or len(metrics) > 20 or any(
            not isinstance(item, dict) or not isinstance(item.get("label"), str)
            or len(item["label"]) > 100 or not isinstance(item.get("value"), (str, int, float))
            for item in metrics
        ):
            raise ValueError("Metrics components require up to 20 {label,value} entries.")
    else:
        buttons = payload.get("buttons")
        if not isinstance(buttons, list) or not 1 <= len(buttons) <= 8 or any(
            not isinstance(item, dict) or not isinstance(item.get("label"), str)
            or not isinstance(item.get("value"), str) or len(item["label"]) > 80
            or len(item["value"]) > 1000 for item in buttons
        ):
            raise ValueError("Button components require 1–8 bounded {label,value} entries.")

    component_id = args.get("component_id")
    if component_id is not None and (not isinstance(component_id, str) or len(component_id) > 80):
        raise ValueError("component_id must be at most 80 characters.")
    return {
        "component_id": component_id.strip() if isinstance(component_id, str) and component_id.strip()
        else f"component-{run_id}",
        "title": title.strip(), "kind": kind, "data": payload,
    }


async def queue_component_event(
    args: dict[str, Any], run_id: str,
    event_queue: Any,
) -> dict[str, Any]:
    """Execute the push protocol against a run queue (also used by integration checks)."""
    if event_queue is None:
        raise RuntimeError("The current run cannot deliver structured components.")
    component = normalize_component_args(args, run_id)
    await event_queue.put({"type": "component.push", "data": component})
    return component
