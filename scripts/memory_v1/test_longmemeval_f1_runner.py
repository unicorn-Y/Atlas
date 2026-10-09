from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_longmemeval_f1 as runner
import gemini_runtime as gemini


class LongMemEvalRunnerInputTests(unittest.TestCase):
    def test_latency_summary_reports_distribution_and_empty_input(self) -> None:
        self.assertEqual({
            "count": 3,
            "total_ms": 60.0,
            "mean_ms": 20.0,
            "p50_ms": 20.0,
            "p95_ms": 30.0,
            "max_ms": 30.0,
        }, runner._summarize_latency_ms([30, 10, 20]))
        self.assertEqual({
            "count": 0,
            "total_ms": 0,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }, runner._summarize_latency_ms([]))

    def test_question_config_binds_to_its_isolated_memoryos_subject(self) -> None:
        import importlib
        import os
        import tempfile
        from contextlib import ExitStack
        from unittest.mock import patch

        import real_memory
        from atlas.memory.unified_facade import UnifiedMemoryFacade

        question_id = "001be529"
        subject_id = runner._question_subject_id(question_id)
        service = real_memory.RealMemoryService(
            Path("D:/Temp/F1-D-subject-test") / "memoryos",
            subject_id=subject_id, subject_aliases="", service_python=sys.executable,
        )
        modules = [
            (importlib.import_module(name), names)
            for name, names in (
                ("atlas.config", ("_config", "get_config", "load_user_settings")),
                ("atlas.agent", ("get_config",)),
                ("atlas.memory", ("get_config",)),
                ("atlas.models", ("get_config", "load_user_settings")),
                ("atlas.models.manager", ("get_config", "load_user_settings")),
            )
        ]
        with tempfile.TemporaryDirectory(prefix="f1d-subject-") as test_root:
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"ATLAS_DATA_DIR": test_root}))
                for module, names in modules:
                    for name in names:
                        if hasattr(module, name):
                            stack.enter_context(patch.object(module, name, getattr(module, name)))
                config = runner._prepare_atlas_config(
                    {}, {}, service_url="http://127.0.0.1:58175",
                    internal_token="test-internal-token", subject_binding=subject_id,
                    observer_budget=6_000_000,
                )
                facade_context = UnifiedMemoryFacade(config=config).default_context()

        self.assertEqual(service.subject_id, config.get("memory.unified.subject_binding"))
        self.assertEqual(service.subject_id, facade_context["memory_subject_id"])
        self.assertEqual("f1d-001be529", facade_context["memory_subject_id"])
        self.assertEqual("", service.subject_aliases)

    def test_question_hermes_config_sets_isolated_timeouts_and_empty_fallbacks(self) -> None:
        import os
        import tempfile
        from unittest.mock import patch

        from agent.auxiliary_client import _effective_aux_timeout, _get_auxiliary_task_config
        from hermes_cli.config import get_config_path, load_config_readonly
        from hermes_cli.fallback_config import get_fallback_chain

        loaded_paths = []
        loaded_configs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory(prefix="f1d-hermes-", dir="D:/Temp") as test_root:
                hermes_home = Path(test_root) / "hermes-home"
                hermes_home.mkdir()
                with patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}):
                    config_path = runner._write_question_hermes_config(hermes_home)
                    self.assertEqual(config_path, get_config_path())
                    config = load_config_readonly()
                    self.assertEqual(120, _effective_aux_timeout("memory_observe", None))
                    self.assertEqual(120, _effective_aux_timeout("memory_reflect", None))
                    for task in ("memory_observe", "memory_reflect"):
                        self.assertEqual([], _get_auxiliary_task_config(task).get("fallback_chain"))
                    self.assertEqual([], get_fallback_chain(config))
                    self.assertEqual([], config.get("fallback_model"))
                    loaded_paths.append(config_path)
                    loaded_configs.append(config)

        self.assertNotEqual(loaded_paths[0], loaded_paths[1])
        self.assertIsNot(loaded_configs[0], loaded_configs[1])

    def test_route_info_trace_retains_each_actual_provider_model_pair(self) -> None:
        trace = runner._RouteInfoTrace()
        for provider, model in (
            ("custom", "gemini-3.8-flash"),
            ("custom", "gemini-3.8-flash"),
        ):
            trace["provider"] = provider
            trace["model"] = model

        self.assertEqual([
            {"provider": "custom", "model": "gemini-3.8-flash"},
            {"provider": "custom", "model": "gemini-3.8-flash"},
        ], trace.attempts)

    def test_full_120_mode_needs_no_obsolete_gateway_price_override(self) -> None:
        args = runner._make_parser().parse_args([
            "--limit", "120", "--full-evaluation", "--run-real",
            "--service-port", "12345", "--service-python", sys.executable,
        ])

        runner._validate_run_args(args)

    def test_full_120_mode_still_requires_explicit_evaluation_flag(self) -> None:
        args = runner._make_parser().parse_args([
            "--limit", "120", "--run-real", "--service-port", "12345",
            "--service-python", sys.executable,
        ])

        with self.assertRaisesRegex(ValueError, "--full-evaluation"):
            runner._validate_run_args(args)

    def test_observer_budget_uses_model_independent_source_upper_bound(self) -> None:
        estimate = runner._observer_budget_estimate([{
            "content_tokens_char_div_3_5": 100,
            "observer_calls_char_div_3_5": 2,
        }])

        self.assertEqual(33_096, estimate)

    def test_smoke_is_two_fixed_questions_per_category(self) -> None:
        categories = list(runner.CANONICAL_CATEGORIES)
        subset_rows = [
            {
                "question_id": f"{category}-{i}",
                "question_type": category,
                "question": f"question {i}",
            }
            for category in categories
            for i in range(1, 21)
        ]
        canonical = {row["question_id"]: row for row in subset_rows}

        selected = runner.select_questions(subset_rows, canonical, limit=12)

        self.assertEqual(12, len(selected))
        self.assertEqual(
            {category: 2 for category in categories},
            {category: sum(row["question_type"] == category for row in selected) for category in categories},
        )
        self.assertEqual(
            [f"{category}-{i}" for category in categories for i in (1, 2)],
            [row["question_id"] for row in selected],
        )

    def test_dataset_wall_clock_is_normalized_but_retained_as_utc_frame(self) -> None:
        stamp = runner.parse_source_datetime("2023/05/28 (Sun) 19:47")

        self.assertEqual("2023-05-28T19:47:00+00:00", stamp.isoformat())

    def test_fixed_questions_bind_to_canonical_full_history_rows(self) -> None:
        subset_rows = []
        canonical = {}
        for category in runner.CANONICAL_CATEGORIES:
            for i in range(20):
                qid = f"{category}-{i}"
                fixed = {
                    "question_id": qid,
                    "question_type": category,
                    "question": f"question {i}",
                    "haystack_sessions": [[{"role": "user", "content": "short oracle history"}]],
                }
                source = {
                    **fixed,
                    "answer": f"gold {i}",
                    "haystack_sessions": [[{"role": "user", "content": "complete canonical history"}]],
                }
                subset_rows.append(fixed)
                canonical[qid] = source

        selected = runner.select_questions(subset_rows, canonical, limit=12)

        self.assertEqual("complete canonical history", selected[0]["haystack_sessions"][0][0]["content"])
        self.assertEqual("gold 0", selected[0]["answer"])

    def test_observer_budget_uses_model_independent_history_upper_bound(self) -> None:
        rows = [{
            "content_tokens_char_div_3_5": 100,
            "observer_calls_char_div_3_5": 2,
        }]

        self.assertEqual(33_096, runner._observer_budget_estimate(rows))
        self.assertEqual(33_096, runner._observer_budget_estimate(rows * 2))

    def test_observer_model_respects_user_memory_model_without_switching(self) -> None:
        class ConfiguredModels:
            current_model = "chat-model"

            @staticmethod
            def list_models():
                return [
                    {"id": "chat-model", "litellm_model": "vendor/chat"},
                    {"id": "memory-model", "litellm_model": "vendor/memory"},
                ]

        model_manager = ConfiguredModels()

        self.assertEqual(
            "memory-model",
            gemini.configured_observer_model_id(model_manager, {"memory_model": "vendor/memory"}),
        )
        self.assertEqual(
            "chat-model",
            gemini.configured_observer_model_id(model_manager, {}),
        )

    def test_resume_refuses_partial_question_without_reimporting_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-resume-") as temp:
            run_root = Path(temp)
            (run_root / "question-q2").mkdir()

            with self.assertRaisesRegex(RuntimeError, "refusing to re-import"):
                runner._load_resume_results(run_root, ["q1", "q2"])

    def test_resume_recovers_completed_result_checkpoint_without_duplicate_question(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-resume-") as temp:
            run_root = Path(temp)
            question_root = run_root / "question-q1"
            question_root.mkdir()
            result = {"question_id": "q1", "question_type": "multi-session", "answer": "done"}
            (question_root / "result.json").write_text(json.dumps(result), encoding="utf-8")
            (run_root / "raw_output.jsonl").write_text("", encoding="utf-8")

            completed = runner._load_resume_results(run_root, ["q1", "q2"])

            self.assertEqual({"q1": result}, completed)
            self.assertEqual(result, json.loads((run_root / "raw_output.jsonl").read_text(encoding="utf-8")))

    def test_new_attempt_imports_only_completed_checkpoints_and_preserves_incomplete_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-resume-source-") as temp:
            prior_root = Path(temp)
            completed_root = prior_root / "question-q1"
            completed_root.mkdir()
            result = {"question_id": "q1", "question_type": "multi-session", "answer": "done"}
            (completed_root / "result.json").write_text(json.dumps(result), encoding="utf-8")
            (prior_root / "raw_output.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
            (prior_root / "question-q2").mkdir()

            completed, unfinished = runner._load_resume_source_results(prior_root, ["q1", "q2"])

            self.assertEqual({"q1": result}, completed)
            self.assertEqual(["q2"], unfinished)

    def test_new_attempt_records_failure_without_runtime_root_as_retryable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="f1d-resume-failure-") as temp:
            prior_root = Path(temp)
            failure = {"question_id": "q2", "status": "FAILED_ATTEMPT", "error": "timeout"}
            (prior_root / "failures.jsonl").write_text(json.dumps(failure) + "\n", encoding="utf-8")

            completed, unfinished = runner._load_resume_source_results(prior_root, ["q1", "q2"])

            self.assertEqual({}, completed)
            self.assertEqual(["q2"], unfinished)

    def test_resume_from_requires_a_new_real_run_root(self) -> None:
        args = runner._make_parser().parse_args([
            "--resume-from", r"D:\Temp\F1-D-old", "--run-real",
            "--service-port", "12345", "--service-python", sys.executable,
        ])

        with self.assertRaisesRegex(ValueError, "new explicit --run-root"):
            runner._validate_run_args(args)

    def test_failure_message_redacts_bearer_and_long_credential_values(self) -> None:
        message = runner._safe_error_message(
            RuntimeError("Authorization: Bearer secret-value-1234567890; token=another-secret-value-1234567890")
        )

        self.assertNotIn("secret-value", message)
        self.assertNotIn("another-secret", message)

if __name__ == "__main__":
    unittest.main()
