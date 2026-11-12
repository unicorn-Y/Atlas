# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/agents_md.rs (Apache-2.0)
# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/context/builder.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/memory and https://code.claude.com/docs/en/skills
"""Ordered context sections with an explicitly registered stable prefix."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from atlas.agent.prompt_cache_boundary import register_stable_prefix


def discover_rules(workspace: str | Path, *, max_bytes: int = 32_768,
                   trusted: bool = True) -> str:
    """Load trusted rule files in root-to-cwd order under one byte budget.

    Codex project instructions stop at the nearest ``.git`` ancestor (or the
    cwd when there is no marker). Claude memory files also apply above that
    project root. Within a directory Claude files precede AGENTS files;
    ``AGENTS.override.md`` replaces ``AGENTS.md`` at that level.
    """
    if not trusted or max_bytes <= 0:
        return ""
    cwd = Path(workspace).resolve()
    ancestors = list(reversed([cwd, *cwd.parents]))
    nearest_first = [cwd, *cwd.parents]
    project_root = next((p for p in nearest_first if (p / ".git").exists()), cwd)
    project_ancestors = [p for p in ancestors if p == project_root or project_root in p.parents]
    chunks: list[str] = []
    seen: set[Path] = set()
    remaining = max_bytes

    def append_files(candidates: Sequence[Path]) -> None:
        nonlocal remaining
        for path in candidates:
            if remaining <= 0:
                break
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                with path.open("rb") as stream:
                    data = stream.read(remaining)
            except FileNotFoundError:
                continue
            seen.add(resolved)
            text = data.decode("utf-8-sig", errors="replace").strip()
            remaining -= len(data)
            if text:
                chunks.append(f"Workspace rules from {path}:\n{text}")

    append_files([Path.home() / ".claude" / "CLAUDE.md"])
    for directory in ancestors:
        candidates = [
            directory / "CLAUDE.md",
            directory / ".claude" / "CLAUDE.md",
            directory / "CLAUDE.local.md",
        ]
        if directory in project_ancestors:
            override = directory / "AGENTS.override.md"
            candidates.append(override if override.is_file() else directory / "AGENTS.md")
        candidates.append(directory / ".claude" / "AGENTS.md")
        append_files(candidates)
    return "\n\n".join(chunks)


@dataclass(slots=True)
class PromptResult:
    system_prompt: str
    messages: list[dict[str, Any]]
    stable_prefix: str


def _catalog(skills: Sequence[Any]) -> str:
    entries = []
    for skill in skills:
        if isinstance(skill, Mapping):
            name, description = skill.get("name", ""), skill.get("description", "")
        else:
            name, description = getattr(skill, "name", ""), getattr(skill, "description", "")
        if name:
            # Deliberately do not read body/content/path: skills expand only on demand.
            entries.append(f"- {name}: {' '.join(str(description).split())}")
    return "Available skills (read the selected skill only when needed):\n" + "\n".join(entries) if entries else ""


def _environment(workspace: str | Path | None, env_info: Mapping[str, Any] | None,
                 model: str) -> str:
    """Render executor-provided environment facts as a dynamic prompt section."""
    info = env_info if isinstance(env_info, Mapping) else {}

    def value(snake: str, camel: str | None = None) -> Any:
        return info.get(snake, info.get(camel) if camel else None)

    lines = ["# Environment", "You have been invoked in the following environment:"]
    cwd = value("cwd") or workspace
    if cwd:
        lines.append(f"- Primary working directory: {cwd}")
    is_git_repo = value("is_git_repository", "isGitRepository")
    git_status = value("git_status", "gitStatus")
    if is_git_repo is None and git_status is not None:
        is_git_repo = git_status != "not_repo"
    if is_git_repo is not None:
        lines.append(f"- Is a git repository: {'yes' if is_git_repo else 'no'}")
    for label, snake, camel in (
        ("Platform", "platform", None),
        ("Shell", "shell", None),
        ("OS Version", "os_version", "osVersion"),
    ):
        item = value(snake, camel)
        if item:
            lines.append(f"- {label}: {item}")
    if model:
        lines.append(f"- You are powered by the model named {model}.")

    if is_git_repo:
        git_lines = [
            "gitStatus: This is the git status at the start of the conversation. "
            "Note that this status is a snapshot in time, and will not update during the conversation."
        ]
        for label, snake, camel in (
            ("Current branch", "git_branch", "gitBranch"),
            ("Main branch (you will usually use this for PRs)", "git_main_branch", "gitMainBranch"),
            ("Git user", "git_user", "gitUser"),
        ):
            item = value(snake, camel)
            if item:
                git_lines.extend(("", f"{label}: {item}"))
        status_lines = value("git_status_lines", "gitStatusLines")
        if status_lines:
            status_text = "\n".join(str(item) for item in status_lines)
        elif git_status == "dirty":
            status_text = "(dirty)"
        elif git_status == "clean":
            status_text = "(clean)"
        else:
            status_text = "(unknown)"
        recent_commits = value("recent_commits", "recentCommits")
        commits_text = "\n".join(str(item) for item in recent_commits) if recent_commits else ""
        git_lines.extend(("", f"Status:\n{status_text}", "", f"Recent commits:\n{commits_text}"))
        lines.extend(("", "\n".join(git_lines)))

    return "\n".join(lines) if len(lines) > 2 else ""


def build_prompt(identity: str = "", tool_policy: str = "", workspace: str | Path | None = None,
                 goal: str = "", skills: Sequence[Any] = (),
                 history: Sequence[Mapping[str, Any]] = (), *, model: str = "",
                 workspace_trusted: bool = True, rules: str | None = None,
                 max_rule_bytes: int = 32_768, assembled_system_prompt: str | None = None,
                 env_info: Mapping[str, Any] | None = None) -> PromptResult:
    """Identity, policy, and rules form the stable prefix; runtime context follows.

    Pass the already assembled identity from the existing runtime to retain its
    model guidance and user instruction injection. Memory recall is assembled
    upstream (run_phases); this builder never recalls on its own.
    ``env_info`` is an executor snapshot; missing platform details are omitted
    instead of being guessed from the host running Atlas.
    """
    if assembled_system_prompt is not None:
        # run_phases already owns the full rules/skills/recall assembly. Preserve
        # its bytes and ordering; only explicit sections may be added afterward.
        stable = assembled_system_prompt
        additions = "\n\n".join(part for part in (
            identity, tool_policy, rules or "", _environment(workspace, env_info, model),
            "Current goal:\n" + goal if goal else "",
            _catalog(skills),
        ) if part)
        prompt = stable + ("\n\n" if stable and additions else "") + additions
        register_stable_prefix(stable)
        messages = [{"role": "system", "content": prompt}] if prompt else []
        messages.extend(copy.deepcopy(list(history)))
        return PromptResult(prompt, messages, stable)
    if model:
        from atlas.engine.atlas_runtime import _model_family_guidance
        identity = identity.rstrip() + "\n\nModel-family guidance: " + _model_family_guidance(model)
    rules_text = rules if rules is not None else (
        discover_rules(workspace, max_bytes=max_rule_bytes, trusted=workspace_trusted) if workspace else "")
    stable = "\n\n".join(part.strip() for part in (identity, tool_policy, rules_text) if part.strip())
    dynamic = "\n\n".join(part for part in (
        _environment(workspace, env_info, model), "Current goal:\n" + goal if goal else "",
        _catalog(skills),
    ) if part)
    prompt = stable + ("\n\n" if stable and dynamic else "") + dynamic
    register_stable_prefix(stable)
    messages = [{"role": "system", "content": prompt}] if prompt else []
    messages.extend(copy.deepcopy(list(history)))
    return PromptResult(prompt, messages, stable)
