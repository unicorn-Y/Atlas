"""Workspace files, git, ssh worktrees, rules, checkpoints and run changes surface (``/api/workspace, /api/git, /api/ssh, /api/checkpoints, /api/runs, /api/lsp``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import structlog
import fnmatch
import mimetypes
import re
import shlex
import subprocess
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from atlas.config import DATA_ROOT, get_config
from atlas.office import MAX_PREVIEW_BYTES, render_office
from atlas.ssh import ssh_workspaces

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


@router.get("/api/ide/status")
async def ide_status() -> dict[str, Any]:
    """Report whether the user's local VS Code bridge lock file is present."""
    from atlas.tools.ide_bridge import request
    try:
        await request("context")
        return {"connected": True, "name": "VS Code"}
    except (ConnectionError, OSError, RuntimeError, TimeoutError):
        return {"connected": False, "name": ""}


@router.post("/api/ide/context")
async def ide_context() -> dict[str, Any]:
    from atlas.tools.ide_bridge import request

    try:
        return await request("context")
    except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"没有连接到 VS Code（请安装并启用 Atlas IDE Bridge 扩展）：{exc}") from exc

log = structlog.get_logger()


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch
    (workspace path/trust, worktrees, run-change helpers, runtime manager)."""
    import atlas.server

    return atlas.server


def _service(name: str, services: AppServices) -> Any:
    """Resolve an optional service: per-app container first, then the server module."""
    value = getattr(services, name, None)
    if value is None:
        value = getattr(_server(), name, None)
    return value


_DASHBOARD_MAX_BYTES = 256 * 1024
_DASHBOARD_MAX_BOARDS = 20
_DASHBOARD_MAX_WIDGETS = 100
_DASHBOARD_MAX_ID_CHARS = 128
_DASHBOARD_MAX_BOARD_TITLE_CHARS = 160
_DASHBOARD_MAX_WIDGET_TITLE_CHARS = 160
_DASHBOARD_MAX_CONTENT_CHARS = 16_000
_DASHBOARD_MAX_SOURCE_EVENT_ID_CHARS = 256
_DASHBOARD_WIDGET_KINDS = {"text", "link", "code", "metric"}


@router.post("/api/chat/prompt-enhance")
async def enhance_chat_prompt(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request,
) -> dict[str, str]:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 32 * 1024:
            raise HTTPException(status_code=413, detail="Prompt is too large to enhance")
        raw.extend(chunk)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object")
    text = payload.get("text")
    model_id = payload.get("model")
    if not isinstance(text, str) or not text.strip() or len(text) > 24_000:
        raise HTTPException(status_code=400, detail="text must contain 1 to 24000 characters")
    if model_id is not None and (not isinstance(model_id, str) or len(model_id) > 256):
        raise HTTPException(status_code=400, detail="model must be a valid model id")
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    if model_mgr is None or model_mgr.model_router is None:
        raise HTTPException(status_code=503, detail="No configured model is available for prompt enhancement")
    selected = model_id or model_mgr.current_model
    try:
        route = await model_mgr.model_router.resolve(selected, "prompt_enhance")
        result = await model_mgr.model_router.complete(
            route,
            messages=[
                {"role": "system", "content": (
                    "Rewrite the user's draft into a clearer, more actionable prompt. Preserve the user's intent, "
                    "language, named entities, constraints, and scope. Do not add facts, requirements, or assumptions. "
                    "Do not answer or execute the prompt. Return only the rewritten prompt; if no improvement is needed, "
                    "return the original text."
                )},
                {"role": "user", "content": text.strip()},
            ],
            max_tokens=min(16_384, max(1_024, len(text) * 2)),
            temperature=0.2,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 — provider SDK errors are surfaced to the composer.
        log.warning("chat.prompt_enhance_failed", model=selected, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Prompt enhancement failed: {exc}") from exc
    raw_result = getattr(result, "raw", None)
    choice = raw_result.get("choices", [None])[0] if isinstance(raw_result, dict) and raw_result.get("choices") else None
    reason = (choice.get("finish_reason") if isinstance(choice, dict) else None) or (
        raw_result.get("stop_reason") if isinstance(raw_result, dict) else None
    )
    if isinstance(reason, str) and reason in {"length", "max_tokens"}:
        raise HTTPException(status_code=502, detail="Prompt enhancement was truncated; your original draft was kept")
    enhanced = str(getattr(result, "text", "") or "").strip()
    if not enhanced:
        raise HTTPException(status_code=502, detail="The selected model returned no rewritten prompt")
    return {"text": enhanced, "model": selected}


def _dashboard_store_path(conversation_id: str) -> Path:
    """Resolve a per-conversation dashboard file under Atlas's isolated data root."""
    data_root = Path(DATA_ROOT).expanduser().resolve()
    data_directory = data_root / "data"
    directory = data_directory / "conversation-dashboards"
    if data_directory.is_symlink() or directory.is_symlink():
        raise HTTPException(status_code=409, detail="Dashboard storage directory cannot be a symlink")
    try:
        directory = directory.resolve()
        directory.relative_to(data_root)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Dashboard storage path escapes ATLAS_DATA_DIR") from exc
    name = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest() + ".json"
    path = directory / name
    return path


def _dashboard_default(conversation_id: str) -> dict[str, Any]:
    return {"conversation_id": conversation_id, "boards": []}


def _read_conversation_dashboard(conversation_id: str) -> dict[str, Any]:
    path = _dashboard_store_path(conversation_id)
    if path.is_symlink():
        raise HTTPException(status_code=409, detail="Dashboard storage path is not a regular file")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _dashboard_default(conversation_id)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read conversation dashboard") from exc
    if len(raw) > _DASHBOARD_MAX_BYTES:
        raise HTTPException(status_code=500, detail="Stored conversation dashboard exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=500, detail="Stored conversation dashboard is invalid") from exc
    if not isinstance(payload, dict) or payload.get("conversation_id") != conversation_id:
        raise HTTPException(status_code=500, detail="Stored conversation dashboard identity mismatch")
    return payload


def _validate_dashboard_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("boards"), list):
        raise HTTPException(status_code=400, detail="Request body must contain a boards array")
    boards = payload["boards"]
    if len(boards) > _DASHBOARD_MAX_BOARDS:
        raise HTTPException(status_code=413, detail=f"At most {_DASHBOARD_MAX_BOARDS} boards are allowed")

    result: list[dict[str, Any]] = []
    board_ids: set[str] = set()
    widget_count = 0
    for board in boards:
        if not isinstance(board, dict):
            raise HTTPException(status_code=400, detail="Each board must be an object")
        board_id = board.get("id")
        title = board.get("title")
        widgets = board.get("widgets")
        if not isinstance(board_id, str) or not board_id or len(board_id) > _DASHBOARD_MAX_ID_CHARS:
            raise HTTPException(status_code=400, detail="Board id must be a non-empty string of at most 128 characters")
        if board_id in board_ids:
            raise HTTPException(status_code=400, detail="Board ids must be unique")
        board_ids.add(board_id)
        if not isinstance(title, str) or len(title) > _DASHBOARD_MAX_BOARD_TITLE_CHARS:
            raise HTTPException(status_code=400, detail="Board title must be a string of at most 160 characters")
        if not isinstance(widgets, list):
            raise HTTPException(status_code=400, detail="Board widgets must be an array")

        normalized_widgets: list[dict[str, Any]] = []
        widget_ids: set[str] = set()
        for widget in widgets:
            widget_count += 1
            if widget_count > _DASHBOARD_MAX_WIDGETS:
                raise HTTPException(status_code=413, detail=f"At most {_DASHBOARD_MAX_WIDGETS} widgets are allowed")
            if not isinstance(widget, dict):
                raise HTTPException(status_code=400, detail="Each widget must be an object")
            widget_id = widget.get("id")
            widget_title = widget.get("title")
            kind = widget.get("kind")
            content = widget.get("content")
            position = widget.get("position")
            if not isinstance(widget_id, str) or not widget_id or len(widget_id) > _DASHBOARD_MAX_ID_CHARS:
                raise HTTPException(status_code=400, detail="Widget id must be a non-empty string of at most 128 characters")
            if widget_id in widget_ids:
                raise HTTPException(status_code=400, detail="Widget ids must be unique within a board")
            widget_ids.add(widget_id)
            if not isinstance(widget_title, str) or len(widget_title) > _DASHBOARD_MAX_WIDGET_TITLE_CHARS:
                raise HTTPException(status_code=400, detail="Widget title must be a string of at most 160 characters")
            if not isinstance(kind, str) or kind not in _DASHBOARD_WIDGET_KINDS:
                raise HTTPException(status_code=400, detail="Widget kind must be text, link, code, or metric")
            if not isinstance(content, str) or len(content) > _DASHBOARD_MAX_CONTENT_CHARS:
                raise HTTPException(status_code=400, detail="Widget content must be a string of at most 16000 characters")
            if (isinstance(position, bool) or not isinstance(position, (int, float))
                    or not 0 <= position <= _DASHBOARD_MAX_WIDGETS or int(position) != position):
                raise HTTPException(status_code=400, detail="Widget position must be an integer from 0 to 100")

            normalized = {
                "id": widget_id,
                "title": widget_title,
                "kind": kind,
                "content": content,
                "position": position,
            }
            source_event_id = widget.get("source_event_id")
            if source_event_id is not None:
                if not isinstance(source_event_id, str) or len(source_event_id) > _DASHBOARD_MAX_SOURCE_EVENT_ID_CHARS:
                    raise HTTPException(status_code=400, detail="source_event_id must be a string of at most 256 characters")
                normalized["source_event_id"] = source_event_id
            normalized_widgets.append(normalized)
        result.append({"id": board_id, "title": title, "widgets": normalized_widgets})
    return result


