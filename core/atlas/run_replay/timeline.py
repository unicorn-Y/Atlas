"""Streaming event folding and chronological replay.

:class:`RunBuilder` is the single place that knows how the log's event vocabulary
maps onto the public model. It is fed one line at a time by
:func:`atlas.run_replay.loader.load_run`, so it must stay O(1) in memory per line:
nothing raw is retained, only compact records for semantic steps.

Event vocabulary (counted from the real archive, 28,221 events):

===========================  ==========================================
``run_start``                ``model, session_id, workspace, kernel``
``run_phase``                ``phase, previous, elapsed_ms``
``model_request``            two shapes, see :class:`ModelCall`
``model_error``              ``purpose, category, status, retry, ...``
``tool_start``               ``tool_call_id, name, arguments``
``tool_end``                 ``+ state, duration_ms, output_ref, output``
``tool_result``              ``+ is_error`` (no ``duration_ms``)
``tool_offer``               schema prep timing -- counted only
``api_timing``               HTTP stage timing -- counted only
``run_phase_timing``         ``stage, duration_ms``
``compaction``               ``before_tokens/after_tokens/budget_tokens``
``repair`` / ``tool_args_*`` stream-repair bookkeeping
``run_end``                  ``status, duration_ms, total_*_tokens``
===========================  ==========================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._util import as_bool, as_int, as_str
from .models import ModelCall, Run, TimelineItem, ToolCall

__all__ = ["RunBuilder", "replay"]

#: Events kept as timeline steps. Everything else is counted only.
_MODEL_EVENTS = {"model_request", "model_error"}
_TOOL_EVENTS = {"tool_start", "tool_end", "tool_result", "tool_args_invalid"}

#: ``model_request`` post-call-only keys -- their presence marks the usage row.
_USAGE_KEYS = ("duration_ms", "output_tokens", "purpose")


def _arguments_length(value: Any) -> int | None:
    """Length of the redacted ``arguments`` payload.

    The writer replaces tool arguments with ``{"length": N}`` (see
    ``atlas/logs.py::_summary``), so a full argument text is *never* on disk and
    only this length can be compared. A raw string/dict is tolerated anyway in
    case a future writer stops redacting.
    """
    if isinstance(value, dict):
        length = as_int(value.get("length"))
        if length is not None:
            return length
        if not value:
            return 0
        return len(value)
    if isinstance(value, str):
        return len(value)
    if value is None:
        return None
    return None


def _output_length(value: Any) -> int | None:
    if isinstance(value, dict):
        return as_int(value.get("length"))
    if isinstance(value, str):
        return len(value)
    return None


def _as_cost(value: Any) -> float | None:
    """Estimated cost as a float; ``None`` when absent or unusable.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, and a ``True``
    cost would silently become ``$1.00`` in any report.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


