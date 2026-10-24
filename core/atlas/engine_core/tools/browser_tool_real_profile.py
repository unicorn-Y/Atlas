"""Run Chromium against an Atlas-owned, incrementally refreshed profile copy.

The user's browser is never launched with debugging flags.  We copy its data to
Atlas' private browser-profile directory and launch the installed browser on
that copy, which also works with Chrome 136+'s default-profile restriction.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from atlas.engine_core.tools.browser_tool_origin import origin_module as _origin
from atlas.engine_core.tools import browser_tool_cloud as _cloud

_RP = "Real-profile browsing: "
_COPY_LOCK = threading.Lock()
_SKIP_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "GrShaderCache",
    "ShaderCache", "Crashpad", "BrowserMetrics", "OptimizationGuidePredictionModels",
    "Safe Browsing", "component_crx_cache", "extensions_crx_cache", "ShaderCache",
}
_SKIP_FILES = {"LOCK", "SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort", "Local State-journal"}


def _browser_paths() -> tuple[str, Path, str]:
    """Resolve source browser, user-data directory and selected profile without guessing channels."""
    bt = _origin()
    from atlas.config import load_user_settings
    saved = load_user_settings().get("browser") or {}
    browser = str(saved.get("profile_browser") or bt._browser_cfg("profile_browser", "chrome", lambda x: str(x or "chrome").lower(), "browser.profile_browser"))
    source_override = os.environ.get("ATLAS_BROWSER_PROFILE_DIR") or saved.get("profile_dir") or bt._browser_cfg(
        "profile_dir", "", lambda x: str(x or "").strip(), "browser.profile_dir")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    if source_override:
        source = Path(source_override).expanduser()
    elif browser == "edge":
        source = local / "Microsoft/Edge/User Data"
    else:
        source = local / "Google/Chrome/User Data"
    selected = str(saved.get("profile") or bt._browser_cfg("profile", "Default", lambda x: str(x or "Default"), "browser.profile"))
    return browser, source, selected


def _binary(browser: str) -> Optional[str]:
    candidates = (
        [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if browser == "edge" else
        [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    )
    return next((p for p in candidates if Path(p).is_file()), None)


def _copy_incremental(src: Path, dst: Path) -> None:
    """Copy profile data, retaining skipped cache trees in the destination."""
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS and not name.startswith("Cache")]
        target = dst / rel
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name in _SKIP_FILES or name.endswith(("-journal", ".lock")):
                continue
            source_file = root_path / name
            target_file = target / name
            try:
                if not target_file.exists() or source_file.stat().st_mtime_ns > target_file.stat().st_mtime_ns or source_file.stat().st_size != target_file.stat().st_size:
                    shutil.copy2(source_file, target_file)
            except (OSError, PermissionError):
                # Chrome may hold a SQLite DB while the copy is refreshed. Keep the last good copy.
                continue


def snapshot_real_profile(browser: str | None = None, src: str | None = None) -> tuple[str | None, str | None]:
    """Snapshot the selected Chromium profile into an Atlas-managed data directory."""
    resolved_browser, default_src, selected = _browser_paths()
    browser = browser or resolved_browser
    source = Path(src) if src else default_src
    source_profile = source / selected
    if not source_profile.is_dir():
        return None, f"profile '{selected}' was not found in {source}; open Chrome/Edge once and check the profile setting."
    try:
        from atlas.engine_core.hermes_constants import get_hermes_home
        dest = get_hermes_home() / "browser-profile" / browser
    except Exception:
        dest = Path.home() / ".atlas" / "browser-profile" / browser
    with _COPY_LOCK:
        dest.mkdir(parents=True, exist_ok=True)
        try:
            state = source / "Local State"
            state_target = dest / "Local State"
            if state.is_file() and (not state_target.exists() or state.stat().st_mtime_ns > state_target.stat().st_mtime_ns):
                shutil.copy2(state, state_target)
        except OSError:
            pass
        _copy_incremental(source_profile, dest / selected)
    return str(dest), None


def _terminate_real_profile_chrome() -> None:
    bt = _origin()
    procs = getattr(bt, "_real_profile_chrome_procs", [])
    while procs:
        proc = procs.pop()
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _real_profile_unsupported_reason(browser: Optional[str]) -> Optional[str]:
    if browser not in {"chrome", "edge"}:
        return _RP + "choose Chrome or Edge in browser.profile_browser."
    if not _binary(browser):
        return _RP + f"the {browser} browser executable was not found."
    return None


def _real_profile_snapshot_error(err: str) -> str:
    return f"{_RP}{err}"


def _auto_fallback(cache: dict, error: str) -> tuple[None, None]:
    """Use Atlas' isolated browser as the last automatic choice and expose why."""
    cache.clear()
    cache.update(lane="atlas", fallback_warning=_real_profile_snapshot_error(error))
    return None, None


