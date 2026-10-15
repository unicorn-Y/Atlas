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
_YAML_FILE_CACHE: dict[str, tuple[tuple[int, int, int, int], Any]] = {}
_YAML_FILE_CACHE_LOCK = threading.Lock()


def is_truthy_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().casefold() in TRUTHY_STRINGS
    return bool(value)


def env_var_enabled(name: str, default: str = "") -> bool:
    """Return True when an environment variable contains a recognized truthy value."""
    return is_truthy_value(os.getenv(name, default), default=False)


def file_signature(st: os.stat_result) -> tuple[int, int, int, int]:
    """Change key that catches atomic replacement as well as in-place edits."""
    return (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)


def fast_safe_load(stream: Any) -> Any:
    """Safely parse YAML using Atlas' installed YAML implementation."""
    import yaml

    return yaml.safe_load(stream)


def load_yaml_file_readonly(path: str | Path) -> Any:
    """Load and cache a read-only YAML file until its file signature changes."""
    target = Path(path)
    signature = file_signature(target.stat())
    key = str(target)
    with _YAML_FILE_CACHE_LOCK:
        cached = _YAML_FILE_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
    with target.open(encoding="utf-8") as stream:
        data = fast_safe_load(stream)
    with _YAML_FILE_CACHE_LOCK:
        _YAML_FILE_CACHE[key] = (signature, data)
    return data


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


def atomic_write_text(
    path: str | Path, content: str, *, encoding: str = "utf-8", tmp_prefix: str = ".tmp_",
    mode: int | None = None,
) -> None:
    """Atomically replace a text file, optionally narrowing its mode before publish."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=tmp_prefix, suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(temp_name, mode)
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
