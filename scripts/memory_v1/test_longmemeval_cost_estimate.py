from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from estimate_longmemeval_f1_cost import estimate
from run_longmemeval_f1 import CANONICAL_CATEGORIES


class LongMemEvalTokenBoundsTests(unittest.TestCase):
    def test_smoke_bounds_are_model_independent_and_unknown_cost_stays_null(self) -> None:
        stats = [
            {
                "question_id": f"{category}-{index}",
                "question_type": category,
                "content_tokens_char_div_3_5": 350,
                "observer_calls_char_div_3_5": 1,
            }
            for category in CANONICAL_CATEGORIES
            for index in range(1, 21)
        ]
        validation = {
            "status": "PASSED",
            "source": {"sha256": "source-sha"},
            "subset": {"sha256": "subset-sha"},
            "question_stats": stats,
        }

        report = estimate(validation, limit=12)

        self.assertEqual(12, report["question_count"])
        self.assertEqual(12, report["observer_batch_count_upper"])
        self.assertEqual(24, report["observer_model_calls_upper_one_retry"])
        self.assertEqual(109_776, report["observer_input_tokens_upper_one_retry"])
        self.assertEqual(96_000, report["observer_output_tokens_upper_one_retry"])
        self.assertEqual(205_776, report["observer_tokens_upper_one_retry"])
        self.assertEqual(17_148, report["max_isolated_question_daily_budget_upper"])
        self.assertEqual("unknown", report["configured_proxy_price"])
        self.assertIsNone(report["estimated_usd"])
        self.assertNotIn("deepseek", str(report).lower())

    def test_full_estimate_requires_every_fixed_question(self) -> None:
        validation = {"status": "PASSED", "question_stats": []}

        with self.assertRaisesRegex(ValueError, "requires 120"):
            estimate(validation, limit=120)


if __name__ == "__main__":
    unittest.main()
