"""Codex backend command and protocol metadata."""

from atlas.runtime.backends import ACPBackend


def create() -> ACPBackend:
    return ACPBackend("codex", "npx", ["--yes", "@agentclientprotocol/codex-acp@1.13.1"])
