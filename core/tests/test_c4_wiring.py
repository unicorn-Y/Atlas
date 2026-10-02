"""C4 extension wiring tests: skill sources (E2), command endpoints (E5),
plugin agents in shared discovery, external import endpoints (E6).

API-level checks against the FastAPI app with stubbed plugin runtime; all
paths stay inside tmp_path and the conftest temp home.
"""

from __future__ import annotations

import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.skills import SkillManager, default_skill_sources, plugin_skill_sources


class _StubPluginRuntime:
    """Stand-in exposing only the contribution surface the server consumes."""

    def __init__(
        self,
        contributions: list[dict] | None = None,
        discovered: list[dict] | None = None,
    ) -> None:
        self._contributions = contributions or []
        self._discovered = discovered

    def enabled_contributions(self) -> list[dict]:
        return self._contributions

    def discover(self) -> list[dict]:
        return self._discovered if self._discovered is not None else [
            {"name": item["name"]} for item in self._contributions
        ]


def _write_command(directory: Path, name: str, frontmatter: str, body: str) -> Path:
    directory.mkdir(parents=True)
    path = directory / f"{name}.md"
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# E2: skill source assembly
# ---------------------------------------------------------------------------

def test_skill_source_priority_project_beats_user(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user_skill = home / ".claude" / "skills" / "release" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text(
        "---\nname: release\ndescription: user copy\n---\nuser body", encoding="utf-8",
    )
    workspace = tmp_path / "ws"
    project_skill = workspace / ".claude" / "skills" / "release" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text(
        "---\nname: release\ndescription: project copy\n---\nproject body", encoding="utf-8",
    )

    sources = default_skill_sources(
        workspace=workspace, atlas_home=tmp_path / "atlas", user_home=home,
    )
    by_name = {source.name: source for source in sources}
    assert by_name["claude-project"].priority > by_name["claude-user"].priority
    assert "hermes" not in by_name  # opt-in only

    manager = SkillManager()
    for source in sources:
        manager.register_skill_source(source)
    manager.scan_skills_sync()

    release = manager.get_skill("release")
    assert release is not None
    assert release.source == "claude-project"
    assert release.description == "project copy"


def test_hermes_source_is_opt_in_between_atlas_and_claude(tmp_path: Path) -> None:
    hermes_dir = tmp_path / "hermes" / "skills"
    skill = hermes_dir / "dev" / "hermes-tool" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: hermes-tool\ndescription: Hermes bundled skill\n---\nbody", encoding="utf-8",
    )

    sources = default_skill_sources(
        atlas_home=tmp_path / "atlas",
        hermes_skills_dir=hermes_dir,
        user_home=tmp_path / "home",
    )
    priorities = {source.name: source.priority for source in sources}
    assert priorities["atlas"] < priorities["hermes"] < priorities["claude-user"]

    manager = SkillManager()
    for source in sources:
        manager.register_skill_source(source)
    manager.scan_skills_sync()
    hermes_skill = manager.get_skill("hermes-tool")
    assert hermes_skill is not None
    assert hermes_skill.source == "hermes"
    assert hermes_skill.category == "dev"


def test_plugin_skill_dirs_join_shared_index_as_single_sources(tmp_path: Path) -> None:
    skill_dir = tmp_path / "plugins" / "audit" / "skills" / "scanner"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: scanner\ndescription: plugin skill\n---\nbody", encoding="utf-8",
    )

    sources = plugin_skill_sources({"audit": [skill_dir]})
    assert [(item.name, item.priority, item.layout) for item in sources] == [
        ("plugin:audit:scanner", 60, "single"),
    ]

    manager = SkillManager()
    manager.replace_skill_sources("plugin:", sources)
    assert manager.get_skill("scanner") is not None


def test_plugin_skill_family_is_replaced_on_reload(tmp_path: Path) -> None:
    def make_skill(name: str) -> Path:
        directory = tmp_path / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name}\n---\nbody", encoding="utf-8",
        )
        return directory

    manager = SkillManager()
    manager.replace_skill_sources("plugin:", plugin_skill_sources({"a": [make_skill("one")]}))
    manager.replace_skill_sources("plugin:", plugin_skill_sources({"b": [make_skill("two")]}))
    assert manager.get_skill("one") is None
    assert manager.get_skill("two") is not None


# ---------------------------------------------------------------------------
# E5: command endpoints
# ---------------------------------------------------------------------------

