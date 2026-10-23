"""Addressable FIFO mailboxes for messages exchanged by collaborating agents."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

_ADDRESS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}@[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def normalize_address(value: str) -> str:
    """Validate and canonicalize ``agent-id@team-id`` mailbox addresses."""
    address = str(value or "").strip()
    if not _ADDRESS.fullmatch(address):
        raise ValueError("agent address must use agent-id@team-id form")
    agent_id, team_id = address.split("@", 1)
    return f"{agent_id}@{team_id}"


@dataclass(frozen=True)
class MailMessage:
    revision: int
    sender: str
    recipient: str
    content: str
    created_at: float


class AgentMailbox:
    """In-process mailbox queues with ordered writes and waiter wakeup.

    A per-mailbox lock serializes concurrent writers. Messages sent before a
    receiver starts remain queued; waiting receivers are woken by ``Queue.put``.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[MailMessage]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._revisions: dict[str, int] = {}
        self._waiters: dict[str, int] = {}

    def _queue(self, address: str) -> asyncio.Queue[MailMessage]:
        return self._queues.setdefault(address, asyncio.Queue())

    async def send(self, sender: str, recipient: str, content: str) -> MailMessage:
        source, target = normalize_address(sender), normalize_address(recipient)
        body = str(content or "").strip()
        if not body:
            raise ValueError("mail message content must be non-empty")
        lock = self._locks.setdefault(target, asyncio.Lock())
        async with lock:
            return self.send_nowait(source, target, body)

    def send_nowait(self, sender: str, recipient: str, content: str) -> MailMessage:
        """Synchronous event-loop delivery for existing non-async steering hooks."""
        source, target = normalize_address(sender), normalize_address(recipient)
        body = str(content or "").strip()
        if not body:
            raise ValueError("mail message content must be non-empty")
        revision = self._revisions.get(target, 0) + 1
        self._revisions[target] = revision
        message = MailMessage(revision, source, target, body, time.time())
        self._queue(target).put_nowait(message)
        return message

    async def receive(
        self, address: str, *, wait: bool = False, limit: int = 100,
    ) -> list[MailMessage]:
        target = normalize_address(address)
        if type(limit) is not int or limit < 1:
            raise ValueError("mailbox receive limit must be positive")
        queue = self._queue(target)
        messages: list[MailMessage] = []
        if wait:
            self._waiters[target] = self._waiters.get(target, 0) + 1
            try:
                messages.append(await queue.get())
            finally:
                remaining = self._waiters.get(target, 1) - 1
                if remaining:
                    self._waiters[target] = remaining
                else:
                    self._waiters.pop(target, None)
        while len(messages) < limit and not queue.empty():
            messages.append(queue.get_nowait())
        return messages

    def pending(self, address: str) -> int:
        return self._queue(normalize_address(address)).qsize()

    def waiting_receivers(self, address: str) -> int:
        return self._waiters.get(normalize_address(address), 0)
