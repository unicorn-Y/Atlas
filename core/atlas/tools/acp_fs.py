"""ACP client filesystem bridge scoped to one agent run."""
from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any, Awaitable, Callable

_CURRENT: contextvars.ContextVar["AcpFilesystem | None"] = contextvars.ContextVar(
    "atlas_acp_filesystem", default=None,
)


def capabilities_from_initialize(params: dict[str, Any]) -> dict[str, bool]:
    client = params.get("clientCapabilities")
    fs = client.get("fs") if isinstance(client, dict) else None
    return {
        "read": bool(isinstance(fs, dict) and fs.get("readTextFile")),
        "write": bool(isinstance(fs, dict) and fs.get("writeTextFile")),
    }


class AcpFilesystem:
    def __init__(self, session_id: str, workspace: str,
                 request: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]], *,
                 read_enabled: bool = True, write_enabled: bool = True) -> None:
        self.session_id = session_id
        self.workspace = Path(workspace).resolve()
        self.request = request
        self.read_enabled = read_enabled
        self.write_enabled = write_enabled

    def uri(self, raw: str) -> str:
        path = Path(raw).expanduser()
        path = (path if path.is_absolute() else self.workspace / path).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise PermissionError(f"ACP editor filesystem path is outside the workspace: {path}")
        return path.as_uri()

    async def read(self, path: str) -> str:
        if not self.read_enabled:
            raise PermissionError("ACP client did not declare fs.readTextFile")
        result = await self.request("fs/read_text_file", {
            "sessionId": self.session_id, "uri": self.uri(path),
        })
        content = result.get("content")
        if not isinstance(content, str):
            raise ValueError("ACP fs/read_text_file response is missing text content")
        return content

    async def write(self, path: str, content: str) -> None:
        if not self.write_enabled:
            raise PermissionError("ACP client did not declare fs.writeTextFile")
        await self.request("fs/write_text_file", {
            "sessionId": self.session_id, "uri": self.uri(path), "content": content,
        })


def set_current(filesystem: AcpFilesystem | None) -> contextvars.Token:
    return _CURRENT.set(filesystem)


def reset_current(token: contextvars.Token) -> None:
    _CURRENT.reset(token)


def current() -> AcpFilesystem | None:
    return _CURRENT.get()


async def local_file(filesystem: AcpFilesystem, *, action: str, path: str,
                     content: str = "") -> dict[str, Any]:
    """Run text read/write/append through ACP while preserving the normal tool envelope."""
    if action == "read":
        text = await filesystem.read(path)
        return {"data": {"path": path, "content": text, "complete": True},
                "content": [{"type": "text", "text": text}], "is_error": False}
    if action == "append":
        content = await filesystem.read(path) + content
    if action not in {"write", "append"}:
        raise ValueError(f"Unsupported ACP editor file action: {action}")
    await filesystem.write(path, content)
    return {"data": {"path": path, "written": True}, "is_error": False,
            "content": [{"type": "text", "text": f"Updated editor buffer: {path}"}]}


async def edit_file(filesystem: AcpFilesystem, *, path: str, old_text: str,
                    new_text: str, replace_all: bool = False) -> dict[str, Any]:
    text = await filesystem.read(path)
    if not old_text or old_text not in text:
        raise ValueError("Edit target text was not found in the editor buffer")
    if not replace_all and text.count(old_text) != 1:
        raise ValueError("Edit target is ambiguous in the editor buffer")
    updated = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
    return await local_file(filesystem, action="write", path=path, content=updated)
