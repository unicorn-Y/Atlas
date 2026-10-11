"""GitHub pull request actions for Atlas model-tool calls.

Behavior reference: GitHub CLI `gh pr create` and `gh pr comment` command
contracts. This module uses subprocess argument arrays; no upstream code is copied.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, shell=False,
    )


def _repository_root(workspace: str) -> Path:
    candidate = Path(workspace).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError("The active workspace is not an existing local directory.")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git is not installed or is not available on PATH.")
    result = _run(candidate, git, "rev-parse", "--show-toplevel", timeout=15)
    if result.returncode:
        raise ValueError("The active workspace is not inside a Git repository.")
    return Path(result.stdout.strip()).resolve()


def _require_gh(root: Path) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is unavailable.")
    auth = _run(root, gh, "auth", "status", timeout=15)
    if auth.returncode:
        raise PermissionError("GitHub CLI is not authenticated.")
    return gh


def create_pull_request(
    workspace: str, *, title: str, body: str, base: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """Push the current branch and create a PR with the authenticated gh account."""
    if not title.strip():
        raise ValueError("A non-empty pull request title is required.")
    root = _repository_root(workspace)
    gh = _require_gh(root)
    git = shutil.which("git")
    assert git is not None
    branch_result = _run(root, git, "branch", "--show-current", timeout=15)
    branch = branch_result.stdout.strip()
    if branch_result.returncode or not branch:
        raise ValueError("Creating a pull request requires a checked-out local branch; detached HEAD is unsupported.")
    pushed = _run(root, git, "push", "--set-upstream", "origin", branch, timeout=120)
    if pushed.returncode:
        raise RuntimeError(pushed.stderr.strip() or "Unable to push the current branch.")
    command = [gh, "pr", "create", "--title", title.strip(), "--body", body]
    if base and base.strip():
        command.extend(["--base", base.strip()])
    if draft:
        command.append("--draft")
    created = _run(root, *command, timeout=60)
    if created.returncode:
        raise RuntimeError(created.stderr.strip() or "Unable to create the pull request.")
    view = _run(
        root, gh, "pr", "view", "--json",
        "number,title,url,state,isDraft,baseRefName,headRefName", timeout=30,
    )
    if view.returncode:
        return {"created": True, "url": created.stdout.strip(), "details": view.stderr.strip()}
    try:
        result = json.loads(view.stdout)
    except json.JSONDecodeError:
        return {"created": True, "url": created.stdout.strip()}
    return {"created": True, "pull_request": result}


def comment_pull_request(
    workspace: str, *, body: str, pr_number: int | None = None,
) -> dict[str, Any]:
    """Add a comment to an explicit PR number or the PR for the current branch."""
    if not body.strip():
        raise ValueError("A non-empty pull request comment is required.")
    root = _repository_root(workspace)
    gh = _require_gh(root)
    command = [gh, "pr", "comment"]
    if pr_number is not None:
        if pr_number < 1:
            raise ValueError("pr_number must be a positive integer.")
        command.append(str(pr_number))
    command.extend(["--body", body])
    result = _run(root, *command, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to comment on the pull request.")
    return {"commented": True, "message": result.stdout.strip()}
