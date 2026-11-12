"""Structured comparison of two runs, plus a text rendering of it.

``diff`` answers the tuning questions that motivated this package: *what changed
between two runs of the same task?* -- the tool sequence, where the time went,
whether the token bill moved, and whether the second run started (or stopped)
failing.
"""

from __future__ import annotations

from typing import Any, Sequence

from ._util import as_int
from .models import Run
from .summary import summarize

__all__ = ["diff", "format_diff", "format_diff_sequence"]


def _as_dict(run: Run | dict[str, Any]) -> dict[str, Any]:
    return run if isinstance(run, dict) else summarize(run)


def _delta(a: Any, b: Any) -> int | float | None:
    left, right = as_int(a), as_int(b)
    if left is None or right is None:
        return None
    return right - left


def _tool_durations(summary: dict[str, Any]) -> dict[str, int]:
    return {row["name"]: row["total_ms"] for row in summary.get("tools") or []}


def diff(run_a: Run | dict[str, Any], run_b: Run | dict[str, Any]) -> dict[str, Any]:
    """Compare two runs.

    Accepts :class:`~atlas.run_replay.models.Run` objects or already-summarised
    dicts (so the CLI can compare without loading both into memory at once).

    Returns a dict with these keys:

    ``run_a`` / ``run_b``      identifying fields of each side.
    ``summary_delta``          ``wall_ms``, ``model_ms``, ``tool_ms``,
                               ``tool_calls``, ``model_calls``, ``steps``,
                               ``tool_failures`` -- each ``{"a", "b", "delta"}``.
    ``tokens``                 ``{"a": {...}, "b": {...}, "delta": {...}}``.
    ``tools``                  per-tool call/duration/failure comparison.
    ``sequence``               tool sequence diff: ``common_prefix``,
                               ``added``, ``removed``, ``order_changes``,
                               ``a`` and ``b`` signature lists.
    ``outcome``                status / failure-count difference.
    ``verdict``                one-line human summary.
    """
    left = _as_dict(run_a)
    right = _as_dict(run_b)

    timing_a = left.get("timing") or {}
    timing_b = right.get("timing") or {}

    pairs = {
        "wall_ms": (left.get("wall_ms"), right.get("wall_ms")),
        "model_ms": (timing_a.get("model_ms"), timing_b.get("model_ms")),
        "tool_ms": (timing_a.get("tool_ms"), timing_b.get("tool_ms")),
        "tool_calls": (left.get("tool_calls"), right.get("tool_calls")),
        "model_calls": (left.get("model_calls"), right.get("model_calls")),
        "steps": (left.get("steps"), right.get("steps")),
        "tool_failures": (left.get("tool_failures"), right.get("tool_failures")),
        "errors": (left.get("error_events"), right.get("error_events")),
    }
    summary_delta = {
        key: {"a": a, "b": b, "delta": _delta(a, b)} for key, (a, b) in pairs.items()
    }

    tokens_a = left.get("tokens") or {}
    tokens_b = right.get("tokens") or {}
    tokens = {
        "a": dict(tokens_a),
        "b": dict(tokens_b),
        "delta": {
            key: _delta(tokens_a.get(key), tokens_b.get(key))
            for key in ("input", "output", "cached")
        },
    }

    durations_a = _tool_durations(left)
    durations_b = _tool_durations(right)
    calls_a = {row["name"]: row["calls"] for row in left.get("tools") or []}
    calls_b = {row["name"]: row["calls"] for row in right.get("tools") or []}
    fails_a = {row["name"]: row["failures"] for row in left.get("tools") or []}
    fails_b = {row["name"]: row["failures"] for row in right.get("tools") or []}
    tools: dict[str, Any] = {}
    for name in sorted(set(durations_a) | set(durations_b) | set(calls_a) | set(calls_b)):
        entry = {
            "calls": {"a": calls_a.get(name, 0), "b": calls_b.get(name, 0)},
            "failures": {"a": fails_a.get(name, 0), "b": fails_b.get(name, 0)},
            "total_ms": {
                "a": durations_a.get(name, 0),
                "b": durations_b.get(name, 0),
            },
        }
        entry["calls"]["delta"] = entry["calls"]["b"] - entry["calls"]["a"]
        entry["failures"]["delta"] = entry["failures"]["b"] - entry["failures"]["a"]
        entry["total_ms"]["delta"] = entry["total_ms"]["b"] - entry["total_ms"]["a"]
        tools[name] = entry

    sequence = _diff_sequence(left.get("tool_sequence"), right.get("tool_sequence"))

    outcome = {
        "status": {"a": left.get("status"), "b": right.get("status")},
        "reason": {"a": left.get("reason"), "b": right.get("reason")},
        "terminal_status": {
            "a": left.get("terminal_status"),
            "b": right.get("terminal_status"),
        },
        "became_worse": bool(
            (left.get("status") == "completed" and right.get("status") != "completed")
            or (right.get("tool_failures") or 0) > (left.get("tool_failures") or 0)
        ),
        "became_better": bool(
            (left.get("status") != "completed" and right.get("status") == "completed")
        ),
    }

    return {
        "run_a": {
            "id": left.get("run_id"),
            "files": left.get("files"),
            "status": left.get("status"),
            "wall_ms": left.get("wall_ms"),
        },
        "run_b": {
            "id": right.get("run_id"),
            "files": right.get("files"),
            "status": right.get("status"),
            "wall_ms": right.get("wall_ms"),
        },
        "summary_delta": summary_delta,
        "tokens": tokens,
        "tools": tools,
        "sequence": sequence,
        "outcome": outcome,
        "verdict": _verdict(left, right, summary_delta, token_delta=tokens["delta"]),
    }


