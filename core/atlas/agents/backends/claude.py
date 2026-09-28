"""Official Claude Agent SDK backend boundary."""

from __future__ import annotations

from typing import Any

from atlas.runtime.backends import ACPBackend


def sdk_available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def create() -> ACPBackend:
    return ACPBackend("claude", "npx", ["--yes", "@agentclientprotocol/claude-agent-acp@0.81.2"])


async def run(prompt: str, *, cwd: str | None = None) -> list[Any]:
    """Run one SDK request; account/API configuration is resolved by the SDK."""
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(cwd=cwd) if cwd else ClaudeAgentOptions()
    return [message async for message in query(prompt=prompt, options=options)]
