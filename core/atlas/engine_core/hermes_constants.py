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
from typing import MutableMapping


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


def _expand_hermes_home(path: str) -> Path:
    """Expand environment and user-home syntax in a Hermes home path."""
    return Path(os.path.expanduser(os.path.expandvars(path)))


def _get_platform_default_hermes_home() -> Path:
    """Return the platform default with the literal data-directory suffix."""
    suffix = os.environ.get("HERMES_DATA_DIR_SUFFIX", "")
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / ("hermes" + suffix)
    return Path.home() / (".hermes" + suffix)


_default_hermes_root_memo: tuple[str, str, Path] | None = None


def get_default_hermes_root(*, home: str | Path | None = None) -> Path:
    """Root of an explicit home, or the process home when none is supplied."""
    global _default_hermes_root_memo
    native_home = _get_platform_default_hermes_home()
    env_home = str(home).strip() if home is not None else os.environ.get("HERMES_HOME", "").strip()
    env_path = _expand_hermes_home(env_home) if env_home else None
    memo_key = (str(native_home), str(env_path) if env_path is not None else "")
    memo = _default_hermes_root_memo
    if memo is not None and memo[:2] == memo_key:
        return memo[2]
    result = native_home
    if env_path is not None:
        try:
            env_path.resolve().relative_to(native_home.resolve())
        except ValueError:
            result = env_path.parent.parent if env_path.parent.name == "profiles" else env_path
    _default_hermes_root_memo = (*memo_key, result)
    return result


_DELETED_PROFILES_DIR = ".deleted"
_HERMES_HOME_MARKERS = ("config.yaml", ".env", "state.db")


def _is_hermes_profiles_root(profiles_dir: Path) -> bool:
    """Whether *profiles_dir* is a recognized ``<hermes-home>/profiles`` directory."""
    root = profiles_dir.parent
    if root.name == ".hermes":
        return True
    try:
        if (profiles_dir / _DELETED_PROFILES_DIR).is_dir() or any(
            (root / marker).exists() for marker in _HERMES_HOME_MARKERS
        ):
            return True
    except OSError:
        pass
    try:
        return root.resolve(strict=False) == get_default_hermes_root().resolve(strict=False)
    except OSError:
        return False


def named_profile_home(path: str | Path) -> Path | None:
    """Return the named profile home containing *path*, if it belongs to one."""
    current = Path(path)
    for candidate in (current, *current.parents):
        if (candidate.parent.name == "profiles" and not candidate.name.startswith(".")
                and _is_hermes_profiles_root(candidate.parent)):
            return candidate
        if candidate.name == ".hermes":
            return None
    return None


def hermes_home_key(path: str | Path | None = None) -> str:
    candidate = Path(path) if path is not None else get_hermes_home()
    return os.path.normcase(str(candidate.expanduser().resolve(strict=False)))


SOCKET_TMPDIR_MAX_LEN = 50


def socket_safe_tmpdir() -> str:
    """Return a short temp root for AF_UNIX socket paths."""
    import tempfile
    if sys.platform == "darwin":
        return "/tmp"
    candidate = tempfile.gettempdir()
    if len(candidate) <= SOCKET_TMPDIR_MAX_LEN or not os.path.isdir("/tmp"):
        return candidate
    return "/tmp"


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

# Process identity is distinct from the context-local active home above. These
# helpers are shared by subprocess and tool launches; they never rewrite the
# parent's process environment.
_PINNED_PROCESS_HERMES_HOME: str | None = None
SCRATCH_TMP_ENV_VARS = ("TMPDIR", "TMP", "TEMP")
SCRATCH_DIR_MARKER_ENV = "HERMES_SCRATCH_DIR"


def get_process_hermes_home() -> Path:
    """Return the launch profile, ignoring a request-scoped home override."""
    configured = os.environ.get("ATLAS_HOME", "").strip() or os.environ.get("HERMES_HOME", "").strip()
    if configured:
        return _expand_hermes_home(configured).resolve()
    from atlas.config import get_config

    return Path(get_config().db_path).parent.resolve()


def pin_process_hermes_home(path: str | Path | None) -> None:
    global _PINNED_PROCESS_HERMES_HOME
    _PINNED_PROCESS_HERMES_HOME = None if path is None else str(path)


def get_routing_process_hermes_home() -> Path:
    """Return the process launch home pinned by the host, or its current home."""
    return (_expand_hermes_home(_PINNED_PROCESS_HERMES_HOME)
            if _PINNED_PROCESS_HERMES_HOME else get_process_hermes_home())


