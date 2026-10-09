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
import run_longmemeval_f2 as f2_runner


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
            Path(tempfile.gettempdir()) / "F1-D-subject-test" / "memoryos",
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
            with tempfile.TemporaryDirectory(prefix="f1d-hermes-") as test_root:
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

    def test_real_f2_6_and_30_runs_require_a_persistent_cache(self) -> None:
        for limit in (6, 30):
            args = runner._make_parser().parse_args([
                "--limit", str(limit), "--run-real", "--service-port", "12345",
                "--service-python", sys.executable,
            ])
            with self.assertRaisesRegex(ValueError, "observation-cache"):
                runner._validate_run_args(args)

            args.observation_cache = Path("D:/Temp/F2-B-test-cache")
            runner._validate_run_args(args)

        from unittest.mock import patch

        with patch.dict("os.environ", {
            "LOCALAPPDATA": "C:/Users/test-user/AppData/Local",
        }), patch.object(Path, "home", return_value=Path("C:/Users/test-user")):
            args = runner._make_parser().parse_args([
                "--limit", "6", "--run-real", "--service-port", "12345",
                "--service-python", sys.executable,
                "--run-root", "C:/Users/test-user/AppData/Local/Temp/F2-B-run",
                "--observation-cache", "C:/Users/test-user/AppData/Local/Temp/F2-B-cache",
            ])
            runner._validate_run_args(args)

    def test_temp_artifacts_allow_legacy_and_local_user_temp_only(self) -> None:
        from unittest.mock import patch

        import longmemeval_observation_cache as cache

        local_appdata = Path("C:/Users/test-user/AppData/Local")
        user_home = Path("C:/Users/test-user")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(local_appdata)}), \
                patch.object(Path, "home", return_value=user_home):
            local_child = Path("C:/Users/test-user/AppData/Local/Temp/F2-B-run")
            expected_root = Path("C:/Users/test-user/AppData/Local/Temp").resolve()
            self.assertEqual(
                local_child.resolve(), runner._checked_temp_child(local_child),
            )
            self.assertEqual(local_child.resolve(), cache._temp_child(local_child))
            self.assertEqual(expected_root, cache.preferred_temp_root())
            f2_args = f2_runner._make_parser().parse_args(["--limit", "6"])
            self.assertEqual(expected_root, f2_runner._runner_args(f2_args).run_root.parent.resolve())
            self.assertEqual(
                Path("D:/Temp/F2-B-run").resolve(),
                runner._checked_temp_child(Path("D:/Temp/F2-B-run")),
            )
            for unsafe in (
                Path("C:/Temp/F2-B-run"),
                Path("C:/Users/other-user/AppData/Local/Temp/F2-B-run"),
                Path("D:/Atlas/data/F2-B-run"),
                Path("D:/MemoryOSData/F2-B-run"),
            ):
                with self.subTest(path=str(unsafe)), self.assertRaises(RuntimeError):
                    runner._checked_temp_child(unsafe)

    def test_observer_budget_config_reader_returns_only_allowlisted_integer(self) -> None:
        toml = (
            '[models.gateway]\napi_key = "synthetic-secret"\n'
            '[memory.v1]\nobserver_daily_token_budget = 6_000_000 # isolated ceiling\n'
        )
        with tempfile.TemporaryDirectory(prefix="f4-budget-") as root:
            config_path = Path(root) / "atlas.toml"
            config_path.write_text(toml, encoding="utf-8")
            parsed = runner._read_observer_budget_allowlist(config_path)

        self.assertEqual(
            {"memory": {"v1": {"observer_daily_token_budget": 6_000_000}}},
            parsed,
        )
        self.assertNotIn("synthetic-secret", json.dumps(parsed))

    def test_observer_budget_config_reader_resets_on_quoted_table_header(self) -> None:
        toml = (
            '[memory.v1]\nobserver_daily_token_budget = 6000000\n'
            '["other.section"]\nobserver_daily_token_budget = 9\n'
        )
        with tempfile.TemporaryDirectory(prefix="f4-budget-quoted-") as root:
            config_path = Path(root) / "atlas.toml"
            config_path.write_text(toml, encoding="utf-8")
            parsed = runner._read_observer_budget_allowlist(config_path)

        self.assertEqual(
            {"memory": {"v1": {"observer_daily_token_budget": 6_000_000}}},
            parsed,
        )

    def test_observer_budget_config_reader_resets_on_array_table_header(self) -> None:
        toml = (
            '[memory.v1]\nobserver_daily_token_budget = 6000000\n'
            '[[models.gateway]]\nobserver_daily_token_budget = 9\n'
        )
        with tempfile.TemporaryDirectory(prefix="f4-budget-array-") as root:
            config_path = Path(root) / "atlas.toml"
            config_path.write_text(toml, encoding="utf-8")
            parsed = runner._read_observer_budget_allowlist(config_path)

        self.assertEqual(
            {"memory": {"v1": {"observer_daily_token_budget": 6_000_000}}},
            parsed,
        )

    def test_isolated_process_temp_uses_run_scoped_directory(self) -> None:
        import os
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="f4-process-env-") as root:
            run_root = Path(root) / "F2-B-run"
            run_root.mkdir()
            with patch.dict(os.environ, {}, clear=True):
                runner._set_isolated_process_env(run_root)
                expected = str(run_root / "temp")
                self.assertEqual(expected, os.environ["TEMP"])
                self.assertEqual(expected, os.environ["TMP"])
                self.assertEqual(expected, os.environ["TMPDIR"])
                self.assertTrue((run_root / "temp").is_dir())
                self.assertTrue(Path(os.environ["MEMORYOS_DATA_ROOT"]).is_relative_to(run_root))

    def test_observer_budget_uses_model_independent_source_upper_bound(self) -> None:
        estimate = runner._observer_budget_estimate([{
            "content_tokens_char_div_3_5": 100,
            "observer_calls_char_div_3_5": 2,
        }])

        self.assertEqual(33_096, estimate)

    def test_observation_cache_identity_tracks_observer_route_not_answer_model(self) -> None:
        from unittest.mock import patch

        if str(runner.CORE) not in sys.path:
            sys.path.insert(0, str(runner.CORE))
        validation = {"source": {"sha256": "source"}, "subset": {"sha256": "subset"}}
        raw_config = {"memory": {"v1": {"observer_daily_token_budget": 1000}}}
        settings = {
            "memory_model": "gemini-3.8-flash",
            "custom_models": [{"id": "gemini-3.8-flash", "provider": "custom",
                               "litellm_model": "gemini-3.8-flash"}],
            "providers": {"custom": {"base_url": "https://provider.invalid/v1"}},
            "judge_model": "judge-a",
        }
        route = {
            "model_id": "answer-a", "observer_model_id": "gemini-3.8-flash",
            "provider_id": "custom", "provider_endpoint_host": "provider.invalid",
        }
        with patch.object(runner, "_source_tree_sha256", return_value="code-hash"), \
                patch.object(runner, "sha256_file", return_value="config-file-hash"):
            baseline = runner._observation_cache_identity(
                validation=validation, raw_config=raw_config, settings=settings,
                model_route=route, service_python=Path(sys.executable), observer_budget=1000,
            )
            changed_answer = runner._observation_cache_identity(
                validation=validation, raw_config=raw_config,
                settings={**settings, "judge_model": "judge-b"},
                model_route={**route, "model_id": "answer-b"},
                service_python=Path(sys.executable), observer_budget=1000,
            )

        self.assertEqual(baseline, changed_answer)
        self.assertIn("atlas_model_router_code_sha256", baseline)
        self.assertEqual("low", baseline["observer_route_variant"]["reasoning_effort"])
        self.assertEqual(120.0, baseline["observer_route_variant"]["auxiliary_timeout_seconds"])

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

    def test_f2_smoke_and_reference_selection_take_first_one_or_five_per_category(self) -> None:
        categories = list(runner.CANONICAL_CATEGORIES)
        subset_rows = [
            {"question_id": f"{category}-{i}", "question_type": category,
             "question": f"question {i}"}
            for category in categories
            for i in range(1, 21)
        ]
        canonical = {row["question_id"]: row for row in subset_rows}

        smoke = runner.select_questions(subset_rows, canonical, limit=6)
        reference = runner.select_questions(subset_rows, canonical, limit=30)

        self.assertEqual(
            [f"{category}-1" for category in categories],
            [row["question_id"] for row in smoke],
        )
        self.assertEqual(
            [f"{category}-{i}" for category in categories for i in range(1, 6)],
            [row["question_id"] for row in reference],
        )

    def test_f2_entrypoint_only_exposes_six_and_thirty_question_modes(self) -> None:
        parser = f2_runner._make_parser()
        self.assertEqual(6, parser.parse_args([]).limit)
        self.assertEqual(30, parser.parse_args(["--limit", "30"]).limit)
        self.assertEqual(6_000_000, parser.parse_args([]).observer_daily_token_budget)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--limit", "120"])

        filtered = f2_runner._filtered_question_result({
            "question_id": "q1", "question_type": "single-session-user",
            "question": "private question", "answer": {"text": "private answer", "model_id": "chat"},
            "official_judge": {"label": True, "reason": "contains judge details"},
            "gold_answer": "private gold",
            "observation_cache": {"hit": True, "fingerprint": "a" * 64, "entry_path": "D:/Temp/cache"},
        })
        self.assertEqual("q1", filtered["question_id"])
        self.assertTrue(filtered["official_judge_label"])
        self.assertNotIn("question", filtered)
        self.assertNotIn("answer", filtered)
        self.assertNotIn("gold_answer", filtered)

    def test_usage_summary_separates_cached_observation_from_current_billing(self) -> None:
        results = [
            {
                "question_id": "cached-q",
                "observation_cache": {"hit": True},
                "token_totals": {
                    "observer_budget_accounted_input_tokens": 80,
                    "observer_provider_reported_input_tokens": 100,
                    "observer_provider_reported_output_tokens": 10,
                    "observer_provider_reported_complete": True,
                    "answer_provider_reported_input_tokens": 20,
                    "answer_provider_reported_output_tokens": 5,
                    "judge_provider_reported_input_tokens": 8,
                    "judge_provider_reported_output_tokens": 2,
                },
                "observer": {"router_calls": [{"purpose": "memory_observe"}]},
                "answer": {"run_usage": [{"input_tokens": 20}]},
            },
            {
                "question_id": "new-q",
                "observation_cache": {"hit": False},
                "token_totals": {
                    "observer_budget_accounted_input_tokens": 160,
                    "observer_provider_reported_input_tokens": 200,
                    "observer_provider_reported_output_tokens": 20,
                    "observer_provider_reported_complete": True,
                    "answer_provider_reported_input_tokens": 30,
                    "answer_provider_reported_output_tokens": 7,
                    "judge_provider_reported_input_tokens": 9,
                    "judge_provider_reported_output_tokens": 3,
                },
                "observer": {"router_calls": [{"purpose": "memory_observe"}, {"purpose": "memory_observe"}]},
                "answer": {"run_usage": [{"input_tokens": 30}]},
            },
        ]

        usage = runner._summarize_attempt_usage(results)

        self.assertEqual(100, usage["historical_observation_usage"]["observer_provider_reported_input_tokens"])
        self.assertEqual(200, usage["actual_observer_usage_this_attempt"]["observer_provider_reported_input_tokens"])
        self.assertEqual(["cached-q"], usage["historical_observation_usage"]["question_ids"])
        self.assertEqual(["new-q"], usage["actual_observer_usage_this_attempt"]["question_ids"])
        self.assertEqual(50, usage["actual_answer_judge_usage_this_attempt"]["answer_provider_reported_input_tokens"])
        self.assertEqual(17, usage["actual_answer_judge_usage_this_attempt"]["judge_provider_reported_input_tokens"])
        self.assertEqual(267, usage["token_totals"]["provider_reported_input_tokens"])
        self.assertEqual(37, usage["token_totals"]["provider_reported_output_tokens"])

    def test_cost_summary_separates_cached_observer_cost_from_this_attempt(self) -> None:
        results = [
            {
                "question_id": "cached-q",
                "observation_cache": {"hit": True},
                "provider_reported_cost_usd": {"observer": [0.03], "answer": [0.01], "judge": 0.001},
                "observer": {"router_calls": [{"purpose": "memory_observe"}]},
                "answer": {"run_usage": [{}]},
            },
            {
                "question_id": "new-q",
                "observation_cache": {"hit": False},
                "provider_reported_cost_usd": {"observer": [0.02], "answer": [0.01], "judge": 0.002},
                "observer": {"router_calls": [{"purpose": "memory_observe"}, {"purpose": "memory_observe"}]},
                "answer": {"run_usage": [{}]},
            },
        ]

        cost = runner._summarize_attempt_cost(results)

        self.assertFalse(cost["provider_reported_cost"]["complete_for_all_calls"])
        self.assertEqual(6, cost["provider_reported_cost"]["calls_total"])
        self.assertEqual(5, cost["provider_reported_cost"]["calls_with_known_cost"])
        self.assertAlmostEqual(0.043, cost["provider_reported_cost"]["known_partial_sum_usd"])
        self.assertTrue(cost["historical_observation_provider_reported_cost_reused_from_cache"]["complete"])
        self.assertEqual(1, cost["historical_observation_provider_reported_cost_reused_from_cache"]["calls_total"])
        self.assertAlmostEqual(
            0.03,
            cost["historical_observation_provider_reported_cost_reused_from_cache"]["complete_sum_usd"],
        )

    def test_f2_report_validates_selected_ids_and_separates_historical_usage(self) -> None:
        import tempfile
        from unittest.mock import patch

        categories = list(runner.CANONICAL_CATEGORIES)
        with tempfile.TemporaryDirectory(prefix="f2-report-test-") as root:
            run_root = Path(root) / "run"
            run_root.mkdir()
            rows = [
                {
                    "question_id": f"q-{index}",
                    "question_type": category,
                    "official_judge": {"label": index % 2 == 0, "reason": "must not be copied"},
                    "observation_cache": {"hit": index == 0, "fingerprint": "a" * 64},
                    "timing": {},
                    "token_totals": {"observer_provider_reported_input_tokens": 100},
                    "answer": {"model_id": "chat", "text": "must not be copied"},
                    "question": "must not be copied",
                    "gold_answer": "must not be copied",
                }
                for index, category in enumerate(categories)
            ]
            selected_ids = [row["question_id"] for row in rows]
            (run_root / "raw_output.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            summary = {
                "status": "COMPLETED", "question_count": 6, "correct": 3,
                "selected_question_ids": selected_ids,
                "token_totals": {"provider_reported_input_tokens": 90},
                "historical_observation_usage": {"observer_provider_reported_input_tokens": 100},
                "actual_observer_usage_this_attempt": {"observer_provider_reported_input_tokens": 0},
                "actual_answer_judge_usage_this_attempt": {"answer_provider_reported_input_tokens": 60},
                "provider_reported_cost": {"known_partial_sum_usd": 0.2, "calls_total": 3},
                "historical_observation_provider_reported_cost_reused_from_cache": {
                    "known_partial_sum_usd": 0.1, "calls_total": 1,
                },
                "observer_budget_preflight": {
                    "raw_config_value": 50000,
                    "explicit_isolated_override": 6000000,
                    "effective_value": 6000000,
                },
                "category_results": {
                    category: {"total": 1, "correct": int(index % 2 == 0)}
                    for index, category in enumerate(categories)
                },
            }
            (run_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            report_root = Path(root) / "reports"
            with patch.object(f2_runner, "EVAL_ROOT", report_root):
                report_path = f2_runner.write_completion_report(run_root, limit=6)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(20261007, report["random_seed"])
                self.assertEqual(100, report["historical_observation_usage"]["observer_provider_reported_input_tokens"])
                self.assertEqual(0, report["actual_observer_usage_this_attempt"]["observer_provider_reported_input_tokens"])
                self.assertEqual(60, report["actual_answer_judge_usage_this_attempt"]["answer_provider_reported_input_tokens"])
                self.assertEqual(0.2, report["provider_reported_cost"]["known_partial_sum_usd"])
                self.assertEqual(
                    0.1,
                    report["historical_observation_provider_reported_cost_reused_from_cache"]["known_partial_sum_usd"],
                )
                self.assertEqual(50000, report["observer_budget_preflight"]["raw_config_value"])
                self.assertEqual(6000000, report["observer_budget_preflight"]["explicit_isolated_override"])
                self.assertNotIn("token_totals", report["questions"][0])
                self.assertIn("original evaluation settings", report["comparison_note"])
                self.assertNotIn("30-sample reference", report["comparison_note"])
                self.assertNotIn("question", report["questions"][0])
                self.assertNotIn("answer", report["questions"][0])
                self.assertNotIn("gold_answer", report["questions"][0])

                summary["selected_question_ids"] = ["wrong-id"] * 6
                (run_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "selected question IDs"):
                    f2_runner.write_completion_report(run_root, limit=6)

    def test_f2_failed_attempt_report_preserves_partial_labels_without_claiming_a_score(self) -> None:
        import tempfile
        from unittest.mock import patch

        categories = list(runner.CANONICAL_CATEGORIES)
        with tempfile.TemporaryDirectory(prefix="f2-failure-report-test-") as root:
            run_root = Path(root) / "run"
            run_root.mkdir()
            selected_ids = [f"q-{index}" for index in range(6)]
            row = {
                "question_id": selected_ids[0],
                "question_type": categories[0],
                "official_judge": {"label": False},
                "observation_cache": {"hit": True, "fingerprint": "b" * 64},
                "timing": {},
                "token_totals": {"observer_provider_reported_input_tokens": 100},
                "provider_reported_cost_usd": {"observer": [0.05], "answer": [0.01], "judge": 0.002},
                "observer": {"router_calls": [{"purpose": "memory_observe"}]},
                "answer": {"run_usage": [{}]},
                "question": "private question",
                "gold_answer": "private gold",
            }
            (run_root / "raw_output.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            (run_root / "summary.json").write_text(json.dumps({
                "status": "FAILED_QUESTION",
                "question_count": 0,
                "selected_question_ids": selected_ids,
                "completed_question_ids": [selected_ids[0]],
                "failed_question": {
                    "question_id": selected_ids[1],
                    "question_type": categories[1],
                    "error_type": "TimeoutError",
                    "error": "safe timeout summary",
                },
            }), encoding="utf-8")
            report_root = Path(root) / "reports"
            with patch.object(f2_runner, "EVAL_ROOT", report_root):
                report_path = f2_runner.write_failure_report(run_root, limit=6)
                report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual("FAILED_QUESTION", report["status"])
        self.assertEqual(6, report["target_sample_size"])
        self.assertEqual(1, report["completed_count"])
        self.assertEqual([selected_ids[0]], report["completed_question_ids"])
        self.assertEqual("TimeoutError", report["failure"]["error_type"])
        self.assertAlmostEqual(
            0.05,
            report["historical_observation_provider_reported_cost_reused_from_cache"]["complete_sum_usd"],
        )
        self.assertAlmostEqual(0.012, report["provider_reported_cost"]["complete_sum_usd"])
        self.assertNotIn("accuracy", report)
        self.assertNotIn("question", report["questions"][0])
        self.assertNotIn("gold_answer", report["questions"][0])

    def test_observation_cache_fingerprint_and_copy_on_reuse(self) -> None:
        import importlib
        import importlib.util
        import sqlite3
        from contextlib import closing

        spec = importlib.util.find_spec("longmemeval_observation_cache")
        self.assertIsNotNone(spec, "F2-B needs a persistent observation cache module")
        cache = importlib.import_module("longmemeval_observation_cache")
        row = {
            "question_id": "fixed-q1", "answer": "gold answer",
            "haystack_sessions": [[{"role": "user", "content": "source text"}]],
            "haystack_session_ids": ["session-1"], "haystack_dates": ["2024/01/01"],
        }
        identity = {
            "source_sha256": "source", "subset_sha256": "subset",
            "observer_model_id": "memory-model", "observer_config_sha256": "config-v1",
            "observer_code_sha256": "observer-v1",
        }
        fingerprint = cache.question_fingerprint(row, identity)
        self.assertEqual(fingerprint, cache.question_fingerprint({**row, "answer": "other gold"}, identity))
        self.assertNotEqual(
            fingerprint,
            cache.question_fingerprint(row, {**identity, "observer_model_id": "other-memory-model"}),
        )

        with tempfile.TemporaryDirectory(prefix="f2b-cache-") as temp:
            root = Path(temp)
            source = root / "source"
            for relative in ("atlas-data/engine.sqlite3", "outbox/unified_outbox.sqlite3",
                             "memoryos/db/memoryos.sqlite3"):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(path)) as database:
                    database.execute("CREATE TABLE marker (value TEXT NOT NULL)")
                    database.execute("INSERT INTO marker(value) VALUES (?)", (relative,))
                    database.commit()
            (source / "hermes-home/config.yaml").parent.mkdir(parents=True, exist_ok=True)
            (source / "hermes-home/config.yaml").write_text("fallback_model: []\n", encoding="utf-8")
            (source / "source_dialogue.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
            (source / "observer_batches.jsonl").write_text('{"batch_id":"batch-1"}\n', encoding="utf-8")
            checkpoint = {
                "phase": "OBSERVATION_COMPLETE", "observe_complete": True,
                "outbox_drained": True, "semantic_ready": True,
            }
            cache_root = root / "cache"
            cache.save_observation_snapshot(cache_root, "fixed-q1", fingerprint, source, checkpoint)
            expected_entry = cache.question_cache_entry_path(cache_root, "fixed-q1", fingerprint)
            restored = root / "restored"
            restored.mkdir()

            entry = cache.restore_observation_snapshot(
                cache_root, "fixed-q1", fingerprint, restored,
            )

            self.assertEqual("OBSERVATION_COMPLETE", entry["checkpoint"]["phase"])
            self.assertEqual(expected_entry, cache.question_cache_entry_path(cache_root, "fixed-q1", fingerprint))
            with closing(sqlite3.connect(restored / "outbox/unified_outbox.sqlite3")) as database:
                self.assertEqual("ok", database.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual(("outbox/unified_outbox.sqlite3",),
                                 database.execute("SELECT value FROM marker").fetchone())
            restored_memoryos = restored / "memoryos/db/memoryos.sqlite3"
            with closing(sqlite3.connect(restored_memoryos)) as database:
                database.execute("INSERT INTO marker(value) VALUES ('answer mutation')")
                database.commit()
            with closing(sqlite3.connect(cache_root / "questions" / cache.question_cache_key("fixed-q1")
                                         / fingerprint / "snapshot/memoryos/db/memoryos.sqlite3")) as database:
                self.assertEqual(("memoryos/db/memoryos.sqlite3",),
                                 database.execute("SELECT value FROM marker").fetchone())

            mismatch = cache.restore_observation_snapshot(
                cache_root, "fixed-q1", "0" * 64, root / "miss",
            )
            self.assertIsNone(mismatch)

    def test_observation_cache_snapshots_committed_wal_state_without_sidecars(self) -> None:
        import importlib
        import sqlite3
        from contextlib import closing

        cache = importlib.import_module("longmemeval_observation_cache")
        row = {
            "question_id": "wal-q1",
            "haystack_sessions": [[{"role": "user", "content": "source"}]],
        }
        fingerprint = cache.question_fingerprint(row, {"observer_model_id": "memory-model"})
        with tempfile.TemporaryDirectory(prefix="f2b-wal-cache-") as temp:
            root = Path(temp)
            source = root / "source"
            db_path = source / "memoryos/db/memoryos.sqlite3"
            db_path.parent.mkdir(parents=True)
            database = sqlite3.connect(db_path)
            try:
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("CREATE TABLE observations (value TEXT NOT NULL)")
                database.execute("INSERT INTO observations(value) VALUES ('committed')")
                database.commit()
                database.execute("BEGIN")
                database.execute("INSERT INTO observations(value) VALUES ('uncommitted')")

                for relative in ("outbox/unified_outbox.sqlite3", "atlas-data/engine.sqlite3"):
                    path = source / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with closing(sqlite3.connect(path)) as auxiliary:
                        auxiliary.execute("CREATE TABLE marker (value TEXT)")
                        auxiliary.commit()
                (source / "source_dialogue.jsonl").write_text('{"role":"user"}\n', encoding="utf-8")
                (source / "observer_batches.jsonl").write_text('{"batch_id":"b1"}\n', encoding="utf-8")
                checkpoint = {
                    "phase": "OBSERVATION_COMPLETE", "observe_complete": True,
                    "outbox_drained": True, "semantic_ready": True,
                }
                cache_root = root / "cache"
                cache.save_observation_snapshot(cache_root, "wal-q1", fingerprint, source, checkpoint)
            finally:
                database.rollback()
                database.close()

            snapshot = (cache.question_cache_entry_path(cache_root, "wal-q1", fingerprint)
                        / "snapshot/memoryos/db/memoryos.sqlite3")
            self.assertFalse(Path(str(snapshot) + "-wal").exists())
            self.assertFalse(Path(str(snapshot) + "-shm").exists())
            with closing(sqlite3.connect(snapshot)) as copied:
                self.assertEqual("ok", copied.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual([("committed",)], copied.execute(
                    "SELECT value FROM observations ORDER BY rowid").fetchall())

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
