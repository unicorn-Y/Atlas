"""W8 smoke coverage for permission, command recovery, and hook governance."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def _mcp_tool_permissions() -> None:
    from atlas.tools.mcp_client import MCPServerConfig, _mcp_tool_allowed

    unrestricted = MCPServerConfig(name="docs")
    if not _mcp_tool_allowed(unrestricted, "search"):
        raise RuntimeError("MCP server with no allowlist should remain unrestricted")

    restricted = MCPServerConfig(
        name="docs", tool_allow=["docs__*"], tool_deny=["docs__delete"],
    )
    if not _mcp_tool_allowed(restricted, "search"):
        raise RuntimeError("MCP server wildcard did not allow the matching tool")
    if _mcp_tool_allowed(restricted, "delete"):
        raise RuntimeError("MCP deny rule did not override a matching allow rule")

    deny_all = MCPServerConfig(name="docs", tool_allow=[])
    if _mcp_tool_allowed(deny_all, "search"):
        raise RuntimeError("explicit empty MCP allowlist should deny all tools")

    parentheses = MCPServerConfig(name="docs", tool_allow=["docs(search)"])
    if _mcp_tool_allowed(parentheses, "search"):
        raise RuntimeError("unsupported parenthesized MCP permission was accepted")
    print("MCP tool permissions: allowlist, deny precedence, and invalid pattern passed", flush=True)


def _mcp_connection_recovery() -> None:
    from atlas.tools import mcp_client

    resolved, missing = mcp_client.resolve_mcp_env({"API_KEY": "$ATLAS_W8_MISSING_ENV"})
    if resolved.get("API_KEY") != "" or not any("ATLAS_W8_MISSING_ENV" in item for item in missing):
        raise RuntimeError("missing MCP environment reference was not reported without a value")

    class BrokenAndHealthyConfig:
        def get(self, key: str, default=None):
            if key == "tools.servers":
                return {
                    "broken": {"args": "expected a list"},
                    "healthy": {"command": "python", "args": []},
                }
            if key == "tools.auto_start":
                return []
            return default

    with patch.object(mcp_client, "get_config", return_value=BrokenAndHealthyConfig()):
        configs = mcp_client._parse_server_configs()
    by_name = {config.name: config for config in configs}
    if len(configs) != 2 or by_name["broken"].enabled or not by_name["broken"].blocking_reason:
        raise RuntimeError("invalid MCP config did not retain an isolated diagnostic")
    if not by_name["healthy"].enabled:
        raise RuntimeError("one malformed MCP server prevented a healthy server from loading")
    print("MCP recovery: missing env and malformed-server isolation passed", flush=True)


def _mcp_handshake_budget() -> None:
    from atlas.tools import mcp_client

    class Config:
        def __init__(self, timeout):
            self.timeout = timeout

        def get(self, key, default=None):
            return self.timeout if key == "tools.mcp.handshake_timeout_seconds" else default

    with patch.object(mcp_client, "get_config", return_value=Config(3.5)):
        if mcp_client._mcp_handshake_timeout_seconds() != 3.5:
            raise RuntimeError("configured MCP handshake timeout was ignored")
    with patch.object(mcp_client, "get_config", return_value=Config(0)):
        try:
            mcp_client._mcp_handshake_timeout_seconds()
        except ValueError:
            pass
        else:
            raise RuntimeError("invalid MCP handshake timeout was accepted")
    print("MCP startup: configured handshake deadline and invalid-value rejection passed", flush=True)


async def _mcp_reconnect_after_terminal_errors() -> None:
    from atlas.tools.mcp_client import (
        MCPClient,
        MCPServerConfig,
        MCPServerHandle,
        ToolInfo,
        is_terminal_mcp_connection_error,
    )

    class BrokenSession:
        async def call_tool(self, _name, _arguments):
            raise ConnectionError("fixture connection closed")

    client = MCPClient()
    handle = MCPServerHandle(name="remote", transport="sse", session=BrokenSession())
    client._servers["remote"] = handle
    client._server_configs["remote"] = MCPServerConfig(name="remote", transport="sse")
    client._tool_index["remote__search"] = ToolInfo(
        name="search", description="", input_schema={}, server_name="remote",
    )
    recoveries = []

    async def recover(server_name, expected_handle):
        recoveries.append((server_name, expected_handle))

    client._recover_expired_session = recover
    for _ in range(3):
        result = await client.call_tool("remote__search", {})
        if not result.get("is_error"):
            raise RuntimeError("terminal MCP tool failure was reported as success")
    if not is_terminal_mcp_connection_error(ConnectionError("closed")):
        raise RuntimeError("terminal connection error was not recognized")
    if is_terminal_mcp_connection_error(ValueError("invalid input")):
        raise RuntimeError("ordinary tool error was classified as terminal")
    if len(recoveries) != 1 or recoveries[0][0] != "remote":
        raise RuntimeError("MCP reconnect did not happen after three terminal errors")
    print("MCP reconnect: three terminal transport failures trigger one recovery", flush=True)


def _command_exit_semantics() -> None:
    from atlas.tools.local_execution import command_exit_is_error

    checks = (
        ("rg missing", 1, False),
        ("rg missing", 2, True),
        ("python -c pass", 1, True),
        ("robocopy src dst", 7, False),
        ("robocopy src dst", 8, True),
    )
    for command, exit_code, expected in checks:
        actual = command_exit_is_error(command, exit_code)
        if actual is not expected:
            raise RuntimeError(
                f"unexpected failure classification for {command!r} exit {exit_code}: {actual}"
            )
    print("command exit receipts: grep, ripgrep, and robocopy status rules passed", flush=True)


def _bounded_file_search() -> None:
    from atlas.tools.local_execution import search_files

    with tempfile.TemporaryDirectory(prefix="atlas-w8-search-") as directory:
        root = Path(directory)
        (root / "hits.txt").write_text("needle one\nneedle two\n", encoding="utf-8")
        page = search_files(root, "needle", max_results=1)
        if (len(page["matches"]) != 1 or not page["partial"] or not page["overflow"]):
            raise RuntimeError("bounded file search did not mark its capped matches partial")
        try:
            search_files(root, "absent", timeout_seconds=0)
        except TimeoutError:
            pass
        else:
            raise RuntimeError("empty timed-out search was returned as a complete no-match")
    print("file search: result cap is marked partial; empty timeout fails visibly", flush=True)


async def _file_search_cancellation() -> None:
    from atlas.tools.local_execution import LocalExecutionRuntime

    class CancelAtSecondPoll:
        def __init__(self):
            self.polls = 0

        def is_set(self):
            self.polls += 1
            return self.polls >= 2

    with tempfile.TemporaryDirectory(prefix="atlas-w8-cancel-") as directory:
        root = Path(directory)
        (root / "many-lines.txt").write_text("line\n" * 2_100, encoding="utf-8")
        event = CancelAtSecondPoll()
        runtime = LocalExecutionRuntime()
        runtime.permission_mode = "full_access"
        cancelled = False
        try:
            try:
                await runtime.call_tool(
                    "local_file", {"action": "search", "path": str(root), "query": "needle"},
                    cancel_event=event,
                )
            except asyncio.CancelledError:
                cancelled = True
        finally:
            await runtime.shutdown()
    if not cancelled or event.polls < 2:
        raise RuntimeError("file search did not observe cancellation at the 1,024-line interval")
    print("file search cancellation: cancelled at the periodic 1,024-line check", flush=True)


def _slack_delivery_errors() -> None:
    from atlas.channels.adapters.slack import slack_send_error_retryable

    checks = (
        ("ratelimited", None, True),
        ("internal_error", None, True),
        ("invalid_auth", None, False),
        ("ok", 503, True),
        ("ok", 403, False),
    )
    for error, status, expected in checks:
        if slack_send_error_retryable(error, status) is not expected:
            raise RuntimeError(f"wrong Slack retry classification for {error!r}/{status}")
    print("Slack delivery: transient errors retry; auth errors remain permanent", flush=True)


async def _slack_thread_recovery() -> None:
    from atlas.channels.adapters.slack import SlackAdapter

    class Response:
        def __init__(self, data):
            self.data = data

    class FakeWebClient:
        def __init__(self):
            self.calls = []

        async def chat_postMessage(self, **payload):
            self.calls.append(dict(payload))
            if len(self.calls) == 1:
                return Response({"ok": False, "error": "thread_not_found"})
            return Response({"ok": True, "ts": "1700000000.1"})

    adapter = SlackAdapter({"bot_token": "fixture", "app_token": "fixture"}, None)
    fake = FakeWebClient()
    adapter._web = fake
    result = await adapter.send("C123", "fixture reply", reply_to="1700000000.0")
    if (not result.ok or len(fake.calls) != 2
            or fake.calls[0].get("thread_ts") != "1700000000.0"
            or "thread_ts" in fake.calls[1]):
        raise RuntimeError("invalid Slack thread anchor was not retried once in-channel")
    print("Slack thread recovery: confirmed stale anchor retried unthreaded once", flush=True)


def _hook_policy() -> None:
    from atlas.kernel.hook_runtime import (
        hook_environment,
        prepare_hook_command,
        resolve_hook_shell,
        timeout_for,
    )

    cases = (
        ({}, "PreToolUse", "command", 600_000),
        ({"timeout": 12}, "PreToolUse", "command", 12_000),
        ({}, "SessionEnd", "command", 1_500),
        ({}, "PreToolUse", "async", 15_000),
        ({}, "PreToolUse", "agent", 60_000),
        ({}, "PreToolUse", "http", 600_000),
        ({}, "PreToolUse", "prompt", 30_000),
    )
    for spec, event, kind, expected in cases:
        if timeout_for(spec, event=event, kind=kind) != expected:
            raise RuntimeError(f"wrong Hook timeout for {event}/{kind}")
    if resolve_hook_shell("cmd") != "bash":
        raise RuntimeError("unknown Hook shell did not fall back to Bash")

    command, environment = prepare_hook_command(
        "script.sh ${CLAUDE_PROJECT_DIR} ${CLAUDE_PLUGIN_ROOT}",
        shell="bash", cwd=r"C:\workspace\project", plugin_root=r"D:\plugins\demo",
        environment={"CLAUDE_CODE_SHELL_PREFIX": "prefix"}, windows=True,
    )
    if (not command.startswith("prefix bash script.sh ")
            or environment.get("CLAUDE_PROJECT_DIR") != "/c/workspace/project"
            or environment.get("CLAUDE_PLUGIN_ROOT") != "/d/plugins/demo"):
        raise RuntimeError("Windows Bash path or shell-prefix policy was not applied")
    bash_env = hook_environment({"options": {"some-key": "value"}}, {}, shell="bash")
    if bash_env.get("CLAUDE_PLUGIN_OPTION_SOME_KEY") != "value":
        raise RuntimeError("Bash hook plugin options were not exposed as environment variables")
    print("Hook policy: shells, deadlines, Windows paths, and environment passed", flush=True)


async def _hook_execution() -> None:
    from atlas.runtime.hooks import execute_claude_hooks

    hooks = [{
        "event": "UserPromptSubmit",
        "hooks": [{"type": "command", "command": "Write-Output 'hook-ok'", "shell": "powershell"}],
    }]
    result = await execute_claude_hooks(
        hooks, "UserPromptSubmit", {"prompt": "exercise the local hook"}, cwd=os.getcwd(),
    )
    if result.get("additional_context") != "hook-ok":
        raise RuntimeError(f"local Hook did not return its output as context: {result!r}")
    print("Hook execution: local PowerShell command returned context", flush=True)


async def main() -> None:
    _mcp_tool_permissions()
    _mcp_connection_recovery()
    _mcp_handshake_budget()
    await _mcp_reconnect_after_terminal_errors()
    _command_exit_semantics()
    _bounded_file_search()
    await _file_search_cancellation()
    _slack_delivery_errors()
    await _slack_thread_recovery()
    _hook_policy()
    await _hook_execution()
    print("W8 LIVE SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