class RunBuilder:
    """Fold a stream of run events into a :class:`~atlas.run_replay.models.Run`."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.event_counts: dict[str, int] = {}
        self.timeline: list[TimelineItem] = []
        self.tool_calls: list[ToolCall] = []
        self.model_calls: list[ModelCall] = []
        self.errors: list[dict[str, Any]] = []
        self.bad_lines = 0
        self.bad_line_numbers: list[int] = []
        self.total_lines = 0
        self.truncated = False

        #: ``tool_call_id -> ToolCall`` for *every* call started, so the trailing
        #: ``tool_end``/``tool_result`` pair can both fill in their outcome.
        self._calls_by_id: dict[str, ToolCall] = {}
        self._step = 0
        self._model_index = 0

        self.start_time: str | None = None
        self.end_time: str | None = None
        self.status: str | None = None
        self.terminal_status: str | None = None
        self.reason: str | None = None
        self.duration_ms: int | None = None
        self.model: str | None = None
        self.session_id: str | None = None
        self.workspace: str | None = None
        self.kernel: str | None = None
        self.total_input_tokens: int | None = None
        self.total_output_tokens: int | None = None
        self.cost_usd = 0.0
        self.cost_recorded = False

        self._current_file: Path | None = None
        self._file_last_line = ""
        self._file_lines = 0

    # -- file framing ----------------------------------------------------

    def begin_file(self, path: Path) -> None:
        self._current_file = path
        self._file_lines = 0
        self._file_last_line = ""

    def end_file(self, path: Path) -> None:
        """Record whether this file ended without a trailing newline.

        A run killed mid-write leaves a partial final line. Its JSON fails to
        parse, so it is already counted in ``bad_lines``; the extra
        ``truncated`` flag distinguishes "cut off" from "corrupt but complete".
        """
        if self._file_lines and not self._file_last_line.endswith("\n"):
            self.truncated = True
        self._current_file = None

    # -- line folding ----------------------------------------------------

    def add_line(self, number: int, event: dict[str, Any] | None, raw: str) -> None:
        self.total_lines += 1
        self._file_lines += 1
        self._file_last_line = raw
        if event is None:
            self.bad_lines += 1
            self.bad_line_numbers.append(number)
            return

        name = as_str(event.get("event")) or "<missing>"
        self.event_counts[name] = self.event_counts.get(name, 0) + 1

        stamp = as_str(event.get("timestamp"))
        if stamp:
            if self.start_time is None or stamp < self.start_time:
                self.start_time = stamp
            if self.end_time is None or stamp > self.end_time:
                self.end_time = stamp

        handler = _HANDLERS.get(name)
        if handler is not None:
            handler(self, event, stamp)

    # -- event handlers --------------------------------------------------

    def _on_run_start(self, event: dict[str, Any], stamp: str | None) -> None:
        self.model = as_str(event.get("model")) or self.model
        self.session_id = as_str(event.get("session_id")) or self.session_id
        self.workspace = as_str(event.get("workspace")) or self.workspace
        self.kernel = as_str(event.get("kernel")) or self.kernel
        self._emit(
            "run_start",
            stamp,
            f"run_start model={self.model or '?'}",
            {
                "model": self.model,
                "session_id": self.session_id,
                "workspace": self.workspace,
                "kernel": self.kernel,
            },
        )

    def _on_run_end(self, event: dict[str, Any], stamp: str | None) -> None:
        self.status = as_str(event.get("status")) or self.status
        self.terminal_status = as_str(event.get("terminal_status")) or self.terminal_status
        self.reason = as_str(event.get("reason")) or self.reason
        self.duration_ms = as_int(event.get("duration_ms")) or self.duration_ms
        self.total_input_tokens = (
            as_int(event.get("total_input_tokens")) or self.total_input_tokens
        )
        self.total_output_tokens = (
            as_int(event.get("total_output_tokens")) or self.total_output_tokens
        )
        detail = {
            "status": self.status,
            "terminal_status": self.terminal_status,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }
        self._emit(
            "run_end",
            stamp,
            f"run_end status={self.status or '?'}",
            detail,
            elapsed_ms=self.duration_ms,
        )

    def _on_run_phase(self, event: dict[str, Any], stamp: str | None) -> None:
        """One kernel phase transition (``RunPhase`` value).

        Emitted only when the phase actually changes, plus once for the opening
        ``preparing`` phase, so the sequence of these items *is* the run's
        ordered phase history.
        """
        phase = as_str(event.get("phase"))
        previous = as_str(event.get("previous"))
        elapsed_ms = as_int(event.get("elapsed_ms"))
        self._emit(
            "run_phase",
            stamp,
            f"phase {previous or '-'} -> {phase or '?'}",
            {"phase": phase, "previous": previous, "elapsed_ms": elapsed_ms},
            elapsed_ms=elapsed_ms,
        )

    def _on_model_request(self, event: dict[str, Any], stamp: str | None) -> None:
        # Two shapes share the name: a pre-call estimate (input_chars/in
        # tokens/attempt, no duration) and the post-call usage row
        # (purpose/duration/out tokens/cached). Classify rather than guess.
        is_usage = any(key in event for key in _USAGE_KEYS)
        phase = "post" if is_usage else "pre"
        call = ModelCall(
            index=self._model_index,
            phase=phase,
            timestamp=stamp,
            model=as_str(event.get("model")),
            provider=as_str(event.get("provider")),
            purpose=as_str(event.get("purpose")),
            duration_ms=as_int(event.get("duration_ms")),
            input_tokens=as_int(event.get("input_tokens")),
            output_tokens=as_int(event.get("output_tokens")),
            cached_tokens=as_int(event.get("cached_tokens")),
            first_token_ms=as_int(event.get("first_token_ms")),
            attempt=as_int(event.get("attempt")),
            input_chars=as_int(event.get("input_chars")),
            cost_usd=_as_cost(event.get("cost_usd", event.get("est_cost"))),
        )
        self._model_index += 1
        self.model_calls.append(call)
        if call.cost_usd is not None:
            self.cost_usd += call.cost_usd
            self.cost_recorded = True

        if phase == "pre":
            self._emit(
                "model_call",
                stamp,
                f"model_request in={call.input_tokens if call.input_tokens is not None else '?'}t",
                {
                    "phase": "pre",
                    "model": call.model,
                    "input_tokens": call.input_tokens,
                    "input_chars": call.input_chars,
                    "attempt": call.attempt,
                },
            )
            return
        self._emit(
            "model_call",
            stamp,
            (
                f"model_response {call.duration_ms if call.duration_ms is not None else '?'}ms "
                f"out={call.output_tokens if call.output_tokens is not None else '?'}t"
                f"{'' if not call.purpose else ' purpose=' + call.purpose}"
                f"{'' if call.cost_usd is None else f' ${call.cost_usd:.4f}'}"
            ),
            {
                "phase": "post",
                "model": call.model,
                "provider": call.provider,
                "purpose": call.purpose,
                "duration_ms": call.duration_ms,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cached_tokens": call.cached_tokens,
                "first_token_ms": call.first_token_ms,
                "attempt": call.attempt,
                "cost_usd": call.cost_usd,
            },
            elapsed_ms=call.duration_ms,
        )

    def _on_model_error(self, event: dict[str, Any], stamp: str | None) -> None:
        record = {
            "event": "model_error",
            "timestamp": stamp,
            "purpose": as_str(event.get("purpose")),
            "model": as_str(event.get("model")),
            "provider": as_str(event.get("provider")),
            "category": as_str(event.get("category")),
            "status": as_int(event.get("status")),
            "retry": as_bool(event.get("retry")),
            "attempt": as_int(event.get("attempt")),
            "retry_number": as_int(event.get("retry_number")),
            "retry_delay_s": event.get("retry_delay_s"),
            "retry_kind": as_str(event.get("retry_kind")),
            "detail": as_str(event.get("detail")),
        }
        self.errors.append(record)
        self._emit(
            "error",
            stamp,
            "model_error "
            f"{record['category'] or '?'}/{record['status'] or '?'} "
            f"retry={record['retry']}",
            record,
            is_error=True,
        )

    def _on_tool_start(self, event: dict[str, Any], stamp: str | None) -> None:
        call_id = as_str(event.get("tool_call_id"))
        name = as_str(event.get("name"))
        args_len = _arguments_length(event.get("arguments"))
        signature = f"{name}#{args_len}"
        previous = self.tool_calls[-1] if self.tool_calls else None
        repeated = bool(
            previous is not None
            and previous.signature == signature
            and signature != "None#None"
        )
        call = ToolCall(
            index=len(self.tool_calls),
            tool_call_id=call_id,
            name=name,
            started_at=stamp,
            arguments_length=args_len,
            repeated=repeated,
            signature=signature,
        )
        self.tool_calls.append(call)
        if call_id:
            self._calls_by_id[call_id] = call
        self._emit(
            "tool_call",
            stamp,
            f"tool_start {name or '?'}"
            f"{' (repeat)' if repeated else ''}"
            f"{'' if args_len is None else ' args=' + str(args_len)}",
            {
                "tool_call_id": call_id,
                "name": name,
                "arguments_length": args_len,
                "repeated": repeated,
            },
            tool_name=name,
            tool_call_id=call_id,
        )

    def _on_tool_end(self, event: dict[str, Any], stamp: str | None) -> None:
        call = self._tool_for(event)
        duration = as_int(event.get("duration_ms"))
        if call is not None:
            call.ended_at = stamp
            call.duration_ms = duration
            call.state = as_str(event.get("state")) or call.state
            call.output_ref = as_str(event.get("output_ref")) or call.output_ref
            call.output_length = _output_length(event.get("output")) or call.output_length
        self._emit(
            "tool_result",
            stamp,
            f"tool_end {call.name if call else '?'} "
            f"{duration if duration is not None else '?'}ms "
            f"state={as_str(event.get('state')) or '?'}",
            {
                "tool_call_id": as_str(event.get("tool_call_id")),
                "name": as_str(event.get("name")),
                "state": as_str(event.get("state")),
                "duration_ms": duration,
                "output_ref": as_str(event.get("output_ref")),
                "output_length": _output_length(event.get("output")),
            },
            elapsed_ms=duration,
            tool_name=as_str(event.get("name")),
            tool_call_id=as_str(event.get("tool_call_id")),
        )

    def _on_tool_result(self, event: dict[str, Any], stamp: str | None) -> None:
        call = self._tool_for(event)
        is_error = as_bool(event.get("is_error"))
        if call is not None:
            if is_error is not None:
                call.is_error = is_error
            call.state = call.state or as_str(event.get("state"))
            call.output_ref = call.output_ref or as_str(event.get("output_ref"))
            call.output_length = (
                call.output_length or _output_length(event.get("output"))
            )
            if call.ended_at is None:
                call.ended_at = stamp
        self._emit(
            "tool_result",
            stamp,
            f"tool_result {as_str(event.get('name')) or '?'} "
            f"error={is_error} state={as_str(event.get('state')) or '?'}",
            {
                "tool_call_id": as_str(event.get("tool_call_id")),
                "name": as_str(event.get("name")),
                "state": as_str(event.get("state")),
                "is_error": is_error,
                "output_ref": as_str(event.get("output_ref")),
                "output_length": _output_length(event.get("output")),
            },
            is_error=is_error,
            tool_name=as_str(event.get("name")),
            tool_call_id=as_str(event.get("tool_call_id")),
        )

    def _on_tool_args_invalid(self, event: dict[str, Any], stamp: str | None) -> None:
        record = {
            "event": "tool_args_invalid",
            "timestamp": stamp,
            "name": as_str(event.get("name")),
            "error_kind": as_str(event.get("error_kind")),
            "error_pos": as_int(event.get("error_pos")),
            "detail": as_str(event.get("detail")),
        }
        self.errors.append(record)
        self._emit("error", stamp, "tool_args_invalid", record, is_error=True)

    def _on_generic(self, event: dict[str, Any], stamp: str | None) -> None:
        """Record non-timeline but reportable events (compaction, repair, ...)."""

    # -- helpers ---------------------------------------------------------

    def _tool_for(self, event: dict[str, Any]) -> ToolCall | None:
        call_id = as_str(event.get("tool_call_id"))
        if call_id:
            # Every call ever seen, not only still-open ones: the writer emits
            # tool_end *and then* tool_result for the same id, so the second row
            # must resolve even though the call already has an end time.
            found = self._calls_by_id.get(call_id)
            if found is not None:
                return found
        # No id (or an id we never saw a start for): fall back to the newest open
        # call with the same tool name, which keeps counts sane on corrupt runs.
        name = as_str(event.get("name"))
        for call in reversed(self.tool_calls):
            if call.name == name and not call.ended_at:
                return call
        return None

    def _emit(
        self,
        kind: str,
        stamp: str | None,
        label: str,
        detail: dict[str, Any],
        *,
        elapsed_ms: int | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        is_error: bool | None = None,
    ) -> None:
        self._step += 1
        self.timeline.append(
            TimelineItem(
                index=self._step,
                kind=kind,
                timestamp=stamp,
                label=label,
                detail=detail,
                elapsed_ms=elapsed_ms,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                is_error=is_error,
            )
        )

    # -- finish ----------------------------------------------------------

    def build(self, paths: list[Path]) -> Run:
        from .loader import _merge_info  # noqa: PLC0415 - avoids an import cycle

        info = _merge_info(self.run_id, paths)
        # The stream is authoritative for timing; the inventory scan can only see
        # the first and last line of each file.
        if self.start_time:
            info.start_time = self.start_time
        if self.end_time:
            info.end_time = self.end_time
        if self.status:
            info.status = self.status
        if self.duration_ms is not None:
            info.duration_ms = self.duration_ms

        return Run(
            id=self.run_id,
            paths=[str(p) for p in paths],
            info=info,
            start_time=self.start_time,
            end_time=self.end_time,
            status=self.status,
            terminal_status=self.terminal_status,
            reason=self.reason,
            duration_ms=self.duration_ms,
            model=self.model,
            session_id=self.session_id,
            workspace=self.workspace,
            kernel=self.kernel,
            total_input_tokens=self.total_input_tokens,
            total_output_tokens=self.total_output_tokens,
            cost_usd=(self.cost_usd if self.cost_recorded else None),
            timeline=self.timeline,
            tool_calls=self.tool_calls,
            model_calls=self.model_calls,
            errors=self.errors,
            event_counts=self.event_counts,
            total_lines=self.total_lines,
            bad_lines=self.bad_lines,
            bad_line_numbers=self.bad_line_numbers,
            truncated=self.truncated,
        )


_HANDLERS = {
    "run_start": RunBuilder._on_run_start,
    "run_phase": RunBuilder._on_run_phase,
    "run_end": RunBuilder._on_run_end,
    "model_request": RunBuilder._on_model_request,
    "model_error": RunBuilder._on_model_error,
    "tool_start": RunBuilder._on_tool_start,
    "tool_end": RunBuilder._on_tool_end,
    "tool_result": RunBuilder._on_tool_result,
    "tool_args_invalid": RunBuilder._on_tool_args_invalid,
}


def replay(run: Run) -> list[TimelineItem]:
    """Return the run's steps in chronological (file) order.

    Order comes from the file, not from the ``timestamp`` field: the writer
    appends under a lock, so file order is authoritative even when two events
    share a microsecond. Timestamps are still available on every item.

    The returned list is a copy, so a caller cannot corrupt the run's own state.
    """
    return list(run.timeline)
