"""Thread-safe scheduling helper for browser supervisor callbacks."""
from __future__ import annotations

import asyncio


def safe_schedule_threadsafe(loop: asyncio.AbstractEventLoop, callback, *args) -> bool:
    if loop.is_closed():
        return False
    try:
        loop.call_soon_threadsafe(callback, *args)
        return True
    except RuntimeError:
        return False

