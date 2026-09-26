"""PyInstaller entry point for the packaged Atlas backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    from atlas.server import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("ATLAS_PORT", "8765")),
        log_config=None,
    )


if __name__ == "__main__":
    main()
