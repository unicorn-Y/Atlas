# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/agent/turn-state.ts (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/session/turn.rs (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Turn phases and run events for the Atlas kernel.

The phase graph follows ZCode's explicit turn machine. Codex's turn driver
informs the interruption and completion boundaries used by the kernel loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class RunPhase(StrEnum):
    PREPARING = "preparing"
    STREAMING = "streaming"
    TOOLS = "tools"
    WAITING_APPROVAL = "waiting_approval"
    COMPACTING = "compacting"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.PREPARING: frozenset({
        RunPhase.STREAMING, RunPhase.TOOLS, RunPhase.WAITING_APPROVAL,
        RunPhase.COMPACTING, RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.STREAMING: frozenset({
        RunPhase.TOOLS, RunPhase.WAITING_APPROVAL, RunPhase.COMPACTING,
        RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.TOOLS: frozenset({
        RunPhase.STREAMING, RunPhase.WAITING_APPROVAL, RunPhase.COMPACTING,
        RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.WAITING_APPROVAL: frozenset({
        RunPhase.TOOLS, RunPhase.STREAMING, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.COMPACTING: frozenset({
        RunPhase.STREAMING, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.DONE: frozenset(),
    RunPhase.FAILED: frozenset(),
    RunPhase.INTERRUPTED: frozenset(),
}


@dataclass(slots=True)
class RunState:
    run_id: str
    session_id: str
    phase: RunPhase = RunPhase.PREPARING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response_text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def transition(self, phase: RunPhase) -> None:
        if phase not in _TRANSITIONS[self.phase]:
            raise ValueError(f"invalid kernel phase transition: {self.phase} -> {phase}")
        self.phase = phase


@dataclass(frozen=True, slots=True)
class KernelEvent:
    """An event that can be translated to the existing run_turn dict shape."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_run_event(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    id: str
    name: str
    state: str
    duration_ms: int
    output_ref: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "duration_ms": self.duration_ms,
            "output_ref": self.output_ref,
        }
