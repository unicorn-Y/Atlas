# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/tools/sessions-spawn-visible.schema.ts (MIT)
# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/tools/sessions-send-tool.schema.ts (MIT)
"""Model-facing tools for independent sessions.

Contract mirrors Claude Desktop's ``start_session`` / ``dismiss_task`` /
``SendMessage`` / ``list_sessions``: ``initiation`` says whose idea it is
(``user_asked`` starts now; ``offer`` and ``own_initiative`` show a card the
user starts), ``context`` picks a fresh brief or a fork of this conversation,
``use_worktree`` gives a code-writing session its own git worktree.
"""

from __future__ import annotations

import json
from typing import Any

SESSION_TOOL_NAMES = frozenset({
    "session_start", "session_send", "session_list", "session_stop", "session_dismiss",
    "send_user_file", "next_step", "worktree_list", "worktree_create",
})

SESSION_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "session_start",
        "description": (
            "Start (or propose) a separate Atlas session for a self-contained piece of work while you stay "
            "with the user. The new session is a real conversation in the sidebar the user can open, talk to "
            "and stop; when it ends a turn its last reply is reported back to you automatically, so never wait "
            "for it or poll. initiation: 'user_asked' only when the user explicitly asked for separate/parallel/"
            "background work (starts now); 'offer' for a task the user named in their latest message (card asks "
            "them: new session or do it here); 'own_initiative' for a follow-up you noticed yourself (card, nothing "
            "runs until they click). Keep quick things (a question, one edit) in this conversation. prompt is the "
            "full brief: task, files/area, what done looks like. context 'fresh' (default) needs a background of "
            "at least 80 characters; 'fork' copies this conversation. use_worktree=true for code-writing work so "
            "two sessions never edit the same checkout."
        ),
        "parameters": {"type": "object", "properties": {
            "initiation": {"type": "string", "enum": ["user_asked", "offer", "own_initiative"]},
            "title": {"type": "string", "description": "Under 60 characters; names the task."},
            "prompt": {"type": "string", "description": "The brief the new session starts with."},
            "background": {"type": "string", "description": "Goal, decisions and constraints so far (fresh context)."},
            "context": {"type": "string", "enum": ["fresh", "fork"]},
            "use_worktree": {"type": "boolean"},
            "name": {"type": "string", "description": "Short handle [a-z0-9-], at most 24 characters."},
            "notify": {"type": "boolean", "description": "Report back when it ends a turn (default true)."},
        }, "required": ["initiation", "title", "prompt"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "session_send",
        "description": (
            "Send a message to another linked session: one you started (by session_id or name) or 'parent' "
            "(the session that started you). A running session gets it before its next step; an idle one starts "
            "a new turn with it. Use it for follow-ups to a session that already has the context; when blocked, "
            "send ONE short question to 'parent' and end your turn. Never use it for progress updates."
        ),
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string"}, "message": {"type": "string"},
        }, "required": ["to", "message"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "session_list",
        "description": "List the sessions linked to this conversation (ones it started, and its parent) with status and last report.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "session_stop",
        "description": "Stop a running linked session you started (by session_id or name).",
        "parameters": {"type": "object", "properties": {"to": {"type": "string"}},
                       "required": ["to"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "session_dismiss",
        "description": "Withdraw a session proposal the user has not started (it went stale or was done here after all).",
        "parameters": {"type": "object", "properties": {
            "session_id": {"type": "string"}, "reason": {"type": "string"},
        }, "required": ["session_id"], "additionalProperties": False},
    }},
]


SESSION_TOOLS.append({"type": "function", "function": {
    "name": "send_user_file",
    "description": (
        "Show files to the user as cards in this conversation (a generated report, diagram, screenshot, "
        "built artifact) instead of only mentioning their paths. Send deliverables when they are produced; "
        "never scratch files or every incremental save. Paths are absolute or relative to the workspace."
    ),
    "parameters": {"type": "object", "properties": {
        "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
        "caption": {"type": "string"},
    }, "required": ["paths"], "additionalProperties": False},
}})


SESSION_TOOLS.append({"type": "function", "function": {
    "name": "next_step",
    "description": (
        "Close a turn that did real work (changed files, ran commands, multi-step work) with a short box for "
        "the user: recap = 2-3 sentences on what is now true and what is not done or not verified. Only when "
        "the next move is the user's call (a choice, a go-ahead, an approval) add ask = ONE short question "
        "and 1-2 actions (label of 1-4 words, message = what clicking sends back, your recommendation first). "
        "Skip it for short answers and chat. Write no text after calling it with an ask."
    ),
    "parameters": {"type": "object", "properties": {
        "recap": {"type": "string"}, "ask": {"type": "string"},
        "actions": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "message": {"type": "string"},
        }, "required": ["label"], "additionalProperties": False}},
    }, "required": ["recap"], "additionalProperties": False},
}})


