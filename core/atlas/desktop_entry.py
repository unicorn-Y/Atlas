"""PyInstaller entry point for the packaged Atlas backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
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
