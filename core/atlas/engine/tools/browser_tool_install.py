# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
"""PM-owned agent-browser / Chromium discovery, acquisition and readiness.

Split out of ``tools/browser_tool.py``. Facade-owned state is read through ``_bt`` (``tools.browser_tool``, resolved per call) — no import cycle."""

import functools
import os
import shutil
import subprocess
from typing import Optional

from atlas.engine.atlas_constants import agent_browser_runnable, is_termux as _is_termux_environment
from atlas.engine.tools.browser_tool_origin import origin_module as _origin
from atlas.engine.tools import browser_tool_cdp as _cdp
from atlas.engine.tools import browser_tool_cloud as _cloud
from atlas.engine.tools import browser_tool_lightpanda_fallback as _lp


@functools.lru_cache(maxsize=1)
def _discover_homebrew_node_dirs() -> tuple[str, ...]:
    """Homebrew versioned Node bin dirs (node@20, ...) that ``brew`` may not link into /opt/homebrew/bin."""
    homebrew_opt = "/opt/homebrew/opt"
    try:
        entries = os.listdir(homebrew_opt) if os.path.isdir(homebrew_opt) else []
    except OSError:
        entries = []
    return tuple(
        bin_dir
        for entry in entries
        if entry.startswith("node") and entry != "node"
        if os.path.isdir(bin_dir := os.path.join(homebrew_opt, entry, "bin"))
    )


def _browser_candidate_path_dirs() -> list[str]:
    """System PATH fallbacks for externally owned browser helpers."""
    _bt = _origin()
    return [*_discover_homebrew_node_dirs(), *_bt._SANE_PATH_DIRS]


def _merge_browser_path(existing_path: str = "") -> str:
    """Prepend browser-specific PATH fallbacks without reordering existing entries."""
    path_parts = [p for p in (existing_path or "").split(os.pathsep) if p]
    prefix_parts: list[str] = []
    for part in _browser_candidate_path_dirs():
        if part and part not in path_parts and part not in prefix_parts and os.path.isdir(part):
            prefix_parts.append(part)
    return os.pathsep.join(prefix_parts + path_parts)


def _browser_install_hint() -> str:
    # Atlas 不带 Hermes 的 pm 包管理器；npm 全局安装是 Atlas 用户能照做的唯一方式。
    return "npm install -g agent-browser && agent-browser install"


_AUTOINSTALL_ATTEMPTED = False


def _autoinstall_agent_browser() -> Optional[str]:
    """Install agent-browser with npm once per process when it is missing (Atlas has no Hermes pm)."""
    global _AUTOINSTALL_ATTEMPTED
    if _AUTOINSTALL_ATTEMPTED or os.environ.get("ATLAS_BROWSER_AUTOINSTALL", "1") == "0":
        return None
    _AUTOINSTALL_ATTEMPTED = True
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        return None
    try:
        subprocess.run([npm, "install", "-g", "agent-browser"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    for search_path in (None, _merge_browser_path("")):
        candidate = shutil.which("agent-browser", path=search_path) if search_path != "" else None
        if candidate and _agent_browser_candidate_present(candidate):
            return candidate
    return None


def _agent_browser_candidate_present(path: str | None) -> bool:
    if not path:
        return False
    return os.path.isfile(path) and (os.name == "nt" or os.access(path, os.X_OK))


def _find_agent_browser(*, validate: bool = True) -> str:
    """Find the browser CLI on PATH, optionally using Atlas's npm installer."""
    termux = _is_termux_environment()
    usable = agent_browser_runnable if validate else _agent_browser_candidate_present
    for search_path in (None, _merge_browser_path("")):
        if search_path == "":
            continue
        candidate = shutil.which("agent-browser", path=search_path)
        if candidate and usable(candidate):
            return candidate
    hint = f"agent-browser CLI not found. Install it with: {_browser_install_hint()}"
    if validate and not termux:
        installed_path = _autoinstall_agent_browser()
        if installed_path:
            return installed_path
    raise FileNotFoundError(hint)


def warm_agent_browser_npx_cache(timeout: float = 60.0) -> bool:
    """Frozen old-updater surface names this module too (the extraction-era home); tools.browser_tool
    carries the permanent definition. No npx work is performed; relaunch instead."""
    return False


def _chromium_installed() -> bool:
    """An explicit browser executable or PM's selected full Chromium exists."""
    ab_path = _chromium_executable()
    return bool(ab_path and (os.path.isfile(ab_path) or shutil.which(ab_path)))


def _chromium_executable() -> Optional[str]:
    """Resolve an explicitly configured Chromium or a common local browser binary."""
    configured = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH")
    if configured and (os.path.isfile(configured) or shutil.which(configured)):
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
            if not base:
                continue
            for relative in (
                os.path.join("Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join("Google", "Chrome", "Application", "chrome.exe"),
            ):
                candidate = os.path.join(base, relative)
                if os.path.isfile(candidate):
                    return candidate
    return None


def _maybe_autoinstall_chromium() -> bool:
    """Atlas does not bundle a browser package manager; require a detected browser."""
    _bt = _origin()
    if _bt._chromium_autoinstall_attempted:
        return _chromium_installed()
    _bt._chromium_autoinstall_attempted = True
    if _running_in_docker() or _is_termux_environment() or os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH"):
        return False
    return False


def _running_in_docker() -> bool:
    """Best-effort detection of whether we're inside a Docker container."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "rt", encoding="utf-8") as fp:
            return "docker" in fp.read()
    except OSError:
        return False


def check_browser_requirements() -> bool:
    """Whether the browser tools should be advertised.

    Local mode needs the ``agent-browser`` CLI plus a Chromium build (except Lightpanda-only text workflows);
    cloud mode needs the CLI plus provider credentials (the provider hosts its own Chromium).
    """
    _bt = _origin()
    # Browser Use CLI backend: browser_exec replaces the whole browser_* surface (incl. browser_cdp/browser_dialog check_fns).
    if _bt._is_browser_use_cli_mode():
        return False
    # Camofox only needs the server URL, no agent-browser CLI.
    if _bt._is_camofox_mode():
        return True
    # CDP override needs no local binary. Raw (no-I/O) check: this runs during schema build, where a stale endpoint must not cost a blocking probe.
    if _cdp._get_cdp_override_raw():
        return True
    # Do not exec ``agent-browser --version`` here: Windows .cmd shims flash a console during Desktop startup. Execution paths still validate.
    try:
        _find_agent_browser(validate=False)
    except FileNotFoundError:
        return False

    # Cloud mode also requires provider credentials; no local Chromium needed.
    provider = _cloud._get_cloud_provider()
    if provider is not None:
        return provider.is_available()
    # Lightpanda provides text/navigation tools without Chromium; screenshots/vision still return install errors.
    if _lp._using_lightpanda_engine():
        return True
    # Local Chrome mode needs Chromium on disk or the CLI hangs until the command timeout.
    return _chromium_installed()


def check_browser_vision_requirements() -> bool:
    """Advertise ``browser_vision`` only with BOTH a working browser AND a vision backend.

    Without the vision check, the tool stays in the model's tool list even when no vision provider is
    configured, then fails at call time with a cryptic provider-side error like ``unknown variant
    `image_url`, expected `text``` (issue #31179).
    """
    if not check_browser_requirements():
        return False
    from atlas.engine.tools.vision_tools import check_vision_requirements
    return check_vision_requirements()




