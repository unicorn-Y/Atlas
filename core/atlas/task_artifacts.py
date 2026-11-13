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
    {"id": "default", "name": "默认", "description": "Atlas 默认行为", "instructions": "", "active_skills": [], "tools": {"allow": None, "deny": []}, "mode": "act"},
    {"id": "architect", "name": "架构师", "description": "只读规划与设计", "instructions": "设计方案并说明取舍，不要修改文件。", "active_skills": [], "tools": {"allow": ["local_file", "coding.repo_map", "coding.ast_grep.run"], "deny": []}, "mode": "plan"},
    {"id": "reviewer", "name": "审查员", "description": "只读代码审查", "instructions": "检查代码的正确性、回归风险和安全问题，不要修改文件。", "active_skills": [], "tools": {"allow": ["local_file", "coding.repo_map", "coding.ast_grep.run"], "deny": []}, "mode": "act"},
]


def seed_profiles(store: TomlRecordStore) -> None:
    legacy_text = {
        "default": {
            "name": "Default", "description": "Atlas default behavior",
            "instructions": "",
        },
        "architect": {
            "name": "Architect", "description": "Read-only planning and design",
            "instructions": "Design a solution and explain tradeoffs. Do not modify files.",
        },
        "reviewer": {
            "name": "Reviewer", "description": "Read-only code review",
            "instructions": "Review code for correctness, regressions, and security issues. Do not modify files.",
        },
    }
    for profile in DEFAULT_PROFILES:
        existing = store.get(profile["id"])
        if existing is None:
            store.put(profile)
        elif all(existing.get(key) == value for key, value in legacy_text[profile["id"]].items()):
            store.put({**existing, **{
                key: profile[key] for key in ("name", "description", "instructions")
            }})


DEFAULT_AGENT_PRESETS = [
    {
        "id": "default", "name": "默认 Agent", "description": "继承当前会话工具权限",
        "capabilities": {
            "tools": {"allow": [], "allow_all": True, "deny": []}, "skills": [], "mcp_servers": [],
            "model": "inherit", "mode": "act",
        },
    },
]


class AgentPresetStore(TomlRecordStore):
    """Revisioned agent capability sets, stored independently from permission policy."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, "agent-presets")

    @staticmethod
    def _names(value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"{label} must be a list of non-empty strings")
        return list(dict.fromkeys(item.strip() for item in value))

    @classmethod
    def _capabilities(cls, value: Any) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
        allow = tools.get("allow")
        allow_all = bool(tools.get("allow_all", allow is None))
        if allow_all:
            allow = None
        if allow is not None:
            allow = cls._names(allow, "tools.allow")
        deny = cls._names(tools.get("deny", []), "tools.deny")
        skills = cls._names(raw.get("skills", []), "skills")
        mcp_servers = cls._names(raw.get("mcp_servers", []), "mcp_servers")
        model = str(raw.get("model") or "inherit")
        mode = str(raw.get("mode") or "act")
        if mode not in {"act", "plan"}:
            raise ValueError("mode must be act or plan")
        return {
            "tools": {"allow": allow or [], "allow_all": allow_all, "deny": deny}, "skills": skills,
            "mcp_servers": mcp_servers, "model": model, "mode": mode,
        }

    def put(self, value: dict[str, Any]) -> dict[str, Any]:
        preset_id = str(value.get("id") or "")
        current = self.get(preset_id) if preset_id else None
        try:
            revision = max(0, int((current or {}).get("revision", 0))) + 1
        except (TypeError, ValueError):
            revision = 1
        record = {
            **value,
            "name": str(value.get("name") or preset_id),
            "description": str(value.get("description") or ""),
            "capabilities": self._capabilities(value.get("capabilities")),
            "revision": revision,
        }
        return super().put(record)

    def seed(self) -> None:
        for preset in DEFAULT_AGENT_PRESETS:
            if self.get(preset["id"]) is None:
                self.put(preset)

    def resolve(self, preset_id: str) -> dict[str, Any]:
        """Return a preset's normalized capability set; never silently fall back."""
        self.seed()
        record = self.get(str(preset_id or ""))
        if record is None:
            raise KeyError(f"unknown agent preset: {preset_id}")
        return self._capabilities(record.get("capabilities"))


class WorktreeService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        import subprocess
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise ValueError(result.stderr.strip() or "git command failed")
        return result.stdout.strip()

    def create(self, workspace: Path, conversation_id: str, base_branch: str | None = None, name: str | None = None) -> dict[str, str]:
        if not (workspace / ".git").exists():
            raise ValueError("workspace is not a git repository")
        short_id = conversation_id.replace("-", "")[:8]
        suffix = re.sub(r"[^a-z0-9-]", "-", str(name or "").lower())[:24].strip("-")
        branch = f"atlas/{short_id}-{suffix}" if suffix else f"atlas/{short_id}"
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
        dirty_base = subprocess.run(["git", "-C", str(workspace), "status", "--porcelain"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if dirty_base.stdout.strip():
            raise RuntimeError("base workspace has uncommitted changes")
        checkout = subprocess.run(["git", "-C", str(workspace), "checkout", base_branch], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if checkout.returncode:
            raise ValueError(checkout.stderr.strip())
        args = (["git", "-C", str(workspace), "merge", "--squash", branch]
                if strategy == "squash" else
                ["git", "-C", str(workspace), "merge", "--no-edit", branch])
        merged = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if merged.returncode:
            conflicts = subprocess.run(["git", "-C", str(workspace), "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()
            aborted = subprocess.run(["git", "-C", str(workspace), "merge", "--abort"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if aborted.returncode:
                subprocess.run(["git", "-C", str(workspace), "reset", "--merge"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            git_dir_result = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--git-dir"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            git_dir = (workspace / git_dir_result.stdout.strip()).resolve()
            final_state = subprocess.run(
                ["git", "-C", str(workspace), "status", "--porcelain"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            ).stdout.strip()
            if (git_dir / "MERGE_HEAD").exists() or final_state:
                raise RuntimeError("merge conflict cleanup failed; base workspace remains changed")
            raise FileExistsError("\n".join(conflicts) or merged.stderr.strip())
        if strategy == "squash":
            commit = subprocess.run(["git", "-C", str(workspace), "commit", "-m", message or f"Merge {branch}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if commit.returncode:
                subprocess.run(["git", "-C", str(workspace), "reset", "--merge"], capture_output=True, text=True, encoding="utf-8", errors="replace")
                raise ValueError(commit.stderr.strip())
