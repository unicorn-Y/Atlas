# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/fallback_cooldown.py (MIT, (c) Nous Research); no credential-pool coupling.
"""In-process cooldown for models temporarily rejected by their provider."""

from __future__ import annotations

import time

_cooldowns: dict[str, float] = {}


def is_cooling(model: str) -> bool:
    until = _cooldowns.get(model, 0.0)
    if until <= time.monotonic():
        _cooldowns.pop(model, None)
        return False
    return True


def cool(model: str, seconds: float = 60.0) -> None:
    _cooldowns[model] = time.monotonic() + max(0.0, seconds)


def clear() -> None:
    _cooldowns.clear()
