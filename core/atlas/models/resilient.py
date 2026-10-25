"""Model calls that must survive a flaky relay: retry with backoff, then walk the fallback chain.

Used by multi-step features where one failed call would throw away earlier work (ultraplan synthesis
after minutes of research, a repository-review layer). Regular chat turns have their own retry path
in kernel.model_call.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def complete_resilient(router: Any, model: str, purpose: str, messages: list[dict[str, Any]],
                             *, delays: tuple[float, ...] = (0, 3, 8), **kwargs: Any) -> Any:
    from atlas.config import load_user_settings

    chain = [str(item) for item in (load_user_settings().get("fallback_chain") or []) if item]
    ordered = [model, *chain]
    candidates = [item for index, item in enumerate(ordered) if item and item not in ordered[:index]]
    last_error: Exception | None = None
    for candidate in candidates:
        for delay in delays:
            if delay:
                await asyncio.sleep(delay)
            try:
                return await router.complete_for(candidate, purpose, messages, **kwargs)
            except Exception as exc:  # noqa: BLE001 - provider/transport errors vary
                last_error = exc
    assert last_error is not None
    raise last_error
