#!/usr/bin/env python3
"""Estimate model-independent LongMemEval Observer token bounds; proxy price stays unknown."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .gemini_runtime import MODEL_ID
    from .run_longmemeval_f1 import (
        CANONICAL_CATEGORIES,
        OBSERVER_INPUT_OVERHEAD_TOKEN_UPPER,
        OBSERVER_MAX_OUTPUT_TOKENS,
        _observer_budget_requirement,
    )
except ImportError:  # direct script invocation
    from gemini_runtime import MODEL_ID
    from run_longmemeval_f1 import (
        CANONICAL_CATEGORIES,
        OBSERVER_INPUT_OVERHEAD_TOKEN_UPPER,
        OBSERVER_MAX_OUTPUT_TOKENS,
        _observer_budget_requirement,
    )

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VALIDATION = ROOT / "docs/plan/MEMORY-V1/eval/F1-D-source-validation.json"


def estimate(validation: dict[str, Any], limit: int) -> dict[str, Any]:
    if validation.get("status") != "PASSED":
        raise ValueError("source validation must pass before token-bound estimation")
    question_stats = validation.get("question_stats")
    if not isinstance(question_stats, list):
        raise ValueError("source validation is missing per-question statistics")

    if limit == 12:
        selected = []
        for category in CANONICAL_CATEGORIES:
            category_rows = [
                item for item in question_stats
                if item.get("question_type") == category
            ]
            if len(category_rows) < 2:
                raise ValueError(f"source validation has fewer than two fixed questions for {category}")
            selected.extend(category_rows[:2])
    elif limit == 120:
        selected = list(question_stats)
        if len(selected) != 120:
            raise ValueError(f"full LongMemEval estimate requires 120 validated rows, got {len(selected)}")
    else:
        raise ValueError("estimate supports only the stratified 12-question smoke or fixed 120-question set")

    rows: list[dict[str, Any]] = []
    total_input_upper = 0
    total_output_upper = 0
    total_batches = 0
    for item in selected:
        content = int(item["content_tokens_char_div_3_5"])
        batches = int(item["observer_calls_char_div_3_5"])
        if content < 0 or batches < 0:
            raise ValueError("validated history estimates cannot be negative")
        input_upper = 2 * content + batches * (
            2 * OBSERVER_INPUT_OVERHEAD_TOKEN_UPPER + 256
        )
        output_upper = batches * 2 * OBSERVER_MAX_OUTPUT_TOKENS
        combined_budget = _observer_budget_requirement(item)
        if combined_budget != input_upper + output_upper:
            raise AssertionError("cost estimator and runtime Observer budget formula diverged")
        total_batches += batches
        total_input_upper += input_upper
        total_output_upper += output_upper
        rows.append({
            "question_id": str(item["question_id"]),
            "question_type": str(item["question_type"]),
            "observer_batches_upper": batches,
            "observer_input_tokens_upper_one_retry": input_upper,
            "observer_output_tokens_upper_one_retry": output_upper,
            "observer_daily_budget_upper_one_question": combined_budget,
        })

    return {
        "status": "TOKEN_BOUND_ONLY",
        "model_id": MODEL_ID,
        "question_count": len(selected),
        "question_ids": [str(item["question_id"]) for item in selected],
        "observer_batch_count_upper": total_batches,
        "observer_model_calls_upper_one_retry": total_batches * 2,
        "observer_input_tokens_upper_one_retry": total_input_upper,
        "observer_output_tokens_upper_one_retry": total_output_upper,
        "observer_tokens_upper_one_retry": total_input_upper + total_output_upper,
        "max_isolated_question_daily_budget_upper": max(
            (item["observer_daily_budget_upper_one_question"] for item in rows),
            default=0,
        ),
        "answer_and_judge_usage": "measured per call during the run; no price or fixed token assumption",
        "configured_proxy_price": "unknown",
        "estimated_usd": None,
        "retry_assumption": "Each validated Observer batch may use at most one language retry; reserve/commit/release enforcement remains active.",
        "source_sha256": validation.get("source", {}).get("sha256"),
        "subset_sha256": validation.get("subset", {}).get("sha256"),
        "per_question": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--limit", type=int, choices=(12, 120), default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = estimate(json.loads(args.validation.read_text(encoding="utf-8")), args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    print(f"report={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
