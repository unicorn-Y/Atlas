"""Optional browser-call metrics hook.

Atlas does not carry Hermes CLI's local metrics loop; keep the call boundary and
execute the browser handler exactly once.
"""
from __future__ import annotations

from typing import Any, Callable


def record_browser_call(callback: Callable[[Callable[[Callable[[], Any]], Any]], Any],
                        resolve_backend: Callable[[], str]) -> Any:
    del resolve_backend
    return callback(lambda fallback: fallback())