def _write_conversation_dashboard(conversation_id: str, boards: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {"conversation_id": conversation_id, "boards": boards}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > _DASHBOARD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Dashboard exceeds 256 KiB")
    path = _dashboard_store_path(conversation_id)
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent, delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        try:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Could not save conversation dashboard") from exc
    return payload


async def _dashboard_memory(services: AppServices) -> Any:
    memory = _service("memory", services)
    if memory is None:
        raise HTTPException(status_code=503, detail="Conversation store is unavailable")
    return memory


@router.get("/api/conversations/{conversation_id}/dashboard")
async def get_conversation_dashboard(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    if not conversation_id or len(conversation_id) > 512:
        raise HTTPException(status_code=400, detail="Invalid conversation id")
    memory = await _dashboard_memory(services)
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _read_conversation_dashboard(conversation_id)


@router.put("/api/conversations/{conversation_id}/dashboard")
async def put_conversation_dashboard(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
    request: Request,
) -> dict[str, Any]:
    if not conversation_id or len(conversation_id) > 512:
        raise HTTPException(status_code=400, detail="Invalid conversation id")
    memory = await _dashboard_memory(services)
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _DASHBOARD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Dashboard request exceeds 256 KiB")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > _DASHBOARD_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Dashboard request exceeds 256 KiB")
        raw.extend(chunk)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    boards = _validate_dashboard_payload(payload)
    return _write_conversation_dashboard(conversation_id, boards)


@router.get("/api/workspace/trust")
async def get_workspace_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    return {"root": root, "trusted": bool(_server()._workspace_trust().get(root))}


@router.delete("/api/workspace/trust")
async def revoke_workspace_trust(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    _server()._set_workspace_trusted(root, False)
    return {"root": root, "trusted": False}


@router.get("/api/workspace/tree")
async def workspace_tree(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str = "",
) -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        remote = str(PurePosixPath(base).joinpath(*relative.parts))
        try:
            entries = await ssh_workspaces.list_dir(host, remote)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"root": root, "path": path, "entries": entries}
    base, directory = _server()._workspace_path(root, path)
    if not base.is_dir() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    git_status: dict[str, str] = {}
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["git", "-C", str(base), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        status_records = result.stdout.split("\0")
        index = 0
        while index < len(status_records):
            record = status_records[index]
            index += 1
            if len(record) < 4 or record[2] != " ":
                continue
            code = record[:2]
            relative = record[3:].replace("\\", "/")
            git_status[relative] = (
                "?" if code == "??" else "A" if "A" in code else
                "D" if "D" in code else "M"
            )
            if "R" in code or "C" in code:
                index += 1  # -z emits the old path as the next NUL-delimited field.
    except (OSError, subprocess.SubprocessError):
        pass
    directory_git_status: dict[str, str] = {}
    status_rank = {"?": 1, "D": 2, "A": 3, "M": 4}
    for changed_path, status in git_status.items():
        parts = PurePosixPath(changed_path).parts[:-1]
        for index in range(1, len(parts) + 1):
            parent = PurePosixPath(*parts[:index]).as_posix()
            if status_rank.get(status, 0) > status_rank.get(directory_git_status.get(parent, ""), 0):
                directory_git_status[parent] = status
    entries = []
    for item in sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold())):
        if item.name in _server()._WORKSPACE_IGNORES:
            continue
        rel = item.relative_to(base).as_posix()
        entries.append({"name": item.name, "path": rel,
                        "type": "dir" if item.is_dir() else "file",
                        "size": None if item.is_dir() else item.stat().st_size,
                        "git": git_status.get(rel) or directory_git_status.get(rel)})
    return {"root": str(base), "path": Path(path).as_posix() if path else "",
            "entries": entries}


@router.get("/api/workspace/file")
async def workspace_file(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str,
) -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        try:
            raw = await ssh_workspaces.read_bytes(host, str(PurePosixPath(base).joinpath(*relative.parts)))
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Workspace file not found") from exc
        sample = raw[:512 * 1024]
        try:
            text = sample.decode("utf-8")
            binary = b"\x00" in sample
        except UnicodeDecodeError:
            text, binary = "", True
        return {"path": path, "content": "" if binary else text,
                "truncated": len(raw) > 512 * 1024, "binary": binary}
    base, target = _server()._workspace_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found")
    raw = await asyncio.to_thread(target.read_bytes)
    sample = raw[: min(len(raw), 512 * 1024)]
    try:
        text = sample.decode("utf-8")
        binary = b"\x00" in sample
    except UnicodeDecodeError:
        text, binary = "", True
    return {"path": target.relative_to(base).as_posix(),
            "content": "" if binary else text,
            "truncated": len(raw) > 512 * 1024, "binary": binary,
            "sha256": hashlib.sha256(raw).hexdigest()}


class WorkspaceFileSave(BaseModel):
    content: str
    expected_sha256: str


@router.put("/api/workspace/file")
async def save_workspace_file(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str, payload: WorkspaceFileSave,
) -> dict[str, Any]:
    """Save a text file only when its bytes still match the version the editor loaded."""
    if root.startswith("ssh://"):
        raise HTTPException(status_code=501, detail="Saving SSH workspace files is not supported")
    if len(payload.content.encode("utf-8")) > 512 * 1024:
        raise HTTPException(status_code=413, detail="Edited files are limited to 512 KiB")
    base, target = _server()._workspace_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found")
    try:
        current = await asyncio.to_thread(target.read_bytes)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read workspace file") from exc
    if len(current) > 512 * 1024:
        raise HTTPException(status_code=413, detail="Files over 512 KiB cannot be edited here")
    current_hash = hashlib.sha256(current).hexdigest()
    if current_hash != payload.expected_sha256:
        raise HTTPException(status_code=409, detail="File changed on disk; reload it before saving")
    text = payload.content
    if b"\r\n" in current and "\r\n" not in text:
        text = text.replace("\n", "\r\n")
    encoded = text.encode("utf-8")
    if b"\x00" in current or b"\x00" in encoded:
        raise HTTPException(status_code=415, detail="Binary files cannot be edited here")
    # Recheck immediately before writing so an external edit made during validation becomes a conflict.
    latest = await asyncio.to_thread(target.read_bytes)
    if hashlib.sha256(latest).hexdigest() != payload.expected_sha256:
        raise HTTPException(status_code=409, detail="File changed on disk; reload it before saving")
    try:
        await asyncio.to_thread(target.write_bytes, encoded)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save workspace file") from exc
    return {"path": target.relative_to(base).as_posix(), "sha256": hashlib.sha256(encoded).hexdigest()}


@router.get("/api/workspace/raw")
async def workspace_raw(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str,
) -> StreamingResponse:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(status_code=400, detail="path escapes workspace root")
        try:
            raw = await ssh_workspaces.read_bytes(host, str(PurePosixPath(base).joinpath(*relative.parts)))
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Workspace file not found") from exc
        if len(raw) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="file exceeds 50 MB limit")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"}
        if content_type in _SCRIPTABLE_TYPES:
            headers["Content-Security-Policy"] = "sandbox allow-scripts allow-forms allow-popups allow-modals"
        return StreamingResponse(iter([raw]), media_type=content_type, headers=headers)
    base, target = _server()._workspace_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found")
    if target.stat().st_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file exceeds 50 MB limit")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    headers = {"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"}
    if content_type in _SCRIPTABLE_TYPES:
        # Workspace files are untrusted. Sandboxing gives the document an opaque origin, so its
        # scripts still run for the preview but cannot read Atlas's API as same-origin.
        headers["Content-Security-Policy"] = (
            "sandbox allow-scripts allow-forms allow-popups allow-modals"
        )
    return StreamingResponse(target.open("rb"), media_type=content_type, headers=headers)


