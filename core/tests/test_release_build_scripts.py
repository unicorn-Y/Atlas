"""Focused checks for the Windows release packaging inputs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="the bundled Node package is Windows x64 only")
def test_node_archive_hash_mismatch_fails_and_clears_staging(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    frontend = repository / "frontend"
    target = frontend / "backend-release" / "runtime" / "node"
    target.mkdir(parents=True, exist_ok=True)
    (target / "stale-stage-marker").write_text("stale", encoding="utf-8")
    wrong_archive = tmp_path / "node-cache.zip"
    wrong_archive.write_bytes(b"not the canonical Node archive")
    env = os.environ.copy()
    env["ATLAS_NODE_ARCHIVE"] = str(wrong_archive)

    result = subprocess.run(
        ["node", str(frontend / "scripts" / "package-node.mjs")],
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Node runtime source selection: local archive" in result.stdout
    assert "Node archive SHA-256 mismatch" in result.stderr
    assert not target.exists(), "failed archive verification left stale Node staging behind"
