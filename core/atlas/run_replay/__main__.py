"""Plain-text CLI: ``python -m atlas.run_replay <verb> ...``

Verbs
-----
``list``  newest-first table of runs.
``show``  full summary of one run, plus its tool timeline.
``diff``  comparison of two runs.

Read-only by construction: the only file operations performed are directory
listings and ``open(path, "r")``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from .diffing import diff as diff_runs
from .diffing import format_diff
from .loader import RunNotFoundError, list_runs, load_run
from .models import RunInfo
from .summary import format_summary, summarize


def _ms(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "-"
    if number >= 1000:
        return f"{number / 1000.0:.1f}s"
    return f"{number}ms"


def _cmd_list(args: argparse.Namespace) -> int:
    runs = list_runs(limit=None if args.all else args.limit, runs_dir=args.runs_dir)
    if not runs:
        print("no runs found", file=sys.stdout)
        return 0
    print(
        f"{'started':<26}{'status':<13}{'events':>8}{'size':>10}{'dur':>9}  id"
    )
    for info in runs:
        print(
            f"{_short_time(info.start_time):<26}"
            f"{(info.status or '-'):<13}"
            f"{info.event_count:>8}"
            f"{_size(info.size):>10}"
            f"{_ms(info.duration_ms):>9}  {info.id}"
        )
    print(f"\n{len(runs)} run(s)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    run = load_run(args.target, runs_dir=args.runs_dir)
    summary = summarize(run, loop_threshold=args.loop_threshold)
    print(format_summary(summary, top=args.top))

    if args.timeline:
        print("")
        print(f"timeline (first {args.timeline} steps)")
        header = f"{'#':>4}  {'kind':<12}{'at':<14}{'label'}"
        print(header)
        print("-" * len(header))
        for item in run.timeline[: args.timeline]:
            print(
                f"{item.index:>4}  {item.kind:<12}"
                f"{_clock(item.timestamp):<14}{item.label}"
            )
        if len(run.timeline) > args.timeline:
            print(f"   ... {len(run.timeline) - args.timeline} more steps")

    if args.tools:
        print("")
        print(f"tool call sequence ({len(run.tool_calls)} calls)")
        for call in run.tool_calls[: args.tools]:
            flag = " (repeat)" if call.repeated else ""
            print(
                f"{call.index:>4}  {str(call.name)[:22]:<23}"
                f"{_ms(call.duration_ms):>9}"
                f"  {(call.state or '-'):<11}"
                f"{'FAIL' if call.is_error else '    '}"
                f"{flag}"
            )
        if len(run.tool_calls) > args.tools:
            print(f"   ... {len(run.tool_calls) - args.tools} more calls")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    a = summarize(load_run(args.run_a, runs_dir=args.runs_dir))
    b = summarize(load_run(args.run_b, runs_dir=args.runs_dir))
    print(format_diff(diff_runs(a, b), max_rows=args.top))
    return 0


def _short_time(stamp: str | None) -> str:
    if not stamp:
        return "-"
    return stamp.replace("T", " ")[:23]


def _clock(stamp: str | None) -> str:
    if not stamp:
        return "-"
    text = stamp.replace("T", " ")
    return text[11:23] if len(text) >= 23 else text


def _size(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f}M"
    if value >= 1024:
        return f"{value / 1024:.0f}K"
    return f"{value}B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas.run_replay",
        description="Read-only replay, summary and diff of Atlas run event logs.",
    )
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="run log directory (default: <data>/logs/runs, or $ATLAS_RUNS_DIR)",
    )
    sub = parser.add_subparsers(dest="verb", required=True)

    p_list = sub.add_parser("list", help="list runs, newest first")
    p_list.add_argument("limit", nargs="?", type=int, default=20)
    p_list.add_argument("--all", action="store_true", help="ignore the limit")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="summarize one run")
    p_show.add_argument("target", help="run id or path to a .jsonl file")
    p_show.add_argument("--top", type=int, default=10)
    p_show.add_argument(
        "--timeline", type=int, default=None, help="also print N timeline steps"
    )
    p_show.add_argument(
        "--tools", type=int, default=None, help="also print N tool calls"
    )
    p_show.add_argument("--loop-threshold", type=int, default=3)
    p_show.set_defaults(func=_cmd_show)

    p_diff = sub.add_parser("diff", help="compare two runs")
    p_diff.add_argument("run_a")
    p_diff.add_argument("run_b")
    p_diff.add_argument("--top", type=int, default=8)
    p_diff.set_defaults(func=_cmd_diff)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except RunNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
