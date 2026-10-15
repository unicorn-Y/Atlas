"""Linked-session store and hook onFailure: the minimum needed to keep them honest."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atlas.runtime.hooks import execute_claude_hooks
from atlas.sessions.store import SessionStore, slugify


def test_store_lifecycle_and_unique_handles(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "s.db")
    first = store.create(parent_conversation_id="p", title="Fix login bug", prompt="x", status="proposed")
    second = store.create(parent_conversation_id="p", title="Fix login bug", prompt="y", status="proposed")
    assert first["name"] == "fix-login-bug" and second["name"] != first["name"]
    assert first["expires_at"]
    store.add_hub_run(first["session_id"], "run-1")
    updated = store.update(first["session_id"], status="running", conversation_id="c1")
    assert updated["hub_runs"] == ["run-1"] and updated["last_run_id"] == "run-1"
    assert store.by_conversation("c1")["session_id"] == first["session_id"]
    assert [item["session_id"] for item in store.list("p")] == [second["session_id"], first["session_id"]] or \
        {item["session_id"] for item in store.list("p")} == {first["session_id"], second["session_id"]}
    assert slugify("写一首诗").startswith("session-")


@pytest.mark.asyncio
async def test_hook_on_failure_block(tmp_path: Path) -> None:
    failing = {"type": "command", "command": sys.executable, "args": ["-c", "import sys; sys.exit(7)"]}
    hooks = [{"event": "PreToolUse", "matcher": "*", "hooks": [failing]}]
    open_result = await execute_claude_hooks(hooks, "PreToolUse", {"tool_name": "Bash", "tool_input": {}})
    assert open_result["blocked"] is False
    hooks[0]["hooks"] = [{**failing, "onFailure": "block"}]
    closed = await execute_claude_hooks(hooks, "PreToolUse", {"tool_name": "Bash", "tool_input": {}})
    assert closed["blocked"] is True and "onFailure" in closed["reason"]