def _diff_sequence(
    seq_a: list[str] | None, seq_b: list[str] | None
) -> dict[str, Any]:
    """Tool-call sequence comparison.

    Compares the *tool signatures* (name + redacted argument length) in order. The
    full log carries no argument text, so this detects "the same tools ran in a
    different order / one ran extra", not "the same tool ran with different
    content".
    """
    a = list(seq_a or [])
    b = list(seq_b or [])

    prefix = 0
    for left, right in zip(a, b):
        if left != right:
            break
        prefix += 1

    suffix = 0
    while (
        suffix < len(a) - prefix
        and suffix < len(b) - prefix
        and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]
    ):
        suffix += 1

    removed = a[prefix : len(a) - suffix if suffix else len(a)]
    added = b[prefix : len(b) - suffix if suffix else len(b)]

    # Order changes: signatures present in both runs whose relative position moved.
    order_changes: list[dict[str, Any]] = []
    index_b = {sig: i for i, sig in enumerate(b)}
    seen: set[str] = set()
    for i, sig in enumerate(a):
        if sig in seen or sig not in index_b:
            continue
        seen.add(sig)
        j = index_b[sig]
        if i != j and i < len(b) and b[i] != sig:
            order_changes.append({"signature": sig, "a_index": i, "b_index": j})

    return {
        "a": a,
        "b": b,
        "common_prefix": prefix,
        "added": added,
        "removed": removed,
        "order_changes": order_changes[:20],
        "identical": a == b,
    }


def _verdict(
    left: dict[str, Any],
    right: dict[str, Any],
    summary_delta: dict[str, Any],
    token_delta: dict[str, Any],
) -> str:
    parts: list[str] = []
    wall = summary_delta.get("wall_ms", {}).get("delta")
    if wall is not None:
        if wall == 0:
            parts.append("wall time unchanged")
        else:
            direction = "slower" if wall > 0 else "faster"
            parts.append(f"B is {_ms(abs(wall))} {direction}")
    calls = summary_delta.get("tool_calls", {}).get("delta")
    if calls:
        parts.append(f"{'+' if calls > 0 else ''}{calls} tool calls")
    out = token_delta.get("output")
    if out:
        parts.append(f"{'+' if out > 0 else ''}{out} output tokens")
    if left.get("status") != right.get("status"):
        parts.append(f"status {left.get('status')} -> {right.get('status')}")
    fails = summary_delta.get("tool_failures", {}).get("delta")
    if fails:
        parts.append(f"{'+' if fails > 0 else ''}{fails} tool failures")
    return "; ".join(parts) if parts else "no material difference"


