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

import structlog
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from atlas.engine.kernel.context import (
    DEFAULT_CONTEXT_WINDOW,
    ContextManager,
    ContextThresholds,
)

log = structlog.get_logger(__name__)

#: Named bands, ordered. ``critical`` is the one that stops a turn.
LEVELS = ("idle", "roomy", "filling", "tight", "critical")

#: Fraction of the gap between warning and blocking that still counts as roomy.
_ROOMY_BELOW = 0.25
_IMAGE_PART_TYPES = frozenset({"image", "image_url", "input_image"})


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
    surface_nodes: Sequence[Mapping[str, Any]] | None = None,
    route: Mapping[str, Any] | None = None,
    image_pricing: Callable[
        [Mapping[str, Any], Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]
    ]
    | None = None,
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
        return _with_surface_prices({
            "pressure": "unknown",
            "sentence": _SENTENCES["unknown"],
            "used_tokens": used_value,
            "model_window": window,
            "used_percent": None,
            "thresholds": None,
            "headroom": {},
        }, surface_nodes, route, image_pricing)

    manager = ContextManager(config or {})
    thresholds = manager.thresholds(window)
    band = _band(used_value, thresholds)
    percent = max(0, min(100, round(used_value / window * 100)))
    # A window smaller than a watermark would otherwise report a negative gap.
    return _with_surface_prices({
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
    }, surface_nodes, route, image_pricing)


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


def price_surface_nodes(
    nodes: Sequence[Mapping[str, Any]],
    *,
    route: Mapping[str, Any],
    image_pricing: Callable[
        [Mapping[str, Any], Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]
    ]
    | None = None,
) -> dict[str, Any]:
    """Price ordered transcript surface nodes under one model request route.

    Each node is ``{"seq": int, "message": mapping}``. ``image_pricing`` is
    the routed adapter's pricing function: it receives this route and every
    image occurrence in positional order, returning matching
    ``{"visual_tokens": int, "text": str}`` records. Missing image pricing
    keeps Atlas' fixed heuristic for the entire node. The input messages are
    never mutated.
    """
    from atlas.engine.agent.model_metadata import estimate_messages_tokens_rough

    if not isinstance(route, Mapping):
        raise TypeError("route must be a mapping")
    output_nodes: list[dict[str, int]] = []
    surface_tokens = 0
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise TypeError(f"surface node {index} must be a mapping")
        seq = node.get("seq")
        message = node.get("message")
        if type(seq) is not int or seq < 0:
            raise ValueError(f"surface node {index} seq must be a non-negative integer")
        if not isinstance(message, Mapping):
            raise TypeError(f"surface node {index} message must be a mapping")
        heuristic_tokens = estimate_messages_tokens_rough([dict(message)])
        images = _image_parts(message)
        tokens = heuristic_tokens
        if image_pricing is not None and images:
            prices = list(image_pricing(route, images))
            if len(prices) != len(images):
                raise ValueError(
                    "route image pricing returned "
                    f"{len(prices)} prices for {len(images)} image occurrences"
                )
            replacements: dict[int, str] = {}
            visual_tokens = 0
            for image_index, price in enumerate(prices):
                if not isinstance(price, Mapping):
                    raise TypeError(f"route image price {image_index} must be a mapping")
                visual = price.get("visual_tokens")
                text = price.get("text")
                if type(visual) is not int or visual < 0:
                    raise ValueError(
                        f"route image price {image_index} visual_tokens must be non-negative"
                    )
                if not isinstance(text, str):
                    raise TypeError(f"route image price {image_index} text must be a string")
                visual_tokens += visual
                replacements[image_index] = text
            projected = _replace_image_parts(message, replacements)
            tokens = estimate_messages_tokens_rough([projected]) + visual_tokens
        surface_tokens += tokens
        output_nodes.append({"seq": seq, "tokens": tokens, "heuristic_tokens": heuristic_tokens})
    return {"surface_tokens": surface_tokens, "nodes": output_nodes}