_OFFICE_SANDBOX_HEADERS = {
    "Content-Security-Policy": (
        "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
}


@router.get("/api/workspace/preview")
async def workspace_preview(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str,
) -> Response:
    suffix = Path(path).suffix.casefold()
    if suffix not in {".docx", ".xlsx", ".pptx"}:
        raise HTTPException(status_code=415, detail="Only Office documents can use this preview")
    try:
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            relative = Path(path)
            if relative.is_absolute() or ".." in relative.parts:
                raise HTTPException(status_code=400, detail="path escapes workspace root")
            remote_path = ssh_workspaces._remote_path(remote_root, path)
            raw = await ssh_workspaces.read_bytes(host, remote_path)
        else:
            _base, target = _server()._workspace_path(root, path)
            if not target.is_file():
                raise HTTPException(status_code=404, detail="Workspace file not found")
            if target.stat().st_size > MAX_PREVIEW_BYTES:
                raise HTTPException(status_code=413, detail="Office preview is limited to 10 MB")
            raw = await asyncio.to_thread(target.read_bytes)
        rendered = await asyncio.to_thread(render_office, raw, suffix)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Office file could not be read") from exc
    return Response(rendered, media_type="text/html", headers=_OFFICE_SANDBOX_HEADERS)


def _history_checkpoint_manifest(store: Any, checkpoint_id: str) -> tuple[dict[str, Any], Path]:
    # The id comes from the query string and becomes a directory name; checkpoint ids are uuid4 hex.
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", checkpoint_id):
        raise HTTPException(status_code=400, detail="invalid workspace version")
    manifest_path = store.storage_dir / checkpoint_id / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="Workspace version not found")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path.parent
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Workspace version not found") from exc


async def _git_history(
    root: Path, relative: str,
) -> list[dict[str, Any]]:
    try:
        log_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "log", "-20", "--format=%H%x09%cI", "--", relative],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if log_result.returncode:
        return []
    versions: list[dict[str, Any]] = []
    for line in log_result.stdout.splitlines():
        commit, _, created_at = line.partition("\t")
        if not commit or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            continue
        size = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(root), "cat-file", "-s", f"{commit}:{relative}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False,
        )
        versions.append({
            "id": f"git:{commit}", "run_id": None, "conversation_id": None,
            "created_at": created_at,
            "bytes": int(size.stdout) if size.returncode == 0 and size.stdout.strip().isdigit() else 0,
            "source": "git",
        })
    return versions


@router.get("/api/workspace/history")
async def workspace_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str,
) -> dict[str, Any]:
    orchestrator = _service("orchestrator", services)
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="path escapes workspace root")
    normalized = relative.as_posix()
    versions: list[dict[str, Any]] = []
    if root.startswith("ssh://"):
        checkpoints = await ssh_workspaces.list_checkpoints(root)
        _host, remote_root = ssh_workspaces.parse_workspace(root)
        for item in checkpoints:
            entry = next((file for file in item.get("files", [])
                          if file.get("path") == normalized), None)
            if entry is None:
                continue
            size = 0
            if entry.get("exists"):
                with suppress(Exception):
                    raw = await ssh_workspaces.read_bytes(
                        _host, str(PurePosixPath(remote_root) / ".atlas-checkpoints"
                                   / item["id"] / "files" / normalized),
                    )
                    size = len(raw)
            versions.append({
                "id": f"checkpoint:{item['id']}", "run_id": item.get("run_id"),
                "conversation_id": None, "created_at": item.get("created_at", ""),
                "bytes": size, "source": "checkpoint",
            })
    else:
        base, _ = _server()._workspace_path(root, normalized)
        if orchestrator is not None:
            store = orchestrator.checkpoints
            for item in store.list_checkpoints(str(base)):
                manifest, snapshot = _history_checkpoint_manifest(store, item["id"])
                entry = next((file for file in manifest.get("files", [])
                              if file.get("path") == normalized and not file.get("directory")), None)
                if entry is None:
                    continue
                saved = snapshot / "files" / normalized
                versions.append({
                    "id": f"checkpoint:{item['id']}",
                    "run_id": manifest.get("run_id"),
                    "conversation_id": manifest.get("conversation_id"),
                    "created_at": manifest.get("created_at", ""),
                    "bytes": saved.stat().st_size if entry.get("exists") and saved.is_file() else 0,
                    "source": "checkpoint",
                })
        versions.extend(await _git_history(base, normalized))
    versions.sort(key=lambda item: item["created_at"], reverse=True)
    return {"versions": versions}


async def _history_bytes(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str, version: str,
) -> tuple[bytes, bool]:
    orchestrator = _service("orchestrator", services)
    if version.startswith("checkpoint:"):
        checkpoint_id = version.removeprefix("checkpoint:")
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            checkpoints = await ssh_workspaces.list_checkpoints(root)
            checkpoint = next((item for item in checkpoints if item["id"] == checkpoint_id), None)
            if checkpoint is None:
                raise HTTPException(status_code=404, detail="Workspace version not found")
            entry = next((file for file in checkpoint.get("files", [])
                          if file.get("path") == path), None)
            if entry is None:
                raise HTTPException(status_code=404, detail="File is absent from this version")
            if not entry.get("exists"):
                return b"", False
            raw_path = str(PurePosixPath(remote_root) / ".atlas-checkpoints"
                           / checkpoint_id / "files" / path)
            return await ssh_workspaces.read_bytes(host, raw_path), True
        base, _ = _server()._workspace_path(root, path)
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Checkpoint service is unavailable")
        manifest, snapshot = _history_checkpoint_manifest(
            orchestrator.checkpoints, checkpoint_id,
        )
        entry = next((file for file in manifest.get("files", [])
                      if file.get("path") == path and not file.get("directory")), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="File is absent from this version")
        saved = snapshot / "files" / path
        return (saved.read_bytes() if entry.get("exists") and saved.is_file() else b""), bool(entry.get("exists"))
    if version.startswith("git:"):
        if root.startswith("ssh://"):
            raise HTTPException(status_code=404, detail="Git history is unavailable for SSH workspaces")
        commit = version.removeprefix("git:")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            raise HTTPException(status_code=400, detail="invalid git version")
        base, _ = _server()._workspace_path(root, path)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "-C", str(base), "show", f"{commit}:{path}"],
            capture_output=True, timeout=10, check=False,
        )
        if result.returncode:
            return b"", False
        return result.stdout, True
    raise HTTPException(status_code=400, detail="invalid workspace version")


def _content_description(raw: bytes, path: str, exists: bool = True) -> dict[str, Any]:
    try:
        text = raw[:512 * 1024].decode("utf-8")
        binary = b"\x00" in raw[:512 * 1024]
    except UnicodeDecodeError:
        text, binary = "", True
    return {
        "path": path, "content": "" if binary or not exists else text,
        "truncated": len(raw) > 512 * 1024,
        "binary": binary or not exists,
    }


@router.get("/api/workspace/history/content")
async def workspace_history_content(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str, version: str,
) -> dict[str, Any]:
    raw, exists = await _history_bytes(services, root, path, version)
    return _content_description(raw, path, exists)


@router.get("/api/workspace/history/raw")
async def workspace_history_raw(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, path: str, version: str,
) -> Response:
    raw, _exists = await _history_bytes(services, root, path, version)
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(raw, media_type=media_type, headers=_OFFICE_SANDBOX_HEADERS)


@router.post("/api/workspace/history/restore")
async def restore_workspace_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    request: Request,
) -> dict[str, Any]:
    orchestrator = _service("orchestrator", services)
    payload = await request.json()
    root, path, version = (
        str(payload.get("root", "")), str(payload.get("path", "")),
        str(payload.get("version", "")),
    )
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="path escapes workspace root")
    normalized = relative.as_posix()
    raw, exists = await _history_bytes(services, root, normalized, version)
    checkpoint_id = str(uuid.uuid4())
    if root.startswith("ssh://"):
        await ssh_workspaces.create_checkpoint(root, [normalized], checkpoint_id)
        host, remote_root = ssh_workspaces.parse_workspace(root)
        target = ssh_workspaces._remote_path(remote_root, normalized)
        if exists:
            await ssh_workspaces.write_bytes(host, target, raw)
        else:
            await ssh_workspaces.call_tool("local_file", {
                "action": "delete", "path": normalized,
            }, root, run_id=None)
    else:
        base, target = _server()._workspace_path(root, normalized)
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Checkpoint service is unavailable")
        checkpoint = orchestrator.checkpoints.create_checkpoint(
            base, [normalized], run_id=checkpoint_id,
        )
        checkpoint_id = checkpoint["id"]
        if exists:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        elif target.is_file():
            target.unlink()
        elif target.is_dir():
            raise HTTPException(status_code=409, detail="Cannot restore a file over a directory")
    return {"restored": True, "checkpoint_id": checkpoint_id}


_SCRIPTABLE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml"}


def _is_subsequence(needle: str, haystack: str) -> bool:
    pos = 0
    for char in haystack.casefold():
        if pos < len(needle) and char == needle[pos]:
            pos += 1
    return pos == len(needle)


