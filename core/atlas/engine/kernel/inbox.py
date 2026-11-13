"""Durable, ordered next-turn and next-step message inbox for an agent session."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

InboxLane = Literal["next-turn", "next-step"]


@dataclass(frozen=True, slots=True)
class InboxItem:
    event_id: str
    lane: InboxLane
    content: str
    seq: int = 0


class DurableInbox:
    """Append-only session inbox; injecting an item never wakes an active run."""

    def __init__(self, home: str | Path, session_id: str) -> None:
        self.home = Path(home)
        self.session_id = str(session_id)
        self._pending: dict[InboxLane, list[InboxItem]] = {
            "next-turn": [], "next-step": [],
        }
        self._lock = asyncio.Lock()
        self._restored = False

    async def restore(self) -> None:
        """Rebuild pending queues from append-only inbox lifecycle events."""
        async with self._lock:
            if self._restored:
                return
            from atlas.engine.session_sync import read_session_events

            events: list[dict[str, Any]] = []
            cursor = 0
            while True:
                page = await asyncio.to_thread(
                    read_session_events, self.home, self.session_id,
                    after_seq=cursor, limit=1000,
                )
                if not page:
                    break
                events.extend(page)
                cursor = int(page[-1].get("seq") or cursor)
                if len(page) < 1000:
                    break
            pending: dict[str, InboxItem] = {}
            for event in events:
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
                    pending[event_id] = InboxItem(
                        event_id, lane, content, int(event.get("seq") or 0),
                    )
                elif kind == "inbox.consumed":
                    pending.pop(event_id, None)
            self._pending = {"next-turn": [], "next-step": []}
            for item in sorted(pending.values(), key=lambda value: value.seq):
                self._pending[item.lane].append(item)
            self._restored = True

    async def inject(self, content: str, *, lane: InboxLane = "next-step") -> str:
        """Durably enqueue content for a later boundary without interrupting a run."""
        value = str(content or "").strip()
        if lane not in self._pending:
            raise ValueError("lane must be 'next-turn' or 'next-step'")
        if not value:
            raise ValueError("inbox content must not be empty")
        await self.restore()
        event_id = uuid.uuid4().hex
        async with self._lock:
            from atlas.engine.session_sync import append_session_event

            seq = await asyncio.to_thread(
                append_session_event, self.home, self.session_id, "inbox.enqueued",
                {"event_id": event_id, "lane": lane, "content": value},
            )
            self._pending[lane].append(InboxItem(event_id, lane, value, seq))
        return event_id

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
            return self._pending[lane][0] if self._pending[lane] else None

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
                {"event_id": item.event_id, "lane": item.lane},
            )
            self._pending[lane].remove(item)
            return True
