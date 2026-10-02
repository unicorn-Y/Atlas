"""Pinned, cache-backed upstream checkout helper for T1 research tasks 08–09."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path


def run(args: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-3000:]}")
    return result.stdout.strip()


def prepare(workspace: Path, slug: str, remote: str, commit: str) -> Path:
    workspace = workspace.resolve()
    cache_root = Path(os.environ.get("ATLAS_T1_SOURCE_CACHE", Path(tempfile.gettempdir()) / "atlas-t1-source-cache")).resolve()
    if cache_root == workspace or workspace in cache_root.parents:
        raise ValueError("upstream cache must be outside the participant workspace")
    cache = cache_root / slug
    cache_root.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--no-checkout", "--filter=blob:none", remote, str(cache)])
    actual = run(["git", "-C", str(cache), "rev-parse", "HEAD"])
    if actual != commit:
        run(["git", "-C", str(cache), "fetch", "--depth", "1", "origin", commit])
        run(["git", "-C", str(cache), "checkout", "--detach", commit])
    actual = run(["git", "-C", str(cache), "rev-parse", "HEAD"])
    if actual != commit:
        raise RuntimeError(f"cache commit mismatch: expected {commit}, got {actual}")

    destination = workspace / "source" / "upstream" / slug
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing source directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A linked worktree shares the pinned cache objects without asking Git to
    # re-transfer promisor objects from a partial clone. The visible directory
    # is a full, read-only-intended checkout and its .git pointer stays outside
    # the participant workspace.
    run(["git", "-C", str(cache), "worktree", "add", "--detach", str(destination), commit])
    actual = run(["git", "-C", str(destination), "rev-parse", "HEAD"])
    if actual != commit:
        raise RuntimeError(f"workspace source commit mismatch: expected {commit}, got {actual}")
    return destination


def cleanup(workspace: Path, slug: str) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("invalid upstream slug")
    workspace = workspace.resolve()
    destination = workspace / "source" / "upstream" / slug
    if not destination.exists():
        return
    resolved = destination.resolve()
    if resolved == workspace or workspace not in resolved.parents:
        raise ValueError("refusing cleanup outside participant workspace")
    git_dir = Path(run(["git", "-C", str(destination), "rev-parse", "--git-dir"]))
    if not git_dir.is_absolute():
        git_dir = (destination / git_dir).resolve()
    else:
        git_dir = git_dir.resolve()
    expected_cache = Path(os.environ.get("ATLAS_T1_SOURCE_CACHE", Path(tempfile.gettempdir()) / "atlas-t1-source-cache")).resolve() / slug
    expected_git_dir = (expected_cache / ".git" / "worktrees").resolve()
    if not git_dir.is_relative_to(expected_git_dir):
        raise ValueError("worktree metadata does not belong to the configured external source cache")
    run(["git", "-C", str(expected_cache), "worktree", "remove", "--force", str(resolved)])
