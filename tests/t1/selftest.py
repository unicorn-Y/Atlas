"""Verify all fixtures are meaningful: unsolved red, reference green."""
import argparse
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent


def check(task, workspace, timeout):
    try:
        result = subprocess.run([sys.executable, str(task / "check.py"), str(workspace)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        return {"exit_code": result.returncode, "log": (result.stdout + result.stderr)[-2500:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "log": "check timed out"}


def verify(task, full_upstream=False):
    required = ["task.md", "manifest.toml", "check.py", "rubric.md", "fixture", "solution"]
    missing = [name for name in required if not (task / name).exists()]
    if missing:
        return {"task_id": task.name, "passed": False, "error": "missing: " + ", ".join(missing)}
    manifest = tomllib.loads((task / "manifest.toml").read_text(encoding="utf-8-sig"))
    timeout = max(60, float(manifest.get("timeout_seconds", 120)))
    with tempfile.TemporaryDirectory(prefix="Atlas-T1-中文-") as tmp:
        workspace = Path(tmp) / "工作副本"
        shutil.copytree(task / "fixture", workspace)
        # Offline evidence fixtures are complete. Full upstream prepare is
        # verified separately; never clone/network on dry-run or selftest.
        setup = task / "setup.py"
        prepared = setup.is_file() and (full_upstream or not manifest.get("upstream_repository"))
        try:
            if prepared:
                subprocess.run([sys.executable, str(setup), str(workspace)], check=True, capture_output=True, timeout=600)
            baseline = check(task, workspace, timeout)
            shutil.copytree(task / "solution", workspace, dirs_exist_ok=True)
            solved = check(task, workspace, timeout)
            protected = manifest.get("protected_paths", ["tests/**"])
            originals = [path.relative_to(task / "fixture") for path in (task / "fixture").rglob("*") if path.is_file() and any(fnmatch.fnmatchcase(path.relative_to(task / "fixture").as_posix(), pattern) for pattern in protected)]
            tamper_checks = []
            if solved["exit_code"] == 0 and originals:
                victim = workspace / originals[0]
                original = victim.read_bytes()
                victim.unlink()
                deleted = check(task, workspace, timeout)
                victim.write_bytes(original + b"\n# forbidden test edit\n")
                modified = check(task, workspace, timeout)
                victim.write_bytes(original)
                tamper_checks = [{"kind": "delete_protected", "rejected": deleted["exit_code"] != 0}, {"kind": "modify_protected", "rejected": modified["exit_code"] != 0}]
            return {"task_id": task.name, "passed": baseline["exit_code"] != 0 and solved["exit_code"] == 0 and all(c["rejected"] for c in tamper_checks), "baseline": baseline, "reference": solved, "tamper_checks": tamper_checks, "full_upstream": prepared and bool(manifest.get("upstream_repository"))}
        finally:
            if prepared and (task / "cleanup.py").is_file():
                subprocess.run([sys.executable, str(task / "cleanup.py"), str(workspace)], check=True, capture_output=True, timeout=60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="01-20")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full-upstream", action="store_true", help="Prepare actual pinned source checkout for repository tasks")
    args = parser.parse_args()
    if "-" in args.task:
        start, end = map(int, args.task.split("-", 1))
        ids = [f"{n:02}" for n in range(start, end + 1)]
    else:
        ids = [f"{int(n):02}" for n in args.task.split(",")]
    results = []
    for task_id in ids:
        try:
            result = verify(ROOT / "tasks" / task_id, args.full_upstream)
        except Exception as exc:
            result = {"task_id": task_id, "passed": False, "error": str(exc)}
        results.append(result)
        print(task_id, "PASS" if result["passed"] else "FAIL", flush=True)
        if not result["passed"]:
            print(json.dumps(result, ensure_ascii=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixtures: {sum(r['passed'] for r in results)}/{len(results)} passed")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
