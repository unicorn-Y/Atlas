"""Metadata-only HTTPX transport diagnostics for Atlas model traffic.

Install with :func:`instrument_httpx_client` when constructing an Atlas-owned
HTTPX client. The wrappers count payload chunks as HTTPX consumes them and
never inspect or retain chunk contents.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
import time
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlsplit

import httpx

from atlas.logs import LOG_DIR, append_run_event

_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("atlas_http_diagnostic_run_id", default=None)
_INSTALLED = "_atlas_metadata_diagnostics_installed"
_UUID = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f-]{27,}$")
_TOKENISH = re.compile(r"(?i)^(?:sk|key|token|secret|sess|session)[_-][a-z0-9_-]{12,}$")
_SENSITIVE_PATH_KEYS = {"key", "keys", "api_key", "api_keys", "apikey", "token", "access_token", "secret", "secrets", "authorization"}


@contextmanager
def network_diagnostic_run(run_id: str) -> Iterator[None]:
    """Associate transport records with the durable per-run JSONL log."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(run_id))[:128].strip("_")
    token = _RUN_ID.set(safe_id or None)
    try:
        yield
    finally:
        _RUN_ID.reset(token)


def _run_id() -> str:
    return _RUN_ID.get() or "network-unscoped"


def _safe_endpoint(url: Any) -> tuple[str, str]:
    try:
        parsed = urlsplit(str(url))
        hostname = parsed.hostname or "unknown"
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        if parsed.port is not None:
            hostname = f"{hostname}:{parsed.port}"
        parts = parsed.path.split("/")
        safe_parts: list[str] = []
        redact_next = False
        for part in parts[:33]:
            if redact_next:
                safe_parts.append("[redacted]")
                redact_next = False
                continue
            if part.lower() in _SENSITIVE_PATH_KEYS:
                safe_parts.append(part.lower())
                redact_next = True
            elif len(part) > 48 or _UUID.fullmatch(part) or _TOKENISH.fullmatch(part) or (part.isdigit() and len(part) >= 5):
                safe_parts.append("[redacted]")
            else:
                safe_parts.append(part[:128])
        return hostname[:255], ("/".join(safe_parts) or "/")[:512]
    except Exception:
        return "unknown", "/[unavailable]"


def _exception_category(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
        return "cancelled"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.NetworkError):
        return "network_error"
    if isinstance(exc, httpx.ProtocolError):
        return "protocol_error"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    return f"{type(exc).__module__}.{type(exc).__name__}"[:160]


def _record(run_id: str, event: str, **fields: Any) -> None:
    try:
        append_run_event(run_id, event, **fields)
    except Exception:
        # Diagnostics must not change the success/failure of the model request.
        pass