def _profile_home_path(env: MutableMapping[str, str]) -> str | None:
    home = env.get("ATLAS_HOME") or env.get("HERMES_HOME") or os.environ.get("ATLAS_HOME") or os.environ.get("HERMES_HOME")
    if not home:
        return None
    profile_home = str(_expand_hermes_home(home) / "home")
    return profile_home if os.path.isdir(profile_home) else None


def _real_home(env: MutableMapping[str, str]) -> str:
    return get_real_home(env)


def get_real_home(env: MutableMapping[str, str] | None = None) -> str:
    """Return the OS user's home, skipping a Hermes/Atlas profile HOME."""
    env = env or {}
    profile = _profile_home_path(env)
    candidates = [
        env.get("HERMES_REAL_HOME") or os.environ.get("HERMES_REAL_HOME"),
        env.get("HOME") or os.environ.get("HOME"),
    ]
    try:
        import pwd

        candidates.append(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        pass
    candidates.append(env.get("USERPROFILE") or os.environ.get("USERPROFILE"))
    drive = env.get("HOMEDRIVE") or os.environ.get("HOMEDRIVE", "")
    path = env.get("HOMEPATH") or os.environ.get("HOMEPATH", "")
    if drive and path:
        candidates.append(f"{drive}{path}" if path.startswith(("\\", "/")) else os.path.join(drive, path))
    expanded = os.path.expanduser("~")
    if expanded != "~":
        candidates.append(expanded)
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        key = os.path.normcase(os.path.abspath(os.path.expanduser(value)))
        if key in seen:
            continue
        seen.add(key)
        if profile is None or key != os.path.normcase(os.path.abspath(os.path.expanduser(profile))):
            return value
    import tempfile

    try:
        return tempfile.gettempdir()
    except (RuntimeError, OSError):
        return "/tmp"


def _is_container() -> bool:
    if os.environ.get("container") or Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text(errors="ignore").lower()
    except OSError:
        return False


def _subprocess_home(env: MutableMapping[str, str]) -> str | None:
    profile = _profile_home_path(env)
    mode = (env.get("TERMINAL_HOME_MODE") or os.environ.get("TERMINAL_HOME_MODE") or "auto").strip().lower()
    mode = {"isolated": "profile", "profile_home": "profile", "profile-home": "profile",
            "host": "real", "user": "real", "real_home": "real", "real-home": "real"}.get(mode, mode)
    if mode == "profile":
        return profile
    real = _real_home(env)
    current = (env.get("HOME") or os.environ.get("HOME", "")).strip()
    repaired = real if os.path.normcase(os.path.abspath(real)) != os.path.normcase(os.path.abspath(current or real)) else None
    if mode == "real":
        return repaired
    if profile and _is_container():
        return profile
    if not current or (profile and os.path.normcase(os.path.abspath(current)) == os.path.normcase(os.path.abspath(profile))):
        return repaired
    return None


def get_subprocess_home(env: MutableMapping[str, str] | None = None) -> str | None:
    """Resolve a child HOME override according to TERMINAL_HOME_MODE."""
    return _subprocess_home(env or {})


def get_scratch_dir(home: str | Path | None = None) -> Path:
    root = Path(home) if home is not None else get_hermes_home()
    scratch = root / "cache" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def apply_scratch_tmp_env(env: MutableMapping[str, str]) -> bool:
    """Point unset or previously Atlas-owned temporary-directory variables at profile scratch."""
    owned = env.get(SCRATCH_DIR_MARKER_ENV, "")
    if any((value := env.get(key, "").strip()) and value != owned for key in SCRATCH_TMP_ENV_VARS):
        return False
    home = env.get("ATLAS_HOME") or env.get("HERMES_HOME")
    try:
        scratch = str(get_scratch_dir(_expand_hermes_home(home) if home else get_process_hermes_home()))
    except (OSError, RuntimeError):
        return False
    for key in SCRATCH_TMP_ENV_VARS:
        env[key] = scratch
    env[SCRATCH_DIR_MARKER_ENV] = scratch
    return True


def apply_subprocess_home_env(env: MutableMapping[str, str]) -> None:
    """Apply the configured profile HOME contract to a child environment in place."""
    real = _real_home(env)
    if real:
        env["HERMES_REAL_HOME"] = real
    selected = _subprocess_home(env)
    if selected:
        env["HOME"] = selected
    apply_scratch_tmp_env(env)
