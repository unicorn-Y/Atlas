"""MCP SDK OAuth with PKCE, a loopback callback and OS credential storage."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import webbrowser
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

import keyring
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

AUTH_STATUS: dict[str, dict[str, str]] = {}


class CredentialStorage:
    def __init__(self, name: str, url: str, scope: str):
        backend = keyring.get_keyring()
        secure_backends = {"keyring.backends.Windows", "keyring.backends.macOS",
                           "keyring.backends.SecretService", "keyring.backends.kwallet"}
        if backend.priority <= 0 or type(backend).__module__ not in secure_backends:
            raise RuntimeError("OAuth requires an OS credential vault; plaintext storage is rejected")
        self.key = hashlib.sha256(f"{name}\n{url}\n{scope}".encode()).hexdigest()

    async def _get(self, kind, model):
        value = await asyncio.to_thread(keyring.get_password, "Atlas.MCP.OAuth", f"{self.key}:{kind}")
        return model.model_validate_json(value) if value else None

    async def _set(self, kind, value):
        await asyncio.to_thread(keyring.set_password, "Atlas.MCP.OAuth", f"{self.key}:{kind}", value.model_dump_json())

    async def get_tokens(self):
        return await self._get("tokens", OAuthToken)

    async def set_tokens(self, tokens):
        await self._set("tokens", tokens)

    async def get_client_info(self):
        return await self._get("client", OAuthClientInformationFull)

    async def set_client_info(self, client_info):
        await self._set("client", client_info)

    async def clear(self):
        for kind in ("tokens", "client"):
            if await asyncio.to_thread(keyring.get_password, "Atlas.MCP.OAuth", f"{self.key}:{kind}"):
                await asyncio.to_thread(keyring.delete_password, "Atlas.MCP.OAuth", f"{self.key}:{kind}")


@asynccontextmanager
async def oauth_provider(config):
    storage = CredentialStorage(config.name, config.url, config.oauth_scope)
    callback = asyncio.get_running_loop().create_future()
    expected_state = ""
    # Stable redirect URI permits reusing the SDK's registered client metadata.
    port = 43000 + int(hashlib.sha256(config.name.encode()).hexdigest()[:4], 16) % 10000
    callback_path = "/atlas-mcp/" + hashlib.sha256(config.name.encode()).hexdigest()[:24]

    async def receive(reader, writer):
        status, message = "400 Bad Request", "Invalid OAuth callback"
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            if len(raw) > 8192:
                raise ValueError("callback is too large")
            method, target, _ = raw.decode("ascii").split("\r\n", 1)[0].split(" ", 2)
            parsed = urlparse(target)
            values = parse_qs(parsed.query)
            state = values.get("state", [""])[0]
            if method != "GET" or parsed.path != callback_path or not expected_state or not secrets.compare_digest(state, expected_state):
                raise ValueError("invalid OAuth state")
            if values.get("error"):
                if not callback.done():
                    callback.set_exception(RuntimeError("OAuth authorization was declined"))
                status, message = "400 Bad Request", "Authorization declined. Return to Atlas."
            elif values.get("code") and not callback.done():
                callback.set_result((values["code"][0], state, values.get("iss", [None])[0]))
                status, message = "200 OK", "Authorization received. Return to Atlas."
        except (ValueError, UnicodeError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            payload = message.encode()
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/plain\r\nContent-Length: {len(payload)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n".encode() + payload)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

    listener = await asyncio.start_server(receive, "127.0.0.1", port, limit=8192)
    redirect_uri = f"http://127.0.0.1:{port}{callback_path}"

    async def redirect(url):
        nonlocal expected_state, callback
        if callback.done():
            callback = asyncio.get_running_loop().create_future()
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise RuntimeError("OAuth authorization endpoint must use HTTPS or loopback HTTP")
        expected_state = parse_qs(parsed.query).get("state", [""])[0]
        AUTH_STATUS[config.name] = {"state": "awaiting_browser", "message": "请在浏览器完成 OAuth 授权"}
        if not await asyncio.to_thread(webbrowser.open, url):
            raise RuntimeError("Unable to open the OAuth authorization browser")

    async def result():
        code, state, issuer = await asyncio.wait_for(callback, 180)
        try:
            from mcp.shared.auth import AuthorizationCodeResult
        except ImportError:
            return code, state
        return AuthorizationCodeResult(code=code, state=state, iss=issuer)

    provider = OAuthClientProvider(
        server_url=config.url,
        client_metadata=OAuthClientMetadata(
            client_name="Atlas MCP", redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"], response_types=["code"],
            token_endpoint_auth_method="none", scope=config.oauth_scope or None,
        ), storage=storage, redirect_handler=redirect, callback_handler=result,
    )
    try:
        yield provider
    finally:
        listener.close()
        await listener.wait_closed()
        if not callback.done():
            callback.cancel()
