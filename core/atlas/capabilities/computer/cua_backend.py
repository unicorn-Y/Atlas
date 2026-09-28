"""Thin in-process adapter for trycua/cua's typed Cua Driver SDK."""

from __future__ import annotations

import json
from typing import Any


class CuaBackend:
    def __init__(self) -> None:
        self._driver: Any = None
        self._tools: list[dict[str, Any]] | None = None

    async def connect(self) -> dict[str, Any]:
        from cua_driver import CuaDriver

        self._driver = CuaDriver.create()
        metadata = await self._driver.metadata()
        available = self._driver.is_available()
        metadata_value = (
            metadata.model_dump(mode="json")
            if hasattr(metadata, "model_dump")
            else {
                name: getattr(metadata, name)
                for name in dir(metadata)
                if not name.startswith("_") and not callable(getattr(metadata, name))
            }
        )
        return {"available": bool(available), "metadata": metadata_value}

    async def tools(self) -> list[dict[str, Any]]:
        if self._driver is None:
            await self.connect()
        if self._tools is None:
            raw = await self._driver.list_tools_json()
            result = json.loads(raw) if isinstance(raw, str) else raw
            self._tools = result if isinstance(result, list) else result.get("tools", [])
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._driver is None:
            await self.connect()
        tool = next((item for item in await self.tools() if item.get("name") == name), None)
        if tool is None:
            raise ValueError(f"Cua Driver does not expose tool {name!r}")
        schema = tool.get("inputSchema", tool.get("input_schema", {}))
        properties = schema.get("properties", {})
        supported = {key: value for key, value in arguments.items() if key in properties}
        missing = set(schema.get("required", [])) - supported.keys()
        if missing:
            raise ValueError(f"Cua Driver tool {name!r} requires {sorted(missing)}")
        result = await self._driver.call_tool(name, json.dumps(supported))
        raw = (
            result.model_dump(mode="json", by_alias=True)
            if hasattr(result, "model_dump")
            else None
        )
        if isinstance(raw, dict):
            text = raw.get("text", "")
            structured_content = raw.get(
                "structuredContent", raw.get("structured_content"),
            )
            if structured_content is None:
                structured_json = raw.get("structured_json")
                if structured_json:
                    try:
                        structured_content = json.loads(structured_json)
                    except (TypeError, ValueError):
                        structured_content = None
            return {
                "text": text,
                "content": raw.get("content", []),
                "is_error": raw.get("isError", raw.get("is_error", False)),
                "structured_content": structured_content,
            }
        structured_json = getattr(result, "structured_json", None)
        try:
            structured_content = json.loads(structured_json) if structured_json else None
        except (TypeError, ValueError):
            structured_content = None
        return {
            "text": getattr(result, "text", str(result)),
            "content": getattr(result, "content", []),
            "is_error": getattr(result, "is_error", False),
            "structured_content": structured_content,
        }

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.shutdown()
            self._driver = None
