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


def main() -> None:
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
    # Hermes removes stale top-level modules while initializing its config. If
    # another thread is importing ``utils`` at that moment, the frozen importer
    # can lose its in-progress sys.modules entry. Complete this shared import
    # before Uvicorn starts serving concurrent requests.
    import importlib

    importlib.import_module("utils")
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
