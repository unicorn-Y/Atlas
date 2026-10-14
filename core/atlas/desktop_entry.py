"""PyInstaller entry point for the packaged Atlas backend."""

from __future__ import annotations

import os
import sys
import atexit
import secrets
import stat
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


def _guard_loopback_socketpair() -> None:
    """Bound the loopback handshake asyncio needs to create its event loop.

    On Windows ``socket.socketpair`` is a fallback that connects to a listener on
    127.0.0.1 and blocks in ``accept()`` with no timeout. On the 主机 a network filter
    (火绒 / Clash TUN, not pinned down) occasionally never delivers that connect, and
    the backend hung forever right after ``config.loaded`` (2026-10-14/15). Retry on a
    fresh port instead, and leave a line in backend-stdio.log when it happens.
    """
    import socket

    if socket.socketpair is not getattr(socket, "_fallback_socketpair", None):
        return

    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
        for attempt in range(1, 6):
            lsock = socket.socket(family, type, proto)
            try:
                lsock.bind((host, 0))
                lsock.listen()
                addr, port = lsock.getsockname()[:2]
                csock = socket.socket(family, type, proto)
                try:
                    csock.setblocking(False)
                    try:
                        csock.connect((addr, port))
                    except (BlockingIOError, InterruptedError):
                        pass
                    csock.setblocking(True)
                    lsock.settimeout(3.0)
                    try:
                        ssock, _ = lsock.accept()
                    except TimeoutError:
                        csock.close()
                        sys.stderr.write(f"atlas: loopback socketpair attempt {attempt} timed out, retrying\n")
                        sys.stderr.flush()
                        continue
                    ssock.setblocking(True)
                    if (ssock.getsockname() != csock.getpeername()
                            or csock.getsockname() != ssock.getpeername()):
                        ssock.close()
                        csock.close()
                        raise ConnectionError("Unexpected peer connection")
                    return ssock, csock
                except BaseException:
                    csock.close()
                    raise
            finally:
                lsock.close()
        raise OSError("loopback socketpair failed 5 times; a firewall may be blocking 127.0.0.1")

    socket.socketpair = socketpair


def main() -> None:
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
    import uvicorn

    from atlas.server import app

    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("ATLAS_PORT", "8765")),
        log_config=None,
    ))
    app.state.desktop_shutdown_callback = lambda: setattr(server, "should_exit", True)
    server.run()


if __name__ == "__main__":
    main()
