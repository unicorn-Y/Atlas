"""Run the fixed F2-B LongMemEval 6-question smoke or 30-question reference set."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from . import run_longmemeval_f1 as runner
except ImportError:  # direct script invocation
    import run_longmemeval_f1 as runner


ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = ROOT / "docs/plan/MEMORY-V1/eval"


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=runner.DEFAULT_SOURCE)
    parser.add_argument("--subset", type=Path, default=runner.DEFAULT_SUBSET)
    parser.add_argument("--validation", type=Path, default=runner.DEFAULT_VALIDATION)
    parser.add_argument("--official-root", type=Path, default=runner.DEFAULT_OFFICIAL_ROOT)
    parser.add_argument("--limit", type=int, choices=(6, 30), default=6)
    parser.add_argument("--run-real", action="store_true")
    parser.add_argument("--service-port", type=int, default=None)
    parser.add_argument(
        "--service-python", type=Path,
        default=Path(r"D:\MemoryOS\service\.venv\Scripts\python.exe"),
    )
    parser.add_argument("--run-root", type=Path, default=None)
    parser.add_argument("--observation-cache", type=Path, default=runner.DEFAULT_OBSERVATION_CACHE)
    parser.add_argument(
        "--observer-daily-token-budget", type=int, default=6_000_000,
        help="isolated benchmark service budget; does not edit production settings",
    )
    return parser


def _runner_args(args: argparse.Namespace) -> argparse.Namespace:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = args.run_root or runner.TEMP_ROOT / f"F2-B-longmemeval-{args.limit}-{stamp}-{uuid.uuid4().hex[:8]}"
    return argparse.Namespace(
        source=args.source,
        subset=args.subset,
        validation=args.validation,
        official_root=args.official_root,
        limit=args.limit,
        full_evaluation=False,
        run_real=args.run_real,
        service_port=args.service_port,
        service_python=args.service_python,
        run_root=run_root,
        observation_cache=args.observation_cache,
        resume_from=None,
        observer_daily_token_budget=args.observer_daily_token_budget,
    )


def _filtered_question_result(item: dict[str, Any]) -> dict[str, Any]:
    judge = item.get("official_judge") if isinstance(item.get("official_judge"), dict) else {}
    label = judge.get("label")
    if not isinstance(label, bool):
        raise ValueError(f"official judge label is missing or invalid for {item.get('question_id')}")
    cache = item.get("observation_cache") if isinstance(item.get("observation_cache"), dict) else {}
    token_totals = item.get("token_totals") if isinstance(item.get("token_totals"), dict) else {}
    observation_token_fields = runner.OBSERVER_TOKEN_FIELDS
    answer_judge_token_fields = runner.ANSWER_JUDGE_TOKEN_FIELDS
    return {
        "question_id": str(item.get("question_id") or ""),
        "question_type": str(item.get("question_type") or ""),
        "official_judge_label": label,
        "observation_cache_hit": bool(cache.get("hit")),
        "observation_usage": {
            "provenance": "cached_historical" if cache.get("hit") is True else "new_this_attempt",
            "token_totals": {field: token_totals.get(field, 0) for field in observation_token_fields},
        },
        "observation_cache_fingerprint": cache.get("fingerprint"),
        "observation_cache_entry_path": cache.get("entry_path"),
        "timing": item.get("timing", {}),
        "answer_judge_token_totals_this_attempt": {
            field: token_totals.get(field, 0) for field in answer_judge_token_fields
        },
        "answer_model_id": (item.get("answer") or {}).get("model_id")
        if isinstance(item.get("answer"), dict) else None,
        "observer_model_ids": (item.get("observer") or {}).get("model_ids", [])
        if isinstance(item.get("observer"), dict) else [],
    }


def write_completion_report(run_root: Path, *, limit: int) -> Path:
    summary_path = run_root / "summary.json"
    results_path = run_root / "raw_output.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "COMPLETED" or int(summary.get("question_count", 0)) != limit:
        raise RuntimeError("refusing to write a completed F2-B report from a partial run")
    raw_results = []
    with results_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                raw_results.append(json.loads(line))
    questions = [_filtered_question_result(item) for item in raw_results]
    if len(questions) != limit:
        raise RuntimeError("F2-B result journal count does not match the completed summary")
    selected_ids = summary.get("selected_question_ids")
    question_ids = [item["question_id"] for item in questions]
    if not isinstance(selected_ids, list) or question_ids != [str(value) for value in selected_ids]:
        raise RuntimeError("F2-B result journal selected question IDs do not match the completed summary")
    if len(set(question_ids)) != limit:
        raise RuntimeError("F2-B result journal contains duplicate selected question IDs")
    expected_per_category = limit // len(runner.CANONICAL_CATEGORIES)
    expected_categories = {category: expected_per_category for category in runner.CANONICAL_CATEGORIES}
    observed_categories = Counter(item["question_type"] for item in questions)
    if dict(observed_categories) != expected_categories:
        raise RuntimeError("F2-B result journal category counts do not match the stratified sample")
    correct = sum(item["official_judge_label"] is True for item in questions)
    if int(summary.get("correct", -1)) != correct:
        raise RuntimeError("F2-B completed summary correct count does not match official judge labels")
    category_results = summary.get("category_results")
    if not isinstance(category_results, dict):
        raise RuntimeError("F2-B completed summary is missing category results")
    for category, expected_total in expected_categories.items():
        expected_correct = sum(
            item["official_judge_label"] is True
            for item in questions if item["question_type"] == category
        )
        recorded = category_results.get(category)
        if not isinstance(recorded, dict) or (
            int(recorded.get("total", -1)) != expected_total
            or int(recorded.get("correct", -1)) != expected_correct
        ):
            raise RuntimeError(f"F2-B category result does not match official labels for {category}")

    report = {
        "status": "COMPLETED",
        "evaluation": "LongMemEval fixed 20261007 stratified subset",
        "sample_size": limit,
        "sample_scope": "first 1 per category" if limit == 6 else "first 5 per category",
        "selected_question_ids": [item["question_id"] for item in questions],
        "correct": correct,
        "accuracy": correct / limit,
        "category_results": summary.get("category_results", {}),
        "source_sha256": summary.get("source_sha256"),
        "subset_sha256": summary.get("subset_sha256"),
        "official_evaluator": {
            "repository_origin": summary.get("official_repository_origin"),
            "commit": summary.get("official_commit"),
            "source_path": summary.get("official_evaluator_source_path"),
            "blob": summary.get("official_evaluator_blob"),
        },
        "official_evaluator_runtime": summary.get("official_evaluator_runtime", {}),
        "model_router": summary.get("model_router", {}),
        "observation_cache": summary.get("observation_cache", {}),
        "observer_budget_preflight": summary.get("observer_budget_preflight", {}),
        "token_totals": summary.get("token_totals", {}),
        "historical_observation_usage": summary.get("historical_observation_usage", {}),
        "actual_observer_usage_this_attempt": summary.get("actual_observer_usage_this_attempt", {}),
        "actual_answer_judge_usage_this_attempt": summary.get("actual_answer_judge_usage_this_attempt", {}),
        "runtime_measurements": summary.get("runtime_measurements", {}),
        "provider_reported_cost": summary.get("provider_reported_cost", {}),
        "historical_observation_provider_reported_cost_reused_from_cache": summary.get(
            "historical_observation_provider_reported_cost_reused_from_cache", {}
        ),
        "run_root": str(run_root),
        "questions": questions,
        "comparison_note": (
            "Mastra 94.87% and Hindsight 91.4% are public scores from their original evaluation settings; "
            "their sample counts and system configurations are not established here, so they are not "
            "directly comparable. This report's sample is 6 smoke questions."
            if limit == 6 else
            "Mastra 94.87% and Hindsight 91.4% are public scores from their original evaluation settings; "
            "their sample counts and system configurations are not established here, so they are not "
            "directly comparable to this 30-question sample."
        ),
    }
    EVAL_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = EVAL_ROOT / f"F2-B-longmemeval-{limit}-{timestamp}-{uuid.uuid4().hex[:8]}.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return report_path


def write_failure_report(run_root: Path, *, limit: int) -> Path:
    summary_path = run_root / "summary.json"
    results_path = run_root / "raw_output.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "FAILED_QUESTION":
        raise RuntimeError("refusing to write a failure report without a failed question checkpoint")
    selected_ids = summary.get("selected_question_ids")
    if not isinstance(selected_ids, list) or len(selected_ids) != limit:
        raise RuntimeError("failed F2-B summary does not contain the fixed selected question IDs")
    raw_results = []
    with results_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                raw_results.append(json.loads(line))
    questions = [_filtered_question_result(item) for item in raw_results]
    question_ids = [item["question_id"] for item in questions]
    completed_ids = summary.get("completed_question_ids", [])
    if question_ids != completed_ids or len(set(question_ids)) != len(question_ids):
        raise RuntimeError("failed F2-B result journal does not match its completed question IDs")
    selected_set = {str(value) for value in selected_ids}
    failure = summary.get("failed_question")
    if not isinstance(failure, dict) or str(failure.get("question_id") or "") not in selected_set:
        raise RuntimeError("failed F2-B summary is missing a selected failed question")
    if str(failure["question_id"]) in set(question_ids):
        raise RuntimeError("failed F2-B question is already recorded as completed")
    categories = Counter(item["question_type"] for item in questions)
    category_results = {
        category: {
            "correct": sum(
                item["official_judge_label"] is True
                for item in questions if item["question_type"] == category
            ),
            "total": categories.get(category, 0),
        }
        for category in runner.CANONICAL_CATEGORIES
    }
    usage = runner._summarize_attempt_usage(raw_results)
    cost = runner._summarize_attempt_cost(raw_results)
    report = {
        "status": "FAILED_QUESTION",
        "evaluation": "LongMemEval fixed 20261007 stratified subset",
        "target_sample_size": limit,
        "sample_scope": "first 1 per category" if limit == 6 else "first 5 per category",
        "selected_question_ids": [str(value) for value in selected_ids],
        "completed_count": len(questions),
        "completed_question_ids": question_ids,
        "category_results_for_completed_questions_only": category_results,
        "failure": {
            "question_id": str(failure.get("question_id") or ""),
            "question_type": str(failure.get("question_type") or ""),
            "error_type": str(failure.get("error_type") or "UnknownError"),
            "error": runner._safe_error_message(RuntimeError(str(failure.get("error") or ""))),
        },
        "token_totals_for_attempt_so_far": usage["token_totals"],
        "historical_observation_usage": usage["historical_observation_usage"],
        "actual_observer_usage_this_attempt": usage["actual_observer_usage_this_attempt"],
        "actual_answer_judge_usage_this_attempt": usage["actual_answer_judge_usage_this_attempt"],
        **cost,
        "observer_budget_preflight": summary.get("observer_budget_preflight", {}),
        "run_root": str(run_root),
        "questions": questions,
    }
    EVAL_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = EVAL_ROOT / f"F2-B-longmemeval-{limit}-FAILED-{timestamp}-{uuid.uuid4().hex[:8]}.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return report_path


def main() -> int:
    args = _make_parser().parse_args()
    run_args = _runner_args(args)
    try:
        result = asyncio.run(runner._run(run_args))
        if result == 0 and args.run_real:
            report = write_completion_report(run_args.run_root, limit=args.limit)
            print(json.dumps({"f2_report": str(report)}, ensure_ascii=False))
        return result
    except Exception as exc:
        failure_report = None
        summary_path = run_args.run_root / "summary.json"
        if args.run_real and summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if summary.get("status") == "FAILED_QUESTION":
                    failure_report = str(write_failure_report(run_args.run_root, limit=args.limit))
            except Exception as report_exc:
                failure_report = f"report_error:{type(report_exc).__name__}"
        print(json.dumps({
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "message": runner._safe_error_message(exc),
            "f2_failure_report": failure_report,
        }, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