async def test_commands_endpoints_list_and_render(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    _write_command(
        workspace / ".claude" / "commands", "review",
        'description: Review a target\nargument-hint: "[target]"\n'
        "arguments: [target]\nmodel: inherit\nallowed-tools: [local_file]\n",
        "Review $target now\n",
    )
    plugin_commands = tmp_path / "plugins" / "audit" / "commands"
    _write_command(plugin_commands, "check", "description: Plugin check\n", "Check $ARGUMENTS")
    monkeypatch.setattr(server, "plugin_runtime", _StubPluginRuntime([{
        "id": "audit", "name": "audit", "root": str(plugin_commands.parent),
        "version": "1.0.0", "description": "", "skills": [], "commands": [],
        "command_sources": [str(plugin_commands)], "agents": [], "hooks": [],
        "mcp_servers": {},
    }]))

    class _EmptyRecipeStore:
        def list(self) -> list[dict]:
            return []

    monkeypatch.setattr(server, "_task_store", lambda kind: _EmptyRecipeStore())

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/commands", params={"workspace": str(workspace)})
        assert listed.status_code == 200
        commands = listed.json()["commands"]
        names = {item["name"] for item in commands}
        assert "review" in names
        assert "plugin:audit:check" in names
        review = next(item for item in commands if item["name"] == "review")
        assert review["source"] == "claude-project"
        assert review["source_priority"] == 30

        rendered = await client.post("/api/commands/render", json={
            "id": review["id"], "arguments": "core", "workspace": str(workspace),
        })
        missing = await client.post("/api/commands/render", json={
            "id": "claude-project:nope", "workspace": str(workspace),
        })

    assert rendered.status_code == 200
    body = rendered.json()
    assert body["prompt"] == "Review core now\n"
    assert body["model"] == "inherit"
    assert body["tool_allow"] == ["local_file"]
    assert body["tool_deny"] == []
    assert body["mode"] is None
    assert missing.status_code == 404


async def test_recipe_command_renders_through_shared_recipe_renderer(
    tmp_path: Path, monkeypatch,
) -> None:
    class _RecipeStore:
        def list(self) -> list[dict]:
            return [{
                "id": "recipe-1", "name": "Release check", "description": "检查",
                "prompt": "Run checks for {{target}}", "params": [{"name": "target"}],
                "mode": "plan",
            }]

    monkeypatch.setattr(server, "_task_store", lambda kind: _RecipeStore())
    monkeypatch.setattr(server, "plugin_runtime", _StubPluginRuntime())

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/commands")
        recipe = next(item for item in listed.json()["commands"] if item["recipe_id"])
        rendered = await client.post("/api/commands/render", json={
            "id": recipe["id"], "arguments": "backend",
        })

    assert rendered.status_code == 200
    body = rendered.json()
    assert body["prompt"] == "Run checks for backend"
    assert body["mode"] == "plan"


# ---------------------------------------------------------------------------
# E5: plugin agents in the shared discovery layer
# ---------------------------------------------------------------------------

async def test_plugin_agents_reach_shared_agent_discovery(
    tmp_path: Path, monkeypatch,
) -> None:
    agents_dir = tmp_path / "plugins" / "audit" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "auditor.md").write_text(
        "---\nname: auditor\ndescription: Plugin auditor agent\n---\nAudit things.",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "plugin_runtime", _StubPluginRuntime([{
        "id": "audit", "name": "audit", "root": str(agents_dir.parent),
        "version": "1.0.0", "description": "", "skills": [], "commands": [],
        "command_sources": [], "agents": [str(agents_dir / "auditor.md")],
        "hooks": [], "mcp_servers": {},
    }]))

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/agents/types")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["types"]}
    assert "audit:auditor" in names


# ---------------------------------------------------------------------------
# E6: external import endpoints
# ---------------------------------------------------------------------------

async def test_import_endpoints_return_503_while_module_missing(monkeypatch) -> None:
    # None in sys.modules makes the lazy import fail deterministically, even
    # once atlas.runtime.external_import lands.
    monkeypatch.setitem(sys.modules, "atlas.runtime.external_import", None)
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scanned = await client.get(
            "/api/import/external/scan", params={"source": "claude"},
        )
        imported = await client.post(
            "/api/import/external", json={"source": "codex", "items": []},
        )
        bad_source = await client.get(
            "/api/import/external/scan", params={"source": "other"},
        )

    assert scanned.status_code == 503
    assert "external import module unavailable" in scanned.json()["detail"]
    assert imported.status_code == 503
    assert bad_source.status_code == 422


# ---------------------------------------------------------------------------
# E4 follow-up: marketplace error mapping
# ---------------------------------------------------------------------------

async def test_marketplace_and_enable_endpoints_map_missing_to_404(monkeypatch) -> None:
    class _MissingMarketplaceRuntime:
        def list_marketplace_plugins(self, name: str) -> list[dict]:
            raise KeyError(name)

        def discover(self) -> list[dict]:
            return []

    monkeypatch.setattr(server, "plugin_runtime", _MissingMarketplaceRuntime())
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        plugins = await client.get("/api/plugin-marketplaces/missing/plugins")
        enabled = await client.post(
            "/api/plugins/ghost/enabled", json={"enabled": False},
        )

    assert plugins.status_code == 404
    assert enabled.status_code == 404