def read_network_diagnostics(run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    """Read this run's persisted transport metadata without exposing other log events."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
        return []
    safe_limit = max(1, min(int(limit), 2000))
    root = LOG_DIR / "runs"
    if not root.is_dir():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=safe_limit)
    try:
        paths = sorted(root.glob(f"*/{run_id}.jsonl"), key=lambda path: path.parent.name)
        for path in paths:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                    except (json.JSONDecodeError, OSError):
                        continue
                    if isinstance(item, dict) and str(item.get("event", "")).startswith("http_"):
                        rows.append(item)
        return list(rows)
    except OSError:
        return []


class _SyncCountingStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, on_bytes: Any, on_close: Any) -> None:
        self._stream = stream
        self._on_bytes = on_bytes
        self._on_close = on_close
        self._closed = False
        self._finished = False

    def _finish(self, complete: bool, exc: BaseException | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        self._on_close(complete, exc)

    def __iter__(self):
        try:
            for chunk in self._stream:
                self._on_bytes(len(chunk))
                yield chunk
        except BaseException as exc:
            self._finish(False, exc)
            raise
        else:
            self._finish(True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.close()
        finally:
            self._finish(False)


class _AsyncCountingStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, on_bytes: Any, on_close: Any) -> None:
        self._stream = stream
        self._on_bytes = on_bytes
        self._on_close = on_close
        self._closed = False
        self._finished = False

    def _finish(self, complete: bool, exc: BaseException | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        self._on_close(complete, exc)

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                self._on_bytes(len(chunk))
                yield chunk
        except BaseException as exc:
            self._finish(False, exc)
            raise
        else:
            self._finish(True)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._stream.aclose()
        finally:
            self._finish(False)


class _SyncCountingTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport, provider: str) -> None:
        self._transport = transport
        self._provider = provider[:80]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request_id = uuid.uuid4().hex
        run_id = _run_id()
        host, path = _safe_endpoint(request.url)
        started = time.monotonic()
        sent = 0
        received = 0
        method = request.method[:16]
        _record(run_id, "http_request_start", request_id=request_id, provider=self._provider,
                method=method, host=host, path=path, transport="httpx")

        request_finished = False

        def sent_bytes(count: int) -> None:
            nonlocal sent
            sent += count

        def request_end(complete: bool, exc: BaseException | None, source: str = "request_stream") -> None:
            nonlocal request_finished
            if request_finished:
                return
            request_finished = True
            _record(run_id, "http_request_end", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, request_bytes=sent,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    stream_complete=complete if source == "request_stream" else None,
                    completion_source=source,
                    **({"exception_category": _exception_category(exc)} if exc else {}))

        body = _SyncCountingStream(request.stream, sent_bytes, request_end)
        forwarded = httpx.Request(request.method, request.url, headers=request.headers,
                                  stream=body, extensions=request.extensions)
        try:
            response = self._transport.handle_request(forwarded)
        except BaseException as exc:
            request_end(False, exc, "transport_error")
            _record(run_id, "http_request_error", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, request_bytes=sent,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    exception_category=_exception_category(exc))
            raise

        response_started = time.monotonic()
        request_end(True, None, "response_headers_fallback")
        _record(run_id, "http_response_start", request_id=request_id, provider=self._provider,
                method=method, host=host, path=path, status=response.status_code,
                request_bytes=sent)

        def finish(complete: bool, exc: BaseException | None) -> None:
            nonlocal received
            category = _exception_category(exc) if exc else (
                "http_status_error" if response.status_code >= 400 else None
            )
            _record(run_id, "http_response_end", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, status=response.status_code,
                    request_bytes=sent, response_bytes=received,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    response_duration_ms=round((time.monotonic() - response_started) * 1000),
                    stream_complete=complete,
                    **({"exception_category": category} if category else {}))

        def received_bytes(count: int) -> None:
            nonlocal received
            received += count

        response.stream = _SyncCountingStream(response.stream, received_bytes, finish)
        return response

    def close(self) -> None:
        self._transport.close()


class _AsyncCountingTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport, provider: str) -> None:
        self._transport = transport
        self._provider = provider[:80]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request_id = uuid.uuid4().hex
        run_id = _run_id()
        host, path = _safe_endpoint(request.url)
        started = time.monotonic()
        sent = 0
        received = 0
        method = request.method[:16]
        _record(run_id, "http_request_start", request_id=request_id, provider=self._provider,
                method=method, host=host, path=path, transport="httpx_async")

        request_finished = False

        def sent_bytes(count: int) -> None:
            nonlocal sent
            sent += count

        def request_end(complete: bool, exc: BaseException | None, source: str = "request_stream") -> None:
            nonlocal request_finished
            if request_finished:
                return
            request_finished = True
            _record(run_id, "http_request_end", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, request_bytes=sent,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    stream_complete=complete if source == "request_stream" else None,
                    completion_source=source,
                    **({"exception_category": _exception_category(exc)} if exc else {}))

        body = _AsyncCountingStream(request.stream, sent_bytes, request_end)
        forwarded = httpx.Request(request.method, request.url, headers=request.headers,
                                  stream=body, extensions=request.extensions)
        try:
            response = await self._transport.handle_async_request(forwarded)
        except BaseException as exc:
            request_end(False, exc, "transport_error")
            _record(run_id, "http_request_error", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, request_bytes=sent,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    exception_category=_exception_category(exc))
            raise

        response_started = time.monotonic()
        request_end(True, None, "response_headers_fallback")
        _record(run_id, "http_response_start", request_id=request_id, provider=self._provider,
                method=method, host=host, path=path, status=response.status_code,
                request_bytes=sent)

        def finish(complete: bool, exc: BaseException | None) -> None:
            nonlocal received
            category = _exception_category(exc) if exc else (
                "http_status_error" if response.status_code >= 400 else None
            )
            _record(run_id, "http_response_end", request_id=request_id, provider=self._provider,
                    method=method, host=host, path=path, status=response.status_code,
                    request_bytes=sent, response_bytes=received,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    response_duration_ms=round((time.monotonic() - response_started) * 1000),
                    stream_complete=complete,
                    **({"exception_category": category} if category else {}))

        def received_bytes(count: int) -> None:
            nonlocal received
            received += count

        response.stream = _AsyncCountingStream(response.stream, received_bytes, finish)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


def instrument_httpx_client(client: Any, *, provider: str) -> Any:
    """Wrap an HTTPX Client/AsyncClient's transports; safe to call once at construction.

    The returned client records durable Atlas JSONL metadata and counts payload
    bytes yielded through HTTPX. It does not read request/response bodies, headers,
    query parameters, or credentials. HTTP framing, TLS overhead, and bytes not
    yielded by HTTPX are outside these counts.
    """
    if not isinstance(client, (httpx.Client, httpx.AsyncClient)):
        return client
    if getattr(client, _INSTALLED, False):
        return client
    async_mode = isinstance(client, httpx.AsyncClient)
    transport_type = httpx.AsyncBaseTransport if async_mode else httpx.BaseTransport
    wrapper_type = _AsyncCountingTransport if async_mode else _SyncCountingTransport
    wrapped: dict[int, Any] = {}

    def wrap(transport: Any) -> Any:
        if not isinstance(transport, transport_type):
            return transport
        identity = id(transport)
        if identity not in wrapped:
            wrapped[identity] = wrapper_type(transport, provider)
        return wrapped[identity]

    # HTTPX clients route by mount; wrap both the default and mounted transports.
    client._transport = wrap(client._transport)
    if hasattr(client, "_mounts"):
        client._mounts = {pattern: wrap(transport) for pattern, transport in client._mounts.items()}
    setattr(client, _INSTALLED, True)
    return client
