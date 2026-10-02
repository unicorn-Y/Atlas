"""C4 最小验收：插件安装后 command / hook / skill / MCP 各跨一次真实 runtime 路径。

hook 腿最重：Claude 格式插件经 PluginRuntime.install_local → enabled_contributions
→ HookStore(plugin_hooks=…) → AgentOrchestrator._execute_tools_node（run() 的同一
工具执行链），插件的 PreToolUse hook 真实阻断工具调用。skill 腿走共享 SkillManager
来源；command 腿走 list_user_commands/render；MCP 腿走 load_all 的
MCPServerConfig 注册路径（连接桩只记录，不起真服务）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from atlas.agent import AgentOrchestrator
from atlas.plugins.runtime import PluginRuntime
from atlas.runtime.commands import CommandSource, list_user_commands, render_user_command
from atlas.runtime.hooks import HookStore
from atlas.skills import SkillManager, plugin_skill_sources


def _make_plugin(source: Path, python: str, deny_script: Path) -> None:
    (source / ".claude-plugin").mkdir(parents=True)
    (source / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "audit", "version": "1.0.0", "description": "审计插件",
    }), encoding="utf-8")
    (source / "hooks").mkdir()
    (source / "hooks" / "hooks.json").write_text(json.dumps({
        "PreToolUse": [{
            "matcher": "run_checks",
            "hooks": [{"type": "command", "command": python, "args": [str(deny_script)]}],
        }],
    }), encoding="utf-8")
    skill = source / "skills" / "audit-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: audit-skill\ndescription: 插件审计技能\n---\n插件审计指令正文\n",
        encoding="utf-8",
    )
    commands = source / "commands"
    commands.mkdir()
    (commands / "check.md").write_text(
        "---\ndescription: 审计目标\n---\n审计 $ARGUMENTS\n", encoding="utf-8",
    )
    (source / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"audit-mcp": {"command": python, "args": ["-c", "print('mcp')"]}},
    }), encoding="utf-8")


def _deny_script(path: Path) -> None:
    path.write_text(
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',"
        " 'permissionDecision': 'deny', 'permissionDecisionReason': '插件审计：禁止运行检查'}}))\n",
        encoding="utf-8",
    )


def _tool_runtime(tmp_path: Path, callback: Any) -> SimpleNamespace:
    return SimpleNamespace(
        cancel_event=None, pause_event=None, approval_callback=None,
        event_queue=asyncio.Queue(), workspace=str(tmp_path),
        permission_mode="full_access", allowed_paths=[], run_id="run-1",
        conversation_id="conv-1", user_hook_callback=callback,
        tool_allow=None, tool_deny=[], read_only=False, mode="act",
        maintenance_context={},
    )


def _tool_state(name: str, args: dict[str, Any], runtime: Any):
    return {
        "messages": [AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": "tc-1"},
        ])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    }


class _StubMcpClient:
    """记录 load_all 真实构造的 MCPServerConfig，不起真实 MCP 服务。"""

    def __init__(self) -> None:
        self.connected: list[Any] = []

    def get_server_names(self) -> list[str]:
        return []

    async def _connect_server(self, config: Any) -> None:
        self.connected.append(config)


class _StubCapabilities:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def register(self, name: str, **_kwargs: Any) -> None:
        self.registered.append(name)


@pytest.mark.asyncio
async def test_installed_plugin_crosses_real_runtime_paths(tmp_path: Path) -> None:
    python = sys.executable
    deny = tmp_path / "deny.py"
    _deny_script(deny)
    source = tmp_path / "plugin-source" / "audit"
    _make_plugin(source, python, deny)

    plugins_dir = tmp_path / "installed"
    runtime = PluginRuntime([plugins_dir], tmp_path / "plugins-state.json")
    runtime.install_local(source)

    mcp_client = _StubMcpClient()
    capabilities = _StubCapabilities()
    report = await runtime.load_all(mcp_client=mcp_client, capabilities=capabilities)
    assert report["loaded"] == ["audit"]
    contributions = runtime.enabled_contributions()
    assert len(contributions) == 1
    plugin = contributions[0]
    assert plugin["name"] == "audit"

    # -- hook 腿：插件 hook 经 HookStore 进入真实 agent 工具执行链并阻断 --
    store = HookStore(
        tmp_path / "hooks.toml",
        plugin_hooks=lambda: [hook for item in contributions for hook in item["hooks"]],
    )

    async def user_hook(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await store.execute(event_name, payload, cwd=str(tmp_path))

    agent = AgentOrchestrator(MagicMock(), MagicMock())
    result = await agent._execute_tools_node(_tool_state(
        "run_checks", {"target": "core"}, _tool_runtime(tmp_path, user_hook),
    ))
    assert result["pending_events"][0]["is_error"] is True
    assert "禁止运行检查" in result["messages"][0].content

    # -- skill 腿：插件 skills 进入共享 SkillManager（同一 registry，无第二套） --
    manager = SkillManager(tmp_path / "bundled")
    manager.replace_skill_sources(
        "plugin:", plugin_skill_sources({plugin["name"]: plugin["skills"]}))
    manager.scan_skills_sync()
    skill = manager.get_skill("audit-skill")
    assert skill is not None and skill.source.startswith("plugin:")
    assert await manager.activate("audit-skill") == "插件审计指令正文\n"

    # -- command 腿：插件 commands 经共享命令发现层列出并渲染 --
    commands = list_user_commands(
        plugin_sources=[CommandSource("plugin:audit", Path(item), 60, plugin=True)
                        for item in plugin["command_sources"]],
    )
    audit = next(item for item in commands if item.name == "plugin:audit:check")
    assert render_user_command(audit, "core 模块").prompt == "审计 core 模块\n"

    # -- MCP 腿：load_all 把插件 .mcp.json 注册为真实 MCPServerConfig --
    assert "plugin.audit.skill.audit-skill" in capabilities.registered
    assert "plugin.audit.command.check" in capabilities.registered
    assert [config.name for config in mcp_client.connected] == ["audit-mcp"]
    config = mcp_client.connected[0]
    assert config.command == python
    assert config.cwd == str(Path(plugin["root"]))
