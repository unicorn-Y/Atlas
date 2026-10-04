"""H2.3 memory stopgap: bound the advisory context injected per run.

Every turn injects validated memories, knowledge-trace explanations, failure
reflections, goal experiences, consolidated goal knowledge and consolidated
insights into the system prompt. Their combined size was unbounded, so a large
memory library could crowd out the user's actual request. This module caps the
total injected tokens at a configured fraction of the model context window
(default 5%, ``agent.memory_injection.max_context_ratio``) and, when the cap
bites, keeps the head of each block — the retrieval layer already ranks items
by relevance, so dropping from the tail drops the least relevant items first.

Architecture is unchanged: this is a stopgap in front of the existing
injection assembly, not a memory redesign (user holds a memory freeze).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from atlas.models.tokens import estimate_tokens

DEFAULT_MAX_CONTEXT_RATIO = 0.05
# Fallback for models whose catalog entry carries no context_window.
DEFAULT_CONTEXT_WINDOW = 200_000


def injection_budget_tokens(
    get_config: Callable[[], Any], selected_config: dict[str, Any] | None,
) -> int:
    """Token budget for one run's advisory injection.

    Reads ``agent.memory_injection.max_context_ratio`` (fraction of the context
    window, clamped to (0, 1]) and the model's ``context_window``. Always
    positive so the cap is exercised, never a hard zero.
    """
    ratio = DEFAULT_MAX_CONTEXT_RATIO
    try:
        configured = float(
            get_config().get(
                "agent.memory_injection.max_context_ratio", DEFAULT_MAX_CONTEXT_RATIO,
            )
        )
    except (TypeError, ValueError, AttributeError):
        configured = DEFAULT_MAX_CONTEXT_RATIO
    if 0 < configured <= 1:
        ratio = configured
    window = DEFAULT_CONTEXT_WINDOW
    if isinstance(selected_config, dict):
        try:
            configured_window = int(selected_config.get("context_window") or 0)
        except (TypeError, ValueError):
            configured_window = 0
        if configured_window > 0:
            window = configured_window
    return max(1, int(window * ratio))


@dataclass
class InjectionBlock:
    """One advisory system-message block, rendered from relevance-ordered items."""

    label: str
    items: list[Any]
    render: Callable[[list[Any]], str]
    prefix: str = ""
    suffix: str = ""
    cost: list[int] = field(default_factory=list)


def _estimate_item(item: Any) -> int:
    if isinstance(item, str):
        return estimate_tokens(item)
    return estimate_tokens(json.dumps(item, ensure_ascii=False))


def fit_injection_blocks(
    blocks: list[InjectionBlock],
    *,
    budget_tokens: int,
    estimate: Callable[[Any], int] = _estimate_item,
) -> list[list[Any]]:
    """Keep the relevance-ordered head of each block within the shared budget.

    Blocks are filled in the order given (the assembly order: memories first,
    insights last). The budget is measured against the text actually injected
    — prefix plus rendered items — so wrapper and boilerplate count too.
    Within a block, items are kept while the rendered candidate fits the
    remaining budget; the first overflow stops that block (later items are
    strictly less relevant). A block whose very first item does not fit is
    dropped entirely — an empty advisory block is never injected. Returns the
    kept items per block, aligned with ``blocks``.
    """
    kept: list[list[Any]] = []
    remaining = max(0, budget_tokens)
    for block in blocks:
        block_kept: list[Any] = []
        for index, item in enumerate(block.items):
            candidate = block.items[:index + 1]
            rendered = block.prefix + block.render(candidate) + block.suffix
            if estimate(rendered) > remaining:
                break
            block_kept.append(item)
        kept.append(block_kept)
        if block_kept:
            remaining -= estimate(
                block.prefix + block.render(block_kept) + block.suffix
            )
    return kept
