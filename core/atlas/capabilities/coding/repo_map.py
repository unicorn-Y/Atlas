"""Aider's upstream repo-map command wrapper."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def repo_map(path: str, budget: int = 1024) -> dict[str, Any]:
    executable = shutil.which("aider")
    if not executable:
        raise FileNotFoundError("Aider repo-map helper is unavailable")
    result = subprocess.run(
        [executable, "--show-repo-map", "--map-tokens", str(budget)],
        cwd=Path(path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    return {"exit_code": result.returncode, "map": result.stdout, "error": result.stderr}
