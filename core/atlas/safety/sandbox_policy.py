"""Sandbox policy primitives shared by executors, prompts and settings.

Ported from DSH ``packages/sandbox/sandbox-policy`` (master ``2e39e704``) and
adapted to Atlas' execution-world model.  The point of this module is that a
mode, a workspace root and extra writable roots are validated **once**, in one
place, instead of every executor inventing its own idea of "absolute".

Deliberate differences from DSH:

* Path absoluteness is decided from the path's own spelling, not from the host
  OS.  Atlas can hold POSIX paths for a remote SSH workspace while running on
  Windows; using ``os.path.isabs`` there would reject a perfectly valid grant.
* A single-rooted Windows path (``\\foo``) is rejected.  Node treats it as
  absolute, but it silently means "root of whatever drive is current", which is
  not a stable grant and is never what a caller meant.
"""

from __future__ import annotations

import json
import ntpath
import posixpath
import re
from dataclasses import dataclass

__all__ = [
    "SANDBOX_MODES",
    "SandboxPolicyError",
    "SandboxExecutionPolicy",
    "is_execution_world_path",
    "resolve_additional_writable_roots",
    "resolve_execution_policy",
    "render_policy_context",
]

SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")

_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_WINDOWS_ROOTED = re.compile(r"^\\[^\\]")


class SandboxPolicyError(ValueError):
    """A mode, workspace root or extra writable root is not usable."""


def is_execution_world_path(path: object, *, windows: bool | None = None) -> bool:
    """Whether *path* is an absolute execution-world grant without NUL bytes.

    ``windows`` may be passed when the caller already knows the execution world.
    Otherwise the spelling decides: a drive or UNC prefix is Windows; everything
    else is validated as POSIX.
    """
    if not isinstance(path, str):
        return False
    if not path or "\x00" in path:
        return False
    if windows is None:
        windows = bool(_WINDOWS_PATH.match(path))
    if windows:
        if _WINDOWS_ROOTED.match(path):
            # "\\foo" is rooted but drive-relative; not a stable grant.
            return False
        return ntpath.isabs(path)
    return posixpath.isabs(path)


def resolve_additional_writable_roots(
    roots: object,
) -> tuple[str, ...] | None:
    """Validate and freeze extra writable roots, preserving first-seen order.

    ``None`` and an empty sequence both mean "no extra grant" and return
    ``None``.  Every entry must be an absolute execution-world path.  The list
    is not canonicalized or symlink-resolved here: a local host must not rewrite
    a path that belongs to a remote execution world.  The enforcing backend is
    responsible for checking the physical directory.
    """
    if roots is None:
        return None
    if isinstance(roots, (str, bytes)):
        raise SandboxPolicyError("additional writable roots must be a sequence, not a single string")
    try:
        values = list(roots)  # type: ignore[arg-type]
    except TypeError as exc:
        raise SandboxPolicyError("additional writable roots must be a sequence") from exc
    if not values:
        return None
    seen: list[str] = []
    for root in values:
        if not is_execution_world_path(root):
            raise SandboxPolicyError(
                "sandbox-policy: writable directories must be absolute "
                "execution-world paths without NUL bytes"
            )
        if root not in seen:
            seen.append(root)
    return tuple(seen)


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    """The resolved policy one capability call executes under."""

    mode: str
    workspace_root: str
    additional_writable_roots: tuple[str, ...] | None = None


def resolve_execution_policy(
    mode: str,
    workspace_root: str,
    additional_writable_roots: object = None,
) -> SandboxExecutionPolicy:
    """Validate one policy triple and return the frozen result."""
    if mode not in SANDBOX_MODES:
        raise SandboxPolicyError(f"unknown sandbox mode: {mode!r}")
    if not is_execution_world_path(workspace_root):
        raise SandboxPolicyError(
            "sandbox-policy: workspace root must be an absolute "
            "execution-world path without NUL bytes"
        )
    roots = resolve_additional_writable_roots(additional_writable_roots)
    if mode == "read-only":
        # Kept for replay and rendering, but they grant nothing in this mode.
        return SandboxExecutionPolicy(mode, workspace_root, roots)
    return SandboxExecutionPolicy(mode, workspace_root, roots)


def render_policy_context(policy: SandboxExecutionPolicy) -> str:
    """Render the policy for a model-facing context block.

    The text describes the file policy only.  It deliberately does not claim
    which tools or capabilities are mounted: a denial must still come from the
    enforcing backend, and a model must not refuse a required modification
    merely because the policy sounds restrictive.
    """
    if policy.mode == "read-only":
        return (
            "Current Atlas file policy: read-only. Any available operation "
            "enforced by the Atlas file sandbox cannot modify files in the "
            "standing mode. Do not refuse a required modification from this "
            "policy alone: try an available tool normally and follow any "
            "denial and escalation guidance it returns."
        )
    if policy.mode == "workspace-write":
        extra = ""
        if policy.additional_writable_roots:
            extra = (
                " Additional writable directories: "
                + json.dumps(list(policy.additional_writable_roots), ensure_ascii=False)
                + ". On Windows, these additional grants apply to file tools "
                "only, not to sandboxed processes."
            )
        return (
            "Current Atlas file policy: workspace-write. Any available "
            "operation enforced by the Atlas file sandbox may modify files "
            "under the session workspace: "
            + json.dumps(policy.workspace_root, ensure_ascii=False)
            + "."
            + extra
            + " Some platform temporary areas may also be writable."
        )
    if policy.mode == "danger-full-access":
        return (
            "Current Atlas file policy: danger-full-access. The Atlas file "
            "sandbox does not restrict file modifications by available "
            "operations."
        )
    raise SandboxPolicyError(f"unknown sandbox mode: {policy.mode!r}")