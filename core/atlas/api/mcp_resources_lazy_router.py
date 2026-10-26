"""MCP resource routes with endpoint implementations imported on demand."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.mcp_resource_contract import ResourceReadRequest, ResourceTemplateReadRequest

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


@router.get("/api/mcp/resource-templates")
async def list_mcp_resource_templates(
    services: Annotated[AppServices, Depends(get_app_services)],
    server_name: str | None = Query(default=None, max_length=256),
    cursor: str | None = Query(default=None, max_length=4096),
) -> dict[str, Any]:
    """List templates declared by connected MCP servers, one server page at a time."""
    from atlas.api.mcp_resources_router import list_mcp_resource_templates as handler

    return await handler(services, server_name=server_name, cursor=cursor)


@router.post("/api/mcp/resource-templates/read")
async def read_mcp_resource_template(
    req: ResourceTemplateReadRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Expand a declared MCP URI template and return its resource contents."""
    from atlas.api.mcp_resources_router import read_mcp_resource_template as handler

    return await handler(req, services)