async def _next_step(args: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """Claude Desktop ``wrap_up``: recap + optional question with answer buttons."""
    from atlas import server

    recap = str(args.get("recap") or "").strip()[:600]
    ask = str(args.get("ask") or "").strip()[:160]
    actions = [{"label": str(item.get("label") or "")[:24], "message": str(item.get("message") or item.get("label") or "")[:300]}
               for item in list(args.get("actions") or [])[:2] if isinstance(item, dict) and item.get("label")]
    if not recap:
        return {"text": "recap 不能为空。", "is_error": True}
    manager = getattr(server, "runtime_mgr", None)
    run = manager.runs.get(str(getattr(runtime, "run_id", "") or "")) if manager else None
    if run is not None:
        payload = {"kind": "next_step", "recap": recap, "ask": ask if actions else "", "actions": actions if ask else []}
        await manager.send_run(run, run.next_envelope("session.event", payload), "")
    if ask and actions:
        return {"text": "下一步框已显示给用户，等用户点按钮或回复；这一轮到此结束，不要再写正文。"}
    return {"text": "回顾已显示给用户。"}


SESSION_TOOLS.extend([
    {"type": "function", "function": {
        "name": "worktree_list",
        "description": "List the git worktrees of the current workspace (path, branch, whether Atlas manages it).",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "worktree_create",
        "description": (
            "Create a managed git worktree (new branch atlas/<id>-<name>) next to the current workspace for "
            "isolated edits, and return its path. To hand the work to a separate session use session_start "
            "with use_worktree instead."
        ),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "base_branch": {"type": "string"},
        }, "required": ["name"], "additionalProperties": False},
    }},
])


async def _worktree_tool(name: str, args: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """Codex 0.162 managed worktree tools over Atlas's existing WorktreeService."""
    import asyncio as _asyncio
    import subprocess
    import uuid as _uuid
    from pathlib import Path

    from atlas.task_artifacts import WorktreeService

    workspace = str(getattr(runtime, "workspace", "") or "")
    if not workspace or workspace.startswith("ssh://") or not (Path(workspace) / ".git").exists():
        return {"text": "当前工作区不是本地 git 仓库，没法管理 worktree。", "is_error": True}
    root = Path(workspace)
    if name == "worktree_list":
        result = await _asyncio.to_thread(subprocess.run, ["git", "-C", str(root), "worktree", "list", "--porcelain"],
                                          capture_output=True, text=True, encoding="utf-8", errors="replace")
        rows, current = [], {}
        for line in result.stdout.splitlines() + [""]:
            if not line:
                if current:
                    current["managed"] = ".atlas-worktrees" in current.get("path", "")
                    rows.append(current)
                current = {}
            elif line.startswith("worktree "):
                current["path"] = line[9:]
            elif line.startswith("branch "):
                current["branch"] = line[7:].removeprefix("refs/heads/")
        return {"text": json.dumps(rows, ensure_ascii=False, indent=1), "data": {"worktrees": rows}}
    if getattr(runtime, "read_only", False):
        return {"text": "只读模式下不能新建 worktree。", "is_error": True}
    try:
        created = await _asyncio.to_thread(WorktreeService(root).create, root, _uuid.uuid4().hex,
                                           str(args.get("base_branch") or "") or None, str(args.get("name") or ""))
    except ValueError as exc:
        return {"text": f"没建成：{exc}", "is_error": True}
    return {"text": f"已建 worktree：{created['worktree_path']}（分支 {created['worktree_branch']}，基于 {created['base_branch']}）。"
                    "在里面改文件要用这个绝对路径。", "data": created}


async def _send_user_file(args: dict[str, Any], runtime: Any) -> dict[str, Any]:
    from pathlib import Path

    workspace = str(getattr(runtime, "workspace", "") or "")
    queue = getattr(runtime, "event_queue", None)
    sent, missing = [], []
    for raw in list(args.get("paths") or [])[:10]:
        path = Path(str(raw)).expanduser()
        if not path.is_absolute() and workspace and not workspace.startswith("ssh://"):
            path = Path(workspace) / path
        if not path.is_file():
            missing.append(str(raw))
            continue
        sent.append(str(path))
        if queue is not None:
            await queue.put({"type": "artifact_created", "path": str(path), "kind": "file",
                             "bytes": path.stat().st_size})
    caption = str(args.get("caption") or "").strip()
    text = (f"已把 {len(sent)} 个文件发给用户。" if sent else "没有发出任何文件。") + (
        f" 找不到：{', '.join(missing)}" if missing else "") + (f" 说明：{caption}" if caption else "")
    return {"text": text, "data": {"sent": sent, "missing": missing}, "is_error": not sent}


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in (
        "session_id", "name", "title", "status", "initiation", "conversation_id", "worktree_branch",
        "last_status", "last_report", "waiting_for",
    ) if item.get(key) not in (None, "")}


