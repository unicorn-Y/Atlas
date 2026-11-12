"""Loopback WebSocket bridge for the Atlas MV3 browser controller.

Only Chrome debugging commands are relayed. The extension authenticates with a
short pairing code, after which the code rotates and a bearer token is retained
in Atlas settings. No page content is logged by this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
from concurrent.futures import Future
from typing import Any

_LOCK = threading.RLock()
_LOOP: asyncio.AbstractEventLoop | None = None
_SOCKET: Any = None
_PENDING: dict[str, Future] = {}
_SERVER_THREAD: threading.Thread | None = None
_LAST_SEEN = 0.0
_PORT = int(os.environ.get("ATLAS_BROWSER_EXTENSION_PORT", "8766"))


def _browser_settings() -> dict[str, Any]:
    from atlas.config import load_user_settings
    return load_user_settings().get("browser") or {}


def _save_browser_settings(update: dict[str, Any]) -> dict[str, Any]:
    from atlas.config import load_user_settings, save_user_settings
    data = load_user_settings()
    browser = dict(data.get("browser") or {})
    browser.update(update)
    data["browser"] = browser
    save_user_settings(data)
    return browser


def _ensure_code() -> str:
    settings = _browser_settings()
    code = str(settings.get("extension_pairing_code") or "")
    if not (len(code) == 6 and code.isdigit()):
        code = f"{secrets.randbelow(1_000_000):06d}"
        _save_browser_settings({"extension_pairing_code": code, "extension_token": ""})
    return code


def connection_info() -> dict[str, Any]:
    _ensure_server()
    from pathlib import Path
    extension_dir = Path(__file__).resolve().parents[4] / "browser-extension"
    return {"url": f"ws://127.0.0.1:{_PORT}/extension", "pairing_code": _ensure_code(),
            "extension_path": str(extension_dir),
            "connected": is_connected(), "controller": "Chrome extension" if is_connected() else None}


def is_connected() -> bool:
    with _LOCK:
        return _SOCKET is not None and time.monotonic() - _LAST_SEEN < 45


def has_pairing() -> bool:
    return bool(str(_browser_settings().get("extension_token") or ""))


def disconnect() -> None:
    global _SOCKET
    with _LOCK:
        socket = _SOCKET
        _SOCKET = None
    if socket is not None and _LOOP is not None:
        asyncio.run_coroutine_threadsafe(socket.close(), _LOOP)


def _ensure_server() -> None:
    global _SERVER_THREAD
    if _SERVER_THREAD and _SERVER_THREAD.is_alive():
        return
    _SERVER_THREAD = threading.Thread(target=_server_main, name="atlas-browser-extension", daemon=True)
    _SERVER_THREAD.start()


def _server_main() -> None:
    global _LOOP
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _LOOP = loop
    try:
        from websockets.asyncio.server import serve
    except ImportError:
        from websockets import serve
    async def start() -> None:
        await serve(_handle_socket, "127.0.0.1", _PORT, max_size=2_000_000, ping_interval=15)
    try:
        loop.run_until_complete(start())
        loop.run_forever()
    except OSError:
        # Another Atlas process owns the loopback port; callers receive a clear
        # disconnected status rather than assuming the extension is paired.
        return


async def _handle_socket(socket: Any, *_: Any) -> None:
    global _SOCKET, _LAST_SEEN
    try:
        async for raw in socket:
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if message.get("type") == "pair":
                supplied = str(message.get("code") or "")
                expected = _ensure_code()
                if not secrets.compare_digest(supplied, expected):
                    await socket.send(json.dumps({"type": "paired", "ok": False, "error": "配对码无效"}))
                    continue
                token = secrets.token_urlsafe(32)
                _save_browser_settings({"extension_token": token, "extension_pairing_code": ""})
                await socket.send(json.dumps({"type": "paired", "ok": True, "token": token}))
                with _LOCK:
                    _SOCKET = socket
                    _LAST_SEEN = time.monotonic()
                continue
            if message.get("type") == "auth":
                token = str(message.get("token") or "")
                expected = str(_browser_settings().get("extension_token") or "")
                if not expected or not secrets.compare_digest(token, expected):
                    await socket.close(code=4001, reason="invalid token")
                    return
                with _LOCK:
                    _SOCKET = socket
                    _LAST_SEEN = time.monotonic()
                await socket.send(json.dumps({"type": "ready"}))
                continue
            if message.get("type") == "ping":
                continue
            with _LOCK:
                _LAST_SEEN = time.monotonic()
                pending = _PENDING.get(str(message.get("id") or ""))
            if pending is not None and not pending.done():
                pending.set_result(message.get("result") or {"success": False, "error": message.get("error") or "Extension command failed"})
    except Exception as exc:
        if not exc.__class__.__name__.startswith("ConnectionClosed"):
            raise
    finally:
        with _LOCK:
            if _SOCKET is socket:
                _SOCKET = None


def call_extension(action: str, args: dict[str, Any], *, task_id: str | None = None) -> dict[str, Any]:
    """Send one tool operation to the paired extension and wait for its response."""
    _ensure_server()
    with _LOCK:
        socket, loop = _SOCKET, _LOOP
    if socket is None or loop is None:
        raise RuntimeError("Atlas browser extension is disconnected. Reconnect it in Settings → Browser.")
    request_id = secrets.token_hex(12)
    future: Future = Future()
    with _LOCK:
        _PENDING[request_id] = future
    async def send() -> None:
        await socket.send(json.dumps({"type": "command", "id": request_id, "action": action,
                                     "args": args, "task_id": task_id}, ensure_ascii=False))
    try:
        asyncio.run_coroutine_threadsafe(send(), loop).result(timeout=5)
        return future.result(timeout=45)
    except Exception as exc:
        raise RuntimeError(f"Atlas extension action {action} failed: {exc}") from exc
    finally:
        with _LOCK:
            _PENDING.pop(request_id, None)
