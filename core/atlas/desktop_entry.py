"""PyInstaller entry point for the packaged Atlas backend."""

from __future__ import annotations

import os
import sys
import atexit
import logging
import secrets
import select
import stat
import time
from pathlib import Path


def _prepare_runtime_files() -> None:
    data_dir = Path(os.environ.get("ATLAS_DATA_DIR")) / "data" if os.environ.get("ATLAS_DATA_DIR") else Path(__file__).resolve().parents[2] / "data"
    runtime_dir = data_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    token_path = runtime_dir / "api-token"
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        token = secrets.token_urlsafe(32)
        try:
            descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        except FileExistsError:
            token = token_path.read_text(encoding="utf-8").strip()
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(token + "\n")
    if os.name == "nt":
        # Windows ignores POSIX mode bits. Remove inherited ACLs and grant the
        # current account read access; the containing user-data directory remains private.
        import subprocess
        import getpass

        account = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
        subprocess.run(
            ["icacls", str(token_path), "/inheritance:r", "/grant:r", f"{account}:(R)"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        token_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.environ["ATLAS_API_TOKEN"] = token
    pid_path = runtime_dir / "backend.pid"
    temporary = runtime_dir / f"backend.pid.{os.getpid()}.tmp"
    temporary.write_text(str(os.getpid()), encoding="ascii")
    temporary.replace(pid_path)

    def remove_pid() -> None:
        try:
            if pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                pid_path.unlink()
        except OSError:
            pass

    atexit.register(remove_pid)


_SOCKETPAIR_ATTEMPTS = 5
_SOCKETPAIR_HANDSHAKE_S = 3.0


def _boot_note(message: str) -> None:
    """Write a timestamped line to backend-stdio.log.

    The previous version wrote a bare string with no timestamp, so the retries were
    invisible to any timeline analysis of the boot.
    """
    sys.stderr.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} atlas.socketpair {message}\n")
    sys.stderr.flush()


def _await_connect_complete(sock, timeout: float) -> bool:
    """Wait for a non-blocking connect to finish. False if it never does."""
    import socket

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            _, writable, failed = select.select([], [sock], [sock], min(remaining, 0.05))
        except (OSError, ValueError):
            return False
        if writable or failed:
            return sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0


def _guard_loopback_socketpair() -> None:
    """Make the Windows ``socket.socketpair`` fallback bounded and observable.

    CPython on Windows has no ``AF_UNIX``, so ``socket.socketpair`` is
    ``socket._fallback_socketpair``: it binds a listener on 127.0.0.1, starts a
    non-blocking ``connect``, then blocks in ``accept()`` forever. asyncio calls it
    while building every event loop (``ProactorEventLoop._make_self_pipe``), so a
    connect the host network filter never delivers wedges backend start-up with the
    port still unbound, and the UI reports that it cannot reach the backend.

    The earlier version of this guard had two holes:

    * it started the connect non-blocking and went straight to ``accept()``, so a
      SYN that never completed was never diagnosed — the accept just sat there
      until the per-attempt timeout fired;
    * only ``TimeoutError`` was retried. ``ConnectionError`` from the peer identity
      check, and every other socket error, propagated out of ``_make_self_pipe``
      and killed the boot instead of retrying on a fresh port.

    Now the connect is driven to completion with ``select`` under the same
    deadline, every failure retries on a fresh port, and each line is timestamped
    so ``backend-stdio.log`` can be lined up against ``backend.log``.
    """
    import socket

    if socket.socketpair is not getattr(socket, "_fallback_socketpair", None):
        return

    def socketpair(family=socket.AF_INET, sock_type=socket.SOCK_STREAM, proto=0):
        # CPython calls this positionally as socketpair(family, type, proto); the name
        # is sock_type because a local called "type" shadows the builtin.
        host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        started = time.monotonic()
        for attempt in range(1, _SOCKETPAIR_ATTEMPTS + 1):
            lsock = socket.socket(family, sock_type, proto)
            csock = socket.socket(family, sock_type, proto)
            handed_off = False
            try:
                lsock.bind((host, 0))
                lsock.listen()
                addr, port = lsock.getsockname()[:2]
                csock.setblocking(False)
                try:
                    csock.connect((addr, port))
                except (BlockingIOError, InterruptedError):
                    pass
                # Drive the non-blocking connect to completion instead of assuming
                # it landed and blocking in accept() on a connection that may
                # never arrive.
                if not _await_connect_complete(csock, _SOCKETPAIR_HANDSHAKE_S):
                    raise TimeoutError("loopback connect did not complete")
                lsock.settimeout(_SOCKETPAIR_HANDSHAKE_S)
                ssock, _ = lsock.accept()
                ssock.setblocking(True)
                if (ssock.getsockname() != csock.getpeername()
                        or csock.getsockname() != ssock.getpeername()):
                    ssock.close()
                    raise ConnectionError("Unexpected peer connection")
                handed_off = True
                if attempt > 1:
                    _boot_note(
                        f"succeeded on attempt {attempt} after "
                        f"{time.monotonic() - started:.1f}s of retries"
                    )
                return ssock, csock
            except Exception as exc:
                _boot_note(
                    f"attempt {attempt}/{_SOCKETPAIR_ATTEMPTS} failed: "
                    f"{exc.__class__.__name__}: {exc}; retrying on a fresh port"
                )
            finally:
                lsock.close()
                if not handed_off:
                    csock.close()
        total = time.monotonic() - started
        _boot_note(f"gave up after {_SOCKETPAIR_ATTEMPTS} attempts in {total:.1f}s")
        raise OSError(
            f"loopback socketpair failed {_SOCKETPAIR_ATTEMPTS} times in {total:.1f}s; "
            "a firewall may be blocking 127.0.0.1"
        )

    socket.socketpair = socketpair


def _install_boot_watchdog(port: int) -> None:
    """Fail fast when start-up never reaches a bound port.

    uvicorn only binds after ``lifespan()`` completes, so a hang anywhere in start-up
    means the port never opens and the UI reports that it cannot reach the backend.
    Electron's own watchdog (``STARTUP_MAX_WAIT_MS``) then reaps the process only after
    five minutes. Exiting ourselves once the port has been missing for
    ``ATLAS_BOOT_WATCHDOG_S`` turns that five-minute dead zone into a fast, logged
    restart — and it is the only signal for the case where the process is stuck inside
    a C call that no in-process timeout can interrupt.
    """
    import threading

    try:
        limit = float(os.environ.get("ATLAS_BOOT_WATCHDOG_S", "90"))
    except ValueError:
        limit = 90.0
    if limit <= 0:
        return

    def watch() -> None:
        started = time.monotonic()
        deadline = started + limit
        while time.monotonic() < deadline:
            if _port_accepts(port):
                _boot_note(f"port {port} bound after {time.monotonic() - started:.1f}s")
                return
            time.sleep(0.25)
        _boot_note(
            f"boot watchdog: port {port} still unbound after {limit:.0f}s; "
            "exiting so the supervisor can restart the backend"
        )
        sys.stderr.flush()
        sys.stdout.flush()
        logging.getLogger("atlas.boot").error("boot.watchdog_timeout port=%s limit_s=%s", port, limit)
        os._exit(75)

    threading.Thread(target=watch, name="atlas-boot-watchdog", daemon=True).start()


def _port_accepts(port: int) -> bool:
    """Cheap liveness probe: can something connect to the port yet?"""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def main() -> None:
    if "--safe-mode" in sys.argv[1:]:
        os.environ["ATLAS_SAFE_MODE"] = "1"
        sys.stderr.write("atlas.desktop.safe_mode enabled: minimal startup requested by Electron\n")
        sys.stderr.flush()
    _guard_loopback_socketpair()
    if sys.argv[1:] == ["--atlas-mcp-bridge"]:
        import asyncio

        from atlas.tools.agent_bridge import serve

        asyncio.run(serve())
        return
    if sys.argv[1:] == ["--atlas-skill-search-worker"]:
        from atlas.skills.market_search_worker import run_stdio

        run_stdio()
        return
    _prepare_runtime_files()
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    port = int(os.environ.get("ATLAS_PORT", "8765"))
    # Arm the watchdog before importing atlas.server: the import itself loads the whole
    # application and is part of the window in which the port is still closed.
    _install_boot_watchdog(port)
    import uvicorn

    from atlas.server import app

    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
    ))
    app.state.desktop_shutdown_callback = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
