"""Aggregate the fixed three-trial MEMORY-V1 scenario suite without granting acceptance."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

try:
    from .eval_judge import judge_single_scenario
except ImportError:  # direct script invocation
    from eval_judge import judge_single_scenario


TRIALS = (1, 2, 3)
SCENARIO_IDS = frozenset(range(1, 31))
COMMON_CATEGORIES = frozenset({"E1", "E2", "E3", "E4", "E6"})
STRICT_CATEGORIES = frozenset({"E5", "E7", "E8"})
USAGE_FIELDS = frozenset({
    "input_tokens", "prompt_tokens", "output_tokens", "completion_tokens",
    "total_tokens", "cached_input_tokens", "provider_reported_cost_usd", "cost_usd",
})
PRODUCTION_DATA_ROOTS = (
    Path(r"D:\Atlas\data").resolve(),
    Path(r"D:\MemoryOSData").resolve(),
)
METADATA_FIELDS = (
    "generated_at", "execution_mode", "scenario_manifest_sha256", "run_config_sha256",
    "model_configured", "model_id", "model_ids", "provider_id", "provider_endpoint_host",
    "credential_value_recorded", "model_hashes", "atlas_hash", "memoryos_hash",
)


def _failed_check_names(value: Any, prefix: str = "") -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            failures.extend(_failed_check_names(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(_failed_check_names(item, f"{prefix}[{index}]"))
    elif value is False:
        failures.append(prefix)
    return failures


def _usage_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "usage":
                if isinstance(item, dict):
                    yield item
                elif isinstance(item, list):
                    yield from (entry for entry in item if isinstance(entry, dict))
            yield from _usage_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _usage_values(item)


def _summarize_usage(scenarios: list[dict[str, Any]]) -> dict[str, int | float]:
    totals: dict[str, int | float] = {}
    for scenario in scenarios:
        for usage in _usage_values(scenario):
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if (
                        key in USAGE_FIELDS
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        and value >= 0
                    ):
                        totals[key] = totals.get(key, 0) + value
    return totals


def checked_report_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved in PRODUCTION_DATA_ROOTS or any(
        root in resolved.parents for root in PRODUCTION_DATA_ROOTS
    ):
        raise RuntimeError("F4 report output must not use a production data root")
    return resolved


def aggregate_three_trials(payload: dict[str, Any]) -> dict[str, Any]:
    """Judge every scenario and report three-run thresholds, never an acceptance state."""
    metadata = payload.get("metadata")
    scenarios = payload.get("scenarios")
    if not isinstance(metadata, dict) or not isinstance(scenarios, list):
        raise ValueError("scenario evaluation must contain metadata and scenarios")
    if metadata.get("dry_run") is True:
        raise ValueError("dry-run plans cannot be judged as F4 evidence")
    if metadata.get("repetitions") != len(TRIALS) or metadata.get("scenario_count") != len(SCENARIO_IDS):
        raise ValueError("F4 requires exactly 3 repetitions of the fixed 30-scenario suite")
    if len(scenarios) != len(TRIALS) * len(SCENARIO_IDS):
        raise ValueError("F4 requires exactly 30 scenarios per trial (90 total results)")

    grouped: dict[int, dict[int, dict[str, Any]]] = {trial: {} for trial in TRIALS}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("scenario trial result must be an object")
        trial = scenario.get("trial")
        scenario_id = scenario.get("scenario_id")
        if trial not in grouped or scenario_id not in SCENARIO_IDS:
            raise ValueError("scenario result has an unknown trial or scenario ID")
        trial_rows = grouped[trial]
        if scenario_id in trial_rows:
            raise ValueError(f"duplicate scenario {scenario_id} in trial {trial}")
        if not isinstance(scenario.get("category"), str) or not isinstance(
            scenario.get("is_counterexample"), bool
        ):
            raise ValueError(f"scenario {scenario_id} is missing category/counterexample metadata")
        trial_rows[scenario_id] = scenario

    canonical: dict[int, tuple[str, bool]] | None = None
    for trial in TRIALS:
        rows = grouped[trial]
        if set(rows) != SCENARIO_IDS:
            raise ValueError(f"trial {trial} must contain exactly 30 scenarios per trial")
        stable = {
            scenario_id: (str(row["category"]), row["is_counterexample"])
            for scenario_id, row in rows.items()
        }
        if canonical is None:
            canonical = stable
        elif stable != canonical:
            raise ValueError("scenario category or counterexample metadata changed between trials")

    trial_reports: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []
    failure_roots: list[dict[str, Any]] = []
    strict_passes: list[bool] = []
    counterexample_passes: list[bool] = []
    rates: list[float] = []
    for trial in TRIALS:
        evaluations: list[dict[str, Any]] = []
        for scenario_id in sorted(grouped[trial]):
            source = grouped[trial][scenario_id]
            result = judge_single_scenario(source)
            passed = result.get("verdict") == "PASS" and result.get("is_real_pass") is True
            category = str(result.get("category") or source["category"])
            is_counterexample = result.get("is_counterexample") is True
            failed_checks = _failed_check_names(result.get("checks", {}))
            if source.get("execution_status") == "setup_failed":
                failure_root_cause = "setup_failure"
            elif source.get("execution_status") != "completed":
                failure_root_cause = "execution_failure"
            elif scenario_id == 27 and not passed:
                failure_root_cause = "scenario_design_defect"
            elif not passed:
                failure_root_cause = "assertion_failure"
            else:
                failure_root_cause = None
            evaluated = {
                "trial": trial,
                "scenario_id": scenario_id,
                "category": category,
                "is_counterexample": is_counterexample,
                "passed": passed,
                "failure_root_cause": failure_root_cause,
                "failed_checks": failed_checks,
            }
            evaluations.append(evaluated)
            scenario_results.append(evaluated)
            if not passed:
                setup_error = source.get("setup_error")
                execution_errors = source.get("execution_errors")
                safe_execution_errors = [
                    {
                        key: item[key]
                        for key in ("kind", "status", "error_type", "turn_index")
                        if key in item and isinstance(item[key], (str, int, float, bool, type(None)))
                    }
                    for item in execution_errors
                    if isinstance(item, dict)
                ] if isinstance(execution_errors, list) else []
                failure_roots.append({
                    "trial": trial,
                    "scenario_id": scenario_id,
                    "category": category,
                    "failure_root_cause": failure_root_cause,
                    "error_type": setup_error.get("type")
                    if failure_root_cause == "setup_failure" and isinstance(setup_error, dict)
                    else None,
                    "execution_errors": safe_execution_errors,
                    "failed_checks": failed_checks,
                })

        common = [item for item in evaluations if item["category"] in COMMON_CATEGORIES]
        counterexamples = [item for item in evaluations if item["is_counterexample"]]
        strict = [item for item in evaluations if item["category"] in STRICT_CATEGORIES]
        if not common or not counterexamples or not strict:
            raise ValueError(f"trial {trial} is missing a required threshold category")
        common_passed = sum(item["passed"] for item in common)
        cx_passed = sum(item["passed"] for item in counterexamples)
        strict_passed = sum(item["passed"] for item in strict)
        rate = common_passed / len(common)
        rates.append(rate)
        counterexample_passes.append(cx_passed == len(counterexamples))
        strict_passes.append(strict_passed == len(strict))
        trial_reports.append({
            "trial": trial,
            "scenario_count": len(evaluations),
            "passed": sum(item["passed"] for item in evaluations),
            "failed": sum(not item["passed"] for item in evaluations),
            "e1_e4_e6": {
                "passed": common_passed,
                "total": len(common),
                "pass_rate": rate,
            },
            "counterexamples_strict": {
                "passed": cx_passed,
                "total": len(counterexamples),
                "all_passed": cx_passed == len(counterexamples),
            },
            "e5_e7_e8_strict": {
                "passed": strict_passed,
                "total": len(strict),
                "all_passed": strict_passed == len(strict),
            },
        })

    median_rate = statistics.median(rates)
    duration = metadata.get("duration_seconds")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration < 0
    ):
        duration = None
    report: dict[str, Any] = {
        "assessment_status": "REVIEW_REQUIRED",
        "trial_count": len(TRIALS),
        "scenario_count_per_trial": len(SCENARIO_IDS),
        "scenario_result_count": len(scenario_results),
        "trials": trial_reports,
        "median_e1_e4_e6_pass_rate": median_rate,
        "thresholds": {
            "e1_e4_e6_median_met": median_rate >= 0.90,
            "e1_e4_e6_required_rate": 0.90,
            "counterexamples_all_trials_passed": all(counterexample_passes),
            "e5_e7_e8_all_trials_passed": all(strict_passes),
        },
        "scenario_results": scenario_results,
        "failure_root_causes": failure_roots,
        "known_scenario_design_defects": [{
            "scenario_id": 27,
            "classification": "missing_prerequisite_history",
            "handling": "record_as_design_defect_without_adding_input_history",
        }],
        "usage_totals": _summarize_usage(scenarios),
        "duration_seconds": duration,
    }
    report.update({key: metadata[key] for key in METADATA_FIELDS if key in metadata})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="completed real three-trial scenario result JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = aggregate_three_trials(payload)
    output_path = checked_report_output(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(output_path), "scenario_result_count": 90}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
