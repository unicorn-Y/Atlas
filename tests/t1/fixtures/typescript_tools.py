"""Resolve an existing compiler without installing or modifying dependencies."""
import os
from pathlib import Path
import shutil
import subprocess


def compiler(workspace):
    candidates = []
    if os.environ.get("TSC_PATH"):
        candidates.append(Path(os.environ["TSC_PATH"]))
    found = shutil.which("tsc")
    if found:
        path = Path(found)
        if path.suffix.lower() in {".cmd", ".ps1"}:
            candidates.append(path.parent / "node_modules/typescript/bin/tsc")
        else:
            candidates.append(path)
    candidates.append(Path(workspace) / "node_modules/typescript/bin/tsc")
    repository = Path(__file__).resolve().parents[3]
    candidates.append(repository / "node_modules/typescript/bin/tsc")
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repository, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=True).stdout.strip()
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = repository / common_path
        candidates.append(common_path.resolve().parent / "node_modules/typescript/bin/tsc")
    except (OSError, subprocess.SubprocessError):
        pass
    return next((path for path in candidates if path.is_file()), None)
