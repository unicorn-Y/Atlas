#!/usr/bin/env python3
"""Summarize Atlas context and handoff events from a dated run-log directory."""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def read_events(paths: Iterable[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(item, dict) and isinstance(item.get("event"), str):
                        events.append(item)
        except OSError:
            continue
    return events


def summarize(events: Iterable[dict[str, Any]], *, top: int = 5) -> dict[str, Any]:
    rows = list(events)
    requests = [row for row in rows if row.get("event") == "model_request"]
    primary = [row for row in requests if row.get("purpose", "conversation") == "conversation"]
    primary_inputs = [n for row in primary if (n := _number(row.get("input_tokens"))) is not None]
    purpose_totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in requests:
        purpose = str(row.get("purpose") or "unknown")
        input_tokens, cached_tokens = (
            _number(row.get("input_tokens")),
            _number(row.get("cached_tokens")),
        )
        if input_tokens is not None:
            purpose_totals[purpose][0] += input_tokens
            purpose_totals[purpose][1] += min(input_tokens, cached_tokens or 0.0)
    cache_hit = {
        purpose: {
            "input_tokens": int(total),
            "cached_tokens": int(cached),
            "hit_rate": cached / total if total else None,
        }
        for purpose, (total, cached) in sorted(purpose_totals.items())
    }

    compactions = [row for row in rows if row.get("event") == "compaction"]
    methods: dict[str, list[float]] = defaultdict(list)
    for row in compactions:
        method = str(row.get("method") or "unknown")
        before, after = _number(row.get("before_tokens")), _number(row.get("after_tokens"))
        if before and after is not None:
            methods[method].append(after / before)
    compaction_methods = {
        method: {
            "count": sum(1 for row in compactions if str(row.get("method") or "unknown") == method),
            "average_compression_ratio": (sum(ratios) / len(ratios)) if ratios else None,
        }
        for method, ratios in sorted(methods.items())
    }
    for row in compactions:
        method = str(row.get("method") or "unknown")
        compaction_methods.setdefault(method, {"count": 0, "average_compression_ratio": None})
        if method not in methods:
            compaction_methods[method]["count"] += 1
    ineffective = sum(
        1
        for row in compactions
        if (_number(row.get("ineffective_streak")) or 0) > 0
        or (
            (_number(row.get("before_tokens")) or 0) > 0
            and (_number(row.get("after_tokens")) or 0) >= (_number(row.get("before_tokens")) or 0)
        )
    )
    handoffs = [row for row in rows if row.get("event") == "handoff"]
    accepted = sum(row.get("accepted") is True for row in handoffs)
    reasons = Counter(
        str(row.get("category") or row.get("error") or "unknown")
        for row in rows
        if row.get("event") == "model_error"
    )
    inputs_sorted = sorted(primary_inputs)
    return {
        "primary_request_count": len(primary),
        "primary_input_tokens": {
            "count": len(inputs_sorted),
            "median": statistics.median(inputs_sorted) if inputs_sorted else None,
            "p75": (
                statistics.quantiles(inputs_sorted, n=4, method="inclusive")[2]
                if len(inputs_sorted) > 1
                else inputs_sorted[0]
                if inputs_sorted
                else None
            ),
        },
        "cache_hit_by_purpose": cache_hit,
        "compactions_by_method": compaction_methods,
        "ineffective_compactions": ineffective,
        "quality_guard_rejections": sum(
            row.get("method") == "guard_rejected" for row in compactions
        ),
        "handoffs": {
            "count": len(handoffs),
            "accepted": accepted,
            "acceptance_rate": accepted / len(handoffs) if handoffs else None,
        },
        "model_error_top_reasons": reasons.most_common(max(0, top)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", default=datetime.now(UTC).date().isoformat(), help="UTC log date (YYYY-MM-DD)"
    )
    data_root = Path(os.environ.get("ATLAS_DATA_DIR") or Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=data_root / "data" / "logs" / "runs",
        help="Root containing YYYY-MM-DD run directories",
    )
    parser.add_argument("--top", type=int, default=5, help="Number of model error reasons to show")
    args = parser.parse_args()
    directory = args.runs_dir / args.date
    result = summarize(read_events(directory.glob("*.jsonl")), top=max(0, args.top))
    print(f"Context stats for {args.date} ({directory})")
    print(f"Primary requests: {result['primary_request_count']}")
    values = result["primary_input_tokens"]
    print(
        f"Primary input tokens: median={values['median']} P75={values['p75']} n={values['count']}"
    )
    print("Cache hit by purpose:")
    for purpose, stats in result["cache_hit_by_purpose"].items():
        rate = "n/a" if stats["hit_rate"] is None else f"{stats['hit_rate']:.1%}"
        print(f"  {purpose}: {rate} ({stats['cached_tokens']}/{stats['input_tokens']})")
    print("Compactions by method:")
    for method, stats in result["compactions_by_method"].items():
        ratio = (
            "n/a"
            if stats["average_compression_ratio"] is None
            else f"{stats['average_compression_ratio']:.1%}"
        )
        print(f"  {method}: {stats['count']} average_after/before={ratio}")
    print(f"Ineffective compactions: {result['ineffective_compactions']}")
    print(f"Quality guard rejections: {result['quality_guard_rejections']}")
    handoffs = result["handoffs"]
    rate = "n/a" if handoffs["acceptance_rate"] is None else f"{handoffs['acceptance_rate']:.1%}"
    print(f"Handoffs: {handoffs['count']} accepted={handoffs['accepted']} acceptance_rate={rate}")
    print("Model error top reasons:")
    for reason, count in result["model_error_top_reasons"]:
        print(f"  {reason}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
