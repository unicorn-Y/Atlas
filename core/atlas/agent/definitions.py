# Format mapping based on official OpenHands, Claude Code, OpenCode, Codex, and
# GitHub Copilot agent-file documentation; Atlas-specific parsing and built-ins.
# Sources: docs.openhands.dev/sdk/guides/agent-file-based,
# code.claude.com/docs/en/sub-agents, opencode.ai/v2/docs/agents,
# github.com/openai/codex/blob/main/codex-rs/config/src/config_toml.rs,
# docs.github.com/en/copilot/reference/custom-agents-configuration.
"""Agent type definitions and import adapters for supported agent-file formats."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml


BUILTINS: dict[str, dict[str, Any]] = {
    "explore": {"description": "快速调查代码或资料，回结论和证据位置", "tools": ["local_file", "git_*", "mcp__git__*"], "model": "fast", "role": "leaf", "permission_mode": "read_only"},
    "researcher": {"description": "网上调研，回带出处的结论", "tools": ["web_search", "web_fetch"], "model": "inherit", "role": "leaf", "permission_mode": "read_only"},
    "plan": {"description": "给实施方案，不动手", "tools": ["local_file", "git_*", "mcp__git__*"], "model": "inherit", "role": "leaf", "permission_mode": "read_only"},
    "oracle": {"description": "深度分析难 bug、架构取舍和方案", "tools": ["local_file", "git_*", "mcp__git__*"], "model": "strong", "role": "leaf", "permission_mode": "read_only"},
    "verifier": {"description": "对照成功标准验收并说明原因", "tools": ["local_file", "git_*", "mcp__git__*", "run_checks", "local_process"], "model": "inherit", "role": "leaf", "permission_mode": "ask_writes"},
    "general": {"description": "通用子 Agent", "tools": None, "model": "inherit", "role": "leaf"},
}

_NAME = re.compile(r"^[a-z0-9-]+(?::[a-z0-9-]+)?$")
_KNOWN = {"name", "description", "tools", "model", "role", "permission_mode", "skills", "mcp", "max_turns", "output_schema", "mode", "prompt", "developer_instructions", "sandbox_mode", "approval_policy", "nickname_candidates"}


def _markdown(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    _, front, body = raw.split("---", 2)
    data = yaml.safe_load(front) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    data["prompt"] = body.strip()
    return data


def _normalize(name: str, raw: dict[str, Any], source: str, path: Path | None,
               trusted: bool) -> dict[str, Any]:
    warnings = [f"unknown field: {key}" for key in raw if key not in _KNOWN]
    candidate = str(raw.get("name") or name)
    description = str(raw.get("description") or "").strip()
    if not _NAME.fullmatch(candidate):
        warnings.append("invalid name; skipped")
    if not description:
        warnings.append("missing description; skipped")
    tools = raw.get("tools")
    if isinstance(tools, str):
        tools = [item.strip() for item in tools.split(",") if item.strip()]
    if isinstance(tools, dict):
        tools = [key for key, enabled in tools.items() if enabled is True]
    if tools is not None and not isinstance(tools, list):
        warnings.append("tools must be a list, comma-separated string, or boolean map")
        tools = None
    role = raw.get("role", "leaf")
    if role not in {"leaf", "orchestrator"}:
        warnings.append("invalid role; using leaf")
        role = "leaf"
    model = raw.get("model", "inherit")
    if model not in {"inherit", "fast", "strong"} and not isinstance(model, str):
        warnings.append("invalid model; using inherit")
        model = "inherit"
    permission_mode = raw.get("permission_mode")
    if permission_mode is not None and permission_mode not in {"full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only"}:
        warnings.append("invalid permission_mode; ignored")
        permission_mode = None
    prompt = str(raw.get("prompt", raw.get("developer_instructions", "")))
    return {"name": candidate, "description": description, "tools": tools,
            "model": model, "role": role,
            "permission_mode": permission_mode,
            "skills": raw.get("skills", []), "mcp": raw.get("mcp", []),
            "max_turns": raw.get("max_turns"), "output_schema": raw.get("output_schema"),
            "prompt": prompt, "source": source,
            "path": str(path) if path else None, "trusted": trusted,
            "warnings": warnings}


def list_agent_types(data_root: Path, workspace: Path | None = None,
                     workspace_trusted: bool = False,
                     plugin_agent_dirs: tuple[Path, ...] | list[Path] = ()) -> list[dict[str, Any]]:
    """Load built-ins then user/workspace imports; later definitions replace earlier."""
    entries = {name: _normalize(name, {"name": name, **value}, "builtin", None, True)
               for name, value in BUILTINS.items()}
    paths: list[tuple[Path, str, str]] = []
    paths.extend((p, "codex", "toml") for p in sorted((Path.home() / ".codex/agents").glob("*.toml")))
    paths.extend((p, "copilot", "markdown") for p in sorted((Path.home() / ".copilot/agents").glob("*.agent.md")))
    paths.extend((p, "user", "markdown") for p in sorted((data_root / "agents").glob("*.md")))
    if workspace:
        paths.extend((p, "claude", "markdown") for p in sorted((workspace / ".claude/agents").glob("*.md")))
        paths.extend((p, "opencode", "markdown") for parent in (".opencode/agent", ".opencode/agents") for p in sorted((workspace / parent).glob("*.md")))
        paths.extend((p, "copilot", "markdown") for p in sorted((workspace / ".github/agents").glob("*.agent.md")))
        paths.extend((p, "codex", "toml") for p in sorted((workspace / ".codex/agents").glob("*.toml")))
        paths.extend((p, "workspace", "markdown") for p in sorted((workspace / ".atlas/agents").glob("*.md")))
    for agents_dir in plugin_agent_dirs:
        plugin_name = Path(agents_dir).parent.name.lower()
        paths.extend((p, f"plugin:{plugin_name}", "markdown")
                     for p in sorted(Path(agents_dir).glob("*.md")))
    for path, source, kind in paths:
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8")) if kind == "toml" else _markdown(path)
            if source == "opencode" and raw.get("mode") == "primary":
                continue
            name = str(raw.get("name") or path.name.split(".")[0]).lower()
            if source.startswith("plugin:"):
                name = f"{source.split(':', 1)[1]}:{name}"
            in_workspace = bool(workspace and path.resolve().is_relative_to(workspace.resolve()))
            normalized = _normalize(name, raw, source, path, not in_workspace or workspace_trusted)
            if "skipped" not in " ".join(normalized["warnings"]):
                entries[name] = normalized
        except (OSError, ValueError, yaml.YAMLError) as exc:
            name = path.stem.lower()
            entries[name] = _normalize(name, {"description": f"读取失败: {exc}"}, source, path, False)
            entries[name]["warnings"].append("definition could not be parsed")
    return list(entries.values())
