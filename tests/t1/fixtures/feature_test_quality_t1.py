"""Require added feature tests to distinguish the solution from the baseline."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def _run_test(root: Path, pattern: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def validate_added_feature_tests(task_dir: Path, workspace: Path, new_test: str, legacy_test: str,
                                expected_missing_api: tuple[str, ...]) -> None:
    """Require the new tests to pass solved code and fail baseline behavior only."""
    candidate = workspace / "tests" / new_test
    if not candidate.is_file():
        raise ValueError(f"Add behavioral tests in tests/{new_test}.")

    solved = _run_test(workspace, new_test)
    if solved.returncode:
        raise ValueError("Added feature tests fail against the submitted implementation:\n" + solved.stdout + solved.stderr)
    if "Ran 0 tests" in solved.stderr:
        raise ValueError("The added test file did not run any tests.")

    fixture = task_dir / "fixture"
    with tempfile.TemporaryDirectory(prefix="t1-feature-test-baseline-") as temp:
        baseline = Path(temp)
        shutil.copytree(fixture, baseline, dirs_exist_ok=True)
        (baseline / "tests" / new_test).write_bytes(candidate.read_bytes())

        legacy = _run_test(baseline, legacy_test)
        if legacy.returncode or "Ran 0 tests" in legacy.stderr:
            raise ValueError("Pristine baseline legacy tests must pass before checking new tests:\n" + legacy.stdout + legacy.stderr)

        regression = _run_test(baseline, new_test)
        output = regression.stdout + regression.stderr
        errors = []
        for block in output.split("\n======================================================================\n")[1:]:
            if block.startswith("ERROR:"):
                errors.append(block)
        unexpected_errors = [block for block in errors if not any(token in block for token in expected_missing_api)]
        has_behavioral_failure = "FAILED (failures=" in output
        if regression.returncode == 0 or (not has_behavioral_failure and not errors) or unexpected_errors:
            raise ValueError("Added tests must fail on the pristine baseline through feature assertions or the expected missing API, not unrelated errors:\n" + output)
