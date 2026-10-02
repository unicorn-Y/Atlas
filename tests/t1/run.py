#!/usr/bin/env python3
"""Run offline T1 preparation checks or an explicitly enabled participant run."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from harness.runner import PARTICIPANTS, execute, _load_config  # noqa: E402


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="T1 benchmark harness")
    p.add_argument("--participant", choices=PARTICIPANTS, default="fake")
    p.add_argument("--task", help="task id, comma list, range, or omit for all tasks")
    p.add_argument("--repeat", type=int)
    p.add_argument("--track", choices=("same-model", "best"), default="same-model")
    p.add_argument("--model")
    p.add_argument("--dry-run", action="store_true", help="show a redacted command; never set up fixtures or execute the adapter")
    p.add_argument("--allow-real", action="store_true", help="permit a real adapter to run; default is denied")
    p.add_argument("--budget-usd", type=float)
    p.add_argument("--output")
    p.add_argument("--timeout-seconds", type=float)
    p.add_argument("--config", help="TOML config; defaults to no overrides")
    p.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--summary", action="store_true", help="summarize existing result JSON files and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = _load_config(Path(args.config) if args.config else None)
    track = config.get("tracks", {}).get(args.track, {})
    args.repeat = args.repeat if args.repeat is not None else int(track.get("repetitions", config.get("repetitions", 1)))
    args.output = args.output or config.get("result_dir") or str(ROOT / "results" / "runs")
    args.budget_usd = args.budget_usd if args.budget_usd is not None else track.get("budget_usd", config.get("budget_usd"))
    args.timeout_seconds = args.timeout_seconds if args.timeout_seconds is not None else track.get("timeout_seconds", config.get("timeout_seconds"))
    if args.timeout_seconds is not None and (args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds)):
        parser().error("--timeout-seconds must be positive")
    if args.repeat < 1:
        parser().error("--repeat must be at least 1")
    if args.budget_usd is not None and (args.budget_usd < 0 or not math.isfinite(args.budget_usd)):
        parser().error("--budget-usd cannot be negative")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
