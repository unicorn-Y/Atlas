"""Normalized integration discovery and enablement."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CapabilityRecord:
    id: str
    kind: str
    source: str
    version: str | None
    status: str
    capabilities: list[str] = field(default_factory=list)
    enabled: bool = True
    available: bool = False
    connected: bool = False
    last_error: str | None = None
    install_method: str | None = None
    license: str | None = None
    adapter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityBus:
    """Discover selected upstream tools without importing optional runtimes."""

    def __init__(self, integrations: dict[str, Any] | None = None) -> None:
        self.integrations = integrations or {}

    def _enabled(self, key: str, default: bool = True) -> bool:
        value: Any = self.integrations
        for part in key.split("."):
            value = value.get(part, {}) if isinstance(value, dict) else {}
        return value if isinstance(value, bool) else default

    @staticmethod
    def _package_version(*names: str) -> str | None:
        for name in names:
            try:
                return importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                continue
        return None

    @staticmethod
    def _command_version(*commands: str) -> tuple[str | None, str | None]:
        for command in commands:
            executable = shutil.which(command)
            if executable is None:
                repo_root = Path(__file__).resolve().parents[3]
                package_roots = [
                    repo_root / "node_modules" / ".bin",
                    repo_root / "frontend" / "node_modules" / ".bin",
                ]
                for package_root in package_roots:
                    for suffix in (".cmd", ".exe", ""):
                        candidate = package_root / f"{command}{suffix}"
                        if candidate.is_file():
                            executable = str(candidate)
                            break
                    if executable:
                        break
            if not executable:
                continue
            try:
                invocation = [executable, "--version"]
                if executable.lower().endswith((".cmd", ".bat")):
                    invocation = ["cmd.exe", "/d", "/s", "/c", '"' + " ".join(invocation) + '"']
                result = subprocess.run(
                    invocation,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                output = (result.stdout or result.stderr).strip().splitlines()
                version = output[0][:160] if result.returncode == 0 and output else None
                return (
                    version,
                    None if version else f"{command} version probe exited {result.returncode}",
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return None, str(exc)
        return None, "Executable not found"

    @staticmethod
    def _node_version(package: str) -> str | None:
        packaged_versions = os.environ.get("ATLAS_NPM_PACKAGE_VERSIONS")
        if packaged_versions:
            try:
                value = json.loads(packaged_versions).get(package)
                if value:
                    return str(value)
            except (json.JSONDecodeError, AttributeError):
                pass
        repo_root = Path(__file__).resolve().parents[3]
        candidates = [
            repo_root / "node_modules" / package / "package.json",
            repo_root / "frontend" / "node_modules" / package / "package.json",
        ]
        try:
            for package_file in candidates:
                data = json.loads(package_file.read_text(encoding="utf-8"))
                return str(data["version"])
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            pass
        return None

    def _record(
        self,
        *,
        id: str,
        kind: str,
        source: str,
        capabilities: list[str],
        enabled: bool = True,
        version: str | None = None,
        error: str | None = None,
        install_method: str | None = None,
        license: str | None = None,
        adapter: str | None = None,
        connected: bool = False,
    ) -> CapabilityRecord:
        available = bool(version) and enabled
        if error and version and enabled:
            status = "misconfigured"
            available = False
        elif error and enabled:
            status = "missing_dependency" if error == "Executable not found" else "failed"
            available = False
        else:
            status = "disabled" if not enabled else ("ready" if available else "missing_dependency")
        return CapabilityRecord(
            id=id,
            kind=kind,
            source=source,
            version=version,
            status=status,
            capabilities=capabilities,
            enabled=enabled,
            available=available,
            connected=connected,
            last_error=error
            or (None if available or not enabled else "Dependency or executable unavailable"),
            install_method=install_method,
            license=license,
            adapter=adapter,
        )

    def discover(self) -> list[CapabilityRecord]:
        records: list[CapabilityRecord] = []

        def py(
            id: str,
            kind: str,
            package: str,
            repo: str,
            caps: list[str],
            adapter: str,
            license: str,
            config_key: str,
            install: str | None = None,
        ) -> None:
            version = self._package_version(package)
            error = (
                "DBOS_SYSTEM_DATABASE_URL is not configured"
                if id == "durable.dbos"
                and version
                and not os.environ.get("DBOS_SYSTEM_DATABASE_URL")
                else None
            )
            records.append(
                self._record(
                    id=id,
                    kind=kind,
                    source=repo,
                    version=version,
                    capabilities=caps,
                    enabled=self._enabled(config_key),
                    error=error,
                    install_method=install or f"pip: {package}",
                    license=license,
                    adapter=adapter,
                )
            )

        def cli(
            id: str,
            kind: str,
            commands: tuple[str, ...],
            repo: str,
            caps: list[str],
            adapter: str,
            license: str,
            config_key: str,
            install: str | None = None,
        ) -> None:
            version, error = self._command_version(*commands)
            if id == "agent.codex" and version:
                executable = shutil.which("codex")
                if executable:
                    invocation = [executable, "login", "status"]
                    if executable.lower().endswith((".cmd", ".bat")):
                        invocation = [
                            "cmd.exe", "/d", "/s", "/c",
                            '"' + " ".join(invocation) + '"',
                        ]
                    try:
                        auth = subprocess.run(
                            invocation, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=8, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if auth.returncode != 0 or "not logged in" in (
                            (auth.stdout or "") + (auth.stderr or "")
                        ).lower():
                            error = "Codex CLI is not authenticated"
                    except (OSError, subprocess.SubprocessError):
                        error = "Codex CLI authentication status could not be checked"
            records.append(
                self._record(
                    id=id,
                    kind=kind,
                    source=repo,
                    version=version,
                    error=error,
                    capabilities=caps,
                    enabled=self._enabled(config_key),
                    install_method=install or f"command: {commands[0]}",
                    license=license,
                    adapter=adapter,
                )
            )

        def npm(
            id: str,
            repo: str,
            package: str,
            caps: list[str],
            adapter: str,
            license: str,
            config_key: str,
        ) -> None:
            version = self._node_version(package)
            records.append(
                self._record(
                    id=id,
                    kind="mcp_server"
                    if id.startswith("mcp.")
                    else "agent_backend"
                    if id.startswith("agent.")
                    else "coding_backend",
                    source=repo,
                    version=version,
                    capabilities=caps,
                    enabled=self._enabled(config_key),
                    install_method=f"npm: {package}@{version or 'missing'}",
                    license=license,
                    adapter=adapter,
                )
            )

        records.append(
            self._record(
                id="atlas.native",
                kind="agent_backend",
                source="Atlas P18A/P7J",
                version="0.1.0",
                capabilities=["session", "tools", "stream", "cancel", "resume"],
                adapter="atlas.agent.AgentOrchestrator",
                license="UNLICENSED",
                connected=True,
            )
        )
        records.append(
            self._record(
                id="local.full_access",
                kind="local_execution",
                source="Atlas P18A",
                version="0.1.0",
                capabilities=[
                    "powershell",
                    "cmd",
                    "process",
                    "filesystem",
                    "git",
                    "stream",
                    "cancel",
                    "background",
                ],
                adapter="atlas.tools.local_execution.LocalExecutionRuntime",
                license="UNLICENSED",
                connected=True,
            )
        )
        py(
            "computer.cua",
            "computer_backend",
            "cua-driver",
            "trycua/cua",
            ["observe", "windows", "click", "type", "uia"],
            "atlas.capabilities.computer.cua_backend",
            "Apache-2.0",
            "computer.cua",
        )
        py(
            "computer.pywinauto",
            "computer_backend",
            "pywinauto",
            "pywinauto/pywinauto",
            ["uia", "semantic_controls", "invoke", "select"],
            "atlas.capabilities.computer.uia_backend",
            "BSD-3-Clause",
            "computer.pywinauto",
        )
        py(
            "browser.browser_use",
            "browser_backend",
            "browser-use",
            "browser-use/browser-use",
            ["navigate", "inspect", "fill", "click", "session", "cancel"],
            "atlas.capabilities.browser.browser_use",
            "MIT",
            "browser.browser_use",
        )
        npm(
            "mcp.playwright",
            "microsoft/playwright-mcp",
            "@playwright/mcp",
            ["browser", "dom", "accessibility"],
            "atlas.tools.mcp_client.MCPClient",
            "Apache-2.0",
            "browser.playwright_mcp",
        )
        npm(
            "mcp.chrome_devtools",
            "ChromeDevTools/chrome-devtools-mcp",
            "chrome-devtools-mcp",
            ["console", "network", "performance", "browser"],
            "atlas.tools.mcp_client.MCPClient",
            "Apache-2.0",
            "browser.devtools_mcp",
        )
        cli(
            "coding.serena",
            "coding_backend",
            ("serena",),
            "oraios/serena",
            ["symbols", "references", "semantic_edit"],
            "atlas.tools.mcp_client.MCPClient",
            "MIT",
            "coding.serena",
        )
        npm(
            "coding.ast_grep",
            "ast-grep/ast-grep",
            "@ast-grep/cli",
            ["ast_search", "rewrite", "dry_run"],
            "atlas.capabilities.coding.ast_grep",
            "MIT",
            "coding.ast_grep",
        )
        cli(
            "coding.repo_map",
            "coding_backend",
            ("aider",),
            "Aider-AI/aider",
            ["repo_map", "symbols", "dependencies"],
            "atlas.capabilities.coding.repo_map",
            "Apache-2.0",
            "coding.repo_map",
            "pipx: aider-chat",
        )
        py(
            "durable.dbos",
            "durable_backend",
            "dbos",
            "dbos-inc/dbos-transact-py",
            ["workflow", "checkpoint", "resume", "cancel"],
            "atlas.capabilities.durable.dbos_backend",
            "MIT",
            "durable.dbos",
        )
        py(
            "agent.acp",
            "agent_backend",
            "agent-client-protocol",
            "agentclientprotocol/python-sdk",
            ["session", "stream", "cancel", "resume"],
            "atlas.runtime.backends",
            "Apache-2.0",
            "agents.acp",
        )
        cli(
            "agent.codex",
            "agent_backend",
            ("codex",),
            "openai/codex",
            ["session", "prompt", "stream", "cancel", "resume", "cwd"],
            "atlas.agents.backends.codex",
            "Apache-2.0",
            "agents.codex",
        )
        py(
            "agent.claude",
            "agent_backend",
            "claude-agent-sdk",
            "anthropics/claude-agent-sdk-python",
            ["session", "prompt", "stream", "tool_events", "cancel", "resume"],
            "atlas.agents.backends.claude",
            "MIT",
            "agents.claude",
        )
        cli(
            "agent.hermes",
            "agent_backend",
            ("hermes",),
            "NousResearch/hermes-agent",
            ["session", "prompt", "stream", "tools"],
            "atlas.agents.backends.hermes",
            "MIT",
            "agents.hermes",
        )
        npm(
            "agent.pi",
            "badlogic/pi-mono",
            "@mariozechner/pi-coding-agent",
            ["session", "tools", "stream", "cancel"],
            "atlas.agents.backends.pi",
            "MIT",
            "agents.pi",
        )
        cli(
            "agent.zcode",
            "agent_backend",
            ("zcode",),
            "zcode-ai/zcode",
            ["session", "prompt", "stream", "cancel", "cwd"],
            "atlas.agents.backends.zcode",
            "Proprietary CLI",
            "agents.zcode",
        )
        return records

    def set_enabled(self, capability_id: str, enabled: bool) -> bool:
        record = next((item for item in self.discover() if item.id == capability_id), None)
        if record is None:
            return False
        if capability_id.startswith("agent."):
            key = "agents"
        elif capability_id.startswith("computer."):
            key = "computer"
        elif capability_id.startswith("browser.") or capability_id.startswith("mcp."):
            key = "browser"
        elif capability_id.startswith("coding."):
            key = "coding"
        elif capability_id.startswith("durable."):
            key = "durable"
        else:
            return False
        name = capability_id.split(".", 1)[1]
        if capability_id == "mcp.playwright":
            name = "playwright_mcp"
        elif capability_id == "mcp.chrome_devtools":
            name = "devtools_mcp"
        self.integrations.setdefault(key, {})[name] = enabled
        return True

    def status(self) -> dict[str, Any]:
        records = [record.to_dict() for record in self.discover()]
        return {
            "count": len(records),
            "ready": sum(item["status"] == "ready" for item in records),
            "degraded": sum(item["status"] not in {"ready", "disabled"} for item in records),
            "capabilities": records,
        }
