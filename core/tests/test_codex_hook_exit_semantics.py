"""A broken Codex hook must not cancel the turn.

Codex reserves exit code 2 for a hook *error*; Claude reserves it for a
deliberate block. Atlas read every hook with Claude semantics, so a Codex
`UserPromptSubmit` command pointing at a deleted script turned into
``blocked=True``: the turn ended, the reply became the interpreter's error
text, and the model was never called (``request_count: 0``).

This file pins the separation so a broken external hook stays a logged
diagnostic instead of a product-wide outage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.runtime.hooks import codex_hook_settings, execute_claude_hooks

pytestmark = pytest.mark.unit


def _config(command: str) -> dict:
    return {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}}


def _write(tmp_path: Path, command: str) -> Path:
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps(_config(command)), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_codex_exit_two_is_not_a_block(tmp_path: Path):
    hooks = codex_hook_settings(tmp_path, user_hooks_path=_write(
        tmp_path, 'python "C:/definitely/not/here/hook.py"'))
    result = await execute_claude_hooks(
        hooks, "UserPromptSubmit", {"prompt": "hi"}, cwd=str(tmp_path))

    assert result["blocked"] is False
    # The failure is still recorded, so an operator can find the broken hook.
    assert any("codex" in str(entry.get("source", ""))
               for entry in result.get("logs") or [])


@pytest.mark.asyncio
async def test_claude_exit_two_still_blocks(tmp_path: Path):
    """Claude semantics are unchanged: exit 2 there is an intentional block."""
    from atlas.runtime.hooks import parse_claude_hooks

    hooks = parse_claude_hooks(_config('python -c "import sys; sys.exit(2)"'),
                               source="claude:user:test")
    result = await execute_claude_hooks(
        hooks, "UserPromptSubmit", {"prompt": "hi"}, cwd=str(tmp_path))

    assert result["blocked"] is True


@pytest.mark.asyncio
async def test_codex_hook_success_still_contributes_context(tmp_path: Path):
    """The fix must not silence a *working* Codex hook's output."""
    hooks = codex_hook_settings(tmp_path, user_hooks_path=_write(
        tmp_path, 'python -c "print(\'codex context\')"'))
    result = await execute_claude_hooks(
        hooks, "UserPromptSubmit", {"prompt": "hi"}, cwd=str(tmp_path))

    assert result["blocked"] is False
    assert "codex context" in result["additional_context"]
