"""Durable, ordered next-turn and next-step message inbox for an agent session."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

InboxLane = Literal["next-turn", "next-step"]


@dataclass(frozen=True, slots=True)
class InboxItem:
    event_id: str
    lane: InboxLane
    content: str
    seq: int = 0
    started_run_id: str | None = None
    request_id: str | None = None


class DurableInbox:
    """Append-only session inbox; injecting an item never wakes an active run."""

    def __init__(self, home: str | Path, session_id: str) -> None:
        self.home = Path(home)
        self.session_id = str(session_id)
        self._pending: dict[InboxLane, list[InboxItem]] = {
            "next-turn": [], "next-step": [],
        }
        self._receipts: dict[str, InboxItem] = {}
        self._lock = asyncio.Lock()
        self._restored = False
        self._restore_cursor = 0
        self._current_turn_event_id: str | None = None

    def set_current_turn_event(self, event_id: str | None) -> None:
        """Mark an item already supplied as the run's user message, avoiding a second projection."""
        self._current_turn_event_id = str(event_id) if event_id else None

    async def restore(self) -> None:
        """Restore once, then incrementally apply inbox lifecycle events from other processes."""
        async with self._lock:
            if not self._restored:
                self._pending = {"next-turn": [], "next-step": []}
                self._receipts = {}
                self._restore_cursor = 0
            from atlas.engine.session_sync import read_session_inbox_events

            cursor = self._restore_cursor
            while True:
                page, next_cursor = await asyncio.to_thread(
                    read_session_inbox_events, self.home, self.session_id,
                    after_seq=cursor, limit=1000,
                )
                for event in page:
                    kind = str(event.get("event_type") or "")
                    payload = event.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    event_id = str(payload.get("event_id") or "")
                    if not event_id:
                        continue
                    if kind == "inbox.enqueued":
                        lane, content = payload.get("lane"), payload.get("content")
                        if lane not in self._pending or not isinstance(content, str):
                            continue
                        request_id = str(payload.get("request_id") or "").strip() or None
                        item = InboxItem(
                            event_id, lane, content, int(event.get("seq") or 0),
                            request_id=request_id,
                        )
                        items = self._pending[lane]
                        existing_index = next(
                            (index for index, existing in enumerate(items)
                             if existing.event_id == event_id), None,
                        )
                        if existing_index is None:
                            items.append(item)
                        else:
                            items[existing_index] = item
                        if request_id:
                            previous = self._receipts.get(request_id)
                            if previous is not None and (
                                previous.lane != item.lane or previous.content != item.content
                            ):
                                raise RuntimeError("persisted inbox request id has conflicting payloads")
                            self._receipts.setdefault(request_id, item)
                    elif kind == "inbox.started":
                        run_id = str(payload.get("run_id") or "").strip()
                        if run_id:
                            for items in self._pending.values():
                                index = next(
                                    (index for index, existing in enumerate(items)
                                     if existing.event_id == event_id), None,
                                )
                                if index is not None:
                                    items[index] = replace(items[index], started_run_id=run_id)
                                    break
                    elif kind in {"inbox.consumed", "inbox.cancelled"}:
                        for items in self._pending.values():
                            items[:] = [item for item in items if item.event_id != event_id]

                cursor = max(cursor, next_cursor)
                self._restore_cursor = cursor
                if len(page) < 1000:
                    break
            self._restored = True

    async def inject(self, content: str, *, lane: InboxLane = "next-step",
                     request_id: str | None = None) -> str:
        """Durably enqueue content for a later boundary without interrupting a run."""
        event_id, _created = await self.inject_with_receipt(
            content, lane=lane, request_id=request_id,
        )
        return event_id

    async def inject_with_receipt(self, content: str, *, lane: InboxLane = "next-step",
                                  request_id: str | None = None) -> tuple[str, bool]:
        """Return the stable receipt and whether this call appended a new item."""
        value = str(content or "").strip()
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        if not value:
            raise ValueError("inbox content must not be empty")
        request_key = str(request_id or "").strip()
        if request_id is not None and not request_key:
            raise ValueError("request id must not be empty")
        if len(request_key) > 256:
            raise ValueError("request id must be at most 256 characters")
        await self.restore()
        refresh_after_duplicate = False
        async with self._lock:
            if request_key:
                existing = self._receipts.get(request_key)
                if existing is not None:
                    if existing.lane != lane or existing.content != value:
                        raise ValueError("request id was already used with a different payload")
                    return existing.event_id, False

            candidate_event_id = uuid.uuid4().hex
            from atlas.engine.session_sync import append_inbox_enqueue_with_receipt

            payload = {"event_id": candidate_event_id, "lane": lane, "content": value}
            if request_key:
                payload["request_id"] = request_key
            event_id, seq, created = await asyncio.to_thread(
                append_inbox_enqueue_with_receipt,
                self.home, self.session_id, payload,
            )
            if created:
                item = InboxItem(event_id, lane, value, seq, request_id=request_key or None)
                self._pending[lane].append(item)
                if request_key:
                    self._receipts[request_key] = item
            else:
                # Another inbox instance may have committed this event while our
                # local restore snapshot was stale. Refresh after releasing the
                # lock so this instance can also drain the durable pending item.
                self._restored = False
                refresh_after_duplicate = True
        if refresh_after_duplicate:
            await self.restore()
        return event_id, created

    async def mark_started(self, event_id: str, *, lane: InboxLane, run_id: str) -> bool:
        """Persist the worker run identity before execution; claimed items are not replayed."""
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        run_key = str(run_id or "").strip()
        if not run_key or len(run_key) > 256:
            raise ValueError("run id must be non-empty and at most 256 characters")
        await self.restore()
        refresh_snapshot = False
        async with self._lock:
            items = self._pending[lane]
            index = next((i for i, item in enumerate(items)
                          if item.event_id == str(event_id)), None)
            if index is None:
                return False
            item = items[index]
            if item.started_run_id is not None:
                return item.started_run_id == run_key
            from atlas.engine.session_sync import claim_inbox_start

            _seq, owner_run_id, claimed = await asyncio.to_thread(
                claim_inbox_start, self.home, self.session_id,
                event_id=item.event_id, lane=item.lane, run_id=run_key,
                request_id=item.request_id,
            )
            if owner_run_id is not None:
                items[index] = replace(item, started_run_id=owner_run_id)
            else:
                self._restored = False
                refresh_snapshot = True
        if refresh_snapshot:
            await self.restore()
        return claimed

    async def take(self, lane: InboxLane) -> InboxItem | None:
        """Consume the oldest item in one lane and append its consumed marker."""
        item = await self.peek(lane)
        if item is None:
            return None
        await self.ack(item.event_id, lane=lane)
        return item

    async def peek(self, lane: InboxLane) -> InboxItem | None:
        """Read the oldest item without consuming it; safe across interrupted calls."""
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        await self.restore()
        async with self._lock:
            item = self._pending[lane][0] if self._pending[lane] else None
            if (lane == "next-turn" and item is not None
                    and item.event_id == self._current_turn_event_id):
                return None
            return item

    async def ack(self, event_id: str, *, lane: InboxLane) -> bool:
        """Append a consumed marker after the item was included in a model request."""
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        await self.restore()
        async with self._lock:
            item = next((item for item in self._pending[lane]
                         if item.event_id == str(event_id)), None)
            if item is None:
                return False
            from atlas.engine.session_sync import append_session_event

            await asyncio.to_thread(
                append_session_event, self.home, self.session_id, "inbox.consumed",
                {"event_id": item.event_id, "lane": item.lane,
                 "request_id": item.request_id},
            )
            self._pending[lane].remove(item)
            return True

    async def cancel(self, event_id: str, *, lane: InboxLane) -> bool:
        """Cancel a queued item only while it has not crossed the durable start boundary."""
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        await self.restore()
        refresh_snapshot = False
        async with self._lock:
            items = self._pending[lane]
            index = next((i for i, item in enumerate(items)
                          if item.event_id == str(event_id)), None)
            item = items[index] if index is not None else None
            if item is None or item.started_run_id is not None:
                return False
            from atlas.engine.session_sync import cancel_inbox_if_unstarted

            cancelled = await asyncio.to_thread(
                cancel_inbox_if_unstarted, self.home, self.session_id,
                event_id=item.event_id, lane=item.lane, request_id=item.request_id,
            )
            if cancelled:
                items.pop(index)
            else:
                self._restored = False
                refresh_snapshot = True
        if refresh_snapshot:
            await self.restore()
        return cancelled
