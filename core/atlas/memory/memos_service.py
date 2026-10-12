"""Atlas' single door to the MemOS service (:18800), started on demand.

The Hermes memory provider only starts MemOS when the first chat turn builds an
agent, so right after launch the memory page would find nothing listening. Any
request through here first makes sure the service is up, using the plugin's own
``daemon_manager`` (same singleton lock, same node binary, same data home) from
Atlas' fork in ``vendor/memos-local-plugin``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import threading
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import structlog

from atlas.config import DATA_ROOT

log = structlog.get_logger(__name__)

MEMOS_URL = "http://127.0.0.1:18800"
MEMOS_HOME = DATA_ROOT / "data" / "memos-home"  # same default HermesRuntime sets
_PROVIDER = (Path(__file__).resolve().parents[3] / "vendor" / "memos-local-plugin"
             / "adapters" / "hermes" / "memos_provider")
_lock = threading.Lock()
_daemon_manager: ModuleType | None = None


def _listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 18800), timeout=0.5):
            return True
    except OSError:
        return False


def _owned_listener() -> bool:
    """A shared port is usable only when its process owns this data home."""
    import psutil

    expected = os.path.normcase(str(MEMOS_HOME.resolve()))
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if connection.status != psutil.CONN_LISTEN or not connection.laddr or connection.laddr.port != 18800:
                continue
            if connection.pid is None:
                return False
            args = psutil.Process(connection.pid).cmdline()
            homes = [arg.removeprefix("--home=") for arg in args if arg.startswith("--home=")]
            return any(os.path.normcase(str(Path(home).resolve())) == expected for home in homes)
    except (OSError, psutil.Error):
        return False
    return False


def _load_daemon_manager() -> ModuleType:
    global _daemon_manager
    if _daemon_manager is None:
        spec = importlib.util.spec_from_file_location(
            "atlas_memos_daemon_manager", _PROVIDER / "daemon_manager.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"MemOS plugin not found at {_PROVIDER}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _daemon_manager = module
    return _daemon_manager


def ensure_running() -> bool:
    """True when MemOS answers on :18800, starting its daemon if needed."""
    if _listening():
        return _owned_listener()
    with _lock:
        if _listening():
            return _owned_listener()
        os.environ.setdefault("MEMOS_HOME", str(MEMOS_HOME))
        try:
            ok = bool(_load_daemon_manager().ensure_viewer_daemon(runtime_home=MEMOS_HOME))
        except Exception as exc:  # MemOS missing / node unavailable: callers report offline
            log.warning("memos.start_failed", error=str(exc), exc_info=True)
            return False
        log.info("memos.started_on_demand", ok=ok)
        return ok and _listening() and _owned_listener()


def request(method: str, path: str, payload: dict[str, Any] | None = None,
            timeout: float = 15) -> Any:
    """Call the MemOS HTTP API; raises ``ConnectionError`` when it cannot be started."""
    if not ensure_running():
        raise ConnectionError("MemOS 服务未启动，或端口被其他数据目录的实例占用。")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(MEMOS_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed loopback URL
        return json.loads(resp.read().decode("utf-8") or "null")
