# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: agent/web_search_provider.py (MIT)
"""Provider base class (translated from Hermes ``agent/web_search_provider.py``).

A provider implements :meth:`search` and/or :meth:`extract` as coroutines and never raises:
failures come back in the result shapes from :mod:`atlas.websearch.common`.
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Awaitable, Callable

from atlas.websearch.common import VENDOR_ERRORS, describe, extract_fail, search_fail
from atlas.websearch.settings import WebSettings

logger = logging.getLogger("atlas.websearch")


class WebProvider:
    name: str = ""
    display_name: str = ""
    needs_key: bool = True
    can_search: bool = True
    can_extract: bool = False
    signup_url: str = ""

    def available(self, settings: WebSettings) -> bool:
        """Cheap check, no network: is this provider usable right now?"""
        return bool(settings.key(self.name)) if self.needs_key else True

    async def search(self, query: str, limit: int, settings: WebSettings) -> dict[str, Any]:
        return search_fail(f"{self.display_name} does not support search")

    async def extract(self, urls: list[str], settings: WebSettings) -> list[dict[str, Any]]:
        return extract_fail(urls, f"{self.display_name} does not support extract")

    # --- guarded execution: uniform failure messages ---

    async def guard_search(self, body: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await body()
        except ValueError as exc:
            return search_fail(f"{self.display_name} search failed: {exc}")
        except VENDOR_ERRORS as exc:
            logger.warning("%s search error: %s", self.display_name, describe(exc))
            return search_fail(f"{self.display_name} search failed: {describe(exc)}")

    async def guard_extract(self, urls: list[str],
                            body: Callable[[], Awaitable[list[dict[str, Any]]]]) -> list[dict[str, Any]]:
        try:
            return await body()
        except ValueError as exc:
            return extract_fail(urls, f"{self.display_name} extract failed: {exc}")
        except VENDOR_ERRORS as exc:
            logger.warning("%s extract error: %s", self.display_name, describe(exc))
            return extract_fail(urls, f"{self.display_name} extract failed: {describe(exc)}")

    def missing_key(self) -> str:
        from atlas.websearch.settings import KEY_ENV

        where = f"[web.keys] {self.name} or env {KEY_ENV.get(self.name, '')}".strip()
        hint = f" ({self.signup_url})" if self.signup_url else ""
        return f"{self.display_name} key is not set: put it in config/atlas.toml {where}{hint}"
