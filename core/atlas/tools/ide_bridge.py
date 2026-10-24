"""Client for the localhost VS Code bridge started by ide/vscode."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid
from typing import Any

import websockets


def lock_path() -> Path:
    return Path.home() / ".atlas" / "ide" / "vscode.json"


def discover() -> dict[str, Any] | None:
    try:
        value = json.loads(lock_path().read_text(encoding="utf-8"))
        port = int(value["port"])
        token = str(value["token"])
        if not (1 <= port <= 65535 and len(token) >= 32):
            return None
        return {"host": "127.0.0.1", "port": port, "token": token}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


async def request(method: str, params: dict[str, Any] | None = None) -> Any:
    target = discover()
    if target is None:
        raise ConnectionError("VS Code is not connected to Atlas")
    url = f"ws://127.0.0.1:{target['port']}/?token={target['token']}"
    async with websockets.connect(url, open_timeout=2, close_timeout=1) as socket:
        request_id = uuid.uuid4().hex
        await socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(str(message["error"]))
            return message.get("result")


def connected() -> bool:
    return discover() is not None
