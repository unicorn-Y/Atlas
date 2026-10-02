"""Subprocess acceptance tests for the public CLI, using only fake."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class FakeE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="t1-e2e-中文-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.output = self.folder / "results"
        if os.environ.get("T1_E2E_EVIDENCE_DIR"):
            self.addCleanup(self.preserve_evidence)

    def preserve_evidence(self):
        target = Path(os.environ["T1_E2E_EVIDENCE_DIR"]) / self._testMethodName
        shutil.copytree(self.folder, target, dirs_exist_ok=True)
        for path in target.rglob("*.result.json"):
            data = path.read_text(encoding="utf-8")
            data = data.replace(json.dumps(str(self.folder))[1:-1], json.dumps(str(target))[1:-1])
            path.write_text(data, encoding="utf-8")

    def run_cli(self, *args, mode="success", cost=0.01):
        config = self.folder / "fake.toml"
        config.write_text('[participants.fake]\nfake_mode = "' + mode + '"\nfake_cost_usd = ' + str(cost) + '\n', encoding="utf-8")
        command = [sys.executable, str(ROOT / "run.py"), "--participant", "fake", "--task", "01", "--output", str(self.output), "--config", str(config), *args]
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        return result

    def results(self):
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.output.rglob("*.result.json"))]

    def test_repeat_resume_schema_usage_and_summary(self):
        self.run_cli("--repeat", "2")
        results = self.results()
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertTrue(result["success"], result)
            self.assertEqual(result["check_exit_code"], 0)
            self.assertGreater(result["input_tokens"], 0)
            self.assertEqual(result["cost_usd"], 0.01)
            self.assertFalse(result["forbidden_changes"])
            self.assertGreaterEqual(result["duration_ms"], 0)
            self.assertTrue(result["raw_log_paths"])
        before = {str(path): path.stat().st_mtime_ns for path in self.output.rglob("*.result.json")}
        self.run_cli("--repeat", "2")
        self.assertEqual(before, {str(path): path.stat().st_mtime_ns for path in self.output.rglob("*.result.json")})
        summary = subprocess.run([sys.executable, str(ROOT / "run.py"), "--summary", "--output", str(self.output)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertIn("fake", summary.stdout)

    def test_budget_stops_next_attempt_and_resume_counts_cost(self):
        self.run_cli("--repeat", "3", "--budget-usd", "0.005")
        self.assertEqual(len(self.results()), 1)
        self.run_cli("--repeat", "3", "--budget-usd", "0.005")
        self.assertEqual(len(self.results()), 1)

    def test_forbidden_change_cannot_pass(self):
        self.run_cli(mode="forbidden")
        result = self.results()[0]
        self.assertFalse(result["success"])
        self.assertTrue(result["forbidden_changes"])

    def test_failure_preserves_failed_check(self):
        self.run_cli(mode="failure")
        result = self.results()[0]
        self.assertFalse(result["success"])
        self.assertNotEqual(result["check_exit_code"], 0)

    def test_timeout_is_explicit(self):
        self.run_cli(mode="timeout")
        result = self.results()[0]
        self.assertFalse(result["success"])
        self.assertIn("timeout", str(result.get("participant_error")))

    def test_all_twenty_fake_tasks(self):
        self.run_cli("--task", "01-20")
        results = self.results()
        self.assertEqual(len(results), 20)
        failures = [r for r in results if not r["success"]]
        detail = []
        for result in failures:
            path = result.get("raw_log_paths", {}).get("check")
            detail.append({"result": result, "check_tail": Path(path).read_text(encoding="utf-8", errors="replace")[-1800:] if path and Path(path).exists() else None})
        self.assertEqual(failures, [], json.dumps(detail, ensure_ascii=True))

    def test_default_guard_rejects_real_execution(self):
        command = [sys.executable, str(ROOT / "run.py"), "--participant", "codex", "--task", "01", "--output", str(self.output)]
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("allow-real", done.stdout + done.stderr)
        self.assertEqual(self.results(), [])

    def test_dry_run_never_creates_executed_results(self):
        self.run_cli("--dry-run")
        self.assertFalse(any(result.get("success") is True for result in self.results()))

    def test_dry_run_ignores_zero_budget_and_prepares_no_upstream(self):
        self.run_cli("--dry-run", "--config", str(ROOT / "config.example.toml"), "--task", "08")
        results = self.results()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "dry_run")
        self.assertTrue(Path(results[0]["raw_log_paths"]["command"]).is_file())


if __name__ == "__main__":
    unittest.main()
