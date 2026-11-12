"""Persistent, exact-call grants created by interactive approval decisions.

These grants are deliberately separate from safety reviewer glob rules: an
approval can only authorize the same workspace, tool, resource and arguments.

A grant is a capability the user handed to the agent once and may want back.
Storage therefore supports the whole lifecycle — ``grants()`` to list what is
standing, ``revoke()`` to drop one, ``clear()`` for all of it — because an
append-only store leaves a user with no way to see or undo a decision they made
from a single dialog.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from atlas.config import get_config

_LOCK = threading.RLock()
_MAX_GRANTS = 5000

#: Named bundles over the permission modes the kernel already understands.
#: Each preset is a *starting point* the user selects per run; it never widens
#: ``origin_guard`` and never lets an approval outlive its grant.
PERMISSION_PRESETS: dict[str, dict[str, Any]] = {
    "observe": {
        "label": "只看不动",
        "mode": "read_only",
        "allow_always": False,
        "sentence": "只读：可以查看、检索、跑只读命令，任何写入都被拒绝。",
    },
    "ask": {
        "label": "改前问我",
        "mode": "ask_writes",
        "allow_always": True,
        "sentence": "写入前弹审批；你选「始终允许」后同一调用不再询问。",
    },
    "trusted": {
        "label": "可信工作区",
        "mode": "auto_file",
        "allow_always": True,
        "sentence": "工作区内的文件改动直接执行，越界和外部请求仍然询问。",
    },
    "free": {
        "label": "全权",
        "mode": "full_access",
        "allow_always": True,
        "sentence": "不再弹审批，但仍受 origin_guard 与记忆写入规则约束。",
    },
}

DEFAULT_PRESET = "ask"


def preset(name: str | None) -> dict[str, Any]:
    """Look up a preset, falling back to the default rather than raising."""
    key = str(name or "").strip().lower()
    if key not in PERMISSION_PRESETS:
        key = DEFAULT_PRESET
    return {"name": key, **PERMISSION_PRESETS[key]}


def preset_for_mode(mode: str | None) -> dict[str, Any]:
    """The preset whose mode matches ``mode``, or the closest safer one."""
    wanted = str(mode or "").strip().lower()
    for name, body in PERMISSION_PRESETS.items():
        if body["mode"] == wanted:
            return {"name": name, **body}
    return preset(None)


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


def _write(path: Path, grants: list[dict[str, str | None]]) -> None:
    """Atomically replace the grant file. Shared by grant and revoke."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError("Approval permission store cannot be a symlink")
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


def grant(scope: dict[str, str | None] | None) -> None:
    """Persist an exact-call grant. Raises on an unsafe storage target/write."""
    if scope is None:
        raise ValueError("This approval has no stable, bounded permission scope")
    with _LOCK:
        path = _path()
        grants = _read(path)
        if scope not in grants:
            grants.append(scope)
        _write(path, grants)


def grants() -> list[dict[str, str | None]]:
    """Every standing exact-call grant, newest last."""
    with _LOCK:
        return _read(_path())


def _matches(
    scope: dict[str, str | None], *, request_fingerprint: str | None = None,
    tool: str | None = None, workspace: str | None = None,
) -> bool:
    if request_fingerprint is not None:
        return scope.get("request_fingerprint") == request_fingerprint
    if tool is not None and scope.get("tool") != tool:
        return False
    if workspace is not None:
        try:
            root = os.path.normcase(str(Path(workspace).expanduser().resolve(strict=False)))
        except (OSError, RuntimeError, ValueError):
            return False
        if scope.get("workspace") != root:
            return False
    # A filter with no predicate at all must not match: clearing everything is
    # what clear() is for, and a typo in one argument should not wipe the list.
    return tool is not None or workspace is not None


def revoke(
    *, request_fingerprint: str | None = None, tool: str | None = None,
    workspace: str | None = None,
) -> int:
    """Drop standing grants matching the filter. Returns how many went away.

    Refuses to act when the filter names nothing, so a malformed call cannot
    silently revoke every permission the user has ever granted.
    """
    if request_fingerprint is None and tool is None and workspace is None:
        return 0
    with _LOCK:
        path = _path()
        existing = _read(path)
        kept = [
            item for item in existing
            if not _matches(item, request_fingerprint=request_fingerprint,
                            tool=tool, workspace=workspace)
        ]
        if len(kept) == len(existing):
            return 0
        _write(path, kept)
        return len(existing) - len(kept)


def clear() -> int:
    """Remove every standing grant. Returns how many were removed."""
    with _LOCK:
        path = _path()
        existing = _read(path)
        if not existing:
            return 0
        _write(path, [])
        return len(existing)


def _now() -> float:
    """Indirection so tests can pin time without patching ``time``."""
    return time.time()


__all__ = [
    "DEFAULT_PRESET", "PERMISSION_PRESETS", "clear", "grant", "grants",
    "is_allowed", "permission_scope", "preset", "preset_for_mode", "revoke",
]
