"""Official Claude Agent SDK backend boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.runtime.backends import ACPBackend

# Same reasoning as the Codex backend: prefer the installed ACP adapter over an
# ``npx --yes`` fetch, which needs the registry on every single start.
_PACKAGE = "@agentclientprotocol/claude-agent-acp"
_FALLBACK_VERSION = "0.81.2"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _local_entry() -> Path | None:
    base = _repo_root() / "node_modules" / "@agentclientprotocol" / "claude-agent-acp"
    for relative in ("dist/index.js", "dist/cli.js", "index.js"):
        candidate = base / relative
        if candidate.is_file():
            return candidate
    return None


def sdk_available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def create() -> ACPBackend:
    entry = _local_entry()
    if entry is not None:
        from atlas.tools.node_runtime import resolve_node_runtime

        runtime = resolve_node_runtime()
        executable = str(runtime.executable) if runtime.executable else "node"
        return ACPBackend("claude", executable, [str(entry)])
    return ACPBackend("claude", "npx", ["--yes", f"{_PACKAGE}@{_FALLBACK_VERSION}"])


async def run(prompt: str, *, cwd: str | None = None) -> list[Any]:
    """Run one SDK request; account/API configuration is resolved by the SDK."""
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(cwd=cwd) if cwd else ClaudeAgentOptions()
    return [message async for message in query(prompt=prompt, options=options)]
