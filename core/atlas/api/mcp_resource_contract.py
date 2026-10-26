"""Small request contract shared by the lazy MCP resource endpoint shim."""

from __future__ import annotations

from pydantic import BaseModel, Field


MAX_URI_BYTES = 4096


class ResourceReadRequest(BaseModel):
    server_name: str = Field(min_length=1, max_length=256)
    uri: str = Field(min_length=1, max_length=MAX_URI_BYTES)


class ResourceTemplateReadRequest(BaseModel):
    server_name: str = Field(min_length=1, max_length=256)
    uri_template: str = Field(min_length=1, max_length=MAX_URI_BYTES)
    variables: dict[str, str] = Field(default_factory=dict)
