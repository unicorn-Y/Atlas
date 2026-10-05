"""The Hermes fork commit Atlas is built against, and whether it is what is installed.

The pin lives in ``core/pyproject.toml`` under ``[tool.atlas.hermes]``. Hermes is not a
pip dependency (the fork refuses wheel builds); ``core/scripts/setup_hermes.py`` installs
an editable checkout of the pinned commit.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tomllib
from pathlib import Path
from typing import Any

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def read_pin(pyproject: Path = PYPROJECT) -> dict[str, str]:
    """Return ``{"repository", "commit"}`` from ``[tool.atlas.hermes]``."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    hermes = data["tool"]["atlas"]["hermes"]
    return {"repository": str(hermes["repository"]), "commit": str(hermes["commit"])}


def installed_hermes_root() -> Path | None:
    """Directory of the importable Hermes source tree, if Hermes is installed."""
    spec = importlib.util.find_spec("run_agent")
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).resolve().parent


def checkout_commit(root: Path) -> str | None:
    """HEAD of a Hermes git checkout, or None when it is not a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


def check() -> dict[str, Any]:
    """Doctor check: the installed Hermes checkout is at the pinned commit."""
    if not PYPROJECT.exists():
        # Packaged builds bundle the Hermes sources they were built from.
        return {"ok": True, "detail": "packaged build"}
    pinned = read_pin()["commit"]
    root = installed_hermes_root()
    if root is None:
        return {"ok": False, "pinned": pinned,
                "detail": "Hermes is not installed; run core/scripts/setup_hermes.py"}
    head = checkout_commit(root)
    return {
        "ok": head == pinned,
        "pinned": pinned,
        "installed": head or "unknown (not a git checkout)",
        "path": str(root),
        **({} if head == pinned else {"detail": "run core/scripts/setup_hermes.py"}),
    }
