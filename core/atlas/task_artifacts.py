"""Small file-backed stores used by reusable Agent task configuration."""

from __future__ import annotations

import re
import json
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _toml_value(value: Any) -> str:
    if value is None:
        raise TypeError("TOML does not support null values")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {_toml_value(item)}" for key, item in value.items()) + " }"
    raise TypeError(f"unsupported TOML value: {type(value).__name__}")


def encode_toml(value: dict[str, Any]) -> str:
    lines: list[str] = []
    scalar_items = [(key, item) for key, item in value.items()
                    if item is not None and not isinstance(item, dict)
                    and not (isinstance(item, list) and item and all(isinstance(row, dict) for row in item))]
    table_items = [(key, item) for key, item in value.items() if isinstance(item, dict)]
    array_table_items = [(key, item) for key, item in value.items()
                         if isinstance(item, list) and item and all(isinstance(row, dict) for row in item)]
    for key, item in scalar_items:
        lines.append(f"{key} = {_toml_value(item)}")
    for key, item in table_items:
        if item is None:
            continue
        if isinstance(item, dict):
            lines.append(f"[{key}]")
            lines.extend(f"{name} = {_toml_value(child)}" for name, child in item.items() if child is not None)
        lines.append("")
    for key, rows in array_table_items:
        for row in rows:
            lines.append(f"[[{key}]]")
            lines.extend(f"{name} = {_toml_value(child)}" for name, child in row.items() if child is not None)
            lines.append("")
    return "\n".join(lines)


class TomlRecordStore:
    def __init__(self, root: Path, kind: str) -> None:
        self.root = root / kind

    def list(self) -> list[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        return [tomllib.loads(path.read_text(encoding="utf-8")) for path in sorted(self.root.glob("*.toml"))]

    def get(self, record_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record_id):
            return None
        path = self.root / f"{record_id}.toml"
        if not path.is_file():
            return None
        return tomllib.loads(path.read_text(encoding="utf-8"))

    def put(self, value: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        record_id = str(value.get("id") or uuid.uuid4())
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record_id):
            raise ValueError("id must contain only letters, numbers, '_' or '-'")
        now = _stamp()
        record = {**value, "id": record_id, "created_at": value.get("created_at") or now, "updated_at": now}
        (self.root / f"{record_id}.toml").write_text(encode_toml(record), encoding="utf-8")
        return record

    def delete(self, record_id: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record_id):
            return False
        path = self.root / f"{record_id}.toml"
        if not path.is_file():
            return False
        path.unlink()
        return True


DEFAULT_PROFILES = [
    {"id": "default", "name": "Default", "description": "Atlas default behavior", "instructions": "", "active_skills": [], "tools": {"allow": None, "deny": []}, "mode": "act"},
    {"id": "architect", "name": "Architect", "description": "Read-only planning and design", "instructions": "Design a solution and explain tradeoffs. Do not modify files.", "active_skills": [], "tools": {"allow": ["local_file", "coding.repo_map", "coding.ast_grep.run"], "deny": []}, "mode": "plan"},
    {"id": "reviewer", "name": "Reviewer", "description": "Read-only code review", "instructions": "Review code for correctness, regressions, and security issues. Do not modify files.", "active_skills": [], "tools": {"allow": ["local_file", "coding.repo_map", "coding.ast_grep.run"], "deny": []}, "mode": "act"},
]


def seed_profiles(store: TomlRecordStore) -> None:
    for profile in DEFAULT_PROFILES:
        if store.get(profile["id"]) is None:
            store.put(profile)


class WorktreeService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        import subprocess
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "git command failed")
        return result.stdout.strip()

    def create(self, workspace: Path, conversation_id: str, base_branch: str | None = None, name: str | None = None) -> dict[str, str]:
        if not (workspace / ".git").exists():
            raise ValueError("workspace is not a git repository")
        short_id = conversation_id.replace("-", "")[:8]
        branch = f"atlas/{short_id}"
        repo_name = workspace.name
        path = workspace.parent / ".atlas-worktrees" / repo_name / short_id
        base = base_branch or self._git(workspace, "branch", "--show-current")
        if not base:
            base = "HEAD"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git(workspace, "worktree", "add", "-b", branch, str(path), base)
        return {"worktree_path": str(path.resolve()), "worktree_branch": branch, "base_branch": base}

    def status(self, workspace: Path, path: Path, branch: str, base_branch: str) -> dict[str, Any]:
        changed = self._git(path, "status", "--porcelain").splitlines()
        ahead_behind = self._git(path, "rev-list", "--left-right", "--count", f"{base_branch}...HEAD").split()
        return {"path": str(path), "branch": branch, "base_branch": base_branch,
                "ahead": int(ahead_behind[1]), "behind": int(ahead_behind[0]),
                "dirty": bool(changed), "changed_files": [row[3:] for row in changed if len(row) > 3]}

    def remove(self, workspace: Path, path: Path, branch: str, force: bool = False, keep_branch: bool = False) -> None:
        dirty = bool(self._git(path, "status", "--porcelain"))
        if dirty and not force:
            raise RuntimeError("worktree has uncommitted changes")
        self._git(workspace, "worktree", "remove", *( ["--force"] if force else []), str(path))
        if not keep_branch:
            self._git(workspace, "branch", "-D", branch)

    def merge(self, workspace: Path, path: Path, branch: str, base_branch: str, strategy: str, message: str | None = None) -> None:
        if strategy not in {"merge", "squash"}:
            raise ValueError("strategy must be 'merge' or 'squash'")
        import subprocess
        dirty_base = subprocess.run(["git", "-C", str(workspace), "status", "--porcelain"], capture_output=True, text=True)
        if dirty_base.stdout.strip():
            raise RuntimeError("base workspace has uncommitted changes")
        checkout = subprocess.run(["git", "-C", str(workspace), "checkout", base_branch], capture_output=True, text=True)
        if checkout.returncode:
            raise ValueError(checkout.stderr.strip())
        args = (["git", "-C", str(workspace), "merge", "--squash", branch]
                if strategy == "squash" else
                ["git", "-C", str(workspace), "merge", "--no-edit", branch])
        merged = subprocess.run(args, capture_output=True, text=True)
        if merged.returncode:
            conflicts = subprocess.run(["git", "-C", str(workspace), "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True).stdout.splitlines()
            aborted = subprocess.run(["git", "-C", str(workspace), "merge", "--abort"], capture_output=True, text=True)
            if aborted.returncode:
                subprocess.run(["git", "-C", str(workspace), "reset", "--merge"], capture_output=True, text=True)
            git_dir_result = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--git-dir"],
                capture_output=True, text=True,
            )
            git_dir = (workspace / git_dir_result.stdout.strip()).resolve()
            final_state = subprocess.run(
                ["git", "-C", str(workspace), "status", "--porcelain"],
                capture_output=True, text=True,
            ).stdout.strip()
            if (git_dir / "MERGE_HEAD").exists() or final_state:
                raise RuntimeError("merge conflict cleanup failed; base workspace remains changed")
            raise FileExistsError("\n".join(conflicts) or merged.stderr.strip())
        if strategy == "squash":
            commit = subprocess.run(["git", "-C", str(workspace), "commit", "-m", message or f"Merge {branch}"], capture_output=True, text=True)
            if commit.returncode:
                subprocess.run(["git", "-C", str(workspace), "reset", "--merge"], capture_output=True, text=True)
                raise ValueError(commit.stderr.strip())
