# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# agent/retry_utils.py (MIT, (c) Nous Research); Atlas uses bounded local retry policy.
"""Retry delay helpers."""

from __future__ import annotations

import random
import time


def jittered_backoff(attempt: int, *, base_delay: float = 1.0,
                     max_delay: float = 8.0, jitter_ratio: float = 0.2) -> float:
    delay = min(max_delay, base_delay * 2 ** max(0, attempt - 1))
    return delay + random.Random(time.time_ns()).uniform(0, jitter_ratio * delay)
