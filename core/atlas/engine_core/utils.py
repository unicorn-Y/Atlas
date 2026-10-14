"""Small compatibility helpers used by the ported browser and computer tools."""
from __future__ import annotations

import os
import asyncio
import json
import tempfile
import threading
from pathlib import Path
from typing import Any

TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})


def is_truthy_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().casefold() in TRUTHY_STRINGS
    return bool(value)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def run_async(coro):
    """Run a coroutine from sync tool dispatch, including callers already on an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result = []
    error = []

    def worker():
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


def safe_json_loads(value: Any, default: Any = None) -> Any:
    """Parse JSON without letting malformed persisted metadata break a read path."""
    try:
        return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else default
    except (TypeError, ValueError, UnicodeDecodeError):
        return default


def atomic_json_write(path: str | Path, data: Any, **kwargs: Any) -> None:
    """Write JSON by replace so a crash cannot leave a partial state manifest."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, **kwargs)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
