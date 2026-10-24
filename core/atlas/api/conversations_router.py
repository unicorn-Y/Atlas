"""Conversation history, branching, rewind and compaction surface (``/api/conversations``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.ssh import ssh_workspaces

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


class ConversationUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    workspace: str | None = None
    permission_mode: str | None = None
    allowed_paths: list[str] | None = None
    executor: str | None = None
    sandbox: dict[str, Any] | None = None
    extra_roots: list[str] | None = None


class ConversationUiMetadataRequest(BaseModel):
    metadata: dict[str, Any]


@router.get("/api/ui/conversation-metadata")
async def get_conversation_ui_metadata() -> dict[str, Any]:
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "conversation-ui-metadata.json"
    try:
        value = await asyncio.to_thread(path.read_text, encoding="utf-8")
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"metadata": {}}
    except FileNotFoundError:
        return {"metadata": {}}
    except (OSError, json.JSONDecodeError):
        return {"metadata": {}}


@router.put("/api/ui/conversation-metadata")
async def put_conversation_ui_metadata(request: ConversationUiMetadataRequest) -> dict[str, bool]:
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "conversation-ui-metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    payload = json.dumps({"metadata": request.metadata}, ensure_ascii=False, indent=2)
    await asyncio.to_thread(temporary.write_text, payload, encoding="utf-8")
    await asyncio.to_thread(temporary.replace, path)
    return {"saved": True}


class ConversationCreateRequest(BaseModel):
    title: str = "New Conversation"


class ConversationGoalCommandRequest(BaseModel):
    command: str


@router.get("/api/conversations")
async def list_conversations(
    services: Annotated[AppServices, Depends(get_app_services)],
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=500),
    archived: bool | None = Query(None),
    pinned: bool | None = Query(None),
    workspace: str | None = Query(None, min_length=1),
    q: str | None = Query(None, max_length=200),
) -> list[dict[str, Any]]:
    """Return conversation summaries, optionally filtered and paged.

    The default is intentionally unbounded so the desktop sidebar does not
    silently omit conversations after the first 50. ``q`` matches the summary
    fields returned here (ID, title, workspace, and latest-message preview);
    full-transcript search remains available from ``/api/search``.
    """
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    conversations = await memory.list_conversations(limit=None)
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import list_session_previews

    previews = await asyncio.to_thread(list_session_previews, DATA_ROOT / "engine")
    summaries = [
        {**item, "preview": previews.get(str(item["id"]), "")}
        for item in conversations
    ]
    if archived is not None:
        summaries = [item for item in summaries if item.get("archived") is archived]
    if pinned is not None:
        summaries = [item for item in summaries if item.get("pinned") is pinned]
    if workspace is not None:
        summaries = [item for item in summaries if item.get("workspace") == workspace]
    needle = (q or "").strip().casefold()
    if needle:
        summaries = [
            item for item in summaries
            if any(needle in str(item.get(field) or "").casefold()
                   for field in ("id", "title", "workspace", "preview"))
        ]
    summaries = summaries[offset:]
    if limit is not None:
        summaries = summaries[:limit]
    return summaries


@router.post("/api/conversations")
async def create_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ConversationCreateRequest,
) -> dict[str, Any]:
    """Create and return a conversation summary."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    conversation_id = await memory.create_conversation(req.title.strip() or "New Conversation")
    conversation = await memory.get_conversation(conversation_id)
    assert conversation is not None
    return conversation


@router.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
    limit: int = Query(100, ge=1, le=1000),
    before_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Return messages for a conversation: newest ``limit`` in ascending order.

    ``before_id`` pages one window further back in history (same shape, ascending).
    """
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_messages

    return await asyncio.to_thread(
        read_session_messages, DATA_ROOT / "engine", conversation_id,
        limit=limit, before_id=before_id,
    )


@router.get("/api/conversations/{conversation_id}/search")
async def search_conversation_messages(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """Search the complete transcript for one conversation, including compacted history."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if not await memory.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages

    needle = q.strip().casefold()
    if not needle:
        return {"conversation_id": conversation_id, "results": []}
    messages = await asyncio.to_thread(
        read_session_all_messages, DATA_ROOT / "engine", conversation_id,
    )
    results = []
    for message in reversed(messages):
        raw = message.get("content")
        content = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
        index = content.casefold().find(needle)
        if index < 0:
            continue
        start = max(0, index - 100)
        end = min(len(content), index + len(needle) + 180)
        results.append({
            "id": str(message.get("id") or ""),
            "role": str(message.get("role") or "unknown"),
            "created_at": str(message.get("created_at") or ""),
            "snippet": ("…" if start else "") + content[start:end] + ("…" if end < len(content) else ""),
        })
        if len(results) >= limit:
            break
    return {"conversation_id": conversation_id, "results": results}


