"""Compatibility helpers for source-ported Hermes runtime code.

Atlas owns data placement. ``HERMES_HOME`` remains a read-compatible override while
the engine migration is in progress; new Atlas launches should set ``ATLAS_HOME``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextvars import ContextVar, Token
from pathlib import Path


_HOME_OVERRIDE: ContextVar[str | None] = ContextVar("atlas_engine_home_override", default=None)


def set_hermes_home_override(path: str | Path | None) -> Token:
    return _HOME_OVERRIDE.set(str(path) if path is not None else None)


def reset_hermes_home_override(token: Token) -> None:
    _HOME_OVERRIDE.reset(token)


def get_hermes_home_override() -> str | None:
    return (_HOME_OVERRIDE.get() or os.environ.get("ATLAS_HOME", "").strip()
            or os.environ.get("HERMES_HOME", "").strip() or None)


def get_hermes_home() -> Path:
    override = get_hermes_home_override()
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve()
    from atlas.config import get_config

    return Path(get_config().db_path).parent.resolve()


def hermes_home_key(path: str | Path | None = None) -> str:
    candidate = Path(path) if path is not None else get_hermes_home()
    return os.path.normcase(str(candidate.expanduser().resolve(strict=False)))


def normalize_scope(scope: str | Path | None) -> str | None:
    return hermes_home_key(scope) if scope is not None else None


def mkdir_under_hermes_home(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_hermes_dir(new_subpath: str, old_name: str, *, home: Path | None = None) -> Path:
    del old_name
    return (home or get_hermes_home()) / new_subpath


def profile_cli_selector() -> str:
    """Atlas does not expose the Hermes CLI named-profile selector."""
    return ""


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def agent_browser_runnable(path: str | None) -> bool:
    if not path:
        return False
    try:
        result = subprocess.run([path, "--version"], capture_output=True, timeout=5,
                                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
