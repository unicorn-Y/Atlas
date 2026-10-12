"""Persistent, exact-call grants created by interactive approval decisions.

These grants are deliberately separate from safety reviewer glob rules: an
approval can only authorize the same workspace, tool, resource and arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from atlas.config import get_config

_LOCK = threading.RLock()
_MAX_GRANTS = 5000


def permission_scope(
    workspace: str | None, tool: str, arguments: dict[str, Any], resource: str | None,
) -> dict[str, str | None] | None:
    """Return a server-generated grant scope, or None when it cannot be bounded."""
    if not workspace or not tool:
        return None
    try:
        root = os.path.normcase(str(Path(workspace).expanduser().resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        return None
    stable_resource = str(resource).strip()[:2000] if resource else None
    canonical = json.dumps(
        {"workspace": root, "tool": tool, "resource": stable_resource,
         "arguments": arguments},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    )
    return {
        "kind": "exact_call",
        "tool": tool,
        "workspace": root,
        "resource": stable_resource,
        "request_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _path() -> Path:
    return get_config().db_path.parent / "approval-permissions.json"


def _read(path: Path) -> list[dict[str, str | None]]:
    if path.is_symlink():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    grants = value.get("grants", []) if isinstance(value, dict) else []
    if not isinstance(grants, list):
        return []
    return [item for item in grants if isinstance(item, dict)
            and item.get("kind") == "exact_call"
            and isinstance(item.get("tool"), str)
            and isinstance(item.get("workspace"), str)
            and isinstance(item.get("request_fingerprint"), str)][-_MAX_GRANTS:]


def is_allowed(scope: dict[str, str | None] | None) -> bool:
    if scope is None:
        return False
    with _LOCK:
        return scope in _read(_path())


def grant(scope: dict[str, str | None] | None) -> None:
    """Persist an exact-call grant. Raises on an unsafe storage target/write."""
    if scope is None:
        raise ValueError("This approval has no stable, bounded permission scope")
    with _LOCK:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise OSError("Approval permission store cannot be a symlink")
        grants = _read(path)
        if scope not in grants:
            grants.append(scope)
        payload = json.dumps({"version": 1, "grants": grants[-_MAX_GRANTS:]},
                             ensure_ascii=False, indent=2)
        fd, temporary = tempfile.mkstemp(prefix=".approval-permissions-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
