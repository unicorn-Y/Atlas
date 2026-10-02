"""Discovery and on-demand rendering for user-authored slash commands."""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSource:
    name: str
    root: Path
    priority: int
    plugin: bool = False


@dataclass(frozen=True)
class UserCommand:
    id: str
    name: str
    description: str
    argument_hint: str
    source: str
    source_priority: int
    path: str | None = None
    recipe_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "argument_hint": self.argument_hint, "source": self.source,
            "source_priority": self.source_priority,
            "recipe_id": self.recipe_id,
        }


@dataclass
class RenderedCommand:
    prompt: str
    model: str | None = None
    tool_allow: list[str] | None = None
    tool_deny: list[str] = field(default_factory=list)
    mode: str | None = None
    active_skills: list[str] = field(default_factory=list)
    workspace: str | None = None
    profile_id: str | None = None


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text
    metadata = yaml.safe_load(parts[1]) or {}
    if not isinstance(metadata, dict):
        raise ValueError("command frontmatter must be a mapping")
    return metadata, parts[2].lstrip("\r\n")


def _read_command(source: CommandSource, path: Path) -> UserCommand:
    raw = path.read_text(encoding="utf-8")
    try:
        metadata, _body = _frontmatter(raw)
    except ValueError as exc:
        # One malformed command file must not take down the whole listing.
        raise LookupError(f"{path}: {exc}") from exc
    relative = path.relative_to(source.root).with_suffix("").as_posix()
    local_name = relative.replace("/", ":")
    if source.plugin:
        local_name = f"{source.name}:{local_name}"
    argument_hint = metadata.get("argument-hint") or ""
    if isinstance(argument_hint, list):
        argument_hint = " ".join(str(item) for item in argument_hint)
    return UserCommand(
        id=f"{source.name}:{relative}", name=local_name,
        description=str(metadata.get("description") or "").strip(),
        argument_hint=str(argument_hint).strip(),
        source=source.name, source_priority=source.priority, path=str(path),
        metadata={key: metadata[key] for key in (
            "arguments", "allowed-tools", "disallowed-tools", "model",
            "disable-model-invocation", "user-invocable", "mode",
        ) if key in metadata},
    )


def list_user_commands(
    workspace: Path | None = None,
    user_dir: Path | None = None,
    plugin_sources: Sequence[CommandSource] = (),
    recipes: Sequence[dict[str, Any]] = (),
) -> list[UserCommand]:
    """Return summaries for Atlas, Claude, plugin, and Recipe commands.

    Command bodies are read only while rendering a selected command. Higher
    source priority wins same-name collisions; ties use source name and path.
    """
    sources: list[CommandSource] = []
    if user_dir is not None:
        sources.append(CommandSource("atlas", Path(user_dir) / "commands", 50))
        sources.append(CommandSource("claude-user", Path(user_dir) / ".claude" / "commands", 40))
    if workspace is not None:
        root = Path(workspace)
        sources.extend((
            CommandSource("claude-project", root / ".claude" / "commands", 30),
            CommandSource("agents-project", root / ".agents" / "commands", 20),
        ))
    sources.extend(plugin_sources)

    candidates: list[UserCommand] = []
    for source in sources:
        if not source.root.is_dir():
            continue
        for path in sorted(source.root.rglob("*.md"), key=lambda item: item.as_posix().casefold()):
            try:
                candidates.append(_read_command(source, path))
            except LookupError as exc:
                logger.warning("skipping malformed command file: %s", exc)

    for recipe in recipes:
        recipe_id = str(recipe.get("id", ""))
        name = str(recipe.get("name", "")).strip()
        if not recipe_id or not name:
            continue
        params = recipe.get("params", [])
        hint = " ".join(f"[{item['name']}]" for item in params if isinstance(item, dict) and item.get("name"))
        candidates.append(UserCommand(
            id=f"recipe:{recipe_id}", name=f"recipe:{name}",
            description=str(recipe.get("description") or "Atlas 配方"),
            argument_hint=hint, source="recipe", source_priority=5,
            recipe_id=recipe_id,
        ))

    winners: dict[str, UserCommand] = {}
    for command in sorted(candidates, key=lambda item: (-item.source_priority, item.source, item.id)):
        winners.setdefault(command.name.casefold(), command)
    return sorted(winners.values(), key=lambda item: (item.name.casefold(), item.id))


def _list_value(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [item for item in re.split(r"[\s,]+", value.strip()) if item]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("command tool metadata must be a string or list of strings")


def _render_template(template: str, arguments: str, names: Any) -> str:
    try:
        values = shlex.split(arguments)
    except ValueError:
        values = arguments.split()
    replacements = {"ARGUMENTS": arguments}
    # Claude Code convention: $1..$n are positional; $0 kept as an alias of $1.
    replacements.update({str(index): value for index, value in enumerate(values, start=1)})
    if values:
        replacements["0"] = values[0]
    if isinstance(names, str):
        names = names.split()
    if isinstance(names, list):
        replacements.update({str(name): values[index] for index, name in enumerate(names)
                             if isinstance(name, str) and index < len(values)})
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*|\d+)",
                  lambda match: replacements.get(match.group(1), match.group(0)), template)


def render_user_command(
    command: UserCommand,
    arguments: str = "",
    *,
    recipes: Sequence[dict[str, Any]] = (),
    recipe_renderer: Callable[[dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
) -> RenderedCommand:
    """Load a selected body and expand Claude positional placeholders."""
    if command.recipe_id:
        recipe = next((item for item in recipes if str(item.get("id")) == command.recipe_id), None)
        if recipe is None:
            raise KeyError(f"Unknown Recipe: {command.recipe_id}")
        params = recipe.get("params", [])
        values = shlex.split(arguments) if arguments else []
        supplied = {str(item["name"]): values[index] for index, item in enumerate(params)
                    if isinstance(item, dict) and item.get("name") and index < len(values)}
        rendered = recipe_renderer(recipe, supplied) if recipe_renderer else {"prompt": recipe.get("prompt", "")}
        return RenderedCommand(
            prompt=str(rendered.get("prompt", "")),
            mode=rendered.get("mode", recipe.get("mode")),
            active_skills=list(rendered.get("active_skills", recipe.get("active_skills", []))),
            workspace=rendered.get("workspace", recipe.get("workspace")),
            profile_id=rendered.get("profile_id", recipe.get("profile_id")),
        )

    if command.path is None:
        raise ValueError("command has no source file")
    metadata, body = _frontmatter(Path(command.path).read_text(encoding="utf-8"))
    allowed_tools = _list_value(metadata.get("allowed-tools"))
    denied_tools = _list_value(metadata.get("disallowed-tools")) or []
    model = metadata.get("model")
    mode = metadata.get("mode")
    return RenderedCommand(
        prompt=_render_template(body, arguments, metadata.get("arguments")),
        model=str(model) if model else None,
        tool_allow=allowed_tools,
        tool_deny=denied_tools,
        mode=str(mode) if mode in {"act", "plan"} else None,
    )
