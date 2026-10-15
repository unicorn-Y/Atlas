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


@pytest.mark.asyncio
async def test_worktree_tools(tmp_path: Path) -> None:
    import subprocess
    from types import SimpleNamespace

    from atlas.sessions.tools import run_session_tool

    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    runtime = SimpleNamespace(conversation_id="c", run_id="r", workspace=str(repo), read_only=False)
    created = await run_session_tool("worktree_create", {"name": "try it"}, runtime)
    assert not created.get("is_error") and Path(created["data"]["worktree_path"]).is_dir()
    listed = await run_session_tool("worktree_list", {}, runtime)
    assert any(row.get("managed") for row in listed["data"]["worktrees"])