def format_diff(result: dict[str, Any], max_rows: int = 8) -> str:
    """Render :func:`diff` output as a plain-text table."""
    lines: list[str] = []
    add = lines.append

    run_a = result.get("run_a") or {}
    run_b = result.get("run_b") or {}
    add(f"A  {run_a.get('id')}  status={run_a.get('status') or '?'}  {_ms(run_a.get('wall_ms'))}")
    add(f"B  {run_b.get('id')}  status={run_b.get('status') or '?'}  {_ms(run_b.get('wall_ms'))}")
    add("")
    add("metric                     A            B         delta")
    for key, label, as_duration in (
        ("wall_ms", "wall", True),
        ("model_ms", "model time", True),
        ("tool_ms", "tool time", True),
        ("steps", "replay steps", False),
        ("model_calls", "model responses", False),
        ("tool_calls", "tool calls", False),
        ("tool_failures", "tool failures", False),
        ("errors", "error events", False),
    ):
        entry = (result.get("summary_delta") or {}).get(key) or {}
        render = _ms if as_duration else _cell
        add(
            f"{label:<20}"
            f"{render(entry.get('a')):>12}"
            f"{render(entry.get('b')):>13}"
            f"{render(entry.get('delta')):>14}"
        )

    tokens = result.get("tokens") or {}
    tok_a = tokens.get("a") or {}
    tok_b = tokens.get("b") or {}
    tok_d = tokens.get("delta") or {}
    if any(tok_a.get(k) is not None or tok_b.get(k) is not None for k in ("input", "output")):
        add("")
        add("tokens                     A            B         delta")
        for key, label in (("input", "input"), ("output", "output"), ("cached", "cached")):
            add(
                f"{label:<20}"
                f"{_cell(tok_a.get(key)):>12}"
                f"{_cell(tok_b.get(key)):>13}"
                f"{_cell(tok_d.get(key)):>14}"
            )

    tools = result.get("tools") or {}
    changed = {
        name: row
        for name, row in tools.items()
        if row["calls"]["delta"] or row["total_ms"]["delta"] or row["failures"]["delta"]
    }
    add("")
    add(f"tool deltas ({len(changed)} changed of {len(tools)})")
    if not changed:
        add("  (none)")
    else:
        add(
            f"  {'tool':<20}"
            f"{'calls A > B':>15}"
            f"{'total A > B':>30}"
            f"{'fail A > B':>16}"
        )
        ordered = sorted(
            changed.items(), key=lambda kv: -abs(kv[1]["total_ms"]["delta"])
        )
        for name, row in ordered[:max_rows]:
            add(
                f"  {name[:19]:<20}"
                f"{_pair(row['calls'], ms=False):>15}"
                f"{_pair(row['total_ms'], ms=True):>30}"
                f"{_pair(row['failures'], ms=False):>16}"
            )

    sequence = result.get("sequence") or {}
    add("")
    add("tool sequence")
    add(f"  A steps: {len(sequence.get('a') or [])}   B steps: {len(sequence.get('b') or [])}")
    add(f"  shared prefix: {sequence.get('common_prefix')} calls")
    if sequence.get("identical"):
        add("  sequences are identical")
    else:
        added = sequence.get("added") or []
        removed = sequence.get("removed") or []
        if added:
            add(f"  added in B ({len(added)}): {_preview(added, max_rows)}")
        if removed:
            add(f"  missing in B ({len(removed)}): {_preview(removed, max_rows)}")
        for change in (sequence.get("order_changes") or [])[:max_rows]:
            add(
                f"  moved: {change['signature']} "
                f"at A#{change['a_index']} -> B#{change['b_index']}"
            )

    outcome = result.get("outcome") or {}
    add("")
    add(
        "outcome  "
        f"{outcome.get('status', {}).get('a')} -> {outcome.get('status', {}).get('b')}"
        + (
            f"  reason {outcome.get('reason', {}).get('a')} -> {outcome.get('reason', {}).get('b')}"
            if outcome.get("reason", {}).get("a") != outcome.get("reason", {}).get("b")
            else ""
        )
    )
    if outcome.get("became_worse"):
        add("  !! B looks worse than A")
    if outcome.get("became_better"):
        add("  ++ B looks better than A")
    add("")
    add(f"verdict  {result.get('verdict')}")
    return "\n".join(lines)


def format_diff_sequence(signatures: Sequence[str], max_rows: int = 40) -> str:
    """Render one signature list (used by the ``replay`` CLI verb)."""
    lines = [f"{i:>4}  {sig}" for i, sig in enumerate(signatures[:max_rows])]
    if len(signatures) > max_rows:
        lines.append(f"   ... {len(signatures) - max_rows} more")
    return "\n".join(lines)


def _pair(entry: dict[str, Any], ms: bool = False) -> str:
    render = _ms if ms else _cell
    return f"{render(entry.get('a'))} > {render(entry.get('b'))} ({render(entry.get('delta'))})"


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    number = as_int(value)
    if number is not None:
        return f"{number:,}"
    return str(value)


def _preview(items: Sequence[str], limit: int) -> str:
    shown = list(items[:limit])
    suffix = f" (+{len(items) - limit} more)" if len(items) > limit else ""
    return ", ".join(shown) + suffix


def _ms(value: Any) -> str:
    number = as_int(value)
    if number is None:
        return "-"
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    if magnitude >= 1000:
        return f"{sign}{magnitude / 1000.0:.1f}s"
    return f"{sign}{magnitude}ms"
