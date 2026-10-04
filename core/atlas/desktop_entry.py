"""PyInstaller entry point for the packaged Atlas backend."""

from __future__ import annotations

import os
import sys


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
