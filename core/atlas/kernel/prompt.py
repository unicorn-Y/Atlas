# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/agents_md.rs (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/context/builder.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/memory
# Behavior from Claude Code v2.1.296 docs: https://code.claude.com/docs/en/skills
"""Ordered context sections with an explicitly registered stable prefix."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from atlas.agent.prompt_cache_boundary import register_stable_prefix


def discover_rules(workspace: str | Path, *, max_bytes: int = 32_768,
                   trusted: bool = True) -> str:
    """Root-to-cwd precedence; Codex override wins, Claude ancestors inherit."""
    if not trusted or max_bytes <= 0:
        return ""
    cwd = Path(workspace).resolve()
    ancestors = list(reversed([cwd, *cwd.parents]))
    project_root = next((p for p in [cwd, *cwd.parents] if (p / ".git").exists()), cwd)
    chunks: list[str] = []
    remaining = max_bytes
    for directory in ancestors:
        candidates: list[Path] = []
        if directory == project_root or project_root in directory.parents:
            override = directory / "AGENTS.override.md"
            candidates.append(override if override.is_file() else directory / "AGENTS.md")
        candidates.extend((directory / "CLAUDE.md", directory / ".claude" / "CLAUDE.md"))
        for path in candidates:
            if remaining <= 0:
                break
            try:
                with path.open("rb") as stream:
                    data = stream.read(remaining)
            except FileNotFoundError:
                continue
            text = data.decode("utf-8-sig", errors="replace").strip()
            remaining -= len(data)
            if text:
                chunks.append(f"Workspace rules from {path}:\n{text}")
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


def _recalls(recalls: Sequence[Any] | Mapping[str, Any]) -> str:
    # The existing MemOS context loader owns retrieval, relevancy and budget policy.
    values = recalls.get("items", []) if isinstance(recalls, Mapping) else recalls
    entries = []
    for value in values:
        if isinstance(value, str):
            if value.strip():
                entries.append(value.strip())
            continue
        if not isinstance(value, Mapping) or value.get("relevant") is False or value.get("dropped"):
            continue
        content = value.get("text") or value.get("content") or value.get("summary")
        if content:
            reference = value.get("ref") or value.get("memory_ref") or value.get("id")
            entries.append((f"[{reference}] " if reference else "") + str(content))
    return "Relevant MemOS recalls:\n" + "\n".join(entries) if entries else ""


def build_prompt(identity: str = "", tool_policy: str = "", workspace: str | Path | None = None,
                 goal: str = "", skills: Sequence[Any] = (),
                 recalls: Sequence[Any] | Mapping[str, Any] = (),
                 history: Sequence[Mapping[str, Any]] = (), *, model: str = "",
                 workspace_trusted: bool = True, rules: str | None = None,
                 max_rule_bytes: int = 32_768, assembled_system_prompt: str | None = None) -> PromptResult:
    """Identity → policy → rules → goal → skill metadata → recalls → history.

    Pass the already assembled identity from the existing runtime to retain its
    model guidance and user instruction injection. Recalls are prefiltered by
    Atlas's existing MemOS facade; this builder never performs a second recall.
    """
    if assembled_system_prompt is not None:
        # run_phases already owns the full rules/skills/recall assembly. Preserve
        # its bytes and ordering; only explicit sections may be added afterward.
        stable = assembled_system_prompt
        additions = "\n\n".join(part for part in (
            identity, tool_policy, rules or "", "Current goal:\n" + goal if goal else "",
            _catalog(skills), _recalls(recalls),
        ) if part)
        prompt = stable + ("\n\n" if stable and additions else "") + additions
        register_stable_prefix(stable)
        messages = [{"role": "system", "content": prompt}] if prompt else []
        messages.extend(copy.deepcopy(list(history)))
        return PromptResult(prompt, messages, stable)
    if model:
        from atlas.engine.hermes_runtime import _model_family_guidance
        identity = identity.rstrip() + "\n\nModel-family guidance: " + _model_family_guidance(model)
    rules_text = rules if rules is not None else (
        discover_rules(workspace, max_bytes=max_rule_bytes, trusted=workspace_trusted) if workspace else "")
    stable = "\n\n".join(part.strip() for part in (identity, tool_policy, rules_text) if part.strip())
    dynamic = "\n\n".join(part for part in (
        "Current goal:\n" + goal if goal else "", _catalog(skills), _recalls(recalls),
    ) if part)
    prompt = stable + ("\n\n" if stable and dynamic else "") + dynamic
    register_stable_prefix(stable)
    messages = [{"role": "system", "content": prompt}] if prompt else []
    messages.extend(copy.deepcopy(list(history)))
    return PromptResult(prompt, messages, stable)
