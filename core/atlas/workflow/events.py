# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/events.ts (Apache-2.0)
"""Timestamped event creation, durable append, and callback fan-out."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Callable

from .journal import WorkflowJournal
from .types import WorkflowGraph


async def emit_event(
    journal: WorkflowJournal,
    graph: WorkflowGraph,
    on_event: Callable[[dict[str, Any]], Any],
    event_type: str,
    *,
    node_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Journal the event before notifying the caller so event replay stays ordered."""
    event: dict[str, Any] = {
        "workflow_id": graph.workflow_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
    }
    if node_id is not None:
        event["node_id"] = node_id
    if message is not None:
        event["message"] = message
    if payload is not None:
        event["payload"] = payload
    journal.record_event(graph, event, status=status)
    callback_result = on_event(event)
    if inspect.isawaitable(callback_result):
        await callback_result
    return event
