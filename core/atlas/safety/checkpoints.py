"""Backup destructive targets before an auxiliary reviewer approves them."""

from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Any

from atlas.config import get_config

_WINDOWS_ABS = re.compile(r"[A-Za-z]:\\[^\s\"'|;&]+")


def _targets(arguments: dict[str, Any]) -> list[Path]:
    found: list[Path] = []
    for key in ("path", "paths", "source", "destination", "command", "script", "code"):
        value = arguments.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            strings = _WINDOWS_ABS.findall(item) if key in {"command", "script", "code"} else [item]
            for raw in strings:
                raw = raw.rstrip("*?")
                if raw:
                    path = Path(raw)
                    found.append(path if path.is_absolute() else Path.cwd() / path)
    return list(dict.fromkeys(found))


def protect_targets(
    arguments: dict[str, Any], *, workspace: str | None,
    run_id: str, checkpoint_store: Any,
) -> bool:
    """True when every existing target is protected (or there is nothing on disk to protect).

    Work-folder changes are also covered by the per-run checkpoint, so a command with no
    recognisable file targets (``git push --force``, relative paths) is not a failure.
    """
    targets = _targets(arguments)
    if not targets:
        return True
    root = Path(workspace).resolve() if workspace else None
    in_workspace, outside = [], []
    for target in targets:
        try:
            resolved = target.resolve()
        except OSError:
            continue
        if root and (resolved == root or root in resolved.parents):
            in_workspace.append(resolved.relative_to(root).as_posix())
        elif resolved.exists():
            outside.append(resolved)
    if in_workspace:
        if not root:
            return False
        try:
            checkpoint_store.create_checkpoint(
                root, in_workspace, run_id=run_id,
            )
        except Exception:
            return False
    if outside:
        base = get_config().db_path.parent / "safety-backup"
        safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)[:100] or "run"
        backup_root = base / safe_run
        try:
            base.mkdir(parents=True, exist_ok=True)
            cutoff = time.time() - 7 * 86400
            for old in base.iterdir():
                if old.is_dir() and old.stat().st_mtime < cutoff:
                    shutil.rmtree(old)
            for target in outside:
                digest = hashlib.sha256(str(target).encode()).hexdigest()[:12]
                destination = backup_root / f"{digest}-{target.name}"
                if target.is_dir():
                    shutil.copytree(target, destination, dirs_exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, destination)
        except OSError:
            return False
    return True
