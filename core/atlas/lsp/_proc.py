# Atlas-original module (contract: ATLAS-C6A LSP core, owner: subagent A).
# Semantics reference: hermes agent/deadline.py kill_process_tree and
# hermes_cli/_subprocess_compat.py windows_hide_flags.
"""Windows-aware subprocess helpers for the LSP service.

- ``windows_hide_flags``: CREATE_NO_WINDOW on win32 so short-lived helpers
  (``taskkill``, version probes) never flash a console; 0 elsewhere.
- ``child_env``: a copy of ``os.environ`` merged with optional overrides.
- ``kill_process_tree``: terminate a pid and all descendants (``taskkill /T /F``
  on Windows, process-group SIGKILL on POSIX); best-effort, never raises.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys

logger = logging.getLogger("atlas.lsp._proc")

_TASKKILL_TIMEOUT = 15


def windows_hide_flags() -> int:
    """Win32 creationflags hiding the child's console; 0 elsewhere."""
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def child_env(overrides: dict | None = None) -> dict:
    """``os.environ`` copy merged with ``overrides`` (``None`` → plain copy)."""
    env = os.environ.copy()
    return {**env, **(overrides or {})}


def kill_process_tree(pid: int) -> bool:
    """Terminate ``pid`` and all its descendants; best-effort, never raises.

    Windows: ``taskkill /PID <pid> /T /F``.  ``returncode == 0`` → True; a pid
    that no longer exists (returncode 128 or a "not found" message) also counts
    as True — already-dead is success.  Anything else → False.

    POSIX: ``os.killpg(os.getpgid(pid), SIGKILL)``; ``ProcessLookupError`` → True.
    """
    try:
        if sys.platform == "win32":
            try:
                proc = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=_TASKKILL_TIMEOUT,
                    check=False,
                    creationflags=windows_hide_flags(),
                )
            except Exception:
                logger.debug("kill_process_tree: taskkill failed for pid %s", pid, exc_info=True)
                return False
            if proc.returncode == 0:
                return True
            out = b"".join(p for p in (proc.stdout, proc.stderr) if p)
            text = out.decode("utf-8", errors="replace").lower()
            if proc.returncode == 128 or "not found" in text:
                # Already gone counts as success.
                return True
            logger.debug(
                "kill_process_tree: taskkill rc=%s for pid %s: %s",
                proc.returncode, pid, text.strip()[:200],
            )
            return False

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except ProcessLookupError:
            # Already gone counts as success.
            return True
        except Exception:
            logger.debug("kill_process_tree: killpg failed for pid %s", pid, exc_info=True)
            return False
    except Exception:
        logger.debug("kill_process_tree: unexpected failure for pid %s", pid, exc_info=True)
        return False


__all__ = ["windows_hide_flags", "child_env", "kill_process_tree"]
