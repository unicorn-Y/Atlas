"""Normalize lifecycle signals into rebuildable SessionDB pointer tasks."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


_REQUIRED = ("conversation_id", "message_uids", "event_kind", "occurred_at", "scope")
_WATCHERS: dict[str, asyncio.Task[None]] = {}


def enqueue(queue: Any, event: Mapping[str, Any]) -> int:
    """Persist one lifecycle event without transcript content.

    The queue is derived processing state. Its identity is the conversation,
    ordered SessionDB message UIDs, and event kind; duplicate notifications
    therefore return the existing pending row id.
    """
    missing = [key for key in _REQUIRED if key not in event]
    if missing:
        raise ValueError(f"lifecycle event missing fields: {', '.join(missing)}")
    if any(key in event for key in ("content", "text", "user_text", "assistant_text", "transcript")):
        raise ValueError("lifecycle events cannot contain transcript content")
    conversation_id = str(event["conversation_id"] or "").strip()
    event_kind = str(event["event_kind"] or "").strip()
    occurred_at = str(event["occurred_at"] or "").strip()
    scope = str(event["scope"] or "").strip()
    if not conversation_id or not event_kind or not occurred_at or not scope:
        raise ValueError("conversation_id, event_kind, occurred_at and scope are required")
    message_uids = event["message_uids"]
    if not isinstance(message_uids, (list, tuple)):
        raise ValueError("message_uids must be an ordered list")
    uids = list(dict.fromkeys(str(uid).strip() for uid in message_uids if str(uid).strip()))
    if not uids and scope not in {"session", "uid_unknown", "legacy_unanchored"}:
        raise ValueError("message UIDs are required unless scope is session-level")
    return queue.insert(
        conversation_id=conversation_id,
        message_uids=uids,
        event_kind=event_kind,
        occurred_at=occurred_at,
        scope=scope,
        run_id=str(event["run_id"]) if event.get("run_id") else None,
        tool_call_id=str(event["tool_call_id"]) if event.get("tool_call_id") else None,
    )


def rebuild_uncovered_uids(queue: Any, conversation_id: str, message_uids: list[str],
                           processed_uids: set[str] | list[str], *,
                           occurred_at: str | None = None) -> int | None:
    """Recreate a missing queue watermark from SessionDB and Markdown refs.

    ``message_uids`` must be in SessionDB order. ``processed_uids`` comes from
    Markdown source_ref metadata; no transcript body is inspected or copied.
    """
    ordered = list(dict.fromkeys(str(uid) for uid in message_uids if str(uid)))
    if not ordered:
        return None
    processed = {str(uid) for uid in processed_uids}
    last_done = max((index for index, uid in enumerate(ordered) if uid in processed), default=-1)
    uncovered = ordered[last_done + 1:]
    if not uncovered:
        return None
    return enqueue(queue, {
        "conversation_id": conversation_id,
        "message_uids": uncovered,
        "event_kind": "session_recovery",
        "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
        "scope": "messages",
    })


def start_watcher(queue: Any, callback: Any) -> asyncio.Task[None] | None:
    """Keep retries, delayed idle jobs, and expired leases progressing in-process.

    Integrators should start one watcher during library initialization and use
    the same callback for normal lifecycle wakeups.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    key = str(queue.path)
    task = _WATCHERS.get(key)
    if task is not None and not task.done():
        return task

    async def watch() -> None:
        while True:
            try:
                delay = await asyncio.to_thread(queue.next_wake_delay)
                if delay is None:
                    await asyncio.sleep(30)
                    continue
                if delay > 0:
                    await asyncio.sleep(min(delay, 60))
                    continue
                result = callback()
                if inspect.isawaitable(result):
                    await result
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    task = loop.create_task(watch(), name="memory-lifecycle-queue-watcher")
    _WATCHERS[key] = task
    task.add_done_callback(lambda finished: _WATCHERS.pop(key, None)
                           if _WATCHERS.get(key) is finished else None)
    return task


__all__ = ["enqueue", "rebuild_uncovered_uids", "start_watcher"]
