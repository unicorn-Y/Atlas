"""把依赖包归到界面分类里。没认出来的包按来源落到「后端依赖」/「桌面与界面」/「开发与测试工具」，
所以新加的依赖不登记也有归处；想换类只需在下面的表里加一行。"""

from __future__ import annotations

import re

_PIP: dict[str, str] = {
    # 外部 Agent 与协议
    "claude-agent-sdk": "agents", "agent-client-protocol": "agents",
    # 浏览器与电脑操作
    "browser-use": "automation", "cua-driver": "automation", "pywinauto": "automation",
    "mss": "automation", "pywinpty": "automation",
    # 模型接入
    "litellm": "models", "langchain-core": "models", "openai": "models", "anthropic": "models",
    "mcp": "mcp",
    # 外部渠道
    "slack-sdk": "channels", "slack-bolt": "channels", "lark-oapi": "channels",
    "dingtalk-stream": "channels", "apprise": "channels",
    # 学习与进化
    "skillopt": "learning",
    # 运行时（打包）
    "pyinstaller": "dev",
}

_NPM: dict[str, str] = {
    "@agentclientprotocol/claude-agent-acp": "agents",
    "@agentclientprotocol/codex-acp": "agents",
    "@mariozechner/pi-coding-agent": "agents",
    "@playwright/mcp": "automation",
    "chrome-devtools-mcp": "automation",
    "@ast-grep/cli": "backend",
    "electron": "runtime",
    "electron-builder": "dev",
}

_NPM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^@types/"), "dev"),
    (re.compile(
        r"^(typescript|vitest|vite|@vitejs/.*|esbuild|concurrently|cross-env|wait-on)$"), "dev"),
]


def normalize_pip(name: str) -> str:
    """PEP 503 规范名（``Foo_Bar`` → ``foo-bar``）。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def pip_category(name: str, group: str = "") -> str:
    """``group``：pyproject 的可选依赖组名（dev / channels / …），空串表示主依赖。"""
    known = _PIP.get(normalize_pip(name))
    if known:
        return known
    if group in {"dev", "release"}:
        return "dev"
    if group == "channels":
        return "channels"
    if group == "terminal":
        return "automation"
    if group == "learning":
        return "learning"
    return "backend"


def npm_category(name: str, dev: bool = False) -> str:
    known = _NPM.get(name)
    if known:
        return known
    for pattern, category in _NPM_PATTERNS:
        if pattern.match(name):
            return category
    return "dev" if dev else "desktop"
