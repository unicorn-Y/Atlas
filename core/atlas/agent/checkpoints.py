"""Workspace-scoped snapshots kept outside repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ShadowGitCheckpointStore:
    """Snapshot explicitly selected workspace paths without touching its .git directory."""

    EXCLUDED_PARTS = {
        ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
        "dist", "build", ".pytest-wave1-temp",
    }
    SENSITIVE_NAMES = {".env", "atlas.toml"}

    @classmethod
    def _excluded_file(cls, path: Path, root: Path) -> bool:
        relative = path.relative_to(root)
        return (
            any(part in cls.EXCLUDED_PARTS for part in relative.parts)
            or path.name in cls.SENSITIVE_NAMES
            or path.name.startswith(".env")
            or path.suffix.casefold() in {".db", ".sqlite", ".sqlite3", ".log"}
        )

    def __init__(self, storage_dir: Path | None = None) -> None:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
        self.storage_dir = (storage_dir or base / "Atlas" / "checkpoints").resolve()

    def create_checkpoint(self, workspace: str | Path, paths: list[str]) -> dict[str, Any]:
        root = Path(workspace).resolve()
        if not root.is_dir():
            raise ValueError("workspace must be an existing directory")
        if not paths:
            raise ValueError("at least one scoped path is required")
        checkpoint_id = uuid.uuid4().hex
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        snapshot_root = self.storage_dir / checkpoint_id
        files: list[dict[str, Any]] = []
        for relative in paths:
            candidate = (root / relative).resolve()
            if candidate != root and root not in candidate.parents:
                raise ValueError("checkpoint path escapes the workspace")
            if self._excluded_file(candidate, root):
                raise ValueError("checkpoint path is excluded from snapshots")
            if not candidate.exists():
                files.append({"path": candidate.relative_to(root).as_posix(), "exists": False})
                continue
            found = [candidate] if candidate.is_file() else sorted(
                p for p in candidate.rglob("*") if p.is_file()
                and not self._excluded_file(p, root)
                and (p.resolve() == root or root in p.resolve().parents)
            )
            for source in found:
                relative_path = source.relative_to(root).as_posix()
                target = snapshot_root / "files" / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                files.append({"path": relative_path, "exists": True})
            if candidate.is_dir():
                files.append({"path": candidate.relative_to(root).as_posix(), "exists": True,
                              "directory": True})
        manifest = {
            "id": checkpoint_id, "workspace": str(root),
            "created_at": datetime.now(UTC).isoformat(), "files": files,
            "scopes": [{
                "path": Path(relative).as_posix(), "directory": (root / relative).is_dir(),
            } for relative in paths],
        }
        snapshot_root.mkdir(parents=True, exist_ok=True)
        shadow_repo = snapshot_root / "git"
        shadow_repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--quiet", str(shadow_repo)], check=True,
            capture_output=True, text=True,
        )
        for item in files:
            if not item["exists"] or item.get("directory"):
                continue
            source = snapshot_root / "files" / item["path"]
            target = shadow_repo / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        subprocess.run(
            ["git", "-C", str(shadow_repo), "add", "--all"], check=True,
            capture_output=True, text=True,
        )
        staged = subprocess.run(
            ["git", "-C", str(shadow_repo), "diff", "--cached", "--quiet"],
            capture_output=True, check=False,
        )
        if staged.returncode == 1:
            subprocess.run(
                ["git", "-C", str(shadow_repo), "-c", "user.name=Atlas Checkpoint",
                 "-c", "user.email=checkpoint@atlas.local", "commit", "--quiet", "-m",
                 f"checkpoint {checkpoint_id}"], check=True,
                capture_output=True, text=True,
            )
        (snapshot_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return manifest

    def list_checkpoints(self, workspace: str | Path | None = None) -> list[dict[str, Any]]:
        root = Path(workspace).resolve() if workspace is not None else None
        items = []
        if not self.storage_dir.is_dir():
            return items
        for manifest_path in sorted(self.storage_dir.glob("*/manifest.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if root is None or Path(manifest["workspace"]).resolve() == root:
                items.append({"id": manifest["id"], "workspace": manifest["workspace"],
                              "created_at": manifest["created_at"],
                              "file_count": sum(not i.get("directory") for i in manifest["files"])})
        return items

    def restore_checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        snapshot = self.storage_dir / checkpoint_id
        manifest_path = snapshot / "manifest.json"
        if not manifest_path.is_file() or Path(checkpoint_id).name != checkpoint_id:
            raise KeyError(checkpoint_id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        root = Path(manifest["workspace"]).resolve()
        restored: list[str] = []
        saved_files = {item["path"] for item in manifest["files"] if item["exists"]}
        for scope in manifest.get("scopes", []):
            if not scope.get("directory"):
                continue
            scoped_root = (root / scope["path"]).resolve()
            if scoped_root.is_dir() and root in scoped_root.parents:
                for existing in scoped_root.rglob("*"):
                    relative_existing = existing.relative_to(root).as_posix()
                    if (
                        existing.is_file()
                        and not self._excluded_file(existing, root)
                        and relative_existing not in saved_files
                    ):
                        existing.unlink()
        for item in manifest["files"]:
            relative = Path(item["path"])
            target = (root / relative).resolve()
            if target != root and root not in target.parents:
                raise ValueError("checkpoint manifest path escapes the workspace")
            if item.get("directory"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item["exists"]:
                if target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
                restored.append(item["path"])
                continue
            source = snapshot / "git" / relative
            if not source.is_file():
                source = snapshot / "files" / relative
            if not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored.append(item["path"])
        return {"id": checkpoint_id, "restored": restored, "workspace": str(root)}