@router.get("/api/conversations/{conversation_id}/stats")
async def get_conversation_stats(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    """Summarize transcript turns and recorded usage without inventing missing prices."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if not await memory.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages

    messages = await asyncio.to_thread(
        read_session_all_messages, DATA_ROOT / "engine", conversation_id,
    )
    user_turns = sum(1 for item in messages if item.get("role") == "user")
    timestamps = [str(item.get("created_at")) for item in messages if item.get("created_at")]
    parsed_timestamps = []
    for value in timestamps:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            parsed_timestamps.append(parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed)
        except ValueError:
            continue
    usage_ledger = _service("usage_ledger", services)
    usage = None
    if usage_ledger is not None:
        report = await usage_ledger.query(start=None, end=None, group_by="conversation")
        usage = next((row for row in report.get("rows", []) if row.get("key") == conversation_id), None)
    return {
        "conversation_id": conversation_id,
        "message_count": len(messages),
        "user_turns": user_turns,
        "runs": usage.get("runs", 0) if usage else 0,
        "input_tokens": usage.get("input_tokens", 0) if usage else 0,
        "output_tokens": usage.get("output_tokens", 0) if usage else 0,
        "cached_input_tokens": usage.get("cached_input_tokens", 0) if usage else 0,
        "cache_hit_rate": usage.get("cache_hit_rate") if usage else None,
        "est_cost": usage.get("est_cost") if usage else None,
        "started_at": min(parsed_timestamps).isoformat() if parsed_timestamps else None,
        "last_activity_at": max(parsed_timestamps).isoformat() if parsed_timestamps else None,
        "duration_seconds": max(0, int((max(parsed_timestamps) - min(parsed_timestamps)).total_seconds())) if parsed_timestamps else None,
    }


@router.get("/api/conversations/{conversation_id}/log-location")
async def get_conversation_log_location(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, str]:
    """Return the canonical shared transcript database path for this session."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if not await memory.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    from atlas.config import DATA_ROOT

    return {
        "conversation_id": conversation_id,
        "path": str(DATA_ROOT / "engine" / "state.db"),
        "storage": "shared_session_database",
    }


@router.get("/api/conversations/{conversation_id}/branches")
async def get_conversation_branches(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> list[dict[str, Any]]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    from atlas.config import DATA_ROOT
    from atlas.engine.branch_summaries import branch_summaries
    from atlas.engine.session_sync import list_branch_tree

    tree = await asyncio.to_thread(list_branch_tree, DATA_ROOT / "engine", conversation_id)
    # S2: attach per-branch summaries (cached instantly, missing ones generated
    # fire-and-forget so switching never blocks on a model call).
    summaries = {}
    with suppress(Exception):  # Branch summaries are advisory and must not break the tree.
        summaries = await branch_summaries(memory, conversation_id)
    if summaries:
        merged = []
        for node in tree:
            if isinstance(node, dict):
                summary = summaries.get(str(node.get("id") or ""))
                if summary:
                    node = {**node, "summary": summary}
            merged.append(node)
        return merged
    return tree


@router.get("/api/conversations/{conversation_id}/goal")
async def get_conversation_goal(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_command
    return await asyncio.to_thread(goal_command, DATA_ROOT / "engine", conversation_id, "status")


@router.post("/api/conversations/{conversation_id}/goal")
async def run_conversation_goal_command(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, request: ConversationGoalCommandRequest,
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import goal_command
    result = await asyncio.to_thread(goal_command, DATA_ROOT / "engine", conversation_id, request.command)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["output"])
    return result


@router.post("/api/conversations/{conversation_id}/branch-summary")
async def summarize_conversation_branch(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    orchestrator = _service("orchestrator", services)
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    child = await memory.get_conversation(conversation_id)
    if not child or not child.get("parent_conversation_id") or not child.get("fork_message_id"):
        return {"created": False, "reason": "not_a_branch"}
    parent_id, fork_id = str(child["parent_conversation_id"]), str(child["fork_message_id"])
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages

    messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)
    fork_at = next((index for index, item in enumerate(messages) if item["id"] == fork_id), None)
    if fork_at is None or fork_at >= len(messages) - 1:
        return {"created": False, "reason": "no_branch_progress"}
    delta = messages[fork_at + 1:]
    transcript = "\n".join(f"{item['role']}: {str(item['content'])[:1200]}" for item in delta[-30:])
    if orchestrator:
        summary = await orchestrator.context_maintenance.compact({
            "goal": "Summarize this branch's progress and decisions at its fork point.",
            "session_summary": transcript,
        })
        content = str(summary.get("session_summary") or "").strip()
    else:
        content = "\n".join(f"{item['role']}: {str(item['content'])[:350]}" for item in delta[-8:]).strip()
    if not content:
        return {"created": False, "reason": "empty_summary"}
    content = "分支摘要：\n" + content[:2000]
    from atlas.engine.session_sync import append_branch_summary
    await asyncio.to_thread(append_branch_summary, DATA_ROOT / "engine", parent_id, conversation_id, fork_id, content)
    return {"created": True, "parent_conversation_id": parent_id, "fork_message_id": fork_id,
            "summary": content}


@router.put("/api/conversations/{conversation_id}")
async def update_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
    req: ConversationUpdateRequest,
) -> dict[str, str]:
    """Persist conversation title and runtime preferences."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    values = req.model_dump(exclude_unset=True)
    if values.get("permission_mode") not in {
        None, "full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only",
    }:
        raise HTTPException(status_code=400, detail="invalid permission_mode")
    paths = values.get("allowed_paths")
    if paths is not None and any(
        not isinstance(path, str) or not Path(path).is_absolute() for path in paths
    ):
        raise HTTPException(status_code=400, detail="allowed_paths must contain absolute paths")
    workspace = values.get("workspace")
    if workspace:
        try:
            if workspace.startswith("ssh://"):
                ssh_workspaces.parse_workspace(workspace)
            elif not Path(workspace).is_absolute():
                raise ValueError("workspace must be absolute")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    roots = values.get("extra_roots")
    if roots is not None:
        if len(roots) > 5:
            raise HTTPException(status_code=400, detail="最多可添加 5 个附加目录。")
        try:
            normalized_roots = []
            for root in roots:
                if not isinstance(root, str):
                    raise ValueError("附加目录无效。")
                if root.startswith("ssh://"):
                    ssh_workspaces.parse_workspace(root)
                    normalized_roots.append(root)
                elif Path(root).is_absolute():
                    normalized_roots.append(str(Path(root).expanduser().resolve()))
                else:
                    raise ValueError("附加目录必须是绝对路径或 SSH 地址。")
            values["extra_roots"] = normalized_roots
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "sandbox" in values and values["sandbox"] is not None:
        sandbox = values["sandbox"]
        if sandbox.get("type") != "docker" or not isinstance(
            sandbox.get("network", False), bool
        ):
            raise HTTPException(status_code=400, detail="invalid sandbox settings")
    ok = await memory.update_conversation(
        conversation_id,
        title=values.get("title"), pinned=values.get("pinned"),
        archived=values.get("archived"), workspace=values.get("workspace"),
        permission_mode=values.get("permission_mode"),
        allowed_paths=values.get("allowed_paths"), executor=values.get("executor"),
        sandbox=values.get("sandbox"), sandbox_set="sandbox" in values,
        extra_roots=values.get("extra_roots"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if values.get("title") is not None:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_titles import set_user_title

        await asyncio.to_thread(
            set_user_title, DATA_ROOT / "engine", conversation_id, str(values["title"]),
        )
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/api/conversations/{conversation_id}/truncate")
async def truncate_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any],
) -> dict[str, str]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    message_id = str(req.get("from_message_id", ""))
    if not message_id:
        raise HTTPException(status_code=400, detail="from_message_id is required")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import atlas_turn_ordinal, rewind_user_turn, read_session_all_messages

    messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)

    ordinal = atlas_turn_ordinal(messages, message_id, through_target=False)
    snapshot = (
        None if ordinal is None
        else await asyncio.to_thread(
            rewind_user_turn, DATA_ROOT / "engine", conversation_id, ordinal,
        )
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Conversation or message not found")
    return {"status": "ok", "conversation_id": conversation_id}


def _conversation_has_active_run(conversation_id: str) -> bool:
    return any(run.conversation_id == conversation_id and run.status in {
        "running", "waiting", "paused",
    } for run in _server().runtime_mgr.runs.values())


def _not_before(created_at: Any, since: datetime | None) -> bool:
    """True when a checkpoint was taken at/after ``since`` (unparseable times are kept)."""
    if since is None:
        return True
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created >= since


async def _snapshot_rewind_files(
    run_ids: list[str], roots: list[str], since: datetime | None = None,
    time_filtered: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Legacy fallback snapshots for runs without an Atlas rewind point."""
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    checkpoints: list[tuple[str, str, str, str]] = []
    orchestrator = _server().orchestrator
    store = getattr(orchestrator, "checkpoints", None) if orchestrator else None
    for run_id in run_ids:
        run_since = since if time_filtered and run_id in time_filtered else None
        if store is not None:
            for item in store.list_checkpoints(run_id=run_id):
                manifest_path = store.storage_dir / item["id"] / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not _not_before(manifest.get("created_at"), run_since):
                    continue
                root = str(Path(manifest["workspace"]).resolve())
                checkpoints.append((manifest.get("created_at", ""), "local", root, item["id"]))
                for entry in manifest.get("files", []):
                    if entry.get("directory"):
                        continue
                    key = (root, str(entry["path"]))
                    target = (Path(root) / entry["path"]).resolve()
                    if Path(root) not in target.parents:
                        continue
                    exists = target.is_file()
                    data = await asyncio.to_thread(target.read_bytes) if exists else b""
                    snapshots[key] = {
                        "root": root, "path": str(entry["path"]), "exists": exists,
                        "data": base64.b64encode(data).decode("ascii"),
                    }
        for root in roots:
            if not root.startswith("ssh://"):
                continue
            with suppress(Exception):
                host, remote_root = ssh_workspaces.parse_workspace(root)
                for item in await ssh_workspaces.list_checkpoints(root, run_id=run_id):
                    if not _not_before(item.get("created_at"), run_since):
                        continue
                    checkpoints.append((str(item.get("created_at", "")), "ssh", root, item["id"]))
                    for entry in item.get("files", []):
                        if entry.get("directory"):
                            continue
                        relative = str(entry["path"])
                        target = str(PurePosixPath(remote_root) / relative)
                        exists = bool(entry.get("exists"))
                        data = await ssh_workspaces.read_bytes(host, target) if exists else b""
                        snapshots[(root, relative)] = {
                            "root": root, "path": relative, "exists": exists,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
    checkpoints.sort(key=lambda item: item[0], reverse=True)
    return list(snapshots.values()), [
        {"kind": kind, "root": root, "checkpoint_id": checkpoint_id}
        for _created, kind, root, checkpoint_id in checkpoints
    ]


async def _restore_rewind_files(
    files: list[dict[str, Any]],
) -> None:
    for item in files:
        root, relative = item["root"], item["path"]
        data = base64.b64decode(item.get("data", ""), validate=True)
        if root.startswith("ssh://"):
            host, remote_root = ssh_workspaces.parse_workspace(root)
            target = str(PurePosixPath(remote_root) / relative)
            if item["exists"]:
                await ssh_workspaces.write_bytes(host, target, data)
            else:
                await ssh_workspaces.call_tool(
                    "local_file", {"action": "delete", "path": target}, root,
                )
        else:
            base = Path(root).resolve()
            target = (base / relative).resolve()
            if target != base and base not in target.parents:
                raise ValueError("回退文件超出了工作目录。")
            if item["exists"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(target.write_bytes, data)
            elif target.is_file():
                await asyncio.to_thread(target.unlink)


def _snapshot_point_files(workspace: str, files: list[str]) -> list[dict[str, Any]]:
    """Capture current bytes for the legacy redo record before a point rewind."""
    base = Path(workspace).resolve()
    snapshots: list[dict[str, Any]] = []
    for relative in files:
        target = (base / relative).resolve()
        if target != base and base not in target.parents:
            raise ValueError("回退文件超出了工作目录。")
        exists = target.is_file()
        data = target.read_bytes() if exists else b""
        snapshots.append({
            "root": str(base), "path": relative, "exists": exists,
            "data": base64.b64encode(data).decode("ascii"),
        })
    return snapshots


def _truncate_checkpoint_boundary(
    conversation_id: str, after_message_id: str | None,
) -> tuple[dict[str, Any], int]:
    """Apply a checkpoint's post-boundary cut using the existing SessionDB adapter."""
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import (
        atlas_turn_ordinal, read_session_all_messages, rewind_user_turn,
    )

    home = DATA_ROOT / "engine"
    messages = read_session_all_messages(home, conversation_id)
    if after_message_id is None:
        user_ordinal = 0
        removed_messages = len(messages)
    else:
        boundary = next((
            index for index, item in enumerate(messages)
            if str(item.get("id")) == after_message_id
        ), None)
        user_ordinal = atlas_turn_ordinal(
            messages, after_message_id, through_target=True,
        )
        if boundary is None or user_ordinal is None:
            raise ValueError("找不到检查点对应的对话边界。")
        removed_messages = len(messages) - boundary - 1
    snapshot = rewind_user_turn(home, conversation_id, user_ordinal)
    if snapshot is None:
        raise ValueError("找不到要回退的对话。")
    return snapshot, removed_messages


async def _restore_run_checkpoints(
    checkpoints: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    restored: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in checkpoints:
        try:
            if item["kind"] == "ssh":
                data = await ssh_workspaces.restore_checkpoint(item["root"], item["checkpoint_id"])
            else:
                data = await asyncio.to_thread(
                    _server().orchestrator.checkpoints.restore_checkpoint, item["checkpoint_id"],
                )
            restored.extend(str(path) for path in data.get("restored", []))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            skipped.append({"path": item["root"], "reason": str(exc)[:500]})
    return restored, skipped


async def _legacy_rewind_conversation(
    memory: Any, conversation_id: str, message_id: str, files_requested: bool,
) -> dict[str, Any]:
    """Keep the pre-v2 rewind behavior for history without Atlas points and SSH roots."""
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import (
        atlas_turn_ordinal, read_session_all_messages, restore_session, rewind_user_turn,
    )

    messages = await asyncio.to_thread(
        read_session_all_messages, DATA_ROOT / "engine", conversation_id,
    )
    boundary = next((
        index for index, item in enumerate(messages)
        if str(item.get("id")) == message_id
    ), None)
    if boundary is None:
        raise HTTPException(status_code=404, detail="找不到这段对话或指定消息。")
    removed = messages[boundary:]
    run_ids: list[str] = []
    for item in removed:
        metadata = item.get("metadata")
        if isinstance(metadata, str):
            with suppress(TypeError, ValueError):
                metadata = json.loads(metadata or "{}")
        if not isinstance(metadata, dict):
            continue
        run_id = metadata.get("run_id")
        if run_id and run_id not in run_ids:
            run_ids.append(str(run_id))
    discovered: set[str] = set()
    for run in _server().runtime_mgr.runs.values():
        if run.conversation_id == conversation_id and run.run_id not in run_ids:
            run_ids.append(str(run.run_id))
            discovered.add(str(run.run_id))
    since: datetime | None = None
    with suppress(ValueError, TypeError):
        since = datetime.fromisoformat(
            str(messages[boundary].get("created_at")).replace("Z", "+00:00")
        )
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    conversation = await memory.get_conversation(conversation_id) or {}
    roots = [*([conversation["workspace"]] if conversation.get("workspace") else []),
             *conversation.get("extra_roots", [])]
    file_snapshot, checkpoints = ([], [])
    if files_requested:
        file_snapshot, checkpoints = await _snapshot_rewind_files(
            run_ids, roots, since, discovered,
        )
    rewind_id = uuid.uuid4().hex
    snapshot = {
        "messages": messages,
        "files": file_snapshot,
        "checkpoints": checkpoints,
        "files_requested": files_requested,
    }
    user_ordinal = atlas_turn_ordinal(messages, message_id, through_target=False)
    hermes_snapshot = await asyncio.to_thread(
        rewind_user_turn, DATA_ROOT / "engine", conversation_id, user_ordinal,
    )
    if hermes_snapshot:
        snapshot["hermes_session"] = hermes_snapshot
    await memory.save_rewind({
        "rewind_id": rewind_id, "conversation_id": conversation_id,
        "removed_messages": len(removed), "restored_files": 0, "snapshot": snapshot,
    })
    restored_files: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        if files_requested:
            restored_files, skipped = await _restore_run_checkpoints(checkpoints)
    except HTTPException:
        raise
    except Exception:
        if hermes_snapshot:
            await asyncio.to_thread(restore_session, DATA_ROOT / "engine", hermes_snapshot)
        if files_requested:
            await _restore_rewind_files(file_snapshot)
        raise
    await memory.update_rewind_restored_files(rewind_id, len(restored_files))
    return {
        "rewind_id": rewind_id,
        "removed_messages": len(removed),
        "restored_files": sorted(set(restored_files)),
        "skipped": skipped,
    }


@router.post("/api/conversations/{conversation_id}/rewind")
async def rewind_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if _conversation_has_active_run(conversation_id):
        raise HTTPException(status_code=409, detail="这段对话仍在运行，请等它结束后再回退。")

    mode = req.get("mode")
    point_id = req.get("point_id")
    legacy_request = mode is None and point_id is None
    if legacy_request:
        message_id = req.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HTTPException(status_code=400, detail="请选择要回退到的消息。")
        if not isinstance(req.get("files"), bool):
            raise HTTPException(status_code=400, detail="请指定是否同时恢复文件。")
        mode = "both" if req["files"] else "conversation"
    elif mode is None:
        raise HTTPException(status_code=400, detail="point_id 请求必须指定 mode。")
    elif not isinstance(mode, str) or mode not in {"code", "conversation", "both"}:
        raise HTTPException(status_code=400, detail="mode 必须是 code、conversation 或 both。")

    if point_id is not None and (not isinstance(point_id, str) or not point_id):
        raise HTTPException(status_code=400, detail="point_id 无效。")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages
    from atlas.rewind import list_points, preview as preview_rewind, rewind as rewind_point

    points = await asyncio.to_thread(list_points, conversation_id)
    selected = next((point for point in points if point.point_id == point_id), None)
    if point_id is not None and selected is None:
        raise HTTPException(status_code=404, detail="找不到这段对话的检查点。")
    if selected is None:
        message_id = req.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HTTPException(status_code=400, detail="请选择要回退到的消息或检查点。")
        messages = await asyncio.to_thread(
            read_session_all_messages, DATA_ROOT / "engine", conversation_id,
        )
        target = next((
            index for index, item in enumerate(messages)
            if str(item.get("id")) == message_id
        ), None)
        if target is None:
            raise HTTPException(status_code=404, detail="找不到这段对话或指定消息。")
        turn_start = next((
            index for index in range(target, -1, -1)
            if messages[index].get("role") == "user"
        ), target)
        after_message_id = (
            str(messages[turn_start - 1].get("id")) if turn_start > 0 else None
        )
        selected = next((
            point for point in points if point.after_message_id == after_message_id
        ), None)
        if selected is None:
            if legacy_request:
                return await _legacy_rewind_conversation(
                    memory, conversation_id, message_id, req["files"],
                )
            raise HTTPException(status_code=404, detail="找不到对应回合的检查点。")

    rewind_preview = None
    redo_files: list[dict[str, Any]] = []
    wants_code = mode in {"code", "both"}
    if wants_code:
        rewind_preview = await asyncio.to_thread(preview_rewind, selected.point_id)
        redo_files = await asyncio.to_thread(
            _snapshot_point_files, selected.workspace, rewind_preview.files,
        )

    truncate_state: dict[str, Any] = {}

    def truncate_at_checkpoint(
        target_conversation_id: str, after_message_id: str | None,
    ) -> None:
        hermes_snapshot, removed_messages = _truncate_checkpoint_boundary(
            target_conversation_id, after_message_id,
        )
        truncate_state["hermes_session"] = hermes_snapshot
        truncate_state["removed_messages"] = removed_messages

    try:
        result = await asyncio.to_thread(
            rewind_point, selected.point_id, mode,
            truncate_conversation=truncate_at_checkpoint,
        )
    except Exception:
        if truncate_state.get("hermes_session"):
            from atlas.engine.session_sync import restore_session
            await asyncio.to_thread(
                restore_session, DATA_ROOT / "engine", truncate_state["hermes_session"],
            )
        if wants_code and redo_files:
            await _restore_rewind_files(redo_files)
        raise

    rewind_id = uuid.uuid4().hex
    restored_files = sorted(set(result.restored_files))
    removed_messages = int(truncate_state.get("removed_messages", 0))
    snapshot = {
        "messages": [],
        "files": redo_files,
        "files_requested": wants_code,
        "hermes_session": truncate_state.get("hermes_session"),
        "atlas_point_id": selected.point_id,
    }
    try:
        await memory.save_rewind({
            "rewind_id": rewind_id, "conversation_id": conversation_id,
            "removed_messages": removed_messages,
            "restored_files": len(restored_files), "snapshot": snapshot,
        })
    except Exception:
        if truncate_state.get("hermes_session"):
            from atlas.engine.session_sync import restore_session
            await asyncio.to_thread(
                restore_session, DATA_ROOT / "engine", truncate_state["hermes_session"],
            )
        if wants_code and redo_files:
            await _restore_rewind_files(redo_files)
        raise
    return {
        "rewind_id": rewind_id, "removed_messages": removed_messages,
        "restored_files": restored_files, "skipped": [],
        "point_id": selected.point_id,
    }


@router.post("/api/conversations/{conversation_id}/rewind/{rewind_id}/redo")
async def redo_conversation_rewind(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, rewind_id: str,
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if _conversation_has_active_run(conversation_id):
        raise HTTPException(status_code=409, detail="这段对话仍在运行，请等它结束后再重做。")
    if not re.fullmatch(r"[0-9a-f]{32}", rewind_id):
        raise HTTPException(status_code=404, detail="找不到这条回退记录。")
    record = await memory.get_rewind(conversation_id, rewind_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到这条回退记录。")
    if record["redone"]:
        raise HTTPException(status_code=409, detail="这次回退已经重做过了。")
    snapshot = record["snapshot"]
    if snapshot.get("files_requested"):
        await _restore_rewind_files(snapshot.get("files", []))
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import restore_session

    await asyncio.to_thread(
        restore_session, DATA_ROOT / "engine", snapshot.get("hermes_session"),
    )
    await memory.mark_rewind_redone(conversation_id, rewind_id)
    return {"status": "redone", "rewind_id": rewind_id}


@router.get("/api/conversations/{conversation_id}/rewinds")
async def list_conversation_rewinds(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> list[dict[str, Any]]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    from atlas.rewind import list_points

    legacy_records = await memory.list_rewinds(conversation_id)
    points = await asyncio.to_thread(list_points, conversation_id)
    rewinds_by_point: dict[str, dict[str, Any]] = {}
    for item in legacy_records:
        detail = await memory.get_rewind(conversation_id, str(item["rewind_id"]))
        point_id = (detail or {}).get("snapshot", {}).get("atlas_point_id")
        if isinstance(point_id, str):
            rewinds_by_point[point_id] = item
    records: list[dict[str, Any]] = []
    matched_rewind_ids: set[str] = set()
    for point in points:
        rewind_record = rewinds_by_point.get(point.point_id)
        if rewind_record is not None:
            matched_rewind_ids.add(str(rewind_record["rewind_id"]))
        record = dict(rewind_record or {
            "rewind_id": point.point_id,
            "created_at": point.created_at,
            "removed_messages": 0,
            "restored_files": 0,
            "redone": False,
        })
        record.update({
            "point_id": point.point_id,
            "conversation_id": point.conversation_id,
            "turn_id": point.turn_id,
            "workspace": point.workspace,
            "after_message_id": point.after_message_id,
            "can_redo": rewind_record is not None,
        })
        records.append(record)
    records.extend(
        item for item in legacy_records
        if str(item["rewind_id"]) not in matched_rewind_ids
    )
    return records


@router.get("/api/conversations/{conversation_id}/rewinds/{point_id}/preview")
async def preview_conversation_rewind(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, point_id: str,
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    if await memory.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="找不到这段对话。")
    from atlas.rewind import list_points, preview

    points = await asyncio.to_thread(list_points, conversation_id)
    if not any(point.point_id == point_id for point in points):
        raise HTTPException(status_code=404, detail="找不到这段对话的检查点。")
    result = await asyncio.to_thread(preview, point_id)
    return {
        "point_id": result.point_id,
        "files": result.files,
        "diff": result.diff,
        "changes": [
            {"path": item.path, "status": item.status, "binary": item.binary}
            for item in result.changes
        ],
    }


@router.post("/api/conversations/{conversation_id}/fork", status_code=201)
async def fork_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any],
) -> dict[str, Any]:
    orchestrator = _service("orchestrator", services)
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    message_id = str(req.get("through_message_id", ""))
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import atlas_turn_ordinal, fork_session_through_turn, read_session_all_messages

    source_messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)
    user_turns = atlas_turn_ordinal(source_messages, message_id, through_target=True)
    if user_turns is None:
        raise HTTPException(status_code=404, detail="Conversation or message not found")
    # The fork's context summary must be the clone's FIRST message (H2
    # regression fix: it used to be appended last, landing at the transcript
    # tail), so it is computed before the clone and imported as a preamble.
    # Compute it before creating fork metadata too, so a summarizer failure
    # cannot leave an orphan conversation row.
    fork_summary: dict[str, Any] | None = None
    if req.get("summarize") is True:
        boundary = next((i for i, item in enumerate(source_messages) if item["id"] == message_id), -1)
        before = source_messages[:boundary + 1]
        source_conversation = await memory.get_conversation(conversation_id) or {}
        compacted = await orchestrator.context_maintenance.compact({
            "goal": source_conversation.get("title", "Conversation fork"),
            "session_summary": "\n".join(f"{m['role']}: {m['content'][:1000]}" for m in before[-20:]),
        }) if orchestrator else {"session_summary": "\n".join(m["content"][:300] for m in before[-10:])}
        fork_summary = {
            "role": "system", "content": compacted.get("session_summary", ""),
            "display_metadata": {"kind": "fork_summary", "source_conversation_id": conversation_id},
        }
    result = await memory.fork_conversation_metadata(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        await asyncio.to_thread(
            fork_session_through_turn, DATA_ROOT / "engine", conversation_id, str(result["id"]),
            user_turns, branch_message_id=message_id, preamble=fork_summary,
        )
    except Exception:
        await memory.delete_conversation(str(result["id"]))
        raise
    await memory.update_conversation(
        result["id"], parent_conversation_id=conversation_id, fork_message_id=message_id,
        workspace=(await memory.get_conversation(conversation_id) or {}).get("workspace"),
    )
    persisted = await memory.get_conversation(result["id"])
    if persisted is not None:
        result = {**persisted, **{key: result[key] for key in ("files_shared",) if key in result}}
    if req.get("summarize") is True:
        result = await memory.get_conversation(result["id"]) or result
    return result


@router.post("/api/conversations/{conversation_id}/duplicate", status_code=201)
async def duplicate_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages

    messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation has no messages")
    result = await memory.fork_conversation_metadata(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    from atlas.engine.session_sync import atlas_turn_ordinal, fork_session_through_turn

    user_turns = atlas_turn_ordinal(messages, str(messages[-1]["id"]), through_target=True)
    if user_turns is None:
        await memory.delete_conversation(str(result["id"]))
        raise HTTPException(status_code=404, detail="Conversation has no messages")
    try:
        await asyncio.to_thread(
            fork_session_through_turn, DATA_ROOT / "engine", conversation_id, str(result["id"]),
            user_turns, branch_message_id=str(messages[-1]["id"]),
        )
    except Exception:
        await memory.delete_conversation(str(result["id"]))
        raise
    source = await memory.get_conversation(conversation_id) or {}
    await memory.update_conversation(result["id"], parent_conversation_id=conversation_id,
                                     fork_message_id=messages[-1]["id"],
                                     workspace=source.get("workspace"))
    return await memory.get_conversation(result["id"]) or result


@router.post("/api/conversations/{conversation_id}/compact")
async def compact_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str, req: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = _service("memory", services)
    assert memory is not None
    orchestrator = _service("orchestrator", services)
    assert orchestrator is not None
    conv = await memory.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    from atlas.config import DATA_ROOT
    from atlas.engine import HermesRuntime

    return await HermesRuntime(
        data_dir=DATA_ROOT, model_manager=orchestrator._model_mgr,
    ).compact_session(
        conversation_id=conversation_id, workspace=conv.get("workspace"),
        focus_topic=str((req or {}).get("focus_topic") or (req or {}).get("note") or "").strip() or None,
        hook_store=_server()._hook_store(),
    )


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    services: Annotated[AppServices, Depends(get_app_services)],
    conversation_id: str,
) -> dict[str, str]:
    """Delete a conversation and all its messages."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    conv = await memory.get_conversation(conversation_id)
    ok = await memory.delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Real session destruction point: fire SessionEnd after the delete succeeded.
    hook_store = _server()._hook_store()
    await hook_store.execute("SessionEnd", {
        "conversation_id": conversation_id, "reason": "delete",
    }, cwd=conv.get("workspace") if conv else None)
    hook_store.stop_file_watcher(conversation_id)
    return {"status": "ok", "conversation_id": conversation_id}