@router.get("/api/workspace/search")
async def workspace_search(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str, q: str, limit: int = 50,
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    base, _ = _server()._workspace_path(root)
    if not base.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    needle = q.strip().casefold()
    if not needle:
        return {"files": []}
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        try:
            command = f"cd {shlex.quote(base)} && rg --files -g {shlex.quote('*' + needle + '*')} | head -n {limit}"
            output = await ssh_workspaces.run(host, command)
            files = [{"path": item, "name": PurePosixPath(item).name, "type": "file"}
                     for item in output.splitlines()]
            return {"files": files}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        listing = await asyncio.to_thread(
            subprocess.run,
            # Windows 默认按系统代码页解码，中文文件名会让读线程抛错、stdout 变成 None；
            # 固定 UTF-8 并关掉 quotepath，让 git 原样输出非 ASCII 路径。
            ["git", "-c", "core.quotepath=off", "-C", str(base), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        git_listing_ok = listing.returncode == 0 and listing.stdout is not None
        paths = listing.stdout.splitlines() if git_listing_ok else []
    except (OSError, subprocess.SubprocessError):
        git_listing_ok = False
        paths = []
    if not git_listing_ok:
        paths = [p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()]
        patterns = []
        for ignore_file in base.rglob(".gitignore"):
            if any(part in _server()._WORKSPACE_IGNORES for part in ignore_file.relative_to(base).parts[:-1]):
                continue
            try:
                patterns.extend((ignore_file.parent, line.strip()) for line in ignore_file.read_text("utf-8").splitlines()
                                if line.strip() and not line.lstrip().startswith("#"))
            except OSError:
                continue
        filtered = []
        for rel in paths:
            ignored = False
            rel_path = Path(rel)
            for ignore_dir, pattern in patterns:
                negated = pattern.startswith("!")
                value = pattern[1:] if negated else pattern
                target = (ignore_dir / value).relative_to(base).as_posix().lstrip("./")
                candidate = rel_path.as_posix()
                if (candidate == target or candidate.startswith(target.rstrip("/") + "/")
                        or ("/" not in value and fnmatch.fnmatch(rel_path.name, value))):
                    ignored = not negated
            if not ignored:
                filtered.append(rel)
        paths = filtered
    hits = []
    for rel in paths:
        parts = Path(rel).parts
        if any(part in _server()._WORKSPACE_IGNORES for part in parts):
            continue
        name = Path(rel).name
        candidate = name.casefold()
        if needle not in candidate and not _is_subsequence(needle, candidate):
            continue
        score = (0 if candidate.startswith(needle) else 1 if needle in candidate else 2,
                 len(candidate) - len(needle), rel.casefold())
        hits.append((score, {"path": Path(rel).as_posix(), "name": name, "type": "file"}))
    hits.sort(key=lambda row: row[0])
    return {"files": [item for _, item in hits[:limit]]}


@router.get("/api/git/branches")
async def git_branches(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(root)
    if not (base / ".git").exists():
        raise HTTPException(status_code=400, detail="workspace is not a git repository")
    try:
        current = _server()._worktrees()._git(base, "branch", "--show-current")
        branches = _server()._worktrees()._git(base, "branch", "--list", "--format=%(refname:short)").splitlines()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"current": current, "branches": branches}


def _gh_json(root: Path, *args: str) -> dict[str, Any]:
    try:
        auth = subprocess.run(["gh", "auth", "status"], cwd=root, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip() or "gh command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="gh returned invalid JSON") from exc


def _pr_shape(data: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for item in data.get("statusCheckRollup", []):
        checks.append({"name": item.get("name", ""),
                       "status": item.get("status", ""),
                       "conclusion": item.get("conclusion"),
                       "url": item.get("detailsUrl", "")})
    return {"number": data.get("number"), "title": data.get("title"),
            "url": data.get("url"), "state": data.get("state"),
            "draft": data.get("isDraft", False), "base": data.get("baseRefName"),
            "head": data.get("headRefName"), "checks": checks,
            "auto_merge": bool(data.get("autoMergeRequest")),
            "auto_merge_method": (data.get("autoMergeRequest") or {}).get("mergeMethod") if isinstance(data.get("autoMergeRequest"), dict) else None}


@router.get("/api/git/pr")
async def get_git_pr(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(root)
    try:
        data = _gh_json(base, "pr", "view", "--json",
                        "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup,autoMergeRequest")
    except HTTPException as exc:
        if exc.status_code == 502 and "no pull requests found" in str(exc.detail).lower():
            return {"pr": None}
        raise
    return {"pr": _pr_shape(data)}


@router.post("/api/git/pr")
async def create_git_pr(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(str(req.get("root", "")))
    title, body = req.get("title"), req.get("body")
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise HTTPException(status_code=422, detail="title and body are required")
    try:
        auth = subprocess.run(["gh", "auth", "status"], cwd=base, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=15)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    pushed = subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=base,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if pushed.returncode:
        raise HTTPException(status_code=502, detail=pushed.stderr.strip())
    command = ["gh", "pr", "create", "--title", title, "--body", body]
    if req.get("base"):
        command.extend(["--base", str(req["base"])])
    if req.get("draft") is True:
        command.append("--draft")
    created = subprocess.run(command, cwd=base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if created.returncode:
        raise HTTPException(status_code=502, detail=created.stderr.strip())
    result = _gh_json(base, "pr", "view", "--json",
                      "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup,autoMergeRequest")
    return {"pr": _pr_shape(result)}


@router.post("/api/git/pr/auto-merge")
async def set_git_pr_auto_merge(
    services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any],
) -> dict[str, Any]:
    """Enable/disable GitHub's native auto-merge for the current PR."""
    base = _git_workspace(str(req.get("root", "")))
    enabled = req.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    method = str(req.get("method", "squash"))
    if method not in {"squash", "merge", "rebase"}:
        raise HTTPException(status_code=422, detail="method must be squash, merge or rebase")
    command = ["gh", "pr", "merge", "--auto", f"--{method}"] if enabled else ["gh", "pr", "merge", "--disable-auto"]
    try:
        result = subprocess.run(command, cwd=base, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail="Unable to run gh pr merge") from exc
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip() or "gh pr merge failed")
    try:
        data = _gh_json(base, "pr", "view", "--json", "autoMergeRequest")
    except HTTPException:
        raise
    return {"enabled": bool(data.get("autoMergeRequest")), "auto_merge": data.get("autoMergeRequest"), "method": method}


@router.post("/api/git/pr/wizard")
async def run_git_pr_wizard(
    services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any],
) -> dict[str, Any]:
    """Run the editable PR wizard's commit → push → create steps with phase-specific errors."""
    base = _git_workspace(str(req.get("root", "")))
    paths, message = req.get("paths"), req.get("message")
    title, body = req.get("title"), req.get("body")
    branch = req.get("branch")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise HTTPException(status_code=422, detail="至少选择一个要提交的文件。")
    if not isinstance(message, str) or not message.strip() or not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise HTTPException(status_code=422, detail="提交说明、PR 标题和说明都必须先填写。")
    def run(args: list[str], phase: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(args, cwd=base, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=502, detail=f"{phase}失败：{exc}") from exc
        if result.returncode:
            raise HTTPException(status_code=502, detail=f"{phase}失败：{result.stderr.strip() or result.stdout.strip()}")
        return result
    status = run(["git", "status", "--porcelain", "--", *paths], "读取所选改动").stdout
    available = {line[3:].strip().strip('"') for line in status.splitlines() if len(line) >= 4}
    chosen = list(dict.fromkeys(paths))
    already_committed = False
    if any(p not in available for p in chosen):
        last_paths = set(run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"], "检查上一提交").stdout.splitlines())
        last_message = run(["git", "log", "-1", "--format=%s"], "检查上一提交说明").stdout.strip()
        already_committed = all(p in last_paths for p in chosen) and last_message == message.strip()
        if not already_committed:
            raise HTTPException(status_code=409, detail="所选文件已不再是未提交改动，请刷新改动列表后重试。")
    current = run(["git", "branch", "--show-current"], "读取当前分支").stdout.strip()
    default = ""
    try:
        default = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], "读取默认分支").stdout.strip().split("/", 2)[-1]
    except HTTPException:
        pass
    target = str(branch or current).strip()
    if not target:
        raise HTTPException(status_code=409, detail="当前处于 detached HEAD，请在向导中指定分支后重试。")
    if current == default or current in {"main", "master"} and not branch:
        target = str(branch or f"atlas/{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}").strip()
    if target != current:
        exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{target}"], cwd=base)
        run(["git", "switch", target] if exists.returncode == 0 else ["git", "switch", "-c", target], "切换/创建分支")
    if already_committed:
        commit = run(["git", "rev-parse", "--short", "HEAD"], "读取已完成提交")
    else:
        run(["git", "add", "--", *chosen], "暂存所选文件")
        commit = run(["git", "commit", "-m", message.strip()], "创建提交")
    run(["git", "push", "-u", "origin", "HEAD"], "推送分支")
    args = ["gh", "pr", "create", "--title", title.strip(), "--body", body]
    if req.get("base"):
        args.extend(["--base", str(req["base"])])
    if req.get("draft") is True:
        args.append("--draft")
    try:
        existing = _gh_json(base, "pr", "view", "--json", "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup,autoMergeRequest")
    except HTTPException as exc:
        if exc.status_code != 502 or "no pull requests found" not in str(exc.detail).lower():
            raise
        run(args, "创建 PR", 60)
        existing = _gh_json(base, "pr", "view", "--json", "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup,autoMergeRequest")
    return {"commit": commit.stdout.strip().splitlines()[-1] if commit.stdout.strip() else "已提交", "branch": target, "pr": _pr_shape(existing)}


@router.post("/api/git/pr/draft")
async def draft_git_pr(
    services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any],
) -> dict[str, str]:
    base = _git_workspace(str(req.get("root", "")))
    paths = req.get("paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise HTTPException(status_code=422, detail="至少选择一个要提交的文件。")
    diff = subprocess.run(["git", "diff", "--", *paths], cwd=base, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)
    staged = subprocess.run(["git", "diff", "--cached", "--", *paths], cwd=base, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    summary = (diff.stdout + "\n" + staged.stdout)[:18000]
    if not summary.strip():
        summary = "所选文件为新增文件；文件名：" + ", ".join(paths)
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server
        model_mgr = _atlas_server.model_mgr
    if model_mgr is None or model_mgr.model_router is None:
        raise HTTPException(status_code=503, detail="没有可用模型，无法生成提交说明；可手动填写后重试。")
    try:
        route = await model_mgr.model_router.resolve(model_mgr.current_model, "prompt_enhance")
        result = await model_mgr.model_router.complete(route, messages=[
            {"role": "system", "content": "根据 git diff 生成简洁的提交说明、PR 标题和 PR 描述。返回 JSON 对象，字段为 message、title、body。仅总结 diff 可证实的内容，不要添加事实。"},
            {"role": "user", "content": summary},
        ], max_tokens=1200, temperature=0.2, timeout=40)
        text = str(getattr(result, "text", "") or "").strip()
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
        return {key: str(data.get(key, "")) for key in ("message", "title", "body")}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型生成失败：{exc}；可手动填写后重试。") from exc


@router.get("/api/git/pr/checks/{check_name}/log")
async def git_pr_check_log(
    services: Annotated[AppServices, Depends(get_app_services)],
    check_name: str, root: str,
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(root)
    checks = _gh_json(base, "pr", "checks", "--json", "name,state,link")
    match = next((item for item in checks if item.get("name") == check_name), None) \
        if isinstance(checks, list) else None
    if not match or str(match.get("state", "")).upper() not in {"FAILURE", "CANCELLED", "ERROR"}:
        raise HTTPException(status_code=404, detail="failed check not found")
    result = subprocess.run(["gh", "run", "view", str(match["link"]), "--log-failed"],
                            cwd=base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip())
    raw = result.stdout.encode("utf-8")[-65536:].decode("utf-8", errors="replace")
    return {"name": check_name, "log": raw}


def _git_workspace(root: str) -> Path:
    base, _ = _server()._workspace_path(root)
    result = subprocess.run(["git", "-C", str(base), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    if result.returncode:
        raise HTTPException(status_code=400, detail="workspace is not a git repository")
    return base


def _git_run(base: Path, *args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(["git", "-C", str(base), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=f"Unable to run git: {exc}") from exc
    if result.returncode:
        raise HTTPException(status_code=409, detail=result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result.stdout.strip()


def _git_status(base: Path) -> list[dict[str, str]]:
    raw = _git_run(base, "status", "--porcelain=v1", "--untracked-files=all")
    items = []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        items.append({"path": path, "code": code})
    return items


@router.get("/api/git/workspace")
async def get_git_workspace(services: Annotated[AppServices, Depends(get_app_services)], root: str) -> dict[str, Any]:
    base = _git_workspace(root)
    return {"current": _git_run(base, "branch", "--show-current"),
            "branches": _git_run(base, "branch", "--list", "--format=%(refname:short)").splitlines(),
            "status": _git_status(base)}


@router.post("/api/git/branch")
async def update_git_branch(services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any]) -> dict[str, Any]:
    root = str(req.get("root", ""))
    base = _git_workspace(root)
    name = req.get("name")
    create = req.get("create") is True
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=422, detail="branch name is required")
    name = name.strip()
    _git_run(base, "check-ref-format", "--branch", name)
    _git_run(base, "switch", *( ["-c", name] if create else [name] ), timeout=60)
    conversation_id = req.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id:
        memory = _service("memory", services)
        if memory is not None:
            conversation = await memory.get_conversation(conversation_id)
            workspace, _ = _server()._workspace_path(root)
            if conversation and conversation.get("worktree_path"):
                conversation_root, _ = _server()._workspace_path(str(conversation["worktree_path"]))
                if os.path.normcase(str(workspace.resolve())) == os.path.normcase(str(conversation_root.resolve())):
                    await memory.update_conversation(conversation_id, worktree_branch=name)
    return {"current": _git_run(base, "branch", "--show-current"),
            "branches": _git_run(base, "branch", "--list", "--format=%(refname:short)").splitlines(),
            "status": _git_status(base)}


@router.post("/api/git/commit")
async def commit_git_changes(services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any]) -> dict[str, Any]:
    base = _git_workspace(str(req.get("root", "")))
    message = req.get("message")
    paths = req.get("paths")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=422, detail="commit message is required")
    if not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths):
        raise HTTPException(status_code=422, detail="select at least one changed file")
    selected = list(dict.fromkeys(paths))
    available = {item["path"] for item in _git_status(base)}
    if not set(selected).issubset(available):
        raise HTTPException(status_code=409, detail="selected files changed; refresh Git status and try again")
    _git_run(base, "add", "--", *selected, timeout=60)
    _git_run(base, "commit", "-m", message.strip(), timeout=120)
    return {"commit": _git_run(base, "rev-parse", "--short", "HEAD"), "status": _git_status(base)}


@router.post("/api/git/push")
async def push_git_branch(services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any]) -> dict[str, Any]:
    base = _git_workspace(str(req.get("root", "")))
    branch = _git_run(base, "branch", "--show-current")
    if not branch:
        raise HTTPException(status_code=409, detail="cannot push a detached HEAD")
    _git_run(base, "push", "-u", "origin", "HEAD", timeout=120)
    return {"pushed": branch, "status": _git_status(base)}


@router.get("/api/git/history")
async def get_git_history(
    services: Annotated[AppServices, Depends(get_app_services)], root: str, limit: int = Query(default=80, ge=1, le=200),
) -> dict[str, Any]:
    base = _git_workspace(root)
    graph = _git_run(base, "log", "--graph", "--decorate", "--all", "--date-order", "--oneline", f"-n{limit}")
    formatted = _git_run(base, "log", "--all", "--date-order", "--format=%H%x1f%P%x1f%s%x1f%an%x1f%ad", "--date=short", f"-n{limit}")
    commits = []
    for line in formatted.splitlines():
        fields = line.split("\x1f", 4)
        if len(fields) == 5:
            commits.append({"hash": fields[0], "parents": fields[1].split(), "subject": fields[2], "author": fields[3], "date": fields[4]})
    return {"graph": graph.splitlines(), "commits": commits}


def _pr_timeline(base: Path) -> list[dict[str, str]]:
    data = _gh_json(base, "pr", "view", "--json", "number")
    repository = _gh_json(base, "repo", "view", "--json", "nameWithOwner")
    number = data.get("number")
    name = repository.get("nameWithOwner")
    if not number or not isinstance(name, str) or "/" not in name:
        raise HTTPException(status_code=502, detail="Unable to identify the current pull request repository")
    raw_items = _gh_json(base, "api", "--paginate", "--slurp", f"repos/{name}/issues/{number}/timeline")
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=502, detail="GitHub returned an invalid pull request timeline")
    if raw_items and all(isinstance(page, list) for page in raw_items):
        raw_items = [event for page in raw_items for event in page]
    items: list[dict[str, str]] = []
    for event in raw_items:
        if not isinstance(event, dict):
            continue
        actor = event.get("actor") or event.get("user") or {}
        commit = event.get("commit") or {}
        commit_author = commit.get("author") or {}
        body = event.get("body") or commit.get("message") or ""
        if not body:
            event_name = str(event.get("event", "activity")).replace("_", " ")
            label = event.get("label") or {}
            body = f"{event_name}: {label.get('name')}" if label else event_name
        timestamp = event.get("created_at") or event.get("submitted_at") or commit_author.get("date") or ""
        url = event.get("html_url") or event.get("url") or ""
        item_id = event.get("id") or event.get("node_id") or event.get("commit_id") or url or f"{timestamp}-{len(items)}"
        items.append({"id": str(item_id), "kind": str(event.get("event") or event.get("state") or "activity"),
                      "author": str(actor.get("login") or commit_author.get("name") or "GitHub"),
                      "body": str(body), "created_at": str(timestamp), "url": str(url)})
    return sorted(items, key=lambda item: item["created_at"])


@router.get("/api/git/pr/timeline")
async def get_git_pr_timeline(services: Annotated[AppServices, Depends(get_app_services)], root: str) -> dict[str, Any]:
    return {"items": _pr_timeline(_git_workspace(root))}


@router.post("/api/git/pr/comment")
async def comment_git_pr(services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any]) -> dict[str, Any]:
    base = _git_workspace(str(req.get("root", "")))
    body = req.get("body")
    if not isinstance(body, str) or not body.strip():
        raise HTTPException(status_code=422, detail="comment body is required")
    try:
        result = subprocess.run(["gh", "pr", "comment", "--body", body.strip()], cwd=base,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail=f"Unable to run gh: {exc}") from exc
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip() or "gh pr comment failed")
    return {"ok": True, "items": _pr_timeline(base)}


@router.get("/api/ssh/hosts")
async def ssh_hosts(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return {"hosts": ssh_workspaces.hosts()}


@router.post("/api/ssh/test")
async def ssh_test(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    host = str(req.get("host", "")).strip()
    if not host or not any(item["alias"] == host for item in ssh_workspaces.hosts()):
        raise HTTPException(status_code=400, detail="unknown SSH host alias")
    return await ssh_workspaces.test(host)


@router.get("/api/conversations/{conversation_id}/worktree")
async def conversation_worktree(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    memory = _service("memory", services)
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        return _server()._worktrees().status(Path(conv["workspace"]), Path(conv["worktree_path"]),
                                   conv["worktree_branch"], conv["base_branch"])
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/conversations/{conversation_id}/worktree/merge")
async def merge_conversation_worktree(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any],
) -> dict[str, str]:
    memory = _service("memory", services)
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        _server()._worktrees().merge(Path(conv["workspace"]), Path(conv["worktree_path"]),
                           conv["worktree_branch"], conv["base_branch"],
                           str(req.get("strategy", "merge")), req.get("message"))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail={"conflicts": str(exc).splitlines()}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "merged"}


@router.post("/api/conversations/{conversation_id}/worktree/sync")
async def sync_conversation_worktree(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    """Fetch and integrate the recorded base branch into this conversation worktree."""
    import subprocess

    memory = _service("memory", services)
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    root = Path(str(conv["worktree_path"])).resolve()
    strategy = str(req.get("strategy", "merge"))
    if strategy not in {"merge", "rebase"}:
        raise HTTPException(status_code=400, detail="strategy must be merge or rebase")
    branch = str(conv.get("base_branch") or "")
    if not branch:
        raise HTTPException(status_code=409, detail="This worktree has no recorded base branch")

    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120, check=False)
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
        return result

    try:
        status = git("status", "--porcelain").stdout
        dirty = bool(status.strip())
        if dirty:
            raise HTTPException(status_code=409, detail={"message": "Worktree has uncommitted changes; commit or stash them before syncing.", "dirty": True})
        git("fetch", "--all", "--prune")
        remote = git("config", "--get", "branch." + branch + ".remote", check=False).stdout.strip()
        if remote:
            target = f"{remote}/{branch}"
        else:
            target = branch
        if git("rev-parse", "--verify", target, check=False).returncode:
            raise HTTPException(status_code=409, detail=f"Fetched base ref was not found: {target}")
        result = git(strategy, target, check=False)
        if result.returncode:
            conflicts = git("diff", "--name-only", "--diff-filter=U", check=False).stdout.splitlines()
            raise HTTPException(status_code=409, detail={"message": (result.stderr or result.stdout).strip(),
                                                         "conflicts": conflicts, "operation": strategy})
        return {"status": "synced", "strategy": strategy, "base": target,
                "commit": git("rev-parse", "--short", "HEAD").stdout.strip()}
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Git sync timed out") from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/conversations/{conversation_id}/worktree/sync/{action}")
async def resolve_worktree_sync(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, action: str,
) -> dict[str, Any]:
    """Continue or abort an in-progress merge/rebase after conflict resolution."""
    import subprocess

    if action not in {"continue", "abort"}:
        raise HTTPException(status_code=404, detail="Unknown sync action")
    memory = _service("memory", services)
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    args = ["git", "merge", "--continue"] if action == "continue" else ["git", "rebase", "--abort"]
    # Continue supports either merge or rebase state; Git will report when none is active.
    if action == "continue":
        probe = subprocess.run(["git", "rev-parse", "--git-path", "rebase-merge"], cwd=conv["worktree_path"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        rebase_dir = Path(conv["worktree_path"]) / probe.stdout.strip()
        if rebase_dir.is_dir():
            args = ["git", "rebase", "--continue"]
    result = subprocess.run(args, cwd=conv["worktree_path"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120, check=False)
    if result.returncode:
        conflicts = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=conv["worktree_path"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", check=False).stdout.splitlines()
        raise HTTPException(status_code=409, detail={"message": (result.stderr or result.stdout).strip(), "conflicts": conflicts})
    return {"status": "continued" if action == "continue" else "aborted"}


@router.delete("/api/conversations/{conversation_id}/worktree")
async def delete_conversation_worktree(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, keep_branch: bool = False, force: bool = False,
) -> dict[str, str]:
    memory = _service("memory", services)
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv or not conv.get("worktree_path"):
        raise HTTPException(status_code=404, detail="Conversation worktree not found")
    try:
        _server()._worktrees().remove(Path(conv["workspace"]), Path(conv["worktree_path"]),
                            conv["worktree_branch"], force=force, keep_branch=keep_branch)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # C6:worktree 删除成功后，顺手关掉服务于该目录的 LSP 进程（尽力而为）。
    try:
        from atlas.lsp import release_workspace

        release_workspace(str(conv["worktree_path"]))
    except (ImportError, OSError, RuntimeError) as exc:
        log.debug("lsp.workspace_release_failed", path=str(conv["worktree_path"]), error=str(exc))
    await memory.update_conversation(conversation_id, worktree_path="", worktree_branch="", base_branch="")
    return {"status": "removed"}


@router.get("/api/workspace/rules")
async def workspace_rules(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    return await collect_workspace_rules(root)


async def collect_workspace_rules(root: str) -> dict[str, Any]:
    if root.startswith("ssh://"):
        host, base = ssh_workspaces.parse_workspace(root)
        files = []
        for name in _server()._RULE_FILES:
            path = str(PurePosixPath(base) / name)
            try:
                raw = await ssh_workspaces.read_bytes(host, path)
            except Exception:  # noqa: BLE001 — async SSH/SFTP transports use provider-specific errors
                log.exception("workspace.rules_ssh_read_failed", host=host, path=path)
                continue
            files.append({"path": path, "bytes": len(raw),
                          "content": raw[:65536].decode("utf-8", errors="replace"),
                          "truncated": len(raw) > 65536})
        return {"root": root, "files": files}
    base, _ = _server()._workspace_path(root)
    candidates = [base / name for name in _server()._RULE_FILES]
    for directory, pattern in (
        (".atlas/agents", "*.md"), (".claude/agents", "*.md"),
        (".opencode/agent", "*.md"), (".opencode/agents", "*.md"),
        (".codex/agents", "*.toml"), (".github/agents", "*.agent.md"),
    ):
        candidates.extend(sorted((base / directory).glob(pattern))[:20])
    candidates = list(dict.fromkeys(candidates))
    user_rules = Path.home() / ".atlas" / "AGENTS.md"
    candidates.append(user_rules)
    files = []
    for item in candidates:
        if not item.is_file():
            continue
        raw = await asyncio.to_thread(item.read_bytes)
        content = raw[:65536].decode("utf-8", errors="replace")
        if item.name == "NOTES.md" and item.parent.name == ".atlas":
            content = _server()._bounded_project_notes(content)
        files.append({"path": str(item.resolve()), "bytes": len(raw),
                      "content": content,
                      "truncated": len(raw) > 65536})
    return {"root": str(base), "files": files}


@router.get("/api/workspace/notes")
async def get_workspace_notes(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(root)
    root_key = str(base.resolve())
    if not _server()._workspace_trust().get(root_key, False):
        raise HTTPException(status_code=403, detail="Workspace is not trusted")
    path = base / ".atlas" / "NOTES.md"
    if not path.is_file():
        return {"root": root_key, "content": ""}
    return {"root": root_key, "content": (await asyncio.to_thread(path.read_text, encoding="utf-8"))[:65536]}


@router.put("/api/workspace/notes")
async def put_workspace_notes(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: dict[str, Any],
) -> dict[str, Any]:
    root = str(req.get("root", ""))
    content = req.get("content")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 65536:
        raise HTTPException(status_code=422, detail="content must be a string up to 64 KiB")
    base, _ = _server()._workspace_path(root)
    root_key = str(base.resolve())
    if not _server()._workspace_trust().get(root_key, False):
        raise HTTPException(status_code=403, detail="Workspace is not trusted")
    path = base / ".atlas" / "NOTES.md"
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")
    return {"root": root_key, "bytes": len(content.encode("utf-8"))}


@router.get("/api/checkpoints")
async def list_checkpoints(
    services: Annotated[AppServices, Depends(get_app_services)],
    run_id: str | None = None, workspace: str | None = None,
) -> list[dict[str, Any]]:
    orchestrator = _service("orchestrator", services)
    orchestrator = services.orchestrator
    if orchestrator is None:
        from atlas import server as _atlas_server

        orchestrator = _atlas_server.orchestrator
    assert orchestrator is not None
    if workspace and workspace.startswith("ssh://"):
        return await ssh_workspaces.list_checkpoints(workspace, run_id=run_id)
    items = orchestrator.checkpoints.list_checkpoints(workspace, run_id=run_id)
    return [{key: item[key] for key in
             ("id", "workspace", "created_at", "run_id", "files")} for item in items]


_RUN_HUNK_REVIEW_MAX_BYTES = 256 * 1024


def _run_hunk_review_path(run_id: str) -> Path:
    data_root = Path(DATA_ROOT).expanduser().resolve()
    data_directory = data_root / "data"
    directory = data_directory / "run-hunk-reviews"
    if data_directory.is_symlink() or directory.is_symlink():
        raise HTTPException(status_code=409, detail="Hunk review storage directory cannot be a symlink")
    try:
        directory = directory.resolve()
        directory.relative_to(data_root)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Hunk review storage escapes ATLAS_DATA_DIR") from exc
    return directory / (hashlib.sha256(run_id.encode("utf-8")).hexdigest() + ".json")


def _read_run_hunk_reviews(run_id: str) -> list[dict[str, str]]:
    path = _run_hunk_review_path(run_id)
    if path.is_symlink():
        raise HTTPException(status_code=409, detail="Hunk review storage file cannot be a symlink")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read hunk review state") from exc
    if len(raw) > _RUN_HUNK_REVIEW_MAX_BYTES:
        raise HTTPException(status_code=500, detail="Stored hunk review state exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=500, detail="Stored hunk review state is invalid") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id or not isinstance(payload.get("reviews"), list):
        raise HTTPException(status_code=500, detail="Stored hunk review identity mismatch")
    reviews = payload["reviews"]
    if any(not isinstance(item, dict) for item in reviews):
        raise HTTPException(status_code=500, detail="Stored hunk review entry is invalid")
    return reviews


def _write_run_hunk_review(run_id: str, hunk_id: str, diff_hash: str, action: str) -> None:
    # Reviews are only valid for the exact diff generation. A rejected hunk
    # changes that diff, so older decisions cannot be safely applied afterward.
    reviews = [item for item in _read_run_hunk_reviews(run_id) if item.get("diff_hash") == diff_hash]
    record = {"hunk_id": hunk_id, "diff_hash": diff_hash, "status": "accepted" if action == "accept" else "rejected"}
    reviews = [item for item in reviews if not (
        item.get("hunk_id") == hunk_id and item.get("diff_hash") == diff_hash
    )]
    reviews.append(record)
    raw = json.dumps({"run_id": run_id, "reviews": reviews}, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > _RUN_HUNK_REVIEW_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Hunk review history exceeds 256 KiB")
    path = _run_hunk_review_path(run_id)
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{path.stem}.", suffix=".tmp",
                                         dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        try:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Could not save hunk review state") from exc


def _change_hunks(run_id: str, item: dict[str, Any], review_lookup: dict[tuple[str, str], str]) -> tuple[str, list[dict[str, Any]]]:
    diff = str(item.get("diff", ""))
    diff_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    root = str(item.get("root") or item.get("workspace") or "")
    relative_path = str(item.get("relative_path") or item.get("path") or "")
    hunks: list[dict[str, Any]] = []
    matches = list(re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*$", diff, re.MULTILINE))
    for index, match in enumerate(matches):
        old_start, old_count = int(match.group(1)), int(match.group(2) or 1)
        new_start, new_count = int(match.group(3)), int(match.group(4) or 1)
        hunk_id = hashlib.sha256(
            f"{run_id}\0{root}\0{relative_path}\0{diff_hash}\0{index}".encode("utf-8")
        ).hexdigest()[:32]
        hunks.append({
            "id": hunk_id,
            "old_start": old_start,
            "old_count": old_count,
            "new_start": new_start,
            "new_count": new_count,
            "status": review_lookup.get((hunk_id, diff_hash), "pending"),
            "reviewable": not bool(item.get("truncated")) and not root.startswith("ssh://"),
        })
    return diff_hash, hunks


def _parse_hunk_body(diff: str, hunk_index: int) -> tuple[int, int, int, list[str], list[str]]:
    lines = diff.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if line.startswith("@@ ")]
    if hunk_index < 0 or hunk_index >= len(headers):
        raise HTTPException(status_code=409, detail="Diff hunk is no longer available")
    start = headers[hunk_index]
    match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[start])
    if not match:
        raise HTTPException(status_code=409, detail="Diff hunk header is invalid")
    old_start, old_count = int(match.group(1)), int(match.group(2) or 1)
    new_start, new_count = int(match.group(3)), int(match.group(4) or 1)
    old_lines: list[str] = []
    new_lines: list[str] = []
    for line in lines[start + 1:headers[hunk_index + 1] if hunk_index + 1 < len(headers) else len(lines)]:
        if line.startswith("\\ No newline at end of file"):
            raise HTTPException(status_code=409, detail="Cannot safely reverse a hunk without a final newline")
        if not line or line[0] not in " +-":
            continue
        content = line[1:]
        if line[0] in " -":
            old_lines.append(content)
        if line[0] in " +":
            new_lines.append(content)
    if len(old_lines) != old_count or len(new_lines) != new_count:
        raise HTTPException(status_code=409, detail="Diff hunk is incomplete or truncated")
    return old_start, new_start, new_count, old_lines, new_lines


def _reject_run_hunk(item: dict[str, Any], diff_hash: str, hunk_index: int,
                     orchestrator: Any, run_id: str) -> None:
    if item.get("truncated"):
        raise HTTPException(status_code=409, detail="Cannot reject a truncated diff")
    if item.get("root", "").startswith("ssh://"):
        raise HTTPException(status_code=409, detail="Hunk rejection is unavailable for remote workspaces")
    root = str(item.get("root") or item.get("workspace") or "")
    relative_path = str(item.get("relative_path") or item.get("path") or "")
    base, target = _server()._workspace_path(root, relative_path)
    candidate = base / relative_path
    if candidate.is_symlink() or (target.exists() and not target.is_file()):
        raise HTTPException(status_code=409, detail="Cannot safely reject a hunk in this file")
    diff = str(item.get("diff", ""))
    if hashlib.sha256(diff.encode("utf-8")).hexdigest() != diff_hash:
        raise HTTPException(status_code=409, detail="Diff changed; reload the file before reviewing")
    _old_start, new_start, new_count, old_lines, new_lines = _parse_hunk_body(diff, hunk_index)
    try:
        before_bytes = target.read_bytes() if target.is_file() else b""
        current_text = before_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=409, detail="Only readable UTF-8 text files can be reviewed") from exc
    crlf_count = before_bytes.count(b"\r\n")
    lf_count = before_bytes.count(b"\n") - crlf_count
    cr_count = before_bytes.count(b"\r") - crlf_count
    newline = max(((crlf_count, "\r\n"), (lf_count, "\n"), (cr_count, "\r")), key=lambda item: item[0])[1]
    normalized_text = re.sub(r"\r\n|\r|\n", "\n", current_text)
    current_lines = normalized_text.splitlines(keepends=True)
    offset = max(0, new_start - 1) if new_count else new_start
    if current_lines[offset:offset + len(new_lines)] != new_lines:
        raise HTTPException(status_code=409, detail="Hunk no longer matches the current file; reload before reviewing")
    updated_lines = current_lines[:offset] + old_lines + current_lines[offset + len(new_lines):]
    updated_text = "".join(updated_lines)
    if newline != "\n":
        updated_text = updated_text.replace("\n", newline)
    updated = updated_text.encode("utf-8")
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Checkpoint service is unavailable")
    try:
        orchestrator.checkpoints.create_checkpoint(base, [relative_path], run_id=run_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Could not checkpoint the file before reversing this hunk") from exc
    try:
        current_bytes = target.read_bytes() if target.is_file() else b""
        if current_bytes != before_bytes:
            raise HTTPException(status_code=409, detail="File changed during review; reload before reviewing")
        if item.get("status") == "added" and not updated:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{target.name}.", suffix=".tmp",
                                             dir=target.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(updated)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
    except HTTPException:
        raise
    except OSError as exc:
        try:
            if "temporary_path" in locals() and temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Could not reverse this hunk") from exc


async def _collect_run_changes(run_id: str) -> dict[str, Any]:
    run = _server().runtime_mgr.runs.get(run_id)
    if not run:
        return _server()._run_changes(run_id)
    roots = [*([run.workspace] if run.workspace else []), *run.extra_roots]
    combined = []
    for index, root in enumerate(dict.fromkeys(roots)):
        if root.startswith("ssh://"):
            data = await ssh_workspaces.changes(root, run_id)
        else:
            data = _server()._run_changes(run_id, workspace=root)
        for item in data.get("files", []):
            entry = {**item, "root": root, "relative_path": item.get("path", "")}
            if index > 0:
                name = (PurePosixPath(root.split("?", 1)[0]).name
                        if root.startswith("ssh://") else Path(root).name)
                entry["path"] = f"{name or f'目录{index}'}/{item['path']}"
            combined.append(entry)
    return {"run_id": run_id, "files": combined}


@router.get("/api/runs/{run_id}/changes")
async def get_run_changes(
    services: Annotated[AppServices, Depends(get_app_services)],
    run_id: str,
) -> dict[str, Any]:
    result = await _collect_run_changes(run_id)
    stored = _read_run_hunk_reviews(run_id)
    review_lookup = {
        (item["hunk_id"], item["diff_hash"]): item["status"]
        for item in stored
        if item.get("status") in {"accepted", "rejected"}
        and isinstance(item.get("hunk_id"), str)
        and isinstance(item.get("diff_hash"), str)
    }
    for item in result.get("files", []):
        diff_hash, hunks = _change_hunks(run_id, item, review_lookup)
        item["relative_path"] = item.get("relative_path") or item.get("path", "")
        item["diff_hash"] = diff_hash
        item["hunks"] = hunks
    return result


@router.post("/api/runs/{run_id}/changes/hunks/review")
async def review_run_hunk(
    services: Annotated[AppServices, Depends(get_app_services)],
    run_id: str,
    request: Request,
) -> dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 16 * 1024:
            raise HTTPException(status_code=413, detail="Hunk review request exceeds 16 KiB")
        raw.extend(chunk)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object")
    workspace = payload.get("workspace")
    relative_path = payload.get("path")
    hunk_id = payload.get("hunk_id")
    action = payload.get("action")
    expected_diff_hash = payload.get("expected_diff_hash")
    if not all(isinstance(value, str) and value for value in
               (workspace, relative_path, hunk_id, expected_diff_hash)):
        raise HTTPException(status_code=400, detail="workspace, path, hunk_id, and expected_diff_hash are required")
    if action not in {"accept", "reject"}:
        raise HTTPException(status_code=400, detail="action must be accept or reject")
    result = await _collect_run_changes(run_id)
    target = next((item for item in result.get("files", [])
                   if str(item.get("root") or item.get("workspace") or "") == workspace
                   and str(item.get("relative_path") or item.get("path") or "") == relative_path), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Changed file was not found in this run")
    diff_hash, hunks = _change_hunks(run_id, target, {})
    if diff_hash != expected_diff_hash:
        raise HTTPException(status_code=409, detail="Diff changed; reload the file before reviewing")
    hunk_index = next((index for index, item in enumerate(hunks) if item["id"] == hunk_id), None)
    if hunk_index is None:
        raise HTTPException(status_code=404, detail="Diff hunk was not found")
    if not hunks[hunk_index]["reviewable"]:
        raise HTTPException(status_code=409, detail="This hunk cannot be reviewed")
    if action == "reject":
        _reject_run_hunk(target, diff_hash, hunk_index, _service("orchestrator", services), run_id)
    _write_run_hunk_review(run_id, hunk_id, diff_hash, action)
    return {"run_id": run_id, "workspace": workspace, "path": relative_path,
            "hunk_id": hunk_id, "status": "accepted" if action == "accept" else "rejected"}


@router.get("/api/runs/{run_id}/diagnostics")
async def get_run_diagnostics(
    services: Annotated[AppServices, Depends(get_app_services)],
    run_id: str,
) -> dict[str, Any]:
    """本次 run 改动文件的最新 LSP 诊断（fresh 全量，非 delta）。

    count 为 0 也返回——"没有新问题"是有意义的状态；单文件诊断失败按 0 计；
    SSH 工作目录不探测，直接返回空列表。
    """
    changes = _server()._run_changes(run_id)
    run = _server().runtime_mgr.runs.get(run_id)
    if run is not None and run.workspace and str(run.workspace).startswith("ssh://"):
        return {"run_id": run_id, "files": []}
    try:
        from atlas.lsp import diagnostics_for
    except ImportError as exc:
        log.warning("C6 诊断路由的 LSP 模块不可用", error=str(exc))
        return {"run_id": run_id, "files": []}
    files: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in changes["files"]:
        workspace = str(item.get("workspace", ""))
        relative = str(item.get("path", ""))
        key = (workspace, relative)
        if not relative or key in seen:
            continue
        seen.add(key)
        count = 0
        diagnostics: list[dict[str, Any]] = []
        for diag in diagnostics_for(str(Path(workspace) / relative)):
            count += 1
            diagnostics.append({
                "line": diag.line, "column": diag.column,
                "severity": diag.severity, "code": diag.code,
                "message": diag.message,
            })
        files.append({"path": relative, "count": count, "diagnostics": diagnostics})
    return {"run_id": run_id, "files": files}


@router.get("/api/lsp/status")
async def lsp_status(
    services: Annotated[AppServices, Depends(get_app_services)],
    workspace: str | None = None,
) -> dict[str, Any]:
    """逐个语言服务探测可用性；不可用的给出中文安装提示。

    只做二进制探测（与正式启用时的判定一致），不会启动任何语言服务进程。
    """
    from atlas.lsp.availability import missing_server_hint
    from atlas.lsp.servers import SERVERS as LSP_SERVERS, ServerContext, custom_servers

    root = workspace if (workspace and not workspace.startswith("ssh://")
                         and Path(workspace).is_dir()) else Path.cwd()
    servers_cfg = get_config().get("lsp.servers", {})
    servers_cfg = servers_cfg if isinstance(servers_cfg, dict) else {}
    overrides = {name: cfg["command"] for name, cfg in servers_cfg.items()
                 if isinstance(cfg, dict) and isinstance(cfg.get("command"), list) and cfg["command"]}
    disabled = {name for name, cfg in servers_cfg.items()
                if isinstance(cfg, dict) and cfg.get("disabled")}
    ctx = ServerContext(workspace_root=str(root), binary_overrides=overrides)
    servers: list[dict[str, Any]] = []
    for srv in [*custom_servers(servers_cfg), *LSP_SERVERS]:
        if srv.server_id in disabled:
            servers.append({"id": srv.server_id, "languages": list(srv.extensions),
                            "available": False,
                            "hint": "该语言服务已在配置中停用（lsp.servers.<id>.disabled）。"})
            continue
        available = False
        hint = ""
        try:
            available = srv.build_spawn(str(root), ctx) is not None
        except (OSError, RuntimeError, ValueError):
            hint = "探测该语言服务时出错，请检查安装与配置。"
        if not available and not hint:
            hint = missing_server_hint(srv.server_id)
        servers.append({"id": srv.server_id, "languages": list(srv.extensions),
                        "available": available, "hint": hint})
    return {"servers": servers}


@router.get("/api/lsp/diagnostics")
async def lsp_workspace_diagnostics(workspace: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Fresh diagnostics for files already opened by language servers in this workspace."""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Workspace directory not found")
    from atlas.lsp import get_service
    service = get_service()
    if service is None:
        return {"workspace": str(root), "available": False, "count": 0, "files": []}
    files: list[dict[str, Any]] = []
    for client in list(getattr(service, "_clients", {}).values()):
        for path in list(getattr(client, "_docs", {})):
            try:
                relative = Path(path).resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            diagnostics = client.diagnostics_for(path, fresh_only=True)
            if diagnostics:
                files.append({"path": relative, "count": len(diagnostics), "diagnostics": [
                    {"line": d.get("range", {}).get("start", {}).get("line", 0) + 1,
                     "column": d.get("range", {}).get("start", {}).get("character", 0) + 1,
                     "severity": {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(d.get("severity", 3), "information"), "code": d.get("code"),
                     "message": d.get("message", "")}
                    for d in diagnostics[:100]
                ]})
    files.sort(key=lambda item: item["path"].casefold())
    return {"workspace": str(root), "available": True,
            "count": sum(item["count"] for item in files), "files": files}
