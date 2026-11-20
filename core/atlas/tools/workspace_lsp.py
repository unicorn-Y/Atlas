# Behavior reference: Anthropic Claude Code LSP tool documentation and the
# language-server query contracts used by Codex tool handlers. This is an
# independent adapter over Atlas's existing LSP manager; no upstream source copied.
"""Read-only language-server queries inside the active Atlas workspace."""

from __future__ import annotations

import os
import posixpath
from pathlib import Path
from typing import Any


def _workspace_file(workspace: str, raw_path: Any, remote_world: Any = None) -> tuple[Any, str]:
    if remote_world is not None:
        return remote_world.workspace_file(raw_path)
    root = Path(workspace).expanduser().resolve()
    path = Path(str(raw_path or ""))
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("LSP queries are restricted to the active workspace.") from exc
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    return root, str(path)


def _service_for(path: str) -> tuple[Any, Any]:
    from atlas.lsp import get_service

    service = get_service()
    if service is None:
        return None, {"available": False, "reason": "LSP is disabled or unavailable."}
    server = service._server_for(str(path))
    if server is None:
        suffix = os.path.splitext(path)[1]
        return None, {"available": False, "reason": f"No configured LSP server handles {suffix or 'this file type'}."}
    return service, server


async def _query(service: Any, server: Any, path: Path, method: str,
                 line: int | None = None, character: int | None = None,
                 include_declaration: bool = True, remote_world: Any = None) -> Any:
    if remote_world is None:
        client = await service._get_or_spawn(str(path))
    else:
        client = await service._get_or_spawn(str(path), remote_world=remote_world)
    if client is None:
        return {"available": False, "reason": "No trusted and ready LSP server is available for this workspace."}
    from atlas.lsp.servers import language_id_for

    version = await client.open_file(str(path), language_id=language_id_for(str(path), server))
    del version
    params: dict[str, Any] = {"textDocument": {"uri": client._uri_for_path(str(path))}}
    if line is not None and character is not None:
        params["position"] = {"line": line, "character": character}
    if method == "textDocument/references":
        params["context"] = {"includeDeclaration": include_declaration}
    try:
        result = await client._send_request_with_retry(method, params, timeout=20.0)
    except Exception as exc:  # server-specific errors are returned as tool results
        return {"available": False, "reason": f"LSP {method} failed: {exc}"}
    service._touch(client)
    return {"available": True, "result": result}


def query_lsp(workspace: str, *, operation: str, path: str,
              line: int | None = None, character: int | None = None,
              include_declaration: bool = True, remote_world: Any = None) -> dict[str, Any]:
    root, file_path = _workspace_file(workspace, path, remote_world)
    relative = posixpath.relpath(file_path, root) if remote_world is not None else Path(file_path).relative_to(root).as_posix()
    service, server_or_error = _service_for(file_path)
    if service is None:
        return {**server_or_error, "path": relative}
    if operation == "diagnostics":
        try:
            diagnostics = service._loop.run(
                service._open_and_wait_async(str(file_path), remote_world=remote_world), timeout=25.0,
            )
        except Exception as exc:
            return {"available": False, "path": relative,
                    "reason": f"LSP diagnostics failed: {exc}"}
        if diagnostics is None:
            return {"available": False, "path": relative,
                    "reason": "The language server did not return fresh diagnostics in time."}
        return {"available": True, "path": relative,
                "diagnostics": diagnostics}
    if operation in {"hover", "definition", "implementation", "references"}:
        if line is None or character is None or line < 0 or character < 0:
            raise ValueError("line and character must be non-negative zero-based positions")
    methods = {
        "hover": "textDocument/hover",
        "definition": "textDocument/definition",
        "implementation": "textDocument/implementation",
        "references": "textDocument/references",
        "document_symbols": "textDocument/documentSymbol",
    }
    method = methods.get(operation)
    if method is None:
        raise ValueError(f"Unknown LSP operation: {operation}")
    try:
        result = service._loop.run(
            _query(service, server_or_error, file_path, method, line, character,
                   include_declaration, remote_world), timeout=25.0,
        )
    except Exception as exc:
        result = {"available": False, "reason": f"LSP {operation} failed: {exc}"}
    result["path"] = relative
    return result


def lsp_tool_schemas() -> list[dict[str, Any]]:
    path = {"type": "string", "description": "Workspace-relative file path."}
    position = {
        "line": {"type": "integer", "minimum": 0, "description": "Zero-based line."},
        "character": {"type": "integer", "minimum": 0, "description": "Zero-based character offset."},
    }
    return [
        {"type": "function", "function": {
            "name": "lsp_diagnostics", "description": "Get fresh diagnostics for a workspace file from its configured language server.",
            "parameters": {"type": "object", "properties": {"path": path},
                            "required": ["path"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "lsp_hover", "description": "Get language-server hover information at a zero-based file position.",
            "parameters": {"type": "object", "properties": {"path": path, **position},
                            "required": ["path", "line", "character"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "lsp_definition", "description": "Find definitions at a zero-based file position.",
            "parameters": {"type": "object", "properties": {"path": path, **position},
                            "required": ["path", "line", "character"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "lsp_implementation", "description": "Find implementations at a zero-based file position.",
            "parameters": {"type": "object", "properties": {"path": path, **position},
                            "required": ["path", "line", "character"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "lsp_references", "description": "Find references at a zero-based file position.",
            "parameters": {"type": "object", "properties": {
                "path": path, **position,
                "includeDeclaration": {"type": "boolean", "default": True},
            }, "required": ["path", "line", "character"], "additionalProperties": False},
        }},
        {"type": "function", "function": {
            "name": "lsp_document_symbols", "description": "List document symbols for a workspace file.",
            "parameters": {"type": "object", "properties": {"path": path},
                            "required": ["path"], "additionalProperties": False},
        }},
    ]
