"""Small retry wrapper for transient connector HTTP failures."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from fastapi import HTTPException

ResponseT = TypeVar("ResponseT", bound=httpx.Response)
_RETRY_DELAYS = (0.2, 0.5)


async def retry_external_request(
    request: Callable[[], Awaitable[ResponseT]], *, service: str,
) -> ResponseT:
    """Retry request errors and 5xx responses twice, then surface a readable 502."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            response = await request()
        except httpx.RequestError as exc:
            if attempt == len(_RETRY_DELAYS):
                raise HTTPException(
                    status_code=502,
                    detail=f"{service} 网络连接连续失败（已重试 2 次）：{type(exc).__name__}。请检查网络或代理后重试。",
                ) from exc
        else:
            if response.status_code < 500:
                return response
            if attempt == len(_RETRY_DELAYS):
                raise HTTPException(
                    status_code=502,
                    detail=f"{service} 连续返回 HTTP {response.status_code}（已重试 2 次），请稍后重试。",
                )
            await response.aclose()
        await asyncio.sleep(_RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")
