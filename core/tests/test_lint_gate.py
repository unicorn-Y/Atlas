"""H6 exception gate: critical scopes are clean and other scopes cannot grow."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).parent / "snapshots" / "ruff_exceptions_baseline.json"
CRITICAL = re.compile(
    r"^atlas/(?:engine/|agent/|models/|api/|server\.py$|gateway_service\.py$|"
    r"heartbeat/|automation/|channels/)"
)


def test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows():
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "atlas", "--select", "BLE001,S110,S112",
         "--ignore-noqa", "--output-format=json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert completed.returncode in (0, 1), completed.stderr
    rows = json.loads(completed.stdout)
    current = Counter(
        (Path(row["filename"]).relative_to(ROOT).as_posix(), row["code"]) for row in rows
    )
    critical = {scope: count for scope, count in current.items() if CRITICAL.match(scope[0])}
    assert critical == {}, critical
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    allowed = Counter((row["file"], row["code"]) for row in baseline["violations"])
    increases = {scope: count for scope, count in current.items() if count > allowed[scope]}
    assert increases == {}, increases
    totals = Counter(row["code"] for row in rows)
    assert all(count <= baseline["counts"].get(rule, 0) for rule, count in totals.items())
