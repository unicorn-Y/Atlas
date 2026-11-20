"""Temporary uvicorn host that mounts the real u6 router from the worktree core.

The full atlas.server lifespan needs models and lots of state; this harness only
needs the already-real /api/u6/keybindings GET/PUT route (the same router module
that atlas.api.application mounts). The harness page is served from the same
origin so the real browser fetch has no CORS shim.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from atlas.api import u6_router


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    app = FastAPI(title="atlas-par08b-harness")
    app.include_router(u6_router.router)
    harness_dir = Path(__file__).resolve().parent
    app.mount("/", StaticFiles(directory=str(harness_dir), html=True), name="harness")

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()