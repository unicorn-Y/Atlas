"""H8 startup-speed probe: backend cold start to /api/health + atlas.server import cost.

Reuse of the H0 baseline harness (``baseline_metrics.py``) keeps the cold-start
method identical to ``tasks/results/ATLAS-H1-baseline.json`` so before/after
numbers stay comparable. The probe additionally:

* keeps every server log so the startup phase timeline can be inspected;
* measures ``import atlas.server`` wall time and ``-X importtime`` breakdowns
  (the import chain is the other half of the H8 budget).

No real network access and no real model is used: the fake-model config points
at a closed loopback port, which the startup path never contacts.

Usage (from the repository root, Git Bash):

    core/.venv/Scripts/python.exe core/scripts/startup_probe.py \
        --runs 3 --out artifacts/h8-startup/after.json \
        [--hermes-root D:/hermes-agent-h1-core] [--skip-cold] [--skip-import]

Load context (other lanes building/running tests concurrently) must be recorded
next to the numbers; see artifacts/h8-startup/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline_metrics import (  # noqa: E402  (harness parity with the H0 baseline)
    _available_port,
    _clean_environment,
    _source_metadata,
    _stop_owned_process_tree,
    _write_fake_config,
)


def _import_once(python: Path, core_root: Path, env: dict[str, str], *, importtime: bool) -> dict[str, Any]:
    """Time one ``import atlas.server`` in a fresh interpreter."""
    command = [str(python)]
    if importtime:
        command.append("-X")
        command.append("importtime")
    command += ["-c", "import atlas.server"]
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=core_root, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        return {"seconds": elapsed, "error": result.stderr[-2000:]}
    payload: dict[str, Any] = {"seconds": elapsed}
    if importtime:
        rows: list[tuple[int, int, str]] = []
        for line in result.stderr.splitlines():
            match = re.match(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(.*)", line)
            if match:
                rows.append((int(match.group(1)), int(match.group(2)), match.group(3).strip()))
        if rows:
            payload["importtime_total_us"] = max(row[1] for row in rows)
            payload["importtime_modules"] = len(rows)
            aggregate: dict[str, int] = {}
            for self_us, _cum, name in rows:
                aggregate[name.split(".")[0]] = aggregate.get(name.split(".")[0], 0) + self_us
            payload["importtime_top_packages_us"] = dict(
                sorted(aggregate.items(), key=lambda item: -item[1])[:20],
            )
            payload["importtime_rows"] = [
                {"self_us": self_us, "cum_us": cum, "module": name} for self_us, cum, name in rows
            ]
    return payload


def _cold_start_once_keep_log(
    repo_root: Path, python: Path, hermes_root: Path | None, log_dir: Path, index: int,
    *, timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Cold start to /api/health, timed exactly like baseline_metrics._cold_start_once.

    Differences: the fake-model gateway points at a closed loopback port (startup
    never sends a model request) and the server log is preserved for inspection.
    """
    with tempfile.TemporaryDirectory(prefix="atlas-h8-startup-") as temp:
        data_root = Path(temp)
        dead_gateway = "http://127.0.0.1:9"
        _write_fake_config(data_root, dead_gateway)
        env = _clean_environment(repo_root, data_root, dead_gateway)
        core_root = repo_root / "core"
        paths = [str(core_root)]
        if hermes_root is not None:
            paths.insert(0, str(hermes_root))
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        port = _available_port()
        command = [str(python), "-m", "atlas.cli", "serve", "--port", str(port)]
        log_path = log_dir / f"cold-start-{index}.log"
        started = time.perf_counter()
        with log_path.open("wb") as log:
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
            process = subprocess.Popen(
                command, cwd=core_root, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            try:
                deadline = started + timeout_seconds
                health_url = f"http://127.0.0.1:{port}/api/health"
                while time.perf_counter() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"backend exited {process.returncode}: "
                            f"{log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}"
                        )
                    try:
                        with urllib.request.urlopen(health_url, timeout=0.5) as response:
                            payload = json.loads(response.read().decode("utf-8"))
                        if response.status == 200 and payload.get("status") == "ok":
                            return {
                                "seconds": time.perf_counter() - started,
                                "health": payload,
                                "log": str(log_path),
                            }
                    except (OSError, urllib.error.URLError, json.JSONDecodeError):
                        time.sleep(0.05)
                raise TimeoutError(f"health not ready within {timeout_seconds}s")
            finally:
                _stop_owned_process_tree(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--python", default=str(Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"))
    parser.add_argument("--hermes-root", default=os.environ.get("HERMES_ROOT") or None)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default=None, help="Write the JSON report here")
    parser.add_argument("--log-dir", default=None, help="Directory for server logs and importtime dumps")
    parser.add_argument("--label", default="run", help="Label stored in the report (before/after)")
    parser.add_argument("--load-context", default="", help="Free-text machine load context")
    parser.add_argument("--skip-cold", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    python = Path(args.python).resolve()
    hermes_root = Path(args.hermes_root).resolve() if args.hermes_root else None
    out_path = Path(args.out).resolve() if args.out else None
    log_dir = Path(args.log_dir).resolve() if args.log_dir else (out_path.parent / "logs" if out_path else Path("startup-logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    core_root = repo_root / "core"

    result: dict[str, Any] = {
        "schema_version": 1,
        "label": args.label,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "load_context": args.load_context or "not recorded",
        "source": _source_metadata(repo_root),
        "hermes": _source_metadata(hermes_root) if hermes_root else None,
        "python": str(python),
        "metrics": {},
    }

    if not args.skip_import:
        with tempfile.TemporaryDirectory(prefix="atlas-h8-import-") as temp:
            env = _clean_environment(repo_root, Path(temp), "http://127.0.0.1:9")
            env["PYTHONPATH"] = str(core_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            samples: list[dict[str, Any]] = []
            for index in range(args.runs):
                sample = _import_once(python, core_root, env, importtime=(index == args.runs - 1))
                samples.append(sample)
                if "error" in sample:
                    break
            good = [sample["seconds"] for sample in samples if "error" not in sample]
            result["metrics"]["import_atlas_server"] = {
                "samples_seconds": good,
                "median_seconds": statistics.median(good) if good else None,
                "min_seconds": min(good) if good else None,
                "importtime_total_us": next(
                    (sample.get("importtime_total_us") for sample in reversed(samples) if sample.get("importtime_total_us")),
                    None,
                ),
                "importtime_top_packages_us": next(
                    (sample.get("importtime_top_packages_us") for sample in reversed(samples) if sample.get("importtime_top_packages_us")),
                    None,
                ),
                "status": "measured" if good else "error",
                "error": next((sample.get("error") for sample in samples if "error" in sample), None),
            }
            dump = log_dir / "importtime.txt"
            if samples and "importtime_rows" in samples[-1]:
                with dump.open("w", encoding="utf-8") as handle:
                    for row in samples[-1]["importtime_rows"]:
                        handle.write(f"self {row['self_us']:>9} cum {row['cum_us']:>9}  {row['module']}\n")
                result["metrics"]["import_atlas_server"]["importtime_dump"] = str(dump)

    if not args.skip_cold:
        samples: list[dict[str, Any]] = []
        for index in range(args.runs):
            sample = _cold_start_once_keep_log(repo_root, python, hermes_root, log_dir, index)
            samples.append(sample)
        seconds = [sample["seconds"] for sample in samples]
        result["metrics"]["backend_cold_start"] = {
            "samples_seconds": seconds,
            "median_seconds": statistics.median(seconds),
            "health_statuses": [sample["health"].get("status") for sample in samples],
            "logs": [sample["log"] for sample in samples],
            "status": "measured",
        }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"report written: {out_path}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
