"""U39 work-item acceptance scenarios. Uses a real model for the CLI usage-file flow."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
FRONTEND = ROOT / "frontend"
sys.path.insert(0, str(CORE))


def run(label: str, command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 300) -> str:
    print(f"U39 scenario: {label}", flush=True)
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr)[-2400:]
        raise RuntimeError(f"{label} failed with exit {result.returncode}:\n{detail}")
    print(f"U39 scenario PASS: {label}", flush=True)
    return result.stdout


def pytest(label: str, selectors: list[str], env: dict[str, str]) -> None:
    run(label, [sys.executable, "-m", "pytest", *selectors, "-q"], cwd=CORE, env=env)


def cli_usage_terminal_scenarios() -> None:
    from atlas.cli import _cli_usage_record, _write_cli_usage_file

    with tempfile.TemporaryDirectory(prefix="atlas-u39-usage-terminal-") as temp:
        root = Path(temp)
        for status in ("failed", "cancelled"):
            target = root / f"{status}.json"
            record = _cli_usage_record(
                run_id=f"run-{status}", session_id=f"session-{status}", status=status,
                model="deepseek-v4.1-flash", rows=[],
            )
            _write_cli_usage_file(target, record)
            written = json.loads(target.read_text(encoding="utf-8"))
            if written.get("status") != status or written.get("schema_version") != 1:
                raise AssertionError(f"usage file did not preserve {status} terminal state")
        blocked = root / "not-a-file"
        blocked.mkdir()
        try:
            _write_cli_usage_file(blocked, record)
        except OSError:
            pass
        else:
            raise AssertionError("usage-file write failure was silently accepted")


def main() -> None:
    env = dict(os.environ)
    env["ATLAS_ROOT"] = r"C:\engine-reg\_atlasroot"
    python_path = [str(CORE), str(CORE / "atlas" / "engine_core" / "state")]
    if env.get("PYTHONPATH"):
        python_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_path)

    run("0e extraction prompt suppression and reuse triggers",
        [shutil.which("node.exe") or "node", str(ROOT / "node_modules" / "vitest" / "vitest.mjs"),
         "run", "--root", ".", "src/renderer/services/skillExtraction.test.ts"],
        cwd=FRONTEND, env=env, timeout=180)
    pytest("0c ephemeral transcript and runtime persistence isolation", [
        "tests/test_backend_parity_wave2.py::test_ephemeral_run_does_not_change_source_conversation",
        "tests/test_api_runtime.py::test_ephemeral_runs_are_not_written_to_runtime_database",
    ], env)

    cli_usage_terminal_scenarios()
    print("U39 scenario PASS: 1 failed/cancelled versioned usage files and unwritable-path error", flush=True)

    from real_model_check import AttemptResult, retry_real_model_check

    def live_usage_attempt(prompt: str, attempt_number: int) -> AttemptResult:
        with tempfile.TemporaryDirectory(prefix=f"atlas-u39-usage-{attempt_number}-") as temp:
            usage_path = Path(temp) / "usage.json"
            result = subprocess.run([
                sys.executable, "-m", "atlas.cli", "exec", "--model", "deepseek-v4.1-flash",
                "--usage-file", str(usage_path), "--json", prompt,
            ], cwd=CORE, env=env, capture_output=True, text=True,
               encoding="utf-8", errors="replace", timeout=300)
            answer = result.stdout or ""
            if result.returncode:
                return AttemptResult(False, answer=answer,
                                     detail=f"CLI exit {result.returncode}: {(result.stderr or '')[-1200:]}")
            try:
                record = json.loads(usage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return AttemptResult(False, answer=answer, detail=f"usage record unavailable: {exc}")
            usage = record.get("usage") or {}
            valid_record = (record.get("schema_version") == 1 and record.get("status") == "completed"
                            and bool(record.get("run_id")) and record.get("model") == "deepseek-v4.1-flash"
                            and isinstance(usage.get("unavailable"), dict))
            passed = valid_record and "U39_USAGE_OK" in answer
            return AttemptResult(
                passed, answer=answer,
                detail="usage schema or requested marker missing" if not passed else "",
                value=record,
            )

    retry_real_model_check(
        "U39 real CLI usage-file completion",
        "Complete one minimal Atlas run and reply with exactly U39_USAGE_OK.",
        live_usage_attempt,
    )

    pytest("2 complete branch tree and checkpoint fork workspace restore", [
        "tests/test_u39_checkpoint_fork.py",
        "tests/test_hermes_session_sync.py::test_fork_copies_selected_turn_and_delete_removes_hermes_history",
        "tests/test_hermes_session_sync.py::test_fork_session_through_turn_direct_cuts_from_sessiondb_transcript",
    ], env)
    pytest("3 online subagent overview API across parent runs", [
        "tests/test_api_runtime.py::test_online_subtask_query_spans_parent_runs_and_excludes_terminal_children",
    ], env)
    pytest("4 successful-turn auto recap persistence and recent retrieval", [
        "tests/test_api_runtime.py::test_auto_recaps_are_durable_and_listed_per_conversation",
        "tests/test_api_runtime.py::test_auto_recap_route_only_summarizes_a_completed_nonempty_turn",
    ], env)
    pytest("5 daily insight trends, model filtering, missing prices and session counts", [
        "tests/test_u39_insights.py",
        "tests/test_usage.py::test_usage_query_filters_model_without_changing_group_aggregation",
    ], env)
    print("U39 CHECK PASS")


if __name__ == "__main__":
    main()
