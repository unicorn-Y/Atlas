"""Bundled Node runtime resolution and read-only diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NODE_VERSION = "v22.23.3"
NODE_ARCHIVE = "node-v22.23.3-win-x64.zip"
NODE_SOURCE = "https://nodejs.org/dist/v22.23.3/node-v22.23.3-win-x64.zip"
NODE_ARCHIVE_SHA256 = "2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71"


@dataclass(frozen=True)
class NodeRuntime:
    executable: Path | None
    source: str
    npm_script: Path | None
    npx_script: Path | None

    @property
    def bundled(self) -> bool:
        return self.source == "bundled"


def bundled_node_directory() -> Path:
    configured = os.environ.get("ATLAS_NODE_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    atlas_root = os.environ.get("ATLAS_ROOT")
    if atlas_root:
        return (Path(atlas_root) / "runtime" / "node").resolve()
    return (Path(__file__).resolve().parents[3] / "runtime" / "node").resolve()


def _npm_scripts(directory: Path) -> tuple[Path | None, Path | None]:
    npm_root = directory / "npm" / "bin"
    npm = npm_root / "npm-cli.js"
    npx = npm_root / "npx-cli.js"
    return (npm if npm.is_file() else None, npx if npx.is_file() else None)


def resolve_node_runtime() -> NodeRuntime:
    """Prefer Atlas's packaged runtime; fall back to system Node for development."""
    directory = bundled_node_directory()
    executable = directory / "node.exe"
    if executable.is_file():
        npm, npx = _npm_scripts(directory)
        return NodeRuntime(executable, "bundled", npm, npx)
    if os.environ.get("ATLAS_NODE_RUNTIME_REQUIRED") == "1":
        return NodeRuntime(None, "missing", None, None)
    system_node = shutil.which("node")
    if system_node:
        return NodeRuntime(Path(system_node), "system", None, None)
    return NodeRuntime(None, "missing", None, None)


def _probe(executable: Path | None, *, timeout: float = 3.0) -> dict[str, Any]:
    if executable is None or not executable.is_file():
        return {
            "available": False,
            "version": None,
            "blocking_reason": "Node executable is missing",
        }
    try:
        result = subprocess.run(
            [str(executable), "--version"], check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "version": None,
                "blocking_reason": f"Node executable could not run: {exc}"}
    version = result.stdout.strip() if result.returncode == 0 else None
    return {
        "available": result.returncode == 0 and bool(version),
        "version": version,
        "blocking_reason": None if result.returncode == 0 and version else
            f"Node version probe exited with code {result.returncode}",
    }


def get_node_runtime_status() -> dict[str, Any]:
    """Report bundled and development Node availability without changing state."""
    runtime = resolve_node_runtime()
    bundled = runtime if runtime.bundled else NodeRuntime(
        bundled_node_directory() / "node.exe", "bundled",
        *_npm_scripts(bundled_node_directory()),
    )
    bundled_probe = _probe(bundled.executable)
    system_executable = Path(shutil.which("node")) if shutil.which("node") else None
    system_probe = _probe(system_executable)
    npm_available = bool(bundled.npm_script and bundled.npx_script)
    available = runtime.executable is not None and (
        not runtime.bundled or npm_available
    )
    reason = None
    if runtime.executable is None:
        reason = "Atlas bundled Node is missing and no system Node is available"
    elif runtime.bundled and not npm_available:
        reason = "Atlas bundled Node is missing npm/npx scripts"
    elif runtime.bundled and not bundled_probe["available"]:
        reason = bundled_probe["blocking_reason"]
        available = False
    return {
        "available": available,
        "source": runtime.source,
        "version": bundled_probe["version"] if runtime.bundled else system_probe["version"],
        "bundled": {**bundled_probe, "npm_npx_available": npm_available},
        "system": system_probe,
        "blocking_reason": reason,
        "expected_bundled_version": NODE_VERSION,
        "archive": NODE_ARCHIVE,
        "archive_sha256": NODE_ARCHIVE_SHA256,
    }
