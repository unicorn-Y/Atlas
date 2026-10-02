"""Bridge Atlas history mutations to the Hermes SessionDB transcript.

Hermes source: ``hermes_state.py::SessionDB``, ``hermes_state_rewind.py`` and
``hermes_state_portability.py`` at unicorn-Y/hermes-agent@562ad75 (MIT).
"""

from __future__ import annotations

import os
import json
from datetime import UTC, datetime
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
    from hermes_cli.goal_command import dispatch_goal_command, is_goal_control
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    previous = manager.state
    result = dispatch_goal_command(manager, command, authorize_gate=lambda: "Goal gates require explicit approval.")
    state = manager.state
    normalized = command.strip().split(maxsplit=1)[0].casefold() if command.strip() else ""
    event = None
    if normalized in {"pause", "resume", "clear", "stop", "done"}:
        event = "goal.paused" if normalized == "pause" else (
            "goal.resumed" if normalized == "resume" else "goal.cleared"
        )
    elif not is_goal_control(command) and state and (previous is None or previous.status == "cleared"):
        event = "goal.created"
    elif not is_goal_control(command) and state and previous and previous.goal != state.goal:
        event = "goal.replaced"
    if event and not result.error:
        record_goal_event(home, conversation_id, event, {"goal": state.goal if state else ""})
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


def goal_state(home: str | Path, conversation_id: str) -> dict[str, Any] | None:
    """Return the canonical Hermes GoalState for a conversation or automation session."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    state = GoalManager(conversation_id).state
    return json.loads(state.to_json()) if state is not None else None


def set_goal(home: str | Path, conversation_id: str, goal: str) -> dict[str, Any]:
    """Create or replace a goal through Hermes' per-session manager."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    state = manager.set(goal)
    return json.loads(state.to_json())


def mutate_goal(
    home: str | Path, conversation_id: str, action: str, reason: str = "user-paused",
) -> dict[str, Any] | None:
    """Apply a canonical Hermes done, pause, resume, or clear action."""
    os.environ["HERMES_HOME"] = str(Path(home).expanduser().resolve())
    from hermes_cli.goals import GoalManager

    manager = GoalManager(conversation_id)
    if action == "pause":
        state = manager.pause(reason)
    elif action == "resume":
        state = manager.resume()
    elif action == "done":
        manager.mark_done(reason)
        state = manager.state
    elif action == "clear":
        manager.clear()
        state = None
    else:
        raise ValueError(f"unsupported goal action: {action}")
    return json.loads(state.to_json()) if state is not None else None


def record_goal_event(
    home: str | Path, conversation_id: str, event: str,
    data: dict[str, Any] | None = None, run_id: str | None = None,
) -> dict[str, Any]:
    """Append audit-only goal history in Hermes SessionDB state metadata."""
    with _open_db(home) as db:
        key = f"goal-events:{conversation_id}"
        events = json.loads(db.get_meta(key) or "[]")
        if not isinstance(events, list):
            events = []
        sequence = max(
            (int(item.get("sequence", -1)) for item in events if isinstance(item, dict)),
            default=-1,
        ) + 1
        record = {
            "event_id": f"{conversation_id}:{sequence}",
            "sequence": sequence,
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data or {},
        }
        if run_id:
            record["run_id"] = run_id
        events.append(record)
        db.set_meta(key, json.dumps(events[-200:], ensure_ascii=False))
        return record


def goal_events(
    home: str | Path, conversation_id: str, run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read audit-only goal events from the same Hermes SessionDB as GoalManager."""
    with _open_db(home) as db:
        events = json.loads(db.get_meta(f"goal-events:{conversation_id}") or "[]")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)
            and (run_id is None or event.get("run_id") == run_id)]


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
