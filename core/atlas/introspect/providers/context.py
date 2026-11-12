"""Introspection provider: how full each live context is.

``context_breakdown.py`` can already draw a breakdown, but it answers "what is
in the prompt", not "am I about to be compacted". The four watermarks that
decide that (warning / auto-compact / blocking / effective window) are computed
by ``ContextManager.thresholds`` from a model window, and the window is only
known for a model that has metadata. Nothing outside the kernel could ask.

So this provider exposes the *decision*, not the token list: a band name, the
watermarks, and how much room is left before each. A model whose window is
unknown reports ``pressure: "unknown"`` rather than a reassuring zero — the
whole value here is that the answer is never a guess dressed as a measurement.

Read-only by construction: it computes bands from constants and never mutates a
compressor, a message list, or a session row.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _models(ctx: Context) -> list[dict[str, Any]]:
    """Every configured model with the window size it declares, if any."""
    config = getattr(getattr(ctx, "services", None), "config", None)
    if config is None:
        try:
            from atlas.config import get_config

            config = get_config()
        except Exception:  # noqa: BLE001 - no config is an answer, not a 500
            return []
    entries = getattr(getattr(config, "models", None), "custom", None) or []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "id": entry.get("id") or entry.get("name"),
                "context_window": entry.get("context_window") or entry.get("context_length"),
                "max_output_tokens": entry.get("max_output_tokens"),
            }
        )
    return rows


def _windows(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """The watermark table for every model, so a UI can show the real limits."""
    from atlas.engine.agent.token_meter import DEFAULT_CONTEXT_WINDOW, measure

    models = _models(ctx)
    out: list[dict[str, Any]] = []
    for model in models:
        window = model.get("context_window")
        probe = measure(used=0, model_window=window or DEFAULT_CONTEXT_WINDOW)
        out.append({**model, "thresholds": probe["thresholds"], "known": window is not None})
    return {
        "default_window": DEFAULT_CONTEXT_WINDOW,
        "levels": ["idle", "roomy", "filling", "tight", "critical"],
        "models": out,
        "note": (
            "阈值由 ContextManager.thresholds 按模型窗口现算；窗口小于内部保留量时"
            "四个水位会同时归零，内核据此直接拒绝该轮，所以那种情况会报 critical。"
        ),
    }


def _pressure(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Measure one live number, or a stored session's last reading."""
    from atlas.engine.agent.token_meter import measure, measure_session

    session_id = str(args.get("session_id") or "").strip()
    window = args.get("model_window")
    used = args.get("used_tokens")

    if session_id:
        usage: dict[str, Any] = {}
        state = getattr(getattr(ctx, "services", None), "state", None)
        getter = getattr(state, "get_session_usage", None)
        if callable(getter):
            try:
                usage = getter(session_id) or {}
            except Exception as exc:  # noqa: BLE001
                return {"session_id": session_id, "error": f"{type(exc).__name__}: {exc}"}
        result = measure_session(usage, window)
        return {"session_id": session_id, **result}

    if used is None and window is None:
        return {
            "pressure": "unknown",
            "sentence": "没有给 used_tokens 或 session_id，也没有可读的窗口，无法判断。",
            "used_tokens": None,
            "model_window": None,
            "used_percent": None,
            "thresholds": None,
            "headroom": {},
        }
    return measure(used=used, model_window=window)


PROVIDER = Provider(
    id="context",
    title="上下文压力",
    summary="每个模型的上下文水位线，以及「现在这个上下文还剩多少空间」的分档结论。",
    methods=(
        Method(
            name="windows",
            summary="所有已配置模型的窗口大小与四档水位（warning/auto_compact/blocking/有效窗口）。",
            input_schema=object_schema({}),
            run=_windows,
        ),
        Method(
            name="pressure",
            summary="按已用 token 数或某个会话的最后读数，给出 idle/roomy/filling/tight/critical 分档与余额。",
            input_schema=object_schema(
                {
                    "session_id": {
                        "type": "string",
                        "description": "读该会话最后一次记录的用量；给了它就忽略 used_tokens。",
                    },
                    "used_tokens": {
                        "type": "integer",
                        "description": "直接给一个已用 token 数。",
                    },
                    "model_window": {
                        "type": "integer",
                        "description": "模型窗口；不给则尝试从会话行里读。",
                    },
                }
            ),
            run=_pressure,
        ),
    ),
)
