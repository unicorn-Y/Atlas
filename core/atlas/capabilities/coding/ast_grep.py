"""ast-grep CLI bridge for structured search and rewrites."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _executable() -> str | None:
    executable = shutil.which("ast-grep") or shutil.which("sg")
    if executable:
        return executable
    repo_root = Path(
        os.environ.get("ATLAS_ROOT", Path(__file__).resolve().parents[4])
    ).resolve()
    for package_root in (
        repo_root / "node_modules" / "@ast-grep" / "cli-win32-x64-msvc",
        repo_root / "frontend" / "node_modules" / "@ast-grep" / "cli-win32-x64-msvc",
    ):
        for package in ("ast-grep.exe", "sg.exe"):
            candidate = package_root / package
            if candidate.is_file():
                return str(candidate)
    return None


def run(arguments: list[str], *, cwd: str, timeout: int = 60) -> dict[str, Any]:
    executable = _executable()
    if not executable:
        raise FileNotFoundError("ast-grep CLI is unavailable")
    result = subprocess.run(
        [executable, *arguments],
        cwd=Path(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
