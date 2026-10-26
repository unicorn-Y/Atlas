"""U44 acceptance scenarios for upstream retry policy and all work items."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import Any

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


class _RelayRejection(RuntimeError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("403 Forbidden: message: request illegal; type: bad_response_status_code")
        self.response = SimpleNamespace(
            status_code=403, headers={},
            text='{"error":{"message":"request illegal","type":"bad_response_status_code"}}',
        )


class _Unauthorized(RuntimeError):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("401 Unauthorized: invalid api key")
        self.response = SimpleNamespace(status_code=401, headers={}, text='{"error":"invalid api key"}')


def _text_chunks() -> list[dict[str, Any]]:
    return [
        {"choices": [{"delta": {"content": "fixture-ok"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


class _Router:
    def __init__(self, scripts: dict[str, list[str]], *, api_mode: str = "openai_compatible") -> None:
        self.scripts = scripts
        self.calls: dict[str, int] = {}
        self.api_mode = api_mode
        self.messages: list[list[dict[str, Any]]] = []

    async def resolve(self, model: str, _purpose: str) -> Any:
        return SimpleNamespace(
            model=model, model_id=model, wire_model=model, provider="fixture-relay",
            base_url="http://127.0.0.1/fixture", api_mode=self.api_mode,
            credential_pool=None, key="fixture-only",
        )

    def stream(self, route: Any, messages: Any, **_kwargs: Any) -> Any:
        self.messages.append(messages)
        model = route.model_id
        index = self.calls.get(model, 0)
        self.calls[model] = index + 1
        result = self.scripts[model][min(index, len(self.scripts[model]) - 1)]
        if result == "403":
            raise _RelayRejection()
        if result == "401":
            raise _Unauthorized()
        return _text_chunks()


async def check_upstream_retry_policy() -> None:
    from atlas.kernel.model_call import ModelCallError, classify_error, complete_stream

    category, retryable, status = classify_error(_RelayRejection())
    assert (category, retryable, status) == ("upstream_rejection", True, 403)
    assert classify_error(_Unauthorized()) == ("authentication", False, 401)
    ordinary_403 = RuntimeError("403 Forbidden: invalid permissions")
    ordinary_403.status_code = 403
    assert classify_error(ordinary_403) == ("authentication", False, 403)

    previous_attempts = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS")
    previous_wait = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_SECONDS")
    os.environ["ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS"] = "4"
    os.environ["ATLAS_MODEL_RETRY_BUDGET_SECONDS"] = "2"
    try:
        router = _Router({"primary": ["403", "403"], "backup": ["ok"]})
        attempts: list[dict[str, Any]] = []
        result = await complete_stream(
            SimpleNamespace(_model_router=router, source="foreground"), "primary",
            [{"role": "user", "content": "probe"}], [], max_retries=8,
            fallback_models=["backup"], on_attempt=attempts.append,
        )
        assert result.model == "backup" and result.text == "fixture-ok"
        assert router.calls == {"primary": 2, "backup": 1}, router.calls
        retried = [item for item in attempts
                   if item.get("category") == "upstream_rejection" and not item.get("fallback")]
        assert len(retried) == 2 and retried[0].get("retry") is True
        assert retried[0].get("retry_kind") == "upstream_rejection"
        assert retried[1].get("retry") is False

        auth_router = _Router({"primary": ["401"], "backup": ["ok"]})
        try:
            await complete_stream(
                SimpleNamespace(_model_router=auth_router, source="foreground"), "primary",
                [{"role": "user", "content": "probe"}], [], max_retries=8,
                fallback_models=["backup"],
            )
        except ModelCallError:
            pass
        assert auth_router.calls.get("primary") == 1, auth_router.calls
    finally:
        for key, value in (("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", previous_attempts),
                           ("ATLAS_MODEL_RETRY_BUDGET_SECONDS", previous_wait)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("U44 item 0 PASS: relay 403 retries once on the same model then uses fallback; 401 is not retried")


async def check_prompt_cache_diagnostics() -> None:
    from atlas.kernel.model_call import complete_stream

    router = _Router({"primary": ["ok"]}, api_mode="anthropic_messages")

    def stream(route: Any, messages: Any, **_kwargs: Any) -> Any:
        router.messages.append(messages)
        return [
            {"choices": [{"delta": {"content": "cache-debug-ok"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 9, "completion_tokens": 1, "prompt_cache_hit_tokens": 7}},
        ]

    router.stream = stream
    attempts: list[dict[str, Any]] = []
    result = await complete_stream(
        SimpleNamespace(_model_router=router, source="foreground"), "primary",
        [{"role": "system", "content": "stable system"}, {"role": "user", "content": "probe"}],
        [], bypass_prompt_cache=True, cache_bypass_nonce="u44-fixed-run-id",
        on_attempt=attempts.append,
    )
    system = [item for item in router.messages[0] if item.get("role") == "system"]
    assert system[0]["content"].startswith("[Atlas prompt-cache diagnostic nonce: u44-fixed-run-id]")
    assert not any("cache_control" in str(item) for item in router.messages[0])
    debug = result.usage.get("atlas_cache_debug", {})
    assert debug.get("bypass_requested") is True
    assert debug.get("cache_control_markers") == 0
    assert debug.get("cache_hit_reported") is True and debug.get("cache_hit_tokens") == 7, debug
    assert attempts[0]["usage"]["atlas_cache_debug"] == debug
    print("U44 item 5 PASS: unique stable run prefix, omitted Anthropic cache markers, and provider cache-hit reporting")


async def check_archive_bulk_delete() -> None:
    from atlas.api import conversations_router
    from atlas.api.app_services import AppServices

    class Memory:
        items = {
            "archived": {"archived": True, "pinned": False, "workspace": None},
            "pinned": {"archived": True, "pinned": True, "workspace": None},
            "active": {"archived": False, "pinned": False, "workspace": None},
        }

        async def get_conversation(self, conversation_id: str) -> Any:
            return self.items.get(conversation_id)

        async def delete_conversation(self, conversation_id: str) -> bool:
            return self.items.pop(conversation_id, None) is not None

    class Hooks:
        def __init__(self) -> None:
            self.ended: list[str] = []

        async def execute(self, _name: str, payload: dict[str, str], cwd: str | None = None) -> None:
            del cwd
            self.ended.append(payload["conversation_id"])

        def stop_file_watcher(self, _conversation_id: str) -> None:
            return

    memory, hooks = Memory(), Hooks()
    original_server = conversations_router._server
    conversations_router._server = lambda: SimpleNamespace(_hook_store=lambda: hooks)
    try:
        result = await conversations_router.delete_archived_conversations(
            AppServices(memory=memory),
            {"conversation_ids": ["archived", "pinned", "active", "missing", "archived"]},
        )
    finally:
        conversations_router._server = original_server
    outcomes = {item["conversation_id"]: item["status"] for item in result["results"]}
    assert outcomes == {"archived": "deleted", "pinned": "failed", "active": "failed", "missing": "failed"}, outcomes
    assert "archived" not in memory.items and "pinned" in memory.items and "active" in memory.items
    assert hooks.ended == ["archived"]
    print("U44 item 1 PASS: bulk archive delete is idempotent, reports each failure, preserves pinned/active, and emits one SessionEnd")


async def check_cli_desktop_handoff() -> None:
    from atlas.api.app_services import AppServices
    from atlas.api.conversations_router import queue_cli_desktop_handoff, take_cli_desktop_handoff

    class Memory:
        async def get_conversation(self, conversation_id: str) -> Any:
            return {"id": conversation_id} if conversation_id == "u44-cli-session" else None

    services = AppServices(memory=Memory())
    queued = await queue_cli_desktop_handoff(
        services, {"conversation_id": "u44-cli-session", "draft": "unsubmitted U44 draft"},
    )
    handoff = await take_cli_desktop_handoff(services)
    empty = await take_cli_desktop_handoff(services)
    assert queued == {"queued": True}
    assert handoff == {"handoff": {"conversation_id": "u44-cli-session", "draft": "unsubmitted U44 draft"}}
    assert empty == {"handoff": None}
    print("U44 item 2 PASS: CLI-to-desktop handoff resolves an existing session, preserves draft, and consumes once")


async def check_office_addin() -> None:
    from fastapi import HTTPException
    from atlas.api.app_services import AppServices
    from atlas.api.office_router import (
        create_office_pairing, pair_office_addin, send_office_context,
        take_office_context, queue_office_writeback, take_office_writeback,
        unpair_office_addin,
    )

    class Memory:
        async def get_conversation(self, conversation_id: str) -> Any:
            return {"id": conversation_id} if conversation_id == "u44-office-session" else None

    services = AppServices(memory=Memory())
    invitation = await create_office_pairing(services, {"conversation_id": "u44-office-session"})
    assert len(invitation["pairing_code"]) == 8 and invitation["expires_in"] == 300
    try:
        await pair_office_addin(services, {"pairing_code": "00000000"})
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Office accepted an incorrect pairing code")
    paired = await pair_office_addin(services, {"pairing_code": invitation["pairing_code"]})
    token = paired["session_token"]
    headers = {"x_atlas_office_token": token}
    try:
        await send_office_context(services, {"host": "Word", "selection": "real selected text"}, "invalid")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Office context endpoint accepted an unpaired token")
    await send_office_context(services, {
        "host": "Excel", "document_name": "Budget.xlsx", "address": "Sheet1!A1:B2",
        "selection": "Q1\t100\nQ2\t200",
    }, token)
    context = await take_office_context(services)
    assert context["handoff"]["conversation_id"] == "u44-office-session"
    assert context["handoff"]["address"] == "Sheet1!A1:B2" and "Q2" in context["handoff"]["selection"]
    result = await queue_office_writeback(services, {
        "conversation_id": "u44-office-session", "text": "Reviewed Atlas result",
    })
    writeback = await take_office_writeback(services, token)
    assert result == {"queued": 1} and writeback["writeback"]["text"] == "Reviewed Atlas result"
    assert await unpair_office_addin(services, token) == {"unpaired": True}
    try:
        await take_office_writeback(services, token)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Office token remained active after unpair")
    print("U44 item 3 PASS: one-time Office pairing, scoped selection handoff/writeback, and token revocation")


def check_git_graph() -> None:
    from fastapi import HTTPException
    from atlas.api.workspace_router import _git_commit_detail, _git_run, _parse_git_graph

    with tempfile.TemporaryDirectory(prefix="atlas-u44-git-graph-") as temp:
        repo = Path(temp)

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(repo), *args], check=True,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            )
            return result.stdout.strip()

        git("init", "-b", "main")
        git("config", "user.name", "U44 Graph Fixture")
        git("config", "user.email", "u44@example.test")
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        git("add", "base.txt")
        git("commit", "-m", "base commit")
        git("switch", "-c", "side")
        (repo / "side.txt").write_text("side\n", encoding="utf-8")
        git("add", "side.txt")
        git("commit", "-m", "side branch commit")
        side_hash = git("rev-parse", "HEAD")
        git("switch", "main")
        (repo / "main.txt").write_text("main\n", encoding="utf-8")
        git("add", "main.txt")
        git("commit", "-m", "main branch commit")
        git("merge", "--no-ff", "side", "-m", "merge side branch")

        graph = _git_run(repo, "log", "--graph", "--decorate", "--all", "--date-order", "--oneline", "-n200")
        formatted = _git_run(repo, "log", "--all", "--date-order", "--format=%H%x1f%P%x1f%s%x1f%an%x1f%ad", "--date=short", "-n200")
        commits = []
        for line in formatted.splitlines():
            fields = line.split("\x1f", 4)
            if len(fields) == 5:
                commits.append({"hash": fields[0], "parents": fields[1].split(), "subject": fields[2], "author": fields[3], "date": fields[4]})
        nodes = _parse_git_graph(graph.splitlines(), commits)
        assert len(nodes) == 4, (graph, nodes)
        assert any(node["column"] > 0 for node in nodes), (graph, nodes)
        merge = next(node for node in nodes if node["subject"] == "merge side branch")
        assert len(merge["parents"]) == 2
        detail = _git_commit_detail(repo, merge["hash"])
        assert detail["subject"] == "merge side branch"
        assert len(detail["parents"]) == 2 and detail["author_email"] == "u44@example.test"
        assert "base.txt" in detail["changes"] or "side.txt" in detail["changes"]
        assert any(node["hash"] == side_hash for node in nodes)
        try:
            _git_commit_detail(repo, "../../HEAD")
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("unsafe commit selector was accepted")
    print("U44 item 6 PASS: parsed real merge graph lanes, complete commit metadata/diff, and parent links")


def check_browser_zoom() -> None:
    script = Path(__file__).with_name("u44_check_browser_zoom.mjs")
    result = subprocess.run(
        ["node", str(script)], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "Atlas webview zoom check failed")
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


async def check_real_provider() -> None:
    from atlas.models import ModelManager
    from real_model_check import AttemptResult, retry_real_model_check_async

    async def attempt(prompt: str, attempt_number: int) -> AttemptResult:
        del attempt_number
        response = await ModelManager().model_router.complete_for(
            "deepseek-v4.1-flash", "advisor", [{"role": "user", "content": prompt}],
            max_tokens=48, temperature=0,
        )
        answer = str(response.text or "")
        return AttemptResult("U44_RETRY_HELPER_OK" in answer, answer=answer,
                             detail="required real-model marker missing")

    await retry_real_model_check_async(
        "U44 configured deepseek model route",
        "Reply with exactly U44_RETRY_HELPER_OK and no other text.", attempt,
    )


def main() -> None:
    sys.path.insert(0, str(CORE))
    asyncio.run(check_upstream_retry_policy())
    asyncio.run(check_archive_bulk_delete())
    asyncio.run(check_cli_desktop_handoff())
    asyncio.run(check_office_addin())
    asyncio.run(check_prompt_cache_diagnostics())
    check_git_graph()
    asyncio.run(check_real_provider())
    check_terminal_setup()
    check_browser_zoom()
    print("U44 CHECK PASS")


def check_terminal_setup() -> None:
    from atlas.terminal_setup import detect_shell, integration_installed
    from atlas.cli import main as atlas_cli
    from click.testing import CliRunner

    assert detect_shell({"ATLAS_TERMINAL_SHELL": "bash"}) == "bash"
    with tempfile.TemporaryDirectory(prefix="atlas-u44-terminal-") as temp:
        profile = Path(temp) / ".bashrc"
        profile.write_text("# user profile\n", encoding="utf-8")
        runner = CliRunner()
        environment = {**os.environ, "ATLAS_TERMINAL_SHELL": "bash"}
        installed = runner.invoke(atlas_cli, ["terminal-setup", "--profile", str(profile)], env=environment)
        assert installed.exit_code == 0 and "已配置 bash" in installed.output, installed.output
        original_plus_block = profile.read_text(encoding="utf-8")
        assert "# user profile" in original_plus_block
        assert "ATLAS_SHELL_INTEGRATION=1" in original_plus_block
        assert "13;2u" in original_plus_block and integration_installed(profile)
        again = runner.invoke(atlas_cli, ["terminal-setup", "--profile", str(profile)], env=environment)
        assert again.exit_code == 0 and "已是最新" in again.output
        status = runner.invoke(atlas_cli, ["terminal-setup", "--status", "--profile", str(profile)], env=environment)
        assert status.exit_code == 0 and "installed=yes" in status.output
        removed = runner.invoke(atlas_cli, ["terminal-setup", "--remove", "--profile", str(profile)], env=environment)
        assert removed.exit_code == 0 and "已移除" in removed.output
        assert profile.read_text(encoding="utf-8").strip() == "# user profile"
        assert not integration_installed(profile)
        absent = runner.invoke(atlas_cli, ["terminal-setup", "--remove", "--profile", str(profile)], env=environment)
        assert absent.exit_code == 0 and "未找到" in absent.output
        bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if bash:
            checked = subprocess.run([str(bash), "-n"], input=original_plus_block, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=10)
            if bash.is_file():
                assert checked.returncode == 0, checked.stderr
    print("U44 item 4 PASS: shell detection, idempotent profile install, Shift+Enter binding, and exact managed-block removal")


if __name__ == "__main__":
    main()