def _real_profile_cdp() -> tuple[Optional[str], Optional[str]]:
    """Return a CDP URL for the user-data copy, refreshing it on configured cadence."""
    bt = _origin()
    from atlas.config import load_user_settings
    selected_mode = str((load_user_settings().get("browser") or {}).get("mode") or "").lower()
    config_mode = str(bt._browser_cfg("mode", "", lambda value: str(value or "").lower(), "browser.mode"))
    # 没配置时默认"自动"：扩展 > 直连 Chrome > 复制本机配置 > 隔离浏览器（否则新能力默认关着）。
    mode = selected_mode or config_mode or "auto"
    automatic = mode == "auto"
    if mode == "auto":
        from atlas.engine_core.tools.browser_extension_bridge import is_connected
        if is_connected():
            bt._real_profile_cdp_cache["lane"] = "extension"
            return extension_cdp()
        live_endpoint, live_error = live_chrome_cdp()
        if live_endpoint:
            bt._real_profile_cdp_cache["lane"] = "live_chrome"
            bt._real_profile_cdp_cache.pop("fallback_warning", None)
            return live_endpoint, None
        # A missing live endpoint is an expected auto-selection probe. The copied
        # profile is next; if that also fails, fall back to Atlas with a visible reason.
        mode = "real_profile"
    if mode == "cdp":
        settings = load_user_settings().get("browser") or {}
        configured = str(settings.get("cdp_url") or "").strip()
        if configured and _cdp_ready(configured):
            bt._real_profile_cdp_cache["lane"] = "cdp"
            return configured, None
        return None, "The configured CDP browser is disconnected; check the endpoint in Settings → Browser."
    if mode == "live_chrome":
        endpoint, error = live_chrome_cdp()
        if endpoint:
            bt._real_profile_cdp_cache["lane"] = "live_chrome"
        return endpoint, error
    if mode == "extension":
        return extension_cdp()
    if not (mode in {"real_profile", "real-profile", "copied-profile"} or _cloud._use_real_profile()):
        bt._real_profile_cdp_cache.clear()
        return None, None
    browser, source, selected = _browser_paths()
    unsupported = _real_profile_unsupported_reason(browser)
    if unsupported:
        if automatic:
            return _auto_fallback(bt._real_profile_cdp_cache, unsupported)
        return None, unsupported
    cache = bt._real_profile_cdp_cache
    copy_dir = Path(cache.get("profile_dir") or "")
    interval = max(1, int((load_user_settings().get("browser") or {}).get("profile_sync_interval_minutes")
                          or bt._browser_cfg("profile_sync_interval_minutes", 30, int, "browser.profile_sync_interval_minutes"))) * 60
    now = time.time()
    cdp = cache.get("cdp")
    if cdp and now - float(cache.get("synced_at", 0)) < interval and _cdp_ready(cdp):
        return cdp, None
    # Don't replace profile databases while Chrome has the copy open.
    if cdp and _cdp_ready(cdp):
        return cdp, None
    copied, err = snapshot_real_profile(browser, str(source))
    if err or not copied:
        detail = _real_profile_snapshot_error(err or "profile copy failed")
        return _auto_fallback(cache, detail) if automatic else (None, detail)
    copy_dir = Path(copied)
    executable = _binary(browser)
    if not executable:
        detail = _RP + f"the {browser} browser executable was not found."
        return _auto_fallback(cache, detail) if automatic else (None, detail)
    try:
        (copy_dir / "DevToolsActivePort").unlink(missing_ok=True)
        args = [executable, f"--user-data-dir={copy_dir}", f"--profile-directory={selected}",
                "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
                "--disable-sync", "--no-startup-window", "--headless=new", "about:blank"]
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        bt._real_profile_chrome_procs.append(proc)
    except OSError as exc:
        detail = _RP + f"Chrome/Edge could not start on the private profile copy: {exc}"
        return _auto_fallback(cache, detail) if automatic else (None, detail)
    port_file = copy_dir / "DevToolsActivePort"
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            port = port_file.read_text(encoding="utf-8").splitlines()[0]
            if port.isdigit() and _cdp_ready(f"http://127.0.0.1:{port}"):
                cdp = f"http://127.0.0.1:{port}"
                cache.update(cdp=cdp, profile_dir=str(copy_dir), synced_at=now, browser=browser, lane="real_profile")
                cache.pop("fallback_warning", None)
                return cdp, None
        except (OSError, IndexError):
            pass
        if proc.poll() is not None:
            detail = _RP + "Chrome/Edge exited while starting the profile copy."
            return _auto_fallback(cache, detail) if automatic else (None, detail)
        time.sleep(0.2)
    try:
        proc.terminate()
    except OSError:
        pass
    detail = _RP + "Chrome/Edge did not expose its local DevTools endpoint in time."
    return _auto_fallback(cache, detail) if automatic else (None, detail)


