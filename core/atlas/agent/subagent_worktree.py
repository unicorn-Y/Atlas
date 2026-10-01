# Ported from NousResearch/hermes-agent@330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3:
# tools/subagent_worktree.py (MIT, (c) Nous Research).
# Changes: Atlas branch naming and subprocess integration; no Hermes runtime imports.
"""Git worktree helpers for isolated Atlas children.

An empty, clean child worktree may be removed after both git probes succeed. Any
commit, dirty file, or failed inspection leaves the worktree and branch in place.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
_GIT_TIMEOUT = 30


def _run_git(args: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=_GIT_TIMEOUT,
        stdin=subprocess.DEVNULL, check=False,
    )


def resolve_repo_root(path: str | None) -> str | None:
    candidate = os.path.abspath(os.path.expanduser(path or ""))
    if not candidate or not os.path.isdir(candidate):
        return None
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=candidate)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _ensure_gitignore_entry(repo_root: str) -> None:
    """Keep worktrees out of the parent repository's status output."""
    path = Path(repo_root) / ".gitignore"
    try:
        content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if ".worktrees/" not in content.splitlines():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(("" if not content or content.endswith("\n") else "\n")
                             + ".worktrees/\n")
    except OSError as exc:
        log.warning("Could not add .worktrees/ to %s: %s", path, exc)


def create_subagent_worktree(
    parent_cwd: str | None, subagent_id: str | None = None,
) -> dict[str, str] | None:
    """Create `<repo>/.worktrees/subagent-<id>` and an Atlas-owned branch."""
    repo_root = resolve_repo_root(parent_cwd)
    if not repo_root:
        return None
    suffix = re.sub(r"[^A-Za-z0-9._-]", "-", subagent_id or uuid.uuid4().hex[:8])
    name = f"subagent-{suffix}"
    branch = f"atlas-subagent/{suffix}"
    worktree = Path(repo_root) / ".worktrees" / name
    try:
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _ensure_gitignore_entry(repo_root)
        base = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
        if base.returncode:
            return None
        result = _run_git(
            ["worktree", "add", str(worktree), "-b", branch, base.stdout.strip()],
            cwd=repo_root,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Subagent worktree creation failed: %s", exc)
        return None
    if result.returncode:
        log.warning("Subagent worktree creation failed: %s", result.stderr.strip())
        return None
    return {"path": str(worktree), "branch": branch, "repo_root": repo_root,
            "base_commit": base.stdout.strip()}


def _base_payload(info: dict[str, str]) -> dict[str, Any]:
    return {"path": info.get("path", ""), "branch": info.get("branch", ""),
            "commits": 0, "dirty": False, "pruned": False}


def mark_worktree_payload_unproven(
    payload: dict[str, Any], reason: str, *, unmeasured: str = "commits/dirty",
) -> dict[str, Any]:
    path, branch = payload.get("path", ""), payload.get("branch", "")
    payload["inspection_failed"] = True
    payload["note"] = (
        f"Git 检查失败（{reason}）：{unmeasured} 未知，不能确认工作树为空且干净。"
        f"已保留目录 {path} 和分支 {branch}，请检查后再处理。"
    )
    log.warning("Git inspection failed; preserving child worktree %s (%s)", path, branch)
    return payload


def unproven_worktree_payload(info: dict[str, str], reason: str) -> dict[str, Any]:
    return mark_worktree_payload_unproven(_base_payload(info), reason)


def finalize_subagent_worktree(
    info: dict[str, str], *, prune: bool = True,
) -> dict[str, Any]:
    """Remove only a proven empty worktree; otherwise preserve it for review."""
    path, branch, base = info.get("path", ""), info.get("branch", ""), info.get("base_commit", "")
    payload = _base_payload(info)
    if not path or not os.path.isdir(path):
        payload["pruned"] = True
        return payload
    if not base:
        return mark_worktree_payload_unproven(
            payload, "base_commit is missing", unmeasured="commits",
        )
    probes = (
        ("commits", "rev-list", ["rev-list", "--count", f"{base}..HEAD"],
         lambda value: int(value or 0)),
        ("dirty", "status", ["status", "--porcelain"], bool),
    )
    failed: list[str] = []
    unmeasured: list[str] = []
    try:
        for field, label, args, parse in probes:
            result = _run_git(args, cwd=path)
            if result.returncode == 0:
                payload[field] = parse(result.stdout.strip())
            else:
                failed.append(f"{label} exit {result.returncode}: {result.stderr.strip()[:200]}")
                unmeasured.append(field)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return mark_worktree_payload_unproven(payload, f"inspection raised: {exc}")
    if failed:
        return mark_worktree_payload_unproven(
            payload, "; ".join(failed), unmeasured="/".join(unmeasured),
        )
    if prune and payload["commits"] == 0 and not payload["dirty"]:
        try:
            removed = _run_git(["worktree", "remove", "--force", path], cwd=info.get("repo_root", path))
            if removed.returncode == 0:
                _run_git(["branch", "-D", branch], cwd=info.get("repo_root", path))
                payload["pruned"] = True
        except (OSError, subprocess.SubprocessError) as exc:
            return mark_worktree_payload_unproven(payload, f"cleanup raised: {exc}")
    return payload
