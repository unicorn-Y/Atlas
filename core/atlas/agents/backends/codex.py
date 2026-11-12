"""Codex backend command and protocol metadata."""

from __future__ import annotations

from pathlib import Path

from atlas.runtime.backends import ACPBackend

# Pinned fallback used only when the package is not already installed. Running the
# installed copy first matters: ``npx --yes <pkg>@<version>`` reaches the network on
# every start, so a slow or proxied registry stalls the whole session handshake
# before any prompt is sent.
_PACKAGE = "@agentclientprotocol/codex-acp"
_FALLBACK_VERSION = "1.13.1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _local_entry() -> Path | None:
    root = _repo_root() / "node_modules" / "@agentclientprotocol" / "codex-acp" / "dist" / "index.js"
    return root if root.is_file() else None


def create() -> ACPBackend:
    entry = _local_entry()
    if entry is not None:
        from atlas.tools.node_runtime import resolve_node_runtime

        runtime = resolve_node_runtime()
        executable = str(runtime.executable) if runtime.executable else "node"
        return ACPBackend("codex", executable, [str(entry)])
    return ACPBackend("codex", "npx", ["--yes", f"{_PACKAGE}@{_FALLBACK_VERSION}"])
