"""One queryable answer for "how full is this context right now".

The kernel already knows four numbers per turn — what the compressor last saw,
the model window, the auto-compact trigger and the blocking watermark — but they
live in a compressor instance that no request can reach. ``run.context.warning``
is emitted mid-turn only, so before a turn starts there is nothing to ask.

This module reads the same values the loop reads, so the number the UI shows and
the number that decides compaction cannot disagree. It never estimates a window
it does not know: an unknown model reports ``pressure: "unknown"`` rather than a
comforting zero.
"""

from __future__ import annotations

from typing import Any

from atlas.engine.kernel.context import (
    DEFAULT_CONTEXT_WINDOW,
    ContextManager,
    ContextThresholds,
)

#: Named bands, ordered. ``critical`` is the one that stops a turn.
LEVELS = ("idle", "roomy", "filling", "tight", "critical")

#: Fraction of the gap between warning and blocking that still counts as roomy.
_ROOMY_BELOW = 0.25


def _band(used: int, thresholds: ContextThresholds) -> str:
    """Which band a token count falls in, given the real watermarks."""
    if used <= 0:
        return "idle"
    # A window small enough that the reserve swallows it collapses every
    # watermark to zero. The kernel then reads ``count >= 0`` as over the limit
    # and refuses the turn, so reporting "roomy" here would be the exact
    # opposite of what happens next.
    if thresholds.blocking <= 0:
        return "critical"
    if used >= thresholds.blocking:
        return "critical"
    if thresholds.auto_compact > 0 and used >= thresholds.auto_compact:
        return "tight"
    if thresholds.warning > 0 and used >= thresholds.warning:
        return "filling"
    # Below the warning watermark but within a quarter of the way to it is not
    # "roomy": a UI that flips straight from empty to warning hides the climb.
    if thresholds.warning > 0 and used >= thresholds.warning * _ROOMY_BELOW:
        return "filling"
    return "roomy"


_SENTENCES = {
    "idle": "上下文还是空的。",
    "roomy": "还有大把空间，可以继续正常对话。",
    "filling": "开始占地方了，暂时不用管。",
    "tight": "下一轮会先压缩历史再继续，回答可能变简。",
    "critical": "已经到硬上限，再不压缩这一轮就会失败。",
    "unknown": "不知道这个模型的窗口大小，无法判断压力。",
}


def _headroom(used: int, limit: int) -> int:
    return max(0, limit - max(0, used)) if limit > 0 else 0


def measure(
    *,
    used: int | None = None,
    model_window: int | None = None,
    config: dict[str, Any] | None = None,
    compressor: Any = None,
) -> dict[str, Any]:
    """Report context pressure for one live turn.

    ``compressor`` is the same object the kernel thread holds; when given it wins
    over the explicit ``used`` argument so callers cannot accidentally report a
    stale figure next to live thresholds.
    """
    if compressor is not None:
        # The compressor is the live object: it wins unconditionally, so a caller
        # cannot report a stale figure beside live watermarks.
        used = getattr(compressor, "last_prompt_tokens", None)
        if model_window is None:
            model_window = getattr(compressor, "context_length", None)
            if not model_window:
                configured = getattr(compressor, "config", None)
                if isinstance(configured, dict):
                    model_window = configured.get("context_window")
    try:
        used_value = int(used) if used is not None else None
    except (TypeError, ValueError):
        used_value = None
    try:
        window = int(model_window) if model_window is not None else None
    except (TypeError, ValueError):
        window = None
    if window is not None and window <= 0:
        window = None

    if window is None or used_value is None:
        return {
            "pressure": "unknown",
            "sentence": _SENTENCES["unknown"],
            "used_tokens": used_value,
            "model_window": window,
            "used_percent": None,
            "thresholds": None,
            "headroom": {},
        }

    manager = ContextManager(config or {})
    thresholds = manager.thresholds(window)
    band = _band(used_value, thresholds)
    percent = max(0, min(100, round(used_value / window * 100)))
    # A window smaller than a watermark would otherwise report a negative gap.
    return {
        "pressure": band,
        "sentence": _SENTENCES[band],
        "used_tokens": used_value,
        "model_window": window,
        "used_percent": percent,
        "thresholds": {
            "warning": thresholds.warning,
            "auto_compact": thresholds.auto_compact,
            "blocking": thresholds.blocking,
            "effective_window": thresholds.effective_window,
        },
        "headroom": {
            "to_warning": _headroom(used_value, thresholds.warning),
            "to_auto_compact": _headroom(used_value, thresholds.auto_compact),
            "to_blocking": _headroom(used_value, thresholds.blocking),
        },
    }


def measure_session(session_usage: dict[str, Any], model_window: int | None = None) -> dict[str, Any]:
    """Measure from a stored usage row, for a session with no live agent.

    Stored rows carry whatever the provider reported last; the window is often
    absent, which is exactly when ``unknown`` is the honest answer.
    """
    used = (
        session_usage.get("context_tokens")
        or session_usage.get("prompt_tokens")
        or session_usage.get("input_tokens")
    )
    window = model_window or session_usage.get("context_window") or session_usage.get("context_max")
    return measure(used=used, model_window=window or None)


def level_index(band: str) -> int:
    """Sort key for a band; unknown sorts before every real band."""
    return LEVELS.index(band) if band in LEVELS else -1


__all__ = ["DEFAULT_CONTEXT_WINDOW", "LEVELS", "level_index", "measure", "measure_session"]
