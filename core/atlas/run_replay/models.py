"""Plain data holders for run replay.

Every type here is a small, JSON-friendly ``dataclass`` so callers can
``dataclasses.asdict()`` / ``json.dumps(default=str)`` results directly and so
the CLI stays trivial.

Design note -- *why these are thin*: the Atlas run log stores **no** prompt,
message, tool-argument or tool-output text. ``atlas/logs.py::_summary`` rewrites
those values to ``{"length": N}`` before they reach disk. So every model below
records lengths, ids, states and timings only; nothing pretends to have content
it cannot have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ModelCall", "Run", "RunInfo", "TimelineItem", "ToolCall"]


@dataclass
class RunInfo:
    """One row of :func:`atlas.run_replay.list_runs`.

    ``id`` is the run id taken from the file stem (``<run_id>.jsonl``), which is
    the same value the kernel writes into every event as ``run_id``.
    """

    id: str
    path: str
    size: int
    mtime: float
    event_count: int
    session_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    status: str | None = None
    files: list[str] = field(default_factory=list)
    bad_lines: int = 0
    #: ``run_end.duration_ms`` when the file has one, else last-first timestamp.
    #: ``None`` when a run never ended (killed mid-flight), which is itself a
    #: useful signal -- so it is not rounded to ``0``.
    duration_ms: int | None = None

    @property
    def size_kb(self) -> float:
        return round(self.size / 1024.0, 1)


@dataclass
class ToolCall:
    """A ``tool_start`` joined with its matching ``tool_end`` / ``tool_result``."""

    index: int
    tool_call_id: str | None
    name: str | None
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    state: str | None = None
    is_error: bool | None = None
    output_ref: str | None = None
    output_length: int | None = None
    arguments_length: int | None = None
    #: True when this call repeats the immediately preceding call exactly
    #: (same tool name and same argument length -- argument *text* is redacted).
    repeated: bool = False
    #: Signature used for the repeat test, exposed so a report can explain it.
    signature: str | None = None


@dataclass
class ModelCall:
    """One ``model_request`` row.

    The log emits ``model_request`` twice per turn: a pre-call estimate row
    (``input_chars``/``input_tokens``/``attempt``) and a post-call usage row
    (``purpose``/``duration_ms``/``output_tokens``/``cached_tokens``). The
    ``phase`` field says which one this is, because only post-call rows carry a
    duration and only they may be summed as real model time.
    """

    index: int
    phase: str  # "pre" | "post"
    timestamp: str | None = None
    model: str | None = None
    provider: str | None = None
    purpose: str | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    first_token_ms: int | None = None
    attempt: int | None = None
    input_chars: int | None = None
    #: Estimated USD cost, written by the kernel at call time. ``None`` on rows
    #: from older archives (no price was recorded) and for unpriced models.
    cost_usd: float | None = None


@dataclass
class TimelineItem:
    """One replay step, in file (chronological) order.

    ``kind`` is one of ``run_start``, ``run_phase``, ``model_call``,
    ``tool_call``, ``tool_result``, ``error``, ``run_end``, ``note``.

    ``run_phase`` items are the ordered kernel phase transitions
    (``preparing`` -> ``awaiting_model_response`` -> ... -> ``done``): they are
    what makes a replay reconstruct *where* a run was, not just what it did.
    """

    index: int
    kind: str
    timestamp: str | None
    label: str
    detail: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    is_error: bool | None = None


@dataclass
class Run:
    """A fully streamed run.

    ``timeline`` holds only *semantic* steps (run boundary, model calls, tool
    calls, errors). Noisy high-frequency events such as ``api_timing`` or
    ``tool_offer`` are counted into :attr:`event_counts` but never retained, so
    memory stays proportional to the number of real steps rather than to the
    file size.
    """

    id: str
    paths: list[str] = field(default_factory=list)
    info: RunInfo | None = None

    start_time: str | None = None
    end_time: str | None = None

    status: str | None = None
    terminal_status: str | None = None
    reason: str | None = None
    duration_ms: int | None = None

    model: str | None = None
    session_id: str | None = None
    workspace: str | None = None
    kernel: str | None = None

    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    #: Summed estimated USD cost over the run's model calls, or ``None`` when no
    #: call carried a recorded cost (older archives, unpriced models).
    cost_usd: float | None = None

    timeline: list[TimelineItem] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    event_counts: dict[str, int] = field(default_factory=dict)
    total_lines: int = 0
    bad_lines: int = 0
    bad_line_numbers: list[int] = field(default_factory=list)
    truncated: bool = False

    def count(self, event: str) -> int:
        """Event count for ``event``, ``0`` when the event never appeared."""
        return int(self.event_counts.get(event, 0) or 0)

    @property
    def size(self) -> int:
        return int(self.info.size) if self.info is not None else 0
