"""Workspace files, git, ssh worktrees, rules, checkpoints and run changes surface (``/api/workspace, /api/git, /api/ssh, /api/checkpoints, /api/runs, /api/lsp``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import base64
import json
import structlog
import fnmatch
import mimetypes
import re
import shlex
import shutil
import subprocess
import time
import uuid
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from atlas.config import get_config
from atlas.office import MAX_PREVIEW_BYTES, render_office
from atlas.ssh import ssh_workspaces

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()

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
            subprocess.run, ["git", "-C", str(base), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if len(line) > 3:
                code = line[:2].strip()
                git_status[line[3:].strip().replace("\\", "/")] = (
                    "?" if code == "??" else "A" if "A" in code else
                    "D" if "D" in code else "M"
                )
    except (OSError, subprocess.SubprocessError):
        pass
    entries = []
    for item in sorted(directory.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.casefold())):
        if item.name in _server()._WORKSPACE_IGNORES:
            continue
        rel = item.relative_to(base).as_posix()
        entries.append({"name": item.name, "path": rel,
                        "type": "dir" if item.is_dir() else "file",
                        "size": None if item.is_dir() else item.stat().st_size,
                        "git": git_status.get(rel)})
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
            "truncated": len(raw) > 512 * 1024, "binary": binary}


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
            capture_output=True, text=True, timeout=10, check=False,
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
            capture_output=True, text=True, timeout=10, check=False,
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
            ["git", "-C", str(base), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=15,
        )
        git_listing_ok = listing.returncode == 0
        paths = listing.stdout.splitlines() if listing.returncode == 0 else []
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
                             text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, timeout=30)
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
            "head": data.get("headRefName"), "checks": checks}


@router.get("/api/git/pr")
async def get_git_pr(
    services: Annotated[AppServices, Depends(get_app_services)],
    root: str,
) -> dict[str, Any]:
    base, _ = _server()._workspace_path(root)
    try:
        data = _gh_json(base, "pr", "view", "--json",
                        "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup")
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
                             text=True, timeout=15)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="GitHub CLI (gh) is unavailable") from exc
    if auth.returncode:
        raise HTTPException(status_code=503, detail="GitHub CLI is not authenticated")
    pushed = subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=base,
                            capture_output=True, text=True, timeout=120)
    if pushed.returncode:
        raise HTTPException(status_code=502, detail=pushed.stderr.strip())
    command = ["gh", "pr", "create", "--title", title, "--body", body]
    if req.get("base"):
        command.extend(["--base", str(req["base"])])
    if req.get("draft") is True:
        command.append("--draft")
    created = subprocess.run(command, cwd=base, capture_output=True, text=True, timeout=60)
    if created.returncode:
        raise HTTPException(status_code=502, detail=created.stderr.strip())
    result = _gh_json(base, "pr", "view", "--json",
                      "number,title,url,state,isDraft,baseRefName,headRefName,statusCheckRollup")
    return {"pr": _pr_shape(result)}


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
                            cwd=base, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise HTTPException(status_code=502, detail=result.stderr.strip())
    raw = result.stdout.encode("utf-8")[-65536:].decode("utf-8", errors="replace")
    return {"name": check_name, "log": raw}


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
            except Exception as exc:  # noqa: BLE001 — async SSH/SFTP transports use provider-specific errors
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


@router.get("/api/runs/{run_id}/changes")
async def get_run_changes(
    services: Annotated[AppServices, Depends(get_app_services)],
    run_id: str,
) -> dict[str, Any]:
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
            entry = {**item, "root": root}
            if index > 0:
                name = (PurePosixPath(root.split("?", 1)[0]).name
                        if root.startswith("ssh://") else Path(root).name)
                entry["path"] = f"{name or f'目录{index}'}/{item['path']}"
            combined.append(entry)
    return {"run_id": run_id, "files": combined}


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
