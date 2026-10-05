"""Connect-time DNS validation for Atlas HTTP extraction.

Ported from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
tools/url_safety.py (MIT, (c) Nous Research). Changes: retain Atlas's existing
public-address policy and expose only an AsyncClient factory with optional localhost access.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any


# RFC 2544 benchmarking range. Clash/Mihomo, sing-box, Surge and similar proxies answer
# every DNS query with an address here in fake-IP mode and route the connection
# themselves, so on such machines every public site "resolves" into it. It is never a
# real LAN, so treating it as public keeps web tools working without opening the LAN.
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Public internet address, including a proxy's fake-IP answer for a public host."""
    return address.is_global or (address.version == 4 and address in PROXY_FAKE_IP_NETWORK)


class SSRFConnectionBlocked(ValueError):
    """A target resolved to an address Atlas must not connect to."""


def _resolved_connect_ips(host: str, port: int, allow_local: bool) -> list[str]:
    hostname = host.rstrip(".").casefold()
    if not hostname or hostname in {"metadata.google.internal", "metadata.goog"}:
        raise SSRFConnectionBlocked("Blocked internal hostname")
    try:
        results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SSRFConnectionBlocked("DNS resolution failed") from exc
    safe: list[str] = []
    local_exception = allow_local and hostname in {"localhost", "127.0.0.1"}
    for result in results:
        try:
            address = ipaddress.ip_address(result[4][0])
        except (IndexError, ValueError) as exc:
            raise SSRFConnectionBlocked("DNS returned an invalid IP address") from exc
        if not is_public_address(address) and not (local_exception and address.is_loopback):
            raise SSRFConnectionBlocked("DNS resolved to a private or local address")
        value = str(address)
        if value not in safe and len(safe) < 8:
            safe.append(value)
    if not safe:
        raise SSRFConnectionBlocked("DNS returned no usable IP addresses")
    return safe


class _GuardedBackend:
    def __init__(self, backend: Any, allow_local: bool) -> None:
        self._backend = backend
        self._allow_local = allow_local

    def _connect_ips(self, host: str, port: int) -> list[str]:
        return _resolved_connect_ips(host, port, self._allow_local)

    @staticmethod
    def _connect_errors() -> tuple[type[BaseException], ...]:
        import httpcore
        return (httpcore.ConnectError, httpcore.ConnectTimeout)

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Any = None) -> Any:
        raise SSRFConnectionBlocked("Unix sockets are not allowed for web extraction")


class _GuardedAsyncBackend(_GuardedBackend):
    def __init__(self, allow_local: bool) -> None:
        from httpcore._backends.auto import AutoBackend
        super().__init__(AutoBackend(), allow_local)

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None, socket_options: Any = None) -> Any:
        last_error: Exception | None = None
        for address in await asyncio.to_thread(self._connect_ips, host, port):
            try:
                # The HTTP request still carries the original hostname, preserving Host and TLS SNI.
                return await self._backend.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )
            except self._connect_errors() as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise SSRFConnectionBlocked("DNS returned no usable IP addresses")

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> Any:
        raise SSRFConnectionBlocked("Unix sockets are not allowed for web extraction")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def _install_guard(transport: Any, allow_local: bool) -> None:
    state = getattr(transport, "__dict__", {})
    if state.get("_atlas_ssrf_guarded", False):
        return
    pool = state.get("_pool")
    if pool is None or not hasattr(pool, "_network_backend"):
        raise SSRFConnectionBlocked("Unsupported HTTP transport cannot be made SSRF-safe")
    pool._network_backend = _GuardedAsyncBackend(allow_local)
    transport._atlas_ssrf_guarded = True


def create_ssrf_safe_async_client(*, allow_local: bool = False, **kwargs: Any) -> Any:
    """Create an httpx client that validates and dials the connect-time DNS answer."""
    import httpx
    client = httpx.AsyncClient(**kwargs)
    transport = getattr(client, "__dict__", {}).get("_transport")
    if transport is not None:
        _install_guard(transport, allow_local)
    return client
