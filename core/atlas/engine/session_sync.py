"""Bridge Atlas history mutations to the Hermes SessionDB transcript.

Hermes source: ``hermes_state.py::SessionDB``, ``hermes_state_rewind.py`` and
``hermes_state_portability.py`` at unicorn-Y/hermes-agent@562ad75 (MIT).
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any


def _open_db(home: str | Path):
    root = Path(home).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(root)
    from hermes_state import SessionDB

    return SessionDB(db_path=root / "state.db")


def capture_session(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    with _open_db(home) as db:
        return db.export_session(conversation_id, include_inactive=True)


def restore_session(home: str | Path, payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    with _open_db(home) as db:
        session_id = str(payload.get("id") or "")
        if session_id:
            db.delete_session(session_id)
        result = db.import_sessions([payload])
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Hermes session restore failed: {result.get('errors', result)}")


def delete_session(home: str | Path, conversation_id: str) -> bool:
    with _open_db(home) as db:
        return db.delete_session(conversation_id)


def rewind_to_atlas_message(
    home: str | Path, conversation_id: str, atlas_messages: list[dict[str, Any]], message_id: str,
) -> dict[str, Any] | None:
    """Rewind Hermes at the same user turn Atlas is removing; return a redo snapshot."""
    target = next((index for index, item in enumerate(atlas_messages)
                   if str(item.get("id")) == message_id), None)
    if target is None:
        return None
    user_ordinal = sum(1 for item in atlas_messages[:target] if item.get("role") == "user")
    with _open_db(home) as db:
        snapshot = db.export_session(conversation_id, include_inactive=True)
        if snapshot is None:
            return None
        db.rewind_user_turn(conversation_id, user_ordinal)
        return snapshot


def fork_session(
    home: str | Path, source_id: str, fork_id: str,
    atlas_messages: list[dict[str, Any]], through_message_id: str,
) -> None:
    """Copy the durable Hermes transcript through the selected Atlas turn."""
    target = next((index for index, item in enumerate(atlas_messages)
                   if str(item.get("id")) == through_message_id), None)
    if target is None:
        return
    users_through = sum(1 for item in atlas_messages[:target + 1] if item.get("role") == "user")
    with _open_db(home) as db:
        payload = db.export_session(source_id, include_inactive=True)
        if payload is None:
            return
        transcript = payload.get("messages", [])
        seen_users = 0
        stop = len(transcript)
        for index, item in enumerate(transcript):
            if item.get("role") == "user":
                if seen_users >= users_through:
                    stop = index
                    break
                seen_users += 1
        model_config = payload.get("model_config") or {}
        if isinstance(model_config, str):
            try:
                model_config = json.loads(model_config)
            except ValueError:
                model_config = {}
        cloned = {
            **payload, "id": fork_id, "parent_session_id": source_id,
            "title": f"{str(payload.get('title') or '对话')[:80]} · 分支 {fork_id[:6]}",
            "model_config": {**model_config, "_branched_from": source_id,
                             "_branch_message_id": through_message_id},
            "messages": transcript[:stop],
        }
        result = db.import_sessions([cloned])
        if not result.get("ok") or result.get("imported") != 1:
            raise RuntimeError(f"Hermes session fork failed: {result.get('errors', result)}")


def list_branch_tree(home: str | Path, conversation_id: str) -> list[dict[str, Any]]:
    """Return the explicit Hermes branch lineage around one session."""
    with _open_db(home) as db:
        session = db.get_session(conversation_id)
        if session is None:
            return []
        sessions = db.list_sessions_rich(
            include_children=True, include_archived=True, include_hidden=True,
            limit=10000, project_compression_tips=False,
        )
    by_id = {str(item.get("id")): item for item in sessions}
    by_id[conversation_id] = {**by_id.get(conversation_id, {}), **session}
    for item in by_id.values():
        config = item.get("model_config") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except ValueError:
                config = {}
        item["_branch_config"] = config if isinstance(config, dict) else {}
    branched = {
        key: value for key, value in by_id.items()
        if value["_branch_config"].get("_branched_from")
    }
    root = conversation_id
    ancestors: set[str] = set()
    while root not in ancestors:
        ancestors.add(root)
        parent = str(by_id.get(root, {}).get("parent_session_id") or "")
        if parent not in by_id or root not in branched:
            break
        root = parent
    output: list[dict[str, Any]] = []
    pending = [root]
    seen: set[str] = set()
    while pending:
        current = pending.pop(0)
        if current in seen and current != root:
            continue
        seen.add(current)
        item = by_id.get(current)
        if item is None:
            continue
        output.append({
            "id": current, "parent_session_id": item.get("parent_session_id"),
            "title": item.get("title") or "未命名对话",
            "branch_message_id": item["_branch_config"].get("_branch_message_id"),
        })
        pending.extend(sorted(
            key for key, child in branched.items()
            if child.get("parent_session_id") == current and key not in seen
        ))
    return output


def goal_command(home: str | Path, conversation_id: str, command: str) -> dict[str, Any]:
    """Apply Hermes' canonical per-session /goal command and return its continuation prompt."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goal_command import dispatch_goal_command
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    result = dispatch_goal_command(manager, command, authorize_gate=lambda: "Goal gates require explicit approval.")
    state = manager.state
    return {
        "output": result.output, "prompt": result.prompt, "kickoff": result.kickoff,
        "error": result.error,
        "goal": ({"text": state.goal, "status": state.status, "turns_used": state.turns_used,
                  "max_turns": state.max_turns, "subgoals": state.subgoals}
                 if state is not None else None),
    }


def evaluate_goal_after_turn(
    home: str | Path, conversation_id: str, response: str,
) -> dict[str, Any]:
    """Use Hermes' per-session GoalManager as the authority after an assistant turn."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    if not manager.is_active():
        return {"status": manager.state.status if manager.state else None,
                "should_continue": False, "continuation_prompt": None,
                "verdict": "inactive", "message": ""}
    return manager.evaluate_after_turn(response or "")


def append_branch_summary(
    home: str | Path, parent_id: str, child_id: str, fork_message_id: str, content: str,
) -> None:
    """Mirror the Atlas branch note into Hermes' authoritative parent transcript."""
    with _open_db(home) as db:
        if db.get_session(parent_id) is None:
            return
        existing = db.get_messages_as_conversation(parent_id)
        if any(item.get("display_kind") == "branch_summary"
               and (item.get("display_metadata") or {}).get("child_conversation_id") == child_id
               for item in existing):
            return
        db.append_message(parent_id, "assistant", content, display_kind="branch_summary",
                          display_metadata={"child_conversation_id": child_id,
                                            "fork_message_id": fork_message_id})
