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


class ConversationCreateRequest(BaseModel):
    title: str = "New Conversation"


class ConversationGoalCommandRequest(BaseModel):
    command: str


@router.get("/api/conversations")
async def list_conversations(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    """Return all conversation summaries."""
    memory = services.memory
    if memory is None:
        from atlas import server as _atlas_server

        memory = _atlas_server.memory
    assert memory is not None
    conversations = await memory.list_conversations()
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import list_session_previews

    previews = await asyncio.to_thread(list_session_previews, DATA_ROOT / "engine")
    return [{**item, "preview": previews.get(str(item["id"]), "")} for item in conversations]


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
    from atlas.engine.session_sync import atlas_turn_ordinal, restore_session, rewind_user_turn, read_session_all_messages

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


async def _snapshot_rewind_files(
    run_ids: list[str], roots: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    checkpoints: list[tuple[str, str, str, str]] = []
    orchestrator = _server().orchestrator
    store = getattr(orchestrator, "checkpoints", None) if orchestrator else None
    for run_id in run_ids:
        if store is not None:
            for item in store.list_checkpoints(run_id=run_id):
                manifest_path = store.storage_dir / item["id"] / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
                    snapshots[key] = {"root": root, "path": str(entry["path"]),
                                      "exists": exists,
                                      "data": base64.b64encode(data).decode("ascii")}
        for root in roots:
            if not root.startswith("ssh://"):
                continue
            with suppress(Exception):
                host, remote_root = ssh_workspaces.parse_workspace(root)
                for item in await ssh_workspaces.list_checkpoints(root, run_id=run_id):
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
    message_id = req.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise HTTPException(status_code=400, detail="请选择要回退到的消息。")
    if not isinstance(req.get("files"), bool):
        raise HTTPException(status_code=400, detail="请指定是否同时恢复文件。")
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_all_messages

    messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", conversation_id)
    boundary = next((index for index, item in enumerate(messages) if item["id"] == message_id), None)
    if boundary is None:
        raise HTTPException(status_code=404, detail="找不到这段对话或指定消息。")
    removed = messages[boundary:]
    run_ids = []
    for item in removed:
        with suppress(TypeError, ValueError):
            run_id = json.loads(item.get("metadata") or "{}").get("run_id")
            if run_id and run_id not in run_ids:
                run_ids.append(str(run_id))
    conversation = await memory.get_conversation(conversation_id) or {}
    roots = [*([conversation["workspace"]] if conversation.get("workspace") else []),
             *conversation.get("extra_roots", [])]
    file_snapshot, checkpoints = ([], [])
    if req["files"]:
        file_snapshot, checkpoints = await _snapshot_rewind_files(run_ids, roots)
    rewind_id = uuid.uuid4().hex
    snapshot = {"messages": messages, "files": file_snapshot,
                "checkpoints": checkpoints, "files_requested": req["files"]}
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import atlas_turn_ordinal, restore_session, rewind_user_turn

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
        if req["files"]:
            restored_files, skipped = await _restore_run_checkpoints(checkpoints)
    except HTTPException:
        raise
    except Exception:
        if hermes_snapshot:
            await asyncio.to_thread(restore_session, DATA_ROOT / "engine", hermes_snapshot)
        if req["files"]:
            await _restore_rewind_files(file_snapshot)
        raise
    db = memory._db
    if db is not None:
        await db.execute(
            "UPDATE conversation_rewinds SET restored_files=? WHERE rewind_id=?",
            (len(restored_files), rewind_id),
        )
        await db.commit()
    return {"rewind_id": rewind_id, "removed_messages": len(removed),
            "restored_files": sorted(set(restored_files)), "skipped": skipped}


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
    return await memory.list_rewinds(conversation_id)


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
    result = await memory.fork_conversation_metadata(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        await asyncio.to_thread(
            fork_session_through_turn, DATA_ROOT / "engine", conversation_id, str(result["id"]),
            user_turns, branch_message_id=message_id,
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
        source_messages = await asyncio.to_thread(
            read_session_all_messages, DATA_ROOT / "engine", conversation_id,
        )
        boundary = next((i for i, item in enumerate(source_messages) if item["id"] == message_id), -1)
        before = source_messages[:boundary + 1]
        compacted = await orchestrator.context_maintenance.compact({
            "goal": result.get("title", "Conversation fork"),
            "session_summary": "\n".join(f"{m['role']}: {m['content'][:1000]}" for m in before[-20:]),
        }) if orchestrator else {"session_summary": "\n".join(m["content"][:300] for m in before[-10:])}
        from atlas.engine.session_sync import append_session_message
        await asyncio.to_thread(
            append_session_message, DATA_ROOT / "engine", result["id"], "system",
            compacted.get("session_summary", ""),
            {"kind": "fork_summary", "source_conversation_id": conversation_id},
        )
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
    await _server()._hook_store().execute("SessionEnd", {
        "conversation_id": conversation_id, "reason": "delete",
    }, cwd=conv.get("workspace") if conv else None)
    return {"status": "ok", "conversation_id": conversation_id}
