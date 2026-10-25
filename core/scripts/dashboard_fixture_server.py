"""Minimal live dashboard service used by U25's cross-data-root CLI regression."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from atlas.api.app_services import AppServices
from atlas.api.dashboard_router import router
from atlas.origin_guard import OriginGuard


class Memory:
    async def list_conversations(self, limit: int = 100):
        return [{"id": "live-session", "title": "Live dashboard scenario", "workspace": "local"}][:limit]


app = FastAPI()
app.add_middleware(OriginGuard)
app.include_router(router)
app.state.services = AppServices(
    runtime_mgr=None, startup=None, memory=Memory(), channel_manager=None, device_registry=None,
)


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["ATLAS_FIXTURE_PORT"]))
