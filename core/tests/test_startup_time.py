"""H8 startup-speed gate (taskbook §10 测试).

Cold start to a healthy ``/api/health`` must stay within 5 seconds (median of
three real subprocess starts, fake-model config, no network). Runs the same
harness as the H0 baseline and ``core/scripts/startup_probe.py`` so the numbers
stay comparable with ``tasks/results/ATLAS-H1-baseline.json`` and
``artifacts/h8-startup/``.

Marked ``integration``: it spawns real server processes (and is therefore slow
and machine-sensitive). The unit gate (``-m unit``, the pytest default here)
never picks it up.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from startup_probe import _cold_start_once_keep_log  # noqa: E402

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "core"
PYTHON = CORE_ROOT / ".venv" / "Scripts" / "python.exe"
H8_BUDGET_SECONDS = 5.0
RUNS = 3


@pytest.mark.integration
def test_cold_start_median_within_h8_budget(tmp_path: Path) -> None:
    python = PYTHON if PYTHON.is_file() else Path(sys.executable)
    samples = [
        _cold_start_once_keep_log(REPO_ROOT, python, None, tmp_path, index)
        for index in range(RUNS)
    ]
    seconds = [sample["seconds"] for sample in samples]
    median = statistics.median(seconds)
    assert all(sample["health"].get("status") == "ok" for sample in samples), (
        f"cold starts did not reach a healthy /api/health: {[s['health'] for s in samples]}"
    )
    assert median <= H8_BUDGET_SECONDS, (
        f"cold start median {median:.3f}s exceeds the H8 budget of {H8_BUDGET_SECONDS}s "
        f"(samples: {[round(s, 3) for s in seconds]}; see the lifespan spec in "
        f"tasks/results/ATLAS-H1-H8-lifespan-spec.md for the remaining critical-path work)"
    )
