from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import f4_eval_report as report


class F4EvaluationReportTests(unittest.TestCase):
    def test_report_output_rejects_production_data_roots(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "production data root"):
            report.checked_report_output(Path("D:/Atlas/data/F4-report.json"))
        with self.assertRaisesRegex(RuntimeError, "production data root"):
            report.checked_report_output(Path("D:/MemoryOSData/F4-report.json"))

    @staticmethod
    def _payload() -> dict:
        scenarios = []
        common_categories = ("E1", "E2", "E3", "E4", "E6")
        for trial in (1, 2, 3):
            for scenario_id in range(1, 31):
                if scenario_id <= 20:
                    category = common_categories[(scenario_id - 1) % len(common_categories)]
                elif scenario_id <= 23:
                    category = "E5"
                elif scenario_id <= 26:
                    category = "E7"
                else:
                    category = "E8"
                failures = {1: {2, 3, 4, 5}, 2: {2, 3}, 3: set()}
                scenarios.append({
                    "scenario_id": scenario_id,
                    "category": category,
                    "is_counterexample": scenario_id in {1, 11, 21},
                    "trial": trial,
                    "execution_status": "completed",
                    "records": [{
                        "usage": {"input_tokens": 1, "output_tokens": 2, "api_key": "do-not-copy"},
                    }],
                    "_test_pass": scenario_id not in failures[trial],
                })
        return {
            "metadata": {
                "scenario_count": 30,
                "total_runs": 90,
                "repetitions": 3,
                "duration_seconds": 12.5,
                "model_configured": "gemini-3.8-flash",
                "model_hashes": {"atlas": "atlas-hash", "memoryos": "memoryos-hash"},
                "run_config_sha256": "run-config-hash",
            },
            "scenarios": scenarios,
        }

    def test_three_trial_report_uses_category_median_and_never_claims_acceptance(self) -> None:
        payload = self._payload()

        def fake_judge(item: dict) -> dict:
            passed = item["_test_pass"]
            return {
                "scenario_id": item["scenario_id"],
                "category": item["category"],
                "is_counterexample": item["is_counterexample"],
                "verdict": "PASS" if passed else "FAIL",
                "is_real_pass": passed,
                "checks": {"fixture_check": passed},
            }

        with patch.object(report, "judge_single_scenario", side_effect=fake_judge) as judge:
            measured = report.aggregate_three_trials(payload)
            self.assertEqual(90, judge.call_count)

        rates = measured["trials"]
        self.assertEqual([0.8, 0.9, 1.0], [trial["e1_e4_e6"]["pass_rate"] for trial in rates])
        self.assertEqual(0.9, measured["median_e1_e4_e6_pass_rate"])
        self.assertTrue(measured["thresholds"]["e1_e4_e6_median_met"])
        self.assertTrue(measured["thresholds"]["counterexamples_all_trials_passed"])
        self.assertTrue(measured["thresholds"]["e5_e7_e8_all_trials_passed"])
        self.assertEqual("REVIEW_REQUIRED", measured["assessment_status"])
        self.assertNotIn("ACCEPTED", json.dumps(measured))
        self.assertEqual(90, measured["usage_totals"]["input_tokens"])
        self.assertEqual(180, measured["usage_totals"]["output_tokens"])
        self.assertNotIn("api_key", json.dumps(measured))
        self.assertEqual(12.5, measured["duration_seconds"])
        self.assertEqual("run-config-hash", measured["run_config_sha256"])
        self.assertEqual(90, measured["scenario_result_count"])
        self.assertEqual(27, measured["known_scenario_design_defects"][0]["scenario_id"])
        self.assertEqual(6, len(measured["failure_root_causes"]))
        self.assertTrue(all(
            item["failure_root_cause"] == "assertion_failure"
            for item in measured["failure_root_causes"]
        ))

    def test_report_requires_exact_three_complete_trials_with_same_scenario_ids(self) -> None:
        payload = self._payload()
        payload["scenarios"].pop()

        with self.assertRaisesRegex(ValueError, "exactly 30 scenarios per trial"):
            report.aggregate_three_trials(payload)

    def test_s27_failure_is_classified_as_design_defect_without_changing_its_judgment(self) -> None:
        payload = self._payload()
        next(item for item in payload["scenarios"]
             if item["trial"] == 1 and item["scenario_id"] == 27)["_test_pass"] = False

        def fake_judge(item: dict) -> dict:
            passed = item["_test_pass"]
            return {
                "scenario_id": item["scenario_id"],
                "category": item["category"],
                "is_counterexample": item["is_counterexample"],
                "verdict": "PASS" if passed else "FAIL",
                "is_real_pass": passed,
                "checks": {"fixture_check": passed},
            }

        with patch.object(report, "judge_single_scenario", side_effect=fake_judge):
            measured = report.aggregate_three_trials(payload)

        failed_s27 = next(
            item for item in measured["failure_root_causes"]
            if item["trial"] == 1 and item["scenario_id"] == 27
        )
        self.assertEqual("scenario_design_defect", failed_s27["failure_root_cause"])
        self.assertFalse(measured["thresholds"]["e5_e7_e8_all_trials_passed"])


if __name__ == "__main__":
    unittest.main()
