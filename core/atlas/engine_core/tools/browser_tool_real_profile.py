# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
"""Fail-closed compatibility surface for unsupported real-profile browser access."""

from __future__ import annotations

from typing import Optional

from atlas.engine_core.tools.browser_tool_origin import origin_module as _origin

_RP = "Real-profile browsing is unavailable in this Atlas runtime: "


def _terminate_real_profile_chrome() -> None:
    """Terminate only browser processes tracked by the legacy facade, if any."""
    bt = _origin()
    for proc in list(getattr(bt, "_real_profile_chrome_procs", [])):
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    getattr(bt, "_real_profile_chrome_procs", []).clear()


def _real_profile_unsupported_reason(browser: Optional[str]) -> Optional[str]:
    return _RP + "use an isolated local browser session instead."


def _real_profile_snapshot_error(err: str) -> str:
    return f"{_RP}{err}"


def _real_profile_cdp() -> tuple[None, str | None]:
    """Never attach to user browser profiles; return a clear unsupported result."""
    bt = _origin()
    if not bt._use_real_profile():
        bt._real_profile_cdp_cache.pop("cdp", None)
        return None, None
    return None, _RP + "turn the real-profile toggle off or use an isolated local browser session."