def anchor_surface_to_usage(
    *,
    surface_nodes: Sequence[Mapping[str, Any]],
    surface_tokens: int,
    provider_input_tokens: int,
    request_sha256: str = "",
    cached_tokens: int = 0,
) -> dict[str, Any] | None:
    """Anchor one successful request's provider usage back to surface nodes.

    ``price_surface_nodes`` estimates each node heuristically; a provider that
    returns real usage reports a total that will not match the estimate. The
    anchor is a pure projection: every node's estimate is scaled by
    ``provider_input_tokens / surface_tokens`` so the anchored per-node prices
    sum (modulo rounding) to the provider-reported input. Nothing here mutates
    the estimates themselves — consumers that need the raw heuristic keep
    reading ``surface_node_tokens``.

    Returns ``None`` when there is nothing to anchor with (no usage, no nodes,
    or a non-positive surface total); callers then skip the anchor keys
    entirely instead of writing a misleading empty record.
    """
    try:
        provider_total = max(0, int(provider_input_tokens or 0))
        estimated_total = int(surface_tokens or 0)
        estimated_nodes = list(surface_nodes or ())
    except (TypeError, ValueError):
        return None
    if provider_total <= 0 or estimated_total <= 0 or not estimated_nodes:
        return None
    ratio = provider_total / estimated_total
    anchored_nodes: list[dict[str, int]] = []
    for node in estimated_nodes:
        try:
            seq = int(node.get("seq"))
            estimated = int(node.get("tokens", node.get("heuristic_tokens", 0)) or 0)
        except (TypeError, ValueError, AttributeError):
            return None
        anchored_nodes.append({
            "seq": seq,
            "heuristic_tokens": estimated,
            "anchored_tokens": int(round(estimated * ratio)),
        })
    return {
        "request_sha256": str(request_sha256 or ""),
        "provider_input_tokens": provider_total,
        "surface_tokens": estimated_total,
        "anchor_ratio": round(ratio, 6),
        "anchored": True,
        "surface_node_tokens_anchored": anchored_nodes,
    }


def route_image_pricer(model_config: Mapping[str, Any] | None) -> (
    Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]] | None
):
    """Build the route-aware image pricing callback from the model entry, or ``None``.

    A model entry may declare ``image_pricing`` as a uniform per-image visual
    token cost (``"image_pricing": 800``) or as a mapping
    ``{"visual_tokens": int, "text": str}`` where ``text`` is the placeholder
    substituted for each image occurrence before text estimation. Absent or
    invalid configuration returns ``None`` so the request keeps the fixed
    heuristic — metering must never break a request.
    """
    if not isinstance(model_config, Mapping):
        return None
    pricing = model_config.get("image_pricing")
    if pricing is None:
        return None
    visual: int | None
    text = ""
    if isinstance(pricing, bool):
        visual = None
    elif isinstance(pricing, int) and pricing >= 0:
        visual = pricing
    elif isinstance(pricing, Mapping):
        candidate = pricing.get("visual_tokens")
        visual = candidate if type(candidate) is int and candidate >= 0 else None
        raw_text = pricing.get("text")
        if isinstance(raw_text, str):
            text = raw_text
    else:
        visual = None
    if visual is None:
        log.warning(
            "token_meter.image_pricing_ignored",
            reason="model entry image_pricing must be a non-negative int or "
                   '{"visual_tokens": int, "text": str}',
        )
        return None

    def _price(route: Mapping[str, Any], images: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [{"visual_tokens": visual, "text": text} for _ in images]

    return _price


def _with_surface_prices(
    result: dict[str, Any],
    surface_nodes: Sequence[Mapping[str, Any]] | None,
    route: Mapping[str, Any] | None,
    image_pricing: Callable[
        [Mapping[str, Any], Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]
    ]
    | None,
) -> dict[str, Any]:
    if surface_nodes is None:
        return result
    return {
        **result,
        **price_surface_nodes(surface_nodes, route=route or {}, image_pricing=image_pricing),
    }


def _image_parts(message: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        part
        for part in content
        if isinstance(part, Mapping) and part.get("type") in _IMAGE_PART_TYPES
    ]


def _replace_image_parts(
    message: Mapping[str, Any], replacements: Mapping[int, str]
) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return dict(message)
    projected_content: list[Any] = []
    image_index = 0
    for part in content:
        if isinstance(part, Mapping) and part.get("type") in _IMAGE_PART_TYPES:
            projected_content.append({"type": "text", "text": replacements[image_index]})
            image_index += 1
        else:
            projected_content.append(part)
    return {**message, "content": projected_content}


def level_index(band: str) -> int:
    """Sort key for a band; unknown sorts before every real band."""
    return LEVELS.index(band) if band in LEVELS else -1


__all__ = [
    "DEFAULT_CONTEXT_WINDOW", "LEVELS", "anchor_surface_to_usage", "level_index",
    "measure", "measure_session", "price_surface_nodes", "route_image_pricer",
]
