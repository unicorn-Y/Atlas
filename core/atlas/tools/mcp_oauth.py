"""Persistent MCP OAuth support using the MCP SDK's RFC-compliant client."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata, OAuthClientInformationFull, OAuthToken


class FileTokenStorage:
    """Store per-server OAuth credentials outside the checkout, atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    async def _write(self, key: str, value: Any) -> None:
        async with self._lock:
            data = self._read()
            data[key] = value.model_dump(mode="json", exclude_none=True) if value else None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            temp.replace(self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    async def get_tokens(self) -> OAuthToken | None:
        row = self._read().get("tokens")
        return OAuthToken.model_validate(row) if isinstance(row, dict) else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await self._write("tokens", tokens)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        row = self._read().get("client")
        return OAuthClientInformationFull.model_validate(row) if isinstance(row, dict) else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await self._write("client", client_info)


class BrowserOAuthCallback:
    """Loopback authorization callback with state/code validation delegated to SDK."""

    def __init__(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = int(sock.getsockname()[1])
        self.redirect_uri = f"http://127.0.0.1:{self.port}/callback"
        self._result: asyncio.Future[AuthorizationCodeResult] | None = None
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._result = loop.create_future()
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin1")
            target = request.split(" ")[1] if len(request.split(" ")) > 1 else "/"
            params = parse_qs(urlsplit(target).query)
            if self._result and not self._result.done():
                if params.get("error"):
                    self._result.set_exception(RuntimeError("MCP OAuth authorization was denied"))
                else:
                    self._result.set_result(AuthorizationCodeResult(
                        code=(params.get("code") or [""])[0],
                        state=(params.get("state") or [None])[0],
                        iss=(params.get("iss") or [None])[0],
                    ))
            body = b"Authorization complete. You can return to Atlas."
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n" + body)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def redirect(self, url: str) -> None:
        if not webbrowser.open(url):
            raise RuntimeError(f"Open this MCP authorization URL in a browser: {url}")

    async def callback(self) -> AuthorizationCodeResult:
        assert self._result is not None
        return await asyncio.wait_for(self._result, timeout=300)


@asynccontextmanager
async def oauth_provider(server_name: str, server_url: str, *, scope: str | None = None):
    """Yield SDK OAuth auth and its storage context for an HTTP MCP server."""
    from atlas.config import DATA_ROOT
    from mcp.shared.auth import OAuthClientMetadata

    callback = BrowserOAuthCallback()
    await callback.start()
    storage = FileTokenStorage(DATA_ROOT / "data" / "mcp-oauth" / f"{server_name}.json")
    metadata = OAuthClientMetadata(
        client_name="Atlas", redirect_uris=[callback.redirect_uri], scope=scope,
        token_endpoint_auth_method="none",
    )
    provider = OAuthClientProvider(
        server_url, metadata, storage, redirect_handler=callback.redirect,
        callback_handler=callback.callback,
    )
    try:
        yield provider
    finally:
        await callback.close()


@asynccontextmanager
async def oauth_streamable_transport(server_name: str, server_url: str,
                                     headers: dict[str, str] | None = None,
                                     *, scope: str | None = None):
    """Create streamable HTTP transport with OAuth and configured proxy headers."""
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async with oauth_provider(server_name, server_url, scope=scope) as auth:
        async with create_mcp_http_client(headers=headers, auth=auth) as client:
            async with streamable_http_client(server_url, http_client=client) as streams:
                yield streams

