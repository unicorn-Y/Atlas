import json
import os
import tempfile
import unittest
from pathlib import Path
import sys
import io
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.runner import (
    ScenarioController,
    build_result,
    fingerprint_for,
    inspect_workspace,
    is_resume_match,
    prepare_scenario,
    validate_result,
    _git_baseline,
    _make_diff,
    execute,
    _call_adapter,
    ROOT,
    fault_trace_valid,
)


class RunnerContractTests(unittest.TestCase):
    def test_provider_recovery_requires_observed_complete_fault_sequence(self):
        rows = [{"fault": f, "status": s, "completed": f is None} for f, s in
                [("429", 429), ("500", 500), ("disconnect", None), (None, 200)]]
        self.assertTrue(fault_trace_valid({"recovered": True, "requests": rows}))
        for trace in ({}, {"recovered": True, "requests": []},
                      {"recovered": True, "requests": rows[1:]},
                      {"recovered": False, "requests": rows},
                      {"recovered": True, "requests": rows[:3] + [{"fault": None, "status": 500}]},
                      {"recovered": True, "requests": rows[:3] + [{"fault": None, "status": 200}]},
                      {"recovered": True, "requests": rows[:3] + [{"fault": None, "status": 200, "completed": True, "stream": True}]}):
            self.assertFalse(fault_trace_valid(trace))

    def test_workspace_inspection_finds_untracked_symlinks_and_test_deletions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "original.py").write_text("before", encoding="utf-8")
            before = inspect_workspace(root, protected_paths=["tests/**"], allowed_changes=["src/**"])
            (root / "src").mkdir()
            (root / "src" / "new.py").write_text("new", encoding="utf-8")
            (root / "outside.txt").write_text("bad", encoding="utf-8")
            (root / "tests" / "original.py").unlink()
            has_symlink = True
            try:
                os.symlink("outside.txt", root / "link")
            except (OSError, NotImplementedError):
                has_symlink = False
            after = inspect_workspace(root, protected_paths=["tests/**"], allowed_changes=["src/**"], before=before.before)
            expected = ["outside.txt", "src/new.py", "tests/original.py"] + (["link"] if has_symlink else [])
            self.assertEqual(after.changed_files, sorted(expected))
            self.assertEqual(after.forbidden_changes, sorted(["outside.txt", "tests/original.py"] + (["link"] if has_symlink else [])))
            self.assertEqual(after.test_files_deleted, ["tests/original.py"])
            self.assertEqual(after.symlink_files, ["link"] if has_symlink else [])

    def test_result_schema_accepts_runner_result_and_rejects_missing_fields(self):
        result = build_result(
            participant="fake", track="same-model", model=None, task_id="01", attempt=1,
            success=True, check_exit_code=0, duration_ms=1.5,
        )
        validate_result(result)
        validate_result(json.loads(json.dumps(result)))
        with self.assertRaises(ValueError):
            validate_result({"participant": "fake"})

    def test_resume_requires_matching_fingerprint_and_completed_status(self):
        fingerprint = fingerprint_for({"participant": "fake", "task_id": "01", "fixture": "abc"})
        result = {"status": "completed", "fingerprint": fingerprint, "success": False}
        self.assertTrue(is_resume_match(result, fingerprint))
        self.assertFalse(is_resume_match({**result, "status": "runner_error"}, fingerprint))
        self.assertFalse(is_resume_match({**result, "fingerprint": "different"}, fingerprint))

    def test_scenario_steps_are_serial_and_approval_snapshot_is_runner_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("baseline", encoding="utf-8")
            controller = ScenarioController({"steps": [{"action": "plan"}, {"action": "approve"}]}, root)
            first = controller.due_steps()
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]["action"], "plan")
            self.assertEqual(controller.due_steps(), [])
            controller.record_delivery(first[0], {"protocol": "test", "confirmed": True})
            second = controller.due_steps()
            self.assertEqual(second[0]["action"], "approve")
            (root / "file.txt").write_text("changed before approval", encoding="utf-8")
            self.assertEqual(controller.snapshot_before_approval(), ["file.txt"])

    def test_context_scenario_expands_only_when_configured(self):
        scenario = {"steps": [{"action": "context", "text": "keep this constraint", "target_tokens": 100}]}
        prepared = prepare_scenario(scenario, {})
        self.assertGreaterEqual(len(prepared["steps"][0]["text"]), 400)
        self.assertEqual(scenario["steps"][0]["text"], "keep this constraint")

    def test_context_pressure_needs_window_and_uses_selected_track(self):
        scenario = {"steps": [{"action": "context", "text": "", "target_fraction": .9}]}
        with self.assertRaisesRegex(ValueError, "context_window_tokens"):
            prepare_scenario(scenario, {})
        config = {"_selected_track": "best", "tracks": {"same-model": {"context_window_tokens": 100}, "best": {"context_window_tokens": 1000}}}
        prepared = prepare_scenario(scenario, config)
        self.assertEqual(prepared["steps"][0]["generated_context_target_tokens"], 900)

    def test_nonfinite_usage_cannot_enter_budget_accounting(self):
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                build_result(participant="fake", track="same-model", model=None, task_id="01", cost_usd=value)

    def test_added_tests_allowed_original_tests_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            original = root / "tests/test_original.py"
            original.write_text("original", encoding="utf-8")
            before = inspect_workspace(root).before
            (root / "tests/test_new.py").write_text("new", encoding="utf-8")
            allowed = inspect_workspace(root, ["tests/**"], ["tests/**"], before)
            self.assertEqual(allowed.forbidden_changes, [])
            original.write_text("tampered", encoding="utf-8")
            rejected = inspect_workspace(root, ["tests/**"], ["tests/**"], before)
            self.assertEqual(rejected.forbidden_changes, ["tests/test_original.py"])

    def test_diff_redacts_secret_and_summarizes_binary_payload(self):
        marker = "harmless-marker-123456789"
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"T1_API_KEY": marker}):
            root = Path(temp) / "workspace"
            root.mkdir()
            (root / "source.txt").write_text("baseline\n", encoding="utf-8")
            baseline = _git_baseline(root)
            before = inspect_workspace(root).before
            (root / "source.txt").write_text("api_key=" + marker + "\n", encoding="utf-8")
            (root / "blob.bin").write_bytes(b"\0" + marker.encode())
            after = inspect_workspace(root, [], ["**"], before)
            diff = Path(temp) / "diff.patch"
            _make_diff(root, baseline, after, diff)
            content = diff.read_text(encoding="utf-8")
            self.assertNotIn(marker, content)
            self.assertIn("REDACTED", content)
            self.assertIn("binary file", content)

    def test_schema_rejects_nonobject_events_and_nonstring_paths(self):
        base = build_result(participant="fake", track="same-model", model=None, task_id="01")
        for field, invalid in (("scenario_events", ["bad"]), ("raw_log_paths", {"stdout": 123}), ("unsupported", [False])):
            with self.assertRaises(ValueError):
                validate_result({**base, field: invalid})

    def args(self, output, task="14", budget=None):
        return SimpleNamespace(output=str(output), summary=False, task=task, config=None, participant="fake", track="same-model", model=None, dry_run=False, allow_real=False, budget_usd=budget, repeat=3, resume=True, timeout_seconds=None)

    def test_unsupported_is_recorded_without_invoking_participant(self):
        from participants.fake import FakeAdapter
        with tempfile.TemporaryDirectory() as tmp, patch.object(FakeAdapter, "supports", return_value=False), patch("harness.runner._call_adapter") as invoke, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(execute(self.args(tmp)), 0)
            invoke.assert_not_called()
            records = [json.loads(path.read_text(encoding="utf-8")) for path in Path(tmp).rglob("*.result.json")]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(row["status"] == "unsupported" and row["success"] is None for row in records))

    def test_unknown_cost_stops_budgeted_run(self):
        data = {"exit_code": 0, "events": [], "scenario_events": [], "usage": {"cost_usd": None}}
        with tempfile.TemporaryDirectory() as tmp, patch("harness.runner._call_adapter", return_value=(data, False)) as invoke, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(execute(self.args(tmp, "01", 1.0)), 0)
            self.assertEqual(invoke.call_count, 1)
            records = [json.loads(path.read_text(encoding="utf-8")) for path in Path(tmp).rglob("*.result.json")]
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["cost_usd"])
            self.assertIn("cost unknown", records[0]["runner_error"])

    def test_real_worker_timeout_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            data, timed_out = _call_adapter("fake", {}, "01", workspace, ROOT / "tasks/01", "fake only", None, .001, None)
            self.assertTrue(timed_out)
            self.assertIn("timeout", data["error"])


if __name__ == "__main__":
    unittest.main()
