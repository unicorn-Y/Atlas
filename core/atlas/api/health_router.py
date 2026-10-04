"""Health and runtime observability surface (``/api/health, /api/sandbox, /api/runtime/observability``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value





@router.get("/api/health")
async def health(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@router.get("/api/sandbox/status")
async def sandbox_status(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    sandbox_manager = _service("sandbox_manager", services)
    return {"docker": await sandbox_manager.status()}


@router.get("/api/runtime/observability")
async def runtime_observability(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    scheduler = _service("scheduler", services)
    orchestrator = _service("orchestrator", services)
    memory = _service("memory", services)
    """Report runtime component availability and durable autonomous activity."""
    scheduler_snapshot = scheduler.observability_snapshot() if scheduler else None
    components = {
        "scheduler": {
            "available": scheduler is not None,
            "running": bool(scheduler_snapshot and scheduler_snapshot["scheduler_running"]),
        },
        "orchestrator": {"available": orchestrator is not None},
        "memory": {"available": memory is not None},
    }
    ready = all(component["available"] for component in components.values())
    ready = ready and components["scheduler"]["running"]
    return {
        "status": "ok" if ready else "degraded",
        "components": components,
        "autonomous": scheduler_snapshot,
    }