def _cdp_ready(url: str) -> bool:
    try:
        from urllib.request import urlopen
        with urlopen(url.rstrip("/") + "/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def _devtools_endpoint(data_dir: Path) -> Optional[str]:
    """Validate DevToolsActivePort against /json/version before trusting a live port."""
    try:
        lines = (data_dir / "DevToolsActivePort").read_text(encoding="utf-8-sig").splitlines()
        port, browser_path = lines[0].strip(), lines[1].strip()
        if not port.isdigit() or not browser_path.startswith("/devtools/browser/"):
            return None
        from urllib.request import urlopen
        import json
        root = f"http://127.0.0.1:{port}"
        with urlopen(root + "/json/version", timeout=2) as response:
            version = json.loads(response.read().decode("utf-8"))
        if str(version.get("webSocketDebuggerUrl") or "").endswith(browser_path):
            return root
    except Exception:
        return None
    return None


def live_chrome_cdp() -> tuple[Optional[str], Optional[str]]:
    """Connect to Chrome/Edge after the user enables remote debugging in its settings."""
    from atlas.config import load_user_settings
    browser, source, _ = _browser_paths()
    saved = load_user_settings().get("browser") or {}
    configured = str(saved.get("cdp_url") or _origin()._browser_cfg("cdp_url", "", lambda value: str(value or "").strip(), "browser.cdp_url"))
    if configured and _cdp_ready(configured):
        return configured.rstrip("/"), None
    endpoint = _devtools_endpoint(source)
    if endpoint:
        return endpoint, None
    return None, (_RP + "no live Chrome debugging endpoint was found. Open chrome://inspect/#remote-debugging, enable discovery, then retry. "
                  "Chrome 136+ may require a non-default --user-data-dir when started with a debugging port.")


def extension_cdp() -> tuple[Optional[str], Optional[str]]:
    """Resolve the extension relay's authenticated local CDP-compatible endpoint."""
    from atlas.config import load_user_settings
    settings = load_user_settings().get("browser") or {}
    endpoint = str(settings.get("extension_cdp_url") or "").strip()
    token = str(settings.get("extension_token") or "").strip()
    if not endpoint or not token:
        return None, "Browser extension is selected but no paired controller is connected. Pair the Atlas extension in Settings → Browser."
    return endpoint, None
