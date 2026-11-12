"""Answer "who already owns this port?" before uvicorn tries to bind it.

Why this exists: two Atlas backends were once running against the same port
(PIDs 40820 and 45104, both on 8765). The symptom was not a clear error. It was
which process answered, which one the desktop window had attached to, and which
one the settings writes went to. A new launch would either die on an opaque
``[Errno 10048]`` or, worse, silently lose every request to the older process
while the new window looked connected.

A bind failure is a *late* signal: by then the module is imported, the lifespan
has started, and the stderr above the traceback is a wall of startup logs. This
module moves the discovery earlier and makes it a first-class result: which port,
whether something is listening, which PID, and whether that PID looks like Atlas.
Callers can then refuse to start, or name the process instead of the errno.

Two probes, deliberately:

* **connect** answers "is something accepting on this port right now?" — cheap,
  needs no privileges, and is the only probe that is correct when the owner is in
  another user session or a differently-elevated process.
* **bind** answers "could I take this port?" — occasionally a socket is bound but
  not listening, where connect is silent and bind is the honest check.

Neither probe alone is sufficient, so we take the union: occupied if *either*
says so. Being wrong toward "occupied" only costs a --port argument; being wrong
toward "free" costs a lost session.
"""

from __future__ import annotations

import socket
from typing import Any

__all__ = ["probe", "describe", "PortProbe"]


class PortProbe(dict):
    """A probe result that also renders itself as the sentence a user needs.

    Subclassing ``dict`` keeps it JSON-serializable for the diagnostics router and
    the introspection surface, both of which are happy with plain mappings. The
    rendering lives on the object because the same wording must appear in the CLI,
    the desktop entry, and the API — three copies would drift.
    """

    @property
    def free(self) -> bool:
        return not self.get("listening")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return describe(self)


def _probe_host(host: str) -> str:
    """The address to probe. A server bound to 0.0.0.0 is reachable on loopback."""
    if host in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _connect_ok(host: str, port: int, timeout: float) -> bool:
    """True when something accepts a TCP connection on ``host:port``."""
    try:
        with socket.create_connection((_probe_host(host), port), timeout=timeout):
            return True
    except OSError:
        return False


def _try_bind(host: str, port: int) -> tuple[bool, str]:
    """Return ``(bindable, reason)`` by actually attempting the bind."""
    bind_host = _probe_host(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR: it would mask a listener in TIME_WAIT as free, and a
        # listener in TIME_WAIT is still a listener we cannot take over.
        sock.bind((bind_host, port))
        return True, ""
    except OSError as exc:
        return False, str(exc)
    finally:
        sock.close()


def _owner_pids(port: int) -> list[int]:
    """Best-effort PIDs listening on ``port``. Empty when psutil cannot say.

    psutil needs no elevation for *your own* processes, which is the case that
    matters: a stale backend from the same user. Another user's listener returns
    nothing, and that is fine — the probe still reports occupancy.
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard dependency
        return []
    pids: list[int] = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                pids.append(int(conn.pid))
    except (psutil.AccessDenied, OSError):  # pragma: no cover - platform dependent
        return []
    return sorted(set(pids))


def _looks_like_atlas(pid: int) -> bool:
    """Does this PID look like an Atlas process? Used to sharpen the message."""
    try:
        import psutil

        proc = psutil.Process(pid)
        blob = " ".join([proc.name() or "", " ".join(proc.cmdline() or [])]).lower()
    except Exception:  # noqa: BLE001 - a vanished or protected process is not an error
        return False
    return "atlas" in blob


def probe(host: str = "127.0.0.1", port: int = 8765, *, timeout: float = 0.25) -> PortProbe:
    """Probe one port. Never raises; every failure becomes a field."""
    port = int(port)
    connected = _connect_ok(host, port, timeout)
    bindable, bind_error = _try_bind(host, port)
    listening = connected or not bindable
    pids = _owner_pids(port) if listening else []
    atlas_pids = [pid for pid in pids if _looks_like_atlas(pid)]
    return PortProbe({
        "host": _probe_host(host),
        "port": port,
        "listening": listening,
        "bindable": bindable,
        "bind_error": bind_error,
        "pids": pids,
        "atlas_pids": atlas_pids,
    })


def describe(result: dict[str, Any]) -> str:
    """One sentence, in the user's language, naming the process not the errno."""
    port = result.get("port")
    if not result.get("listening"):
        return f"端口 {port} 空闲，可以启动。"
    pids = result.get("pids") or []
    atlas_pids = result.get("atlas_pids") or []
    if atlas_pids:
        listed = "、".join(str(pid) for pid in atlas_pids)
        return (
            f"端口 {port} 已经有一个 Atlas 后端在跑（PID {listed}）。"
            f"再启动一个不会顶替它：新窗口会连到旧进程，你说的设置也写进旧进程。"
            f"先关掉它（PID {listed}），或者换一个端口（--port）。"
        )
    if pids:
        listed = "、".join(str(pid) for pid in pids)
        return f"端口 {port} 被别的进程占用（PID {listed}）。换一个端口，或先关掉那个进程。"
    reason = result.get("bind_error") or "绑定失败"
    return (
        f"端口 {port} 已被占用，但查不到占用进程（可能属于其他用户或更高权限的进程）。"
        f"换一个端口，或先释放它。系统返回：{reason}"
    )
