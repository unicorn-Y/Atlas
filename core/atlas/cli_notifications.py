"""Content-free completion notifications for non-interactive CLI runs."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

MODES = {"bell", "osc9", "off"}
STATUSES = {"completed", "failed", "cancelled"}
_ENV_ALLOWLIST = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "LANG", "LC_ALL",
}


def notification_config(settings: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """Read safe, local-only CLI notification preferences."""
    if settings is None:
        from atlas.config import load_user_settings

        settings = load_user_settings()
    mode = settings.get("cli_notify_mode", "bell")
    if mode not in MODES:
        mode = "bell"
    command = settings.get("cli_notify_command", [])
    if not isinstance(command, list) or len(command) > 32 or any(
        not isinstance(arg, str) or not arg or len(arg) > 2048 for arg in command
    ):
        command = []
    return str(mode), command


def emit_cli_notification(status: str, *, mode: str, command: list[str] | None = None) -> bool:
    """Notify on completion without forwarding prompt, output, paths, or secrets."""
    if status not in STATUSES:
        raise ValueError(f"Unsupported CLI completion status: {status}")
    if command:
        if not command[0] or len(command) > 32 or any(not isinstance(arg, str) for arg in command):
            raise ValueError("notify command must be a non-empty argv list with at most 32 entries")
        try:
            result = subprocess.run(
                [*command, status], shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
                check=False, close_fds=True, encoding="utf-8", errors="replace",
                env={key: value for key, value in os.environ.items() if key.upper() in _ENV_ALLOWLIST},
            )
        except (OSError, subprocess.TimeoutExpired):
            print("Atlas CLI notification command could not be started or timed out.", file=sys.stderr)
            return False
        if result.returncode:
            print(f"Atlas CLI notification command exited with code {result.returncode}.", file=sys.stderr)
            return False
        return True
    if mode == "off":
        return True
    if mode == "bell":
        if sys.stderr.isatty():
            sys.stderr.write("\a")
            sys.stderr.flush()
        return True
    if mode == "osc9":
        # Keep the OSC payload static and status-only; no user-provided text reaches the terminal.
        label = {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}[status]
        sys.stderr.write(f"\x1b]9;Atlas CLI run {label}\x1b\\")
        sys.stderr.flush()
        return True
    raise ValueError(f"Unsupported CLI notification mode: {mode}")
