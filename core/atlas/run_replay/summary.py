"""Aggregate reporting for one run: durations, tokens, failures, stuck loops.

Everything returned here is derived from the events actually present in the log.
Missing information yields ``None`` rather than ``0`` -- important, because
``model_request`` is written twice per turn and only the post-call row carries a
duration, and old runs predate some fields entirely. Reporting ``0`` for "not
recorded" would silently turn a gap into a measurement.
"""

from __future__ import annotations

from typing import Any

from ._util import as_int
from .models import Run

__all__ = ["summarize", "format_summary"]

#: A run repeating the same tool with the same redacted argument length this many
#: times in a row is treated as a probable stuck loop.
DEFAULT_LOOP_THRESHOLD = 3


def _time_share(part: int | None, whole: int | None) -> float | None:
    if part is None or whole is None or whole <= 0:
        return None
    return round(part / whole * 100.0, 1)


def summarize(run: Run, loop_threshold: int = DEFAULT_LOOP_THRESHOLD) -> dict[str, Any]:
    """Build the tuning report for ``run``.

    Keys (all always present, values may be ``None``):

    ``steps`` / ``model_calls`` / ``tool_calls`` / ``errors``
        Counts. ``model_calls`` counts **post-call usage rows** only, i.e. real
        model responses; the pre-call estimate rows are exposed separately as
        ``model_requests``.
    ``tools``
        Per-tool rows sorted by total duration descending: ``name``, ``calls``,
        ``failures``, ``total_ms``, ``mean_ms``, ``max_ms``, ``missing_duration``.
    ``timing``
        ``wall_ms``, ``model_ms``, ``tool_ms``, ``model_share_pct``,
        ``tool_share_pct``, ``unaccounted_ms`` plus the ``*_coverage`` counts that
        say how many calls actually carried a duration.
    ``tokens``
        Totals plus whether they are ``None`` because no row recorded them.
    ``stuck_loops``
        Consecutive identical tool invocations, strongest first.
    """
    tools: dict[str, dict[str, Any]] = {}
    tool_total_ms = 0
    tool_with_duration = 0
    failures = 0

    for call in run.tool_calls:
        name = call.name or "<unknown>"
        row = tools.setdefault(
            name,
            {
                "name": name,
                "calls": 0,
                "failures": 0,
                "total_ms": 0,
                "max_ms": 0,
                "missing_duration": 0,
            },
        )
        row["calls"] += 1
        failed = call.is_error is True or (
            call.is_error is None
            and call.state is not None
            and call.state not in {"completed", "exited"}
        )
        if failed:
            row["failures"] += 1
            failures += 1
        duration = as_int(call.duration_ms)
        if duration is None:
            row["missing_duration"] += 1
        else:
            row["total_ms"] += duration
            row["max_ms"] = max(row["max_ms"], duration)
            tool_total_ms += duration
            tool_with_duration += 1

    tool_rows: list[dict[str, Any]] = []
    for row in tools.values():
        measured = row["calls"] - row["missing_duration"]
        tool_rows.append(
            {
                "name": row["name"],
                "calls": row["calls"],
                "failures": row["failures"],
                "total_ms": row["total_ms"],
                "mean_ms": (round(row["total_ms"] / measured, 1) if measured else None),
                "max_ms": row["max_ms"],
                "missing_duration": row["missing_duration"],
            }
        )
    tool_rows.sort(key=lambda r: (-r["total_ms"], -r["calls"], r["name"]))

    # Model time: post-call rows only (pre-call rows have no duration at all).
    post_calls = [c for c in run.model_calls if c.phase == "post"]
    model_total_ms = sum(
        d for d in (as_int(c.duration_ms) for c in post_calls) if d is not None
    )
    model_with_duration = sum(1 for c in post_calls if as_int(c.duration_ms) is not None)

    # Tokens: prefer the run_end totals (kernel-computed), else sum the rows.
    in_tokens: int | None = run.total_input_tokens
    out_tokens: int | None = run.total_output_tokens
    if in_tokens is None:
        values = [as_int(c.input_tokens) for c in post_calls if as_int(c.input_tokens) is not None]
        in_tokens = sum(values) if values else None
    if out_tokens is None:
        values = [
            as_int(c.output_tokens) for c in post_calls if as_int(c.output_tokens) is not None
        ]
        out_tokens = sum(values) if values else None
    cached_tokens: int | None
    cached_values = [
        as_int(c.cached_tokens) for c in post_calls if as_int(c.cached_tokens) is not None
    ]
    cached_tokens = sum(cached_values) if cached_values else None

    # Cost: only what the kernel recorded at call time. Nothing is recomputed
    # here -- the price table moves, and a report must not rewrite history.
    cost_values = [c.cost_usd for c in post_calls if c.cost_usd is not None]
    cost_total: float | None = round(sum(cost_values), 6) if cost_values else None
    cost_calls = len(cost_values)

    wall_ms = as_int(run.duration_ms)
    if wall_ms is None:
        started = run.start_time
        ended = run.end_time
        from ._util import parse_ts_ms  # noqa: PLC0415 - local, avoids import cost

        start_ms, end_ms = parse_ts_ms(started), parse_ts_ms(ended)
        if start_ms is not None and end_ms is not None and end_ms >= start_ms:
            wall_ms = int(end_ms - start_ms)

    accounted = (model_total_ms or 0) + (tool_total_ms or 0)
    unaccounted = None
    if wall_ms is not None:
        unaccounted = max(0, wall_ms - accounted)

    def _bucket(category: str | None) -> str:
        return category or "<none>"

    error_categories: dict[str, int] = {}
    retries = 0
    for error in run.errors:
        if error.get("event") != "model_error":
            continue
        category = _bucket(error.get("category"))
        error_categories[category] = error_categories.get(category, 0) + 1
        if error.get("retry") is True:
            retries += 1

    stuck = _stuck_loops(run, threshold=loop_threshold)

    return {
        "run_id": run.id,
        "path": run.paths[0] if run.paths else None,
        "files": list(run.paths),
        "status": run.status,
        "terminal_status": run.terminal_status,
        "reason": run.reason,
        "model": run.model,
        "session_id": run.session_id,
        "start_time": run.start_time,
        "end_time": run.end_time,
        "wall_ms": wall_ms,
        "steps": len(run.timeline),
        "model_calls": len(post_calls),
        "model_requests": len(run.model_calls),
        "tool_calls": len(run.tool_calls),
        "tool_failures": failures,
        "error_events": len(run.errors),
        "error_categories": error_categories,
        "retries": retries,
        "tools": tool_rows,
        "timing": {
            "wall_ms": wall_ms,
            "model_ms": model_total_ms if model_with_duration else None,
            "tool_ms": tool_total_ms if tool_with_duration else None,
            "model_share_pct": _time_share(
                model_total_ms if model_with_duration else None, wall_ms
            ),
            "tool_share_pct": _time_share(
                tool_total_ms if tool_with_duration else None, wall_ms
            ),
            "unaccounted_ms": unaccounted,
            "model_calls_with_duration": model_with_duration,
            "tool_calls_with_duration": tool_with_duration,
        },
        "tokens": {
            "input": in_tokens,
            "output": out_tokens,
            "cached": cached_tokens,
            "recorded": in_tokens is not None or out_tokens is not None,
        },
        "cost": {
            # ``None`` (not 0.0) when no call carried a recorded cost: a run from
            # an older archive must never look free.
            "total_usd": cost_total,
            "recorded": cost_total is not None,
            "calls_with_cost": cost_calls,
            "model_calls": len(post_calls),
        },
        # Ordered kernel phase history; empty for archives written before the
        # kernel emitted ``run_phase``.
        "phases": [str(item.detail.get("phase")) for item in run.timeline
                   if item.kind == "run_phase" and item.detail.get("phase")],
        "stuck_loops": stuck,
        # Compact, ordered list of tool signatures (name + redacted arg length).
        # ``diff`` compares these; keeping them here lets two runs be compared
        # from summaries alone, without either Run staying in memory.
        "tool_sequence": [call.signature or f"{call.name}#{call.arguments_length}" for call in run.tool_calls],
        "bad_lines": run.bad_lines,
        "truncated": run.truncated,
        "event_counts": dict(
            sorted(run.event_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def _stuck_loops(run: Run, threshold: int) -> list[dict[str, Any]]:
    """Find runs of consecutive tool calls with an identical signature.

    Signature = tool name + redacted argument length. Argument *text* is not on
    disk (``atlas/logs.py`` replaces it with ``{"length": N}``), so this is a
    strong heuristic rather than an exact comparison; it is documented as such.
    """
    if threshold < 2:
        threshold = 2
    loops: list[dict[str, Any]] = []
    current_start = 0
    for index in range(1, len(run.tool_calls) + 1):
        ended = index == len(run.tool_calls)
        same = (
            not ended
            and run.tool_calls[index].signature == run.tool_calls[current_start].signature
        )
        if same:
            continue
        length = index - current_start
        if length >= threshold:
            first = run.tool_calls[current_start]
            last = run.tool_calls[index - 1]
            loops.append(
                {
                    "tool": first.name,
                    "signature": first.signature,
                    "repeats": length,
                    "first_index": current_start,
                    "last_index": index - 1,
                    "first_at": first.started_at,
                    "last_at": last.started_at,
                    "failures": sum(
                        1
                        for call in run.tool_calls[current_start:index]
                        if call.is_error is True
                    ),
                }
            )
        current_start = index
    loops.sort(key=lambda item: (-item["repeats"], item["first_index"]))
    return loops


def format_summary(summary: dict[str, Any], top: int = 10) -> str:
    """Render :func:`summarize` output as a plain-text report for the CLI."""
    lines: list[str] = []
    add = lines.append

    add(f"run       {summary.get('run_id')}")
    for path in summary.get("files") or []:
        add(f"file      {path}")
    add(
        "status    "
        f"{summary.get('status') or '?'}"
        f"{'' if not summary.get('reason') else ' (' + str(summary['reason']) + ')'}"
        f"{'' if not summary.get('terminal_status') else ' [' + str(summary['terminal_status']) + ']'}"
    )
    add(f"model     {summary.get('model') or '?'}")
    add(f"window    {summary.get('start_time') or '?'} -> {summary.get('end_time') or '?'}")

    wall = summary.get("wall_ms")
    add(f"wall      {_ms(wall)}")
    add(
        f"steps     {summary.get('steps')} replay items; "
        f"{summary.get('model_calls')} model responses; "
        f"{summary.get('tool_calls')} tool calls"
    )

    timing = summary.get("timing") or {}
    add("")
    add("time split")
    add(
        f"  model   {_ms(timing.get('model_ms'))}  "
        f"{_pct(timing.get('model_share_pct'))}  "
        f"({timing.get('model_calls_with_duration')}/{summary.get('model_calls')} calls measured)"
    )
    add(
        f"  tool    {_ms(timing.get('tool_ms'))}  "
        f"{_pct(timing.get('tool_share_pct'))}  "
        f"({timing.get('tool_calls_with_duration')}/{summary.get('tool_calls')} calls measured)"
    )
    add(f"  other   {_ms(timing.get('unaccounted_ms'))}  (wall - model - tool)")

    tokens = summary.get("tokens") or {}
    add("")
    if tokens.get("recorded"):
        add(f"tokens    in={tokens.get('input')} out={tokens.get('output')} cached={tokens.get('cached')}")
    else:
        add("tokens    not recorded in this run (no token fields on any row)")

    cost = summary.get("cost") or {}
    if cost.get("recorded"):
        add(
            f"cost      ${cost.get('total_usd')} estimated "
            f"({cost.get('calls_with_cost')}/{cost.get('model_calls')} calls priced)"
        )
    else:
        add("cost      not recorded in this run (no cost field on any model call)")

    phases = summary.get("phases") or []
    add("")
    add(f"phases    {' -> '.join(phases) if phases else '(not recorded)'}")

    add("")
    add(f"errors    {summary.get('error_events')} error events, {summary.get('retries')} retried")
    for category, count in sorted(
        (summary.get("error_categories") or {}).items(), key=lambda kv: -kv[1]
    ):
        add(f"  {category:<24} {count}")

    tool_rows = summary.get("tools") or []
    add("")
    add(f"tools by total duration (top {min(top, len(tool_rows))} of {len(tool_rows)})")
    if not tool_rows:
        add("  (none)")
    else:
        add(f"  {'tool':<22}{'calls':>6}{'fail':>6}{'total':>10}{'mean':>10}{'max':>10}")
        for row in tool_rows[:top]:
            add(
                f"  {row['name'][:21]:<22}"
                f"{row['calls']:>6}"
                f"{row['failures']:>6}"
                f"{_ms(row['total_ms']):>10}"
                f"{_ms(row['mean_ms']):>10}"
                f"{_ms(row['max_ms']):>10}"
            )

    loops = summary.get("stuck_loops") or []
    add("")
    if loops:
        add(f"stuck-loop candidates ({len(loops)})")
        for loop in loops[:5]:
            add(
                f"  {loop['tool']} x{loop['repeats']} "
                f"(args len {loop['signature'].split('#')[-1]}, "
                f"{loop['failures']} failed) at steps "
                f"{loop['first_index']}..{loop['last_index']}"
            )
    else:
        add("stuck-loop candidates: none")

    if summary.get("bad_lines"):
        add("")
        add(f"damaged lines skipped: {summary['bad_lines']}")
    if summary.get("truncated"):
        add("note: the log's final line was not newline-terminated (run cut off?)")

    return "\n".join(lines)


def _ms(value: Any) -> str:
    number = as_int(value)
    if number is None:
        return "-"
    if number >= 1000:
        return f"{number / 1000.0:.1f}s"
    return f"{number}ms"


def _pct(value: Any) -> str:
    if value is None:
        return "  -  "
    return f"{value:.1f}%"
