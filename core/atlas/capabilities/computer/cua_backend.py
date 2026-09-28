"""Thin in-process adapter for trycua/cua's typed Cua Driver SDK."""

from __future__ import annotations

import json
from typing import Any


class CuaBackend:
    def __init__(self) -> None:
        self._driver: Any = None

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
        raw = await self._driver.list_tools_json()
        result = json.loads(raw) if isinstance(raw, str) else raw
        return result if isinstance(result, list) else result.get("tools", [])

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._driver is None:
            await self.connect()
        result = await self._driver.call_tool(name, json.dumps(arguments))
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return {
            "text": getattr(result, "text", str(result)),
            "is_error": getattr(result, "is_error", False),
        }

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.shutdown()
            self._driver = None
