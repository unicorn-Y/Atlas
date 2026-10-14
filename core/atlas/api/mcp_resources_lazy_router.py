"""MCP resource routes with endpoint implementations imported on demand."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.mcp_resource_contract import ResourceReadRequest

router = APIRouter()


@router.get("/api/mcp/resources")
async def list_mcp_resources(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """List resources advertised by live sessions and expose current lifecycle state."""
    from atlas.api.mcp_resources_router import list_mcp_resources as handler

    return await handler(services)


@router.post("/api/mcp/resources/read")
async def read_mcp_resource(
    req: ResourceReadRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Read one URI that the selected connected server currently advertises."""
    from atlas.api.mcp_resources_router import read_mcp_resource as handler

    return await handler(req, services)
