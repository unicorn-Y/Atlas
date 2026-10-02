"""Run preparation gates, exclusively against local fakes and dry runs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="Evidence directory outside committed fixture tree")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    commands = [
        ("harness-unit", [sys.executable, "-m", "unittest", "discover", "-s", "harness/tests", "-p", "test*.py", "-v"]),
        ("adapters-unit", [sys.executable, "-m", "unittest", "discover", "-s", "participants/tests", "-p", "test*.py", "-v"]),
        ("fault-proxy", [sys.executable, "-m", "unittest", "discover", "-s", "fault_proxy", "-p", "test_proxy.py", "-v"]),
        ("fake-e2e", [sys.executable, "-m", "unittest", "test_e2e", "-v"]),
        ("fixtures", [sys.executable, "selftest.py", "--output", str(args.output / "fixtures.json")]),
        ("pinned-upstream", [sys.executable, "selftest.py", "--task", "08-09", "--full-upstream", "--output", str(args.output / "pinned-upstream.json")]),
    ]
    commands += [("dry-run-" + name, [sys.executable, "run.py", "--participant", name, "--task", "01-20", "--dry-run", "--output", str(args.output / "dry-run" / name)]) for name in ("atlas", "claude", "codex", "opencode", "pi", "hermes", "zcode", "fake")]
    results = []
    # All HOME/application state exposed to test subprocesses is disposable.
    with tempfile.TemporaryDirectory(prefix="t1-verification-state-") as isolated:
        env = {key: value for key, value in os.environ.items() if not any(marker in key.upper() for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
        env.update({"HOME": isolated, "USERPROFILE": isolated, "HERMES_HOME": isolated, "ATLAS_DATA_DIR": isolated, "ATLAS_SCHEDULER_ENABLED": "false", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})
        env["T1_E2E_EVIDENCE_DIR"] = str(args.output / "fake-e2e-runs")
        for label, command in commands:
            try:
                done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                code, log = done.returncode, done.stdout + done.stderr
                if "unit" in label or label in {"fake-e2e", "fault-proxy"}:
                    if "Ran 0 tests" in log:
                        code = 1
            except subprocess.TimeoutExpired as exc:
                code, log = -1, "verification timeout: " + str(exc)
            (args.output / (label + ".log")).write_text(log, encoding="utf-8")
            results.append({"gate": label, "exit_code": code, "command": command, "log_path": str(args.output / (label + ".log"))})
            print(label, "PASS" if code == 0 else "FAIL", flush=True)
            if code:
                print(log[-2500:], flush=True)
    (args.output / "verification.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Preparation gates: %d/%d passed" % (sum(r["exit_code"] == 0 for r in results), len(results)))
    return 0 if all(r["exit_code"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
