"""Reject browser requests that do not come from the Atlas frontend.

The backend listens on 127.0.0.1, but any web page the user opens can still send
requests there, and WebSockets are not covered by CORS at all. Every HTTP and
WebSocket request therefore has to prove it comes from Atlas itself:

- no ``Origin`` header: a local process (CLI, tests, Electron main) rather than a web page;
- an allowed development origin (the Vite dev and preview servers) or one listed in
  ``server.allowed_origins``;
- the per-launch ``ATLAS_API_TOKEN`` in ``X-Atlas-Api-Token``, which the Electron main
  process attaches to its own requests. The packaged renderer loads from ``file://`` and
  sends ``Origin: null``; sandboxed iframes on any site send that too, so ``null`` alone
  is never enough.

Browsers leave ``Origin`` off same-origin GETs, so a page served *by the backend itself*
(say, a previewed workspace HTML file) would look like a local process. The backend never
serves its own UI, so any browser request marked ``Sec-Fetch-Site: same-origin`` is refused
unless it carries the token.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "x-atlas-api-token"
DEV_ORIGINS = frozenset({
    "http://127.0.0.1:5173", "http://localhost:5173",
    "http://127.0.0.1:4173", "http://localhost:4173",
})


def is_trusted(
    origin: str | None, token: str | None, extra_origins: Iterable[str] = (),
    fetch_site: str | None = None,
) -> bool:
    expected = os.environ.get("ATLAS_API_TOKEN", "")
    if expected and token and secrets.compare_digest(token, expected):
        return True
    if fetch_site == "same-origin":
        return False
    if origin is None:
        return True
    return origin in DEV_ORIGINS or origin in set(extra_origins)


class OriginGuard:
    """ASGI middleware applying :func:`is_trusted` to every HTTP and WebSocket request."""

    def __init__(self, app: ASGIApp, extra_origins: Callable[[], Iterable[str]] = tuple) -> None:
        self.app = app
        self.extra_origins = extra_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        # CORS preflights carry no body and cause no side effects; the CORS middleware
        # decides whether the browser may continue with the real request.
        is_preflight = (scope["type"] == "http" and scope["method"] == "OPTIONS"
                        and "access-control-request-method" in headers)
        origin, token = headers.get("origin"), headers.get(TOKEN_HEADER)
        fetch_site = headers.get("sec-fetch-site")
        if is_preflight or is_trusted(origin, token, self.extra_origins(), fetch_site):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008, "reason": "untrusted origin"})
            return
        response = JSONResponse({"detail": "Requests from this origin are not allowed"},
                                status_code=403)
        await response(scope, receive, send)
