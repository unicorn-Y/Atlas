# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/retry_utils.py (MIT, (c) Nous Research); Atlas uses bounded local retry policy.
"""Retry delay helpers."""

from __future__ import annotations

import random
import time


def jittered_backoff(attempt: int, *, base_delay: float = 0.5,
                     max_delay: float = 32.0, jitter_ratio: float = 0.25) -> float:
    """Claude Code request backoff: 500ms exponential, 32s ceiling, positive 25% jitter."""
    delay = min(max_delay, base_delay * 2 ** max(0, attempt - 1))
    jittered = delay + random.Random(time.time_ns()).uniform(0, jitter_ratio * delay)
    return min(max_delay, jittered)
