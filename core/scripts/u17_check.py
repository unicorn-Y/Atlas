"""Focused end-to-end checks for the four U17 work items; never launches Electron."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def git(path: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if check and result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


async def check_worktree_sync() -> None:
    from fastapi import HTTPException
    from atlas.api.workspace_router import resolve_worktree_sync, sync_conversation_worktree

    class Memory:
        def __init__(self, worktree: Path, base: Path) -> None:
            self.row = {"worktree_path": str(worktree), "workspace": str(base),
                        "worktree_branch": "feature", "base_branch": "main"}

        async def get_conversation(self, _conversation_id: str):
            return self.row

    with tempfile.TemporaryDirectory(prefix="atlas-u17-git-") as directory:
        temp = Path(directory)
        seed, remote, clone, worktree = temp / "seed", temp / "remote.git", temp / "clone", temp / "feature"
        seed.mkdir()
        git(seed, "init", "-b", "main")
        git(seed, "config", "user.email", "u17@example.invalid")
        git(seed, "config", "user.name", "U17 check")
        (seed / "shared.txt").write_text("base\n", encoding="utf-8")
        git(seed, "add", "shared.txt"); git(seed, "commit", "-m", "base")
        git(temp, "clone", "--bare", str(seed), str(remote))
        git(temp, "clone", str(remote), str(clone))
        git(clone, "config", "user.email", "u17@example.invalid")
        git(clone, "config", "user.name", "U17 check")
        git(clone, "worktree", "add", "-b", "feature", str(worktree), "main")
        memory = Memory(worktree, clone)
        services = SimpleNamespace(memory=memory)
        (worktree / "dirty.txt").write_text("pending\n", encoding="utf-8")
        try:
            await sync_conversation_worktree(services, "sample", {"strategy": "merge"})
            raise AssertionError("dirty worktree should be reported")
        except HTTPException as exc:
            assert exc.status_code == 409 and exc.detail.get("dirty") is True
        (worktree / "dirty.txt").unlink()

        (seed / "shared.txt").write_text("remote update\n", encoding="utf-8")
        git(seed, "add", "shared.txt"); git(seed, "commit", "-m", "advance main")
        git(seed, "remote", "add", "origin", str(remote)); git(seed, "push", "origin", "main")
        result = await sync_conversation_worktree(services, "sample", {"strategy": "merge"})
        assert result["status"] == "synced" and "origin/main" in result["base"]
        assert (worktree / "shared.txt").read_text(encoding="utf-8") == "remote update\n"

        # Conflict → abort → retry → resolve → continue exercises both recovery controls.
        (worktree / "shared.txt").write_text("feature edit\n", encoding="utf-8")
        git(worktree, "add", "shared.txt"); git(worktree, "commit", "-m", "feature edit")
        (seed / "shared.txt").write_text("second upstream edit\n", encoding="utf-8")
        git(seed, "add", "shared.txt"); git(seed, "commit", "-m", "conflicting upstream edit")
        git(seed, "push", "origin", "main")
        try:
            await sync_conversation_worktree(services, "sample", {"strategy": "merge"})
            raise AssertionError("conflicting merge should report conflicts")
        except HTTPException as exc:
            assert exc.status_code == 409 and "shared.txt" in exc.detail["conflicts"]
        await resolve_worktree_sync(services, "sample", "abort")
        try:
            await sync_conversation_worktree(services, "sample", {"strategy": "merge"})
            raise AssertionError("retry should reproduce the conflict")
        except HTTPException as exc:
            assert "shared.txt" in exc.detail["conflicts"]
        (worktree / "shared.txt").write_text("resolved\n", encoding="utf-8")
        git(worktree, "add", "shared.txt")
        await resolve_worktree_sync(services, "sample", "continue")
        assert "second upstream edit" in git(worktree, "log", "-1", "--format=%s") or (worktree / "shared.txt").read_text(encoding="utf-8") == "resolved\n"


async def check_lsp_surface_and_handoff() -> None:
    from atlas.api.conversations_router import create_handoff_summary, _redact_handoff_secrets
    from atlas.api.workspace_router import lsp_workspace_diagnostics
    from click.testing import CliRunner
    from atlas.cli import main

    assert "[REDACTED]" in _redact_handoff_secrets("api_key=sk-test-value password:abc Bearer token")
    with tempfile.TemporaryDirectory(prefix="atlas-u17-lsp-") as directory:
        root = Path(directory)
        source = root / "example.py"
        source.write_text("x = 1\n", encoding="utf-8")

        class Client:
            _docs = {str(source): object()}

            @staticmethod
            def diagnostics_for(_path: str, fresh_only: bool = False):
                assert fresh_only
                return [{"range": {"start": {"line": 0, "character": 0}}, "severity": 1,
                         "code": "E999", "message": "synthetic local diagnostic"}]

        fake_service = SimpleNamespace(_clients={"python": Client()})
        with patch("atlas.lsp.get_service", return_value=fake_service):
            result = await lsp_workspace_diagnostics(str(root))
        assert result["count"] == 1 and result["files"][0]["path"] == "example.py"
        assert result["files"][0]["diagnostics"][0]["severity"] == "error"

    cli = CliRunner().invoke(main, ["lsp", "--help"])
    assert cli.exit_code == 0 and "status" in cli.output and "start" in cli.output and "diagnostics" in cli.output
    status_cli = CliRunner().invoke(main, ["lsp", "status", "--workspace", str(ROOT)])
    assert status_cli.exit_code == 0

    class Loop:
        @staticmethod
        def run(coroutine, timeout):
            return asyncio.run(coroutine)

    class QueryService:
        _loop = Loop()

        @staticmethod
        async def _open_and_wait_async(_path: str):
            return []

    query_service = QueryService()
    probe_file = ROOT / "README.md"
    with patch("atlas.tools.workspace_lsp._service_for", return_value=(query_service, object())):
        query_cli = CliRunner().invoke(main, ["lsp", "diagnostics", str(probe_file)])
    assert query_cli.exit_code == 0 and '"available": true' in query_cli.output
    stop_cli = CliRunner().invoke(main, ["lsp", "stop"])
    assert stop_cli.exit_code == 0 and "已停止" in stop_cli.output

    class Memory:
        async def get_conversation(self, _conversation_id: str):
            return {"id": "source-1", "title": "Synthetic task", "workspace": "C:/synthetic",
                    "worktree_path": "C:/synthetic-wt", "worktree_branch": "feature", "base_branch": "main"}

    from atlas.models import ModelManager
    real_router = ModelManager().model_router

    class Router:
        async def resolve(self, model: str, _purpose: str):
            return await real_router.resolve(model, "prompt_enhance")

        async def complete(self, route, messages, **kwargs):
            prompt = messages[1]["content"]
            assert "first requirement" in prompt and "last decision" in prompt
            assert "Git status:" in prompt and "Branch: feature" in prompt
            assert "sk-live-secret-value" not in prompt and "[REDACTED]" in prompt
            return await real_router.complete(route, messages=messages, **kwargs)

    manager = SimpleNamespace(model_router=Router(), current_model="deepseek-v4.1-flash")
    services = SimpleNamespace(memory=Memory(), model_mgr=manager)
    def fake_read(_home, _conversation_id, *, limit, before_id=None):
        assert limit == 1000
        return [{"id": "m1", "role": "user", "content": "first requirement api_key=sk-live-secret-value"},
                {"id": "m2", "role": "assistant", "content": "last decision: use merge"}]
    with patch("atlas.engine.session_sync.read_session_messages", side_effect=fake_read):
        summary = await create_handoff_summary(services, "source-1")
    assert summary["model"] == "deepseek-v4.1-flash" and len(summary["text"]) > 40


def check_pane_and_source_contracts() -> None:
    app = (ROOT / "frontend/src/renderer/App.tsx").read_text(encoding="utf-8")
    pane = (ROOT / "frontend/src/renderer/components/PaneWorkspace.tsx").read_text(encoding="utf-8")
    shortcuts = (ROOT / "frontend/src/renderer/services/shortcuts.ts").read_text(encoding="utf-8")
    assert "atlas:drop-pane" in app and "pane-layout" in pane
    assert "splitAt" in pane and "onPointerDown" in pane and "localStorage.setItem(STORAGE" in pane
    assert "focusNextPane" in shortcuts and "focusPreviousPane" in shortcuts
    assert "handoff-summary" in app and "parent_conversation_id: handoffSource" in app


async def run() -> None:
    check_pane_and_source_contracts()
    await check_lsp_surface_and_handoff()
    await check_worktree_sync()
    print("U17 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(run())
