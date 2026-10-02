from pathlib import Path
import asyncio

from atlas.runtime.commands import (
    CommandSource,
    list_user_commands,
    render_user_command,
)
from atlas.skills import SkillManager, SkillSource


def _skill(root: Path, name: str, body: str, description: str | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    skill_md = directory / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description or name}\n---\n{body}",
        encoding="utf-8",
    )
    return skill_md


def test_skill_sources_use_priority_and_load_body_on_activation(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _skill(bundled, "review", "bundled instructions")
    selected = _skill(user, "review", "user instructions")
    _skill(user, "research", "research body", "Research references")

    manager = SkillManager(bundled)
    manager.register_skill_source(SkillSource("claude-user", user, 40))
    manager.scan_skills_sync()

    review = manager.get_skill("review")
    assert review and review.path == str(selected)
    assert review.source == "claude-user"
    summary = manager.list_skills()
    assert "user instructions" not in repr([item.to_dict() for item in summary])
    assert asyncio.run(manager.activate("review")) == "user instructions"


def test_user_command_frontmatter_arguments_model_and_tool_limits(tmp_path: Path) -> None:
    commands = tmp_path / ".claude" / "commands"
    commands.mkdir(parents=True)
    path = commands / "review.md"
    path.write_text(
        "---\ndescription: Review a target\nargument-hint: \"[target]\"\n"
        "arguments: [target]\nmodel: inherit\nallowed-tools: [local_file, run_checks]\n"
        "disallowed-tools: [delegate_task]\n---\nReview $target; raw=$ARGUMENTS; first=$0\n",
        encoding="utf-8",
    )
    listed = list_user_commands(workspace=tmp_path)
    assert len(listed) == 1
    assert listed[0].name == "review"
    assert listed[0].argument_hint == "[target]"

    rendered = render_user_command(listed[0], '"core module"')
    assert rendered.prompt == "Review core module; raw=\"core module\"; first=core module\n"
    assert rendered.model == "inherit"
    assert rendered.tool_allow == ["local_file", "run_checks"]
    assert rendered.tool_deny == ["delegate_task"]


def test_plugin_command_is_namespaced_and_recipe_maps_to_existing_renderer(tmp_path: Path) -> None:
    plugin_commands = tmp_path / "plugins" / "audit" / "commands"
    plugin_commands.mkdir(parents=True)
    (plugin_commands / "check.md").write_text("Check $ARGUMENTS", encoding="utf-8")
    recipes = [{
        "id": "recipe-1", "name": "Release check", "prompt": "Run checks for {{target}}",
        "params": [{"name": "target"}], "mode": "plan",
    }]
    commands = list_user_commands(
        plugin_sources=[CommandSource("audit", plugin_commands, 60, plugin=True)],
        recipes=recipes,
    )
    plugin_command = next(item for item in commands if item.source == "audit")
    assert plugin_command.name == "audit:check"
    assert render_user_command(plugin_command, "all").prompt == "Check all"

    recipe = next(item for item in commands if item.recipe_id)
    rendered = render_user_command(
        recipe, "backend", recipes=recipes,
        recipe_renderer=lambda item, values: {
            "prompt": item["prompt"].replace("{{target}}", values["target"]),
            "mode": item["mode"],
        },
    )
    assert rendered.prompt == "Run checks for backend"
    assert rendered.mode == "plan"


def test_positional_placeholders_follow_claude_convention_and_skip_malformed(tmp_path: Path) -> None:
    commands = tmp_path / ".claude" / "commands"
    commands.mkdir(parents=True)
    (commands / "two.md").write_text(
        "---\nargument-hint: \"[a] [b]\"\n---\nfirst=$1 second=$2 alias0=$0 raw=$ARGUMENTS\n",
        encoding="utf-8",
    )
    (commands / "broken.md").write_text("---\njust a string\n---\nbody\n", encoding="utf-8")
    (commands / "plain.md").write_text("No frontmatter $ARGUMENTS\n", encoding="utf-8")

    listed = list_user_commands(workspace=tmp_path)
    assert {item.name for item in listed} == {"two", "plain"}

    two = next(item for item in listed if item.name == "two")
    rendered = render_user_command(two, '"x y" z')
    assert rendered.prompt == "first=x y second=z alias0=x y raw=\"x y\" z\n"
