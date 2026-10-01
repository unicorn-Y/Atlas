"""Token cost estimates adapted from Hermes Agent's price table and calculator.

Ported from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
agent/usage_pricing.py (MIT, (c) Nous Research).
Changes: retain static per-token pricing only; remove account, live metadata, and subscription APIs.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

_MILLION = Decimal(1_000_000)

# Hermes official documentation snapshots, expressed as USD per million tokens.
_PRICE_TABLE: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "claude-opus-4": (Decimal("15.00"), Decimal("75.00"), Decimal("1.50"), Decimal("18.75")),
    "claude-opus-4-20250514": (Decimal("15.00"), Decimal("75.00"), Decimal("1.50"), Decimal("18.75")),
    "claude-sonnet-4": (Decimal("3.00"), Decimal("15.00"), Decimal("0.30"), Decimal("3.75")),
    "claude-sonnet-4-20250514": (Decimal("3.00"), Decimal("15.00"), Decimal("0.30"), Decimal("3.75")),
    "claude-haiku-3.5": (Decimal("0.80"), Decimal("4.00"), Decimal("0.08"), Decimal("1.00")),
    "claude-3-5-haiku-20241022": (Decimal("0.80"), Decimal("4.00"), Decimal("0.08"), Decimal("1.00")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00"), Decimal("1.25"), Decimal("2.50")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60"), Decimal("0.075"), Decimal("0.15")),
    "deepseek-v3": (Decimal("0.15"), Decimal("0.60"), Decimal("0.003"), Decimal("0.15")),
    "deepseek-r1": (Decimal("0.15"), Decimal("0.60"), Decimal("0.003"), Decimal("0.15")),
    "deepseek-chat": (Decimal("0.15"), Decimal("0.60"), Decimal("0.003"), Decimal("0.15")),
    "deepseek-reasoner": (Decimal("0.15"), Decimal("0.60"), Decimal("0.003"), Decimal("0.15")),
}


def estimate_cost(
    model: str, *, input_tokens: int, output_tokens: int,
    cached_input_tokens: int = 0, cache_write_tokens: int = 0,
    price: dict[str, Any] | None = None,
) -> Decimal | None:
    """Return estimated USD; custom ``{input, output, cached_input}`` rates override snapshots."""
    if price is not None:
        rates = tuple(_decimal(price.get(key)) for key in ("input", "output", "cached_input"))
        if any(rate is None for rate in rates):
            return None
        input_rate, output_rate, cached_rate = rates
        write_rate = input_rate
    else:
        model_key = (model or "").strip().lower().rsplit("/", 1)[-1]
        if model_key not in _PRICE_TABLE:
            return None
        input_rate, output_rate, cached_rate, write_rate = _PRICE_TABLE[model_key]

    prompt = max(0, int(input_tokens))
    output = max(0, int(output_tokens))
    cached = max(0, int(cached_input_tokens))
    writes = max(0, int(cache_write_tokens))
    uncached = max(0, prompt - cached - writes)
    return (
        Decimal(uncached) * input_rate
        + Decimal(output) * output_rate
        + Decimal(cached) * cached_rate
        + Decimal(writes) * write_rate
    ) / _MILLION


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None
