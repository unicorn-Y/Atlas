# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/fallback_cooldown.py (MIT, (c) Nous Research); no credential-pool coupling.
"""In-process cooldown for models temporarily rejected by their provider."""

from __future__ import annotations

import time

_cooldowns: dict[str, float] = {}
_failures: dict[str, int] = {}

# Claude Code's overload recovery is deliberately finite.  Keep a model out of
# the candidate list after repeated provider failures, then let a later turn
# probe it again instead of permanently poisoning the route.
BREAKER_FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 60.0


def is_cooling(model: str) -> bool:
    until = _cooldowns.get(model, 0.0)
    if until <= time.monotonic():
        _cooldowns.pop(model, None)
        return False
    return True


def cool(model: str, seconds: float = 60.0) -> None:
    _cooldowns[model] = time.monotonic() + max(0.0, seconds)


def record_failure(model: str, *, seconds: float = BREAKER_COOLDOWN_SECONDS) -> bool:
    """Record a consecutive failed model request and open its circuit at 3."""
    failures = _failures.get(model, 0) + 1
    _failures[model] = failures
    if failures >= BREAKER_FAILURE_THRESHOLD:
        cool(model, seconds)
        _failures[model] = 0
        return True
    return False


def record_success(model: str) -> None:
    _failures.pop(model, None)
    _cooldowns.pop(model, None)


def clear() -> None:
    _cooldowns.clear()
    _failures.clear()
