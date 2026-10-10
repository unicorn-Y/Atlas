# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/agent/turn-state.ts (Apache-2.0)
# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/session/turn.rs (Apache-2.0)
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
    AWAITING_MODEL_RESPONSE = "awaiting_model_response"
    STREAMING = "streaming"
    SCHEDULING_TOOLS = "scheduling_tools"
    TOOLS = "tools"
    WAITING_APPROVAL = "waiting_approval"
    AGGREGATING_RESULTS = "aggregating_results"
    COMPACTING = "compacting"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.PREPARING: frozenset({
        RunPhase.AWAITING_MODEL_RESPONSE, RunPhase.STREAMING, RunPhase.TOOLS, RunPhase.WAITING_APPROVAL,
        RunPhase.COMPACTING, RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.AWAITING_MODEL_RESPONSE: frozenset({
        RunPhase.STREAMING, RunPhase.COMPACTING, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.STREAMING: frozenset({
        RunPhase.AWAITING_MODEL_RESPONSE, RunPhase.SCHEDULING_TOOLS,
        RunPhase.TOOLS, RunPhase.WAITING_APPROVAL, RunPhase.COMPACTING,
        RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.SCHEDULING_TOOLS: frozenset({
        RunPhase.TOOLS, RunPhase.WAITING_APPROVAL, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.TOOLS: frozenset({
        RunPhase.WAITING_APPROVAL, RunPhase.AGGREGATING_RESULTS,
        RunPhase.STREAMING, RunPhase.COMPACTING,
        RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.WAITING_APPROVAL: frozenset({
        RunPhase.TOOLS, RunPhase.AGGREGATING_RESULTS, RunPhase.STREAMING,
        RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.AGGREGATING_RESULTS: frozenset({
        RunPhase.AWAITING_MODEL_RESPONSE, RunPhase.STREAMING, RunPhase.COMPACTING,
        RunPhase.DONE, RunPhase.FAILED, RunPhase.INTERRUPTED,
    }),
    RunPhase.COMPACTING: frozenset({
        RunPhase.AWAITING_MODEL_RESPONSE, RunPhase.STREAMING,
        RunPhase.FAILED, RunPhase.INTERRUPTED,
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
    streamed_text: str = ""
    streamed_reasoning: str = ""
    streamed_refusal: str = ""
    streamed_tool_calls: dict[tuple[int, int], dict[str, str]] = field(default_factory=dict)
    usage_rows: list[dict[str, Any]] = field(default_factory=list)
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