async def run_session_tool(name: str, args: dict[str, Any], runtime: Any) -> dict[str, Any]:
    """Execute one session tool; returns ``{"text": ..., "data": ..., "is_error": bool}``."""
    from atlas.sessions.hub import get_session_hub, public

    if name == "send_user_file":
        return await _send_user_file(args, runtime)
    if name == "next_step":
        return await _next_step(args, runtime)
    if name in {"worktree_list", "worktree_create"}:
        return await _worktree_tool(name, args, runtime)
    hub = get_session_hub()
    conversation_id = str(getattr(runtime, "conversation_id", "") or "")
    run_id = str(getattr(runtime, "run_id", "") or "")
    if not conversation_id:
        return {"text": "这次运行没有对话 id，开不了独立会话。", "is_error": True}
    try:
        if name == "session_start":
            title = str(args.get("title") or "").strip()[:120]
            prompt = str(args.get("prompt") or "").strip()
            initiation = str(args.get("initiation") or "own_initiative")
            context = str(args.get("context") or "fresh")
            background = str(args.get("background") or "").strip()
            if not title or not prompt:
                return {"text": "title 和 prompt 都要填：prompt 是新会话的完整任务书。", "is_error": True}
            if context not in {"fresh", "fork"} or initiation not in {"user_asked", "offer", "own_initiative"}:
                return {"text": "context 只能是 fresh/fork，initiation 只能是 user_asked/offer/own_initiative。", "is_error": True}
            if context == "fresh" and len(background) < 80:
                return {"text": "context=fresh 时要给至少 80 字的 background：总目标、已定的决定和约束、这块怎么接回来。", "is_error": True}
            downgraded = False
            if initiation == "user_asked" and run_id in hub.hub_run_ids:
                # A turn another session or a report started is not the user
                # asking: it may only propose (CCD rule).
                initiation, downgraded = "own_initiative", True
            if getattr(runtime, "read_only", False) and initiation == "user_asked":
                initiation, downgraded = "own_initiative", True
            fields = {
                "parent_conversation_id": conversation_id, "parent_run_id": run_id or None,
                "title": title, "prompt": prompt, "background": background, "context": context,
                "use_worktree": bool(args.get("use_worktree")), "name": str(args.get("name") or title),
                "initiation": initiation, "notify_parent": args.get("notify") is not False,
            }
            if initiation == "user_asked":
                record = await hub.create_and_start(**fields)
                return {"text": (
                    f"已开始独立会话「{record['title']}」（句柄 {record['name']}，id {record['session_id']}）。"
                    "它停下时回报会自动送回这里；不要等待或轮询，接着回应用户，最多一句话说明怎么回报。"
                ), "data": {"session": public(record)}}
            fields.pop("parent_run_id")
            record = await hub.propose(parent_run_id=run_id or None, **fields)
            note = "（这一轮不是用户直接发起的，只能提议，不能直接开始。）" if downgraded else ""
            return {"text": (
                f"已提议独立会话「{record['title']}」（id {record['session_id']}），卡片已显示给用户，"
                f"用户点「开始」才会运行；7 天不点自动失效。不要等它，继续手上的事。{note}"
            ), "data": {"session": public(record)}}
        if name == "session_send":
            outcome = await hub.send(str(args.get("to") or ""), str(args.get("message") or ""),
                                     from_conversation=conversation_id)
            verb = "已插入它正在跑的这一轮" if outcome["status"] == "steered" else "它空闲，已用这条消息开了新的一轮"
            return {"text": f"消息已送达（{verb}）。不要轮询，它的回复会按回报规则回来。", "data": outcome}
        if name == "session_list":
            mine = hub.store.by_conversation(conversation_id)
            items = [_brief(item) for item in hub.list(conversation_id)]
            payload = {"sessions": items}
            if mine:
                payload["parent_conversation_id"] = mine.get("parent_conversation_id")
                payload["this_session"] = _brief(mine)
            return {"text": json.dumps(payload, ensure_ascii=False, indent=1), "data": payload}
        if name == "session_stop":
            record = hub.resolve(str(args.get("to") or ""), caller_conversation=conversation_id)
            if record is None or record.get("session_id") == "parent":
                return {"text": "没找到这个会话（只能停你开的会话）。", "is_error": True}
            record = await hub.stop(record["session_id"])
            return {"text": f"会话「{record['title']}」已停止。", "data": {"session": public(record)}}
        if name == "session_dismiss":
            record = hub.store.get(str(args.get("session_id") or ""))
            if record is None or record.get("parent_conversation_id") != conversation_id:
                return {"text": "没找到这个提议（只能撤回本对话提的）。", "is_error": True}
            record = await hub.dismiss(record["session_id"], str(args.get("reason") or ""))
            state = "已撤回" if record["status"] == "dismissed" else f"没撤回：它的状态是 {record['status']}"
            return {"text": f"提议「{record['title']}」{state}。", "data": {"session": public(record)}}
    except KeyError as exc:
        return {"text": f"没找到会话：{exc}", "is_error": True}
    except (ValueError, RuntimeError) as exc:
        return {"text": str(exc), "is_error": True}
    return {"text": f"未知的会话工具：{name}", "is_error": True}
