"""FIFO capacity admission for nested subagent execution.

The three defaults follow OpenClaw's subagent limits: eight concurrent runs,
five children per parent, and two spawn levels. Requests wait in arrival order
when a capacity slot is unavailable; the manager has no permission or sandbox
policy of its own.
"""

from __future__ import annotations

import asyncio
import secrets
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityTicket:
    token: str
    parent_id: str
    depth: int


class SubagentCapacity:
    """FIFO scheduler enforcing global, per-parent, and nesting limits."""

    def __init__(
        self, *, max_concurrent: int = 8, max_children_per_parent: int = 5,
        max_spawn_depth: int = 2,
    ) -> None:
        self._validate(max_concurrent, max_children_per_parent, max_spawn_depth)
        self.max_concurrent = max_concurrent
        self.max_children_per_parent = max_children_per_parent
        self.max_spawn_depth = max_spawn_depth
        self._condition = asyncio.Condition()
        self._waiting: deque[CapacityTicket] = deque()
        self._active: dict[str, CapacityTicket] = {}
        self._by_parent: dict[str, int] = {}

    @staticmethod
    def _validate(concurrent: int, children: int, depth: int) -> None:
        if any(type(value) is not int or value < 1 for value in (concurrent, children, depth)):
            raise ValueError("subagent capacity limits must be positive integers")

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def waiting_count(self) -> int:
        return len(self._waiting)

    async def acquire(self, *, parent_id: str, depth: int) -> CapacityTicket:
        if type(depth) is not int or depth < 1:
            raise ValueError("subagent depth must be a positive integer")
        ticket = CapacityTicket(secrets.token_hex(8), str(parent_id or "root"), depth)
        async with self._condition:
            self._waiting.append(ticket)
            try:
                while True:
                    is_head = bool(self._waiting) and self._waiting[0] == ticket
                    under_caps = (
                        len(self._active) < self.max_concurrent
                        and self._by_parent.get(ticket.parent_id, 0) < self.max_children_per_parent
                        and ticket.depth <= self.max_spawn_depth
                    )
                    if is_head and under_caps:
                        self._waiting.popleft()
                        self._active[ticket.token] = ticket
                        self._by_parent[ticket.parent_id] = self._by_parent.get(ticket.parent_id, 0) + 1
                        return ticket
                    await self._condition.wait()
            except BaseException:
                try:
                    self._waiting.remove(ticket)
                except ValueError:
                    pass
                self._condition.notify_all()
                raise

    async def release(self, ticket: CapacityTicket) -> None:
        async with self._condition:
            active = self._active.pop(ticket.token, None)
            if active is not None:
                count = self._by_parent.get(active.parent_id, 0) - 1
                if count > 0:
                    self._by_parent[active.parent_id] = count
                else:
                    self._by_parent.pop(active.parent_id, None)
            self._condition.notify_all()

    async def set_limits(
        self, *, max_concurrent: int | None = None,
        max_children_per_parent: int | None = None, max_spawn_depth: int | None = None,
    ) -> None:
        """Update runtime limits and wake queued requests."""
        values = (
            self.max_concurrent if max_concurrent is None else max_concurrent,
            self.max_children_per_parent if max_children_per_parent is None else max_children_per_parent,
            self.max_spawn_depth if max_spawn_depth is None else max_spawn_depth,
        )
        self._validate(*values)
        async with self._condition:
            self.max_concurrent, self.max_children_per_parent, self.max_spawn_depth = values
            self._condition.notify_all()


# DelegationService instances are short lived in some tool paths. Keep one
# scheduler per process so the configured global limit actually applies across
# every concurrently created service instance.
_SHARED_CAPACITY = SubagentCapacity()


def get_subagent_capacity() -> SubagentCapacity:
    return _SHARED_CAPACITY


__all__ = ["CapacityTicket", "SubagentCapacity", "get_subagent_capacity"]
