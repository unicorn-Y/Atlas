"""X4 Skill Market bridge tests — fake sources only, no network.

Covers: search, detail + preview, install (user/project scope), same-name
conflict (Chinese message + overwrite), uninstall, update single + update-all,
provenance round-trip, offline Chinese errors, the progressive-loading index
assertion, per-source taps and the router auth shape via TestClient.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.origin_guard import OriginGuard
from atlas.skills import SkillManager, SkillSource, default_skill_sources
from atlas.skills.market import (
    MarketConflictError,
    MarketError,
    MarketUnavailableError,
    SkillMarket,
)
from atlas.skills.registry import SkillRegistry

TOKEN = "test-atlas-api-token"  # conftest exports ATLAS_API_TOKEN


def skill_md(name: str, version: str, description: str, *, tags: list[str] | None = None) -> str:
    tag_line = ""
    if tags:
        tag_line = "tags:\n" + "".join(f"  - {tag}\n" for tag in tags)
    return (
        "---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {description}\n"
        f"{tag_line}"
        "---\n"
        f"# {name}\n\nBody for {name} v{version}.\n"
    )


class FakeHubSource:
    """In-memory Hermes-shaped source adapter (search/inspect/fetch/current_revision)."""

    def __init__(self, source_id: str = "fakehub") -> None:
        self.source_id_value = source_id
        self.catalog: dict[str, dict[str, str]] = {}
        self.fail = False
        self.timeout = False

    def source_id(self) -> str:
        return self.source_id_value

    def trust_level_for(self, identifier: str) -> str:  # noqa: ARG002 - Hermes shape
        return "community"

    def publish(
        self, name: str, version: str, description: str, *, extra_file: bool = False,
    ) -> None:
        files = {"SKILL.md": skill_md(name, version, description, tags=[name])}
        if extra_file:
            files["references/notes.md"] = "# notes\n"
        self.catalog[name] = {
            "version": version, "description": description, "files": files,
        }

    def _require_up(self) -> None:
        if self.timeout:
            raise TimeoutError("simulated timeout")
        if self.fail:
            raise ConnectionError("simulated offline")

    def search(self, query: str, limit: int = 10) -> list[dict]:
        self._require_up()
        results = []
        for name, entry in sorted(self.catalog.items()):
            haystack = f"{name} {entry['description']}".casefold()
            if not query.strip() or query.strip().casefold() in haystack:
                results.append({
                    "name": name,
                    "description": entry["description"],
                    "source": self.source_id_value,
                    "identifier": f"fake/{name}",
                    "trust_level": "community",
                    "tags": [name],
                    "extra": {"version": entry["version"], "author": "fake-author"},
                })
            if len(results) >= limit:
                break
        return results

    def inspect(self, identifier: str) -> dict | None:
        self._require_up()
        name = identifier.rsplit("/", 1)[-1]
        entry = self.catalog.get(name)
        if entry is None:
            return None
        return {
            "name": name, "description": entry["description"], "source": self.source_id_value,
            "identifier": identifier, "trust_level": "community", "tags": [name],
            "extra": {"version": entry["version"], "author": "fake-author"},
        }

    def fetch(self, identifier: str) -> dict | None:
        self._require_up()
        name = identifier.rsplit("/", 1)[-1]
        entry = self.catalog.get(name)
        if entry is None:
            return None
        return {
            "name": name,
            "files": dict(entry["files"]),
            "source": self.source_id_value,
            "identifier": identifier,
            "trust_level": "community",
            "metadata": {"source_url": f"https://example.invalid/{name}",
                         "source_revision": entry["version"]},
        }

    def current_revision(self, identifier: str) -> str:  # noqa: ARG002 - Hermes shape
        return ""


@pytest.fixture()
def env(tmp_path: Path):
    user_skills = tmp_path / "skills"
    workspace = tmp_path / "ws"
    registry = SkillRegistry(tmp_path / "skill-registry.db")
    manager = SkillManager(skills_dir=user_skills)
    for source in default_skill_sources(workspace=workspace, atlas_home=tmp_path):
        manager.register_skill_source(source)
    manager.scan_skills_sync()
    adapter = FakeHubSource()
    market = SkillMarket(
        registry,
        data_dir=tmp_path,
        user_skills_dir=user_skills,
        project_skills_dir=workspace / ".claude" / "skills",
        skill_manager=manager,
        adapters=[adapter],
    )
    return {
        "tmp": tmp_path, "user_skills": user_skills, "workspace": workspace,
        "registry": registry, "manager": manager, "adapter": adapter, "market": market,
    }


# ---------------------------------------------------------------------------
# Search / detail
# ---------------------------------------------------------------------------

async def test_search_and_source_filter(env):
    env["adapter"].publish("demo-skill", "1.0.0", "a demo search helper")
    env["adapter"].publish("other-skill", "1.0.0", "unrelated tooling")
    result = await env["market"].search("demo")
    assert result["count"] == 1
    assert result["results"][0]["id"] == "fake/demo-skill"
    assert result["results"][0]["installed"] is False
    assert result["status"] == "ok"
    filtered = await env["market"].search("demo", source="fakehub")
    assert filtered["count"] == 1
    with pytest.raises(MarketError):
        await env["market"].search("demo", source="no-such-source")


async def test_detail_and_preview(env):
    env["adapter"].publish("demo-skill", "1.2.0", "preview me", extra_file=True)
    detail = await env["market"].detail("fakehub", "fake/demo-skill")
    assert detail["name"] == "demo-skill"
    assert detail["version"] == "1.2.0"
    assert detail["author"] == "fake-author"
    assert sorted(detail["files"]) == ["SKILL.md", "references/notes.md"]
    assert "Body for demo-skill" in detail["skill_md_preview"]
    assert detail["source_url"] == "https://example.invalid/demo-skill"


# ---------------------------------------------------------------------------
# Install: scopes, registry provenance, progressive loading
# ---------------------------------------------------------------------------

async def test_install_user_and_project_scope_with_provenance(env):
    env["adapter"].publish("demo-skill", "1.0.0", "install me")
    user_result = await env["market"].install("fakehub", "fake/demo-skill", scope="user")
    assert user_result["status"] == "installed"
    user_dir = env["user_skills"] / "community" / "demo-skill"
    assert (user_dir / "SKILL.md").is_file()
    record = env["registry"].get("demo-skill", "1.0.0")
    provenance = record["provenance"]
    assert provenance["origin_kind"] == "marketplace"
    assert provenance["market"]["source"] == "fakehub"
    assert provenance["market"]["identifier"] == "fake/demo-skill"
    assert provenance["market"]["scope"] == "user"
    assert provenance["installed_at"] and provenance["computed_sha256"]
    assert len(provenance["computed_sha256"]) == 64

    env["adapter"].publish("proj-skill", "0.2.0", "project scope")
    project_result = await env["market"].install("fakehub", "fake/proj-skill", scope="project")
    project_dir = env["workspace"] / ".claude" / "skills" / "proj-skill"
    assert (project_dir / "SKILL.md").is_file()
    assert project_result["scope"] == "project"

    # Progressive loading unchanged: the shared index surfaces installed skills
    # from their SKILL.md frontmatter only.
    env["manager"].scan_skills_sync()
    assert env["manager"].get_skill("demo-skill") is not None
    assert env["manager"].get_skill("proj-skill") is not None

    installed = env["market"].installed()
    assert {row["name"] for row in installed} == {"demo-skill", "proj-skill"}


# ---------------------------------------------------------------------------
# Same-name conflict: local wins, Chinese message, overwrite gate
# ---------------------------------------------------------------------------

async def test_same_name_conflict_requires_overwrite(env):
    env["adapter"].publish("demo-skill", "1.0.0", "first")
    await env["market"].install("fakehub", "fake/demo-skill")
    env["adapter"].publish("demo-skill", "2.0.0", "second")
    with pytest.raises(MarketConflictError) as excinfo:
        await env["market"].install("fakehub", "fake/demo-skill")
    message = excinfo.value.message
    assert "已存在同名技能" in message and "overwrite=true" in message
    assert excinfo.value.details["local_version"] == "1.0.0"
    result = await env["market"].install("fakehub", "fake/demo-skill", overwrite=True)
    assert result["version"] == "2.0.0"


async def test_local_skill_wins_by_priority(env):
    # A local skill living directly in the managed community dir: conflict,
    # then explicit overwrite replaces it (managed payload).
    local_dir = env["user_skills"] / "community" / "local-skill"
    local_dir.mkdir(parents=True)
    (local_dir / "SKILL.md").write_text(
        skill_md("local-skill", "0.1.0", "hand made"), encoding="utf-8")
    env["manager"].scan_skills_sync()
    env["adapter"].publish("local-skill", "9.9.9", "from market")
    with pytest.raises(MarketConflictError):
        await env["market"].install("fakehub", "fake/local-skill")
    result = await env["market"].install("fakehub", "fake/local-skill", overwrite=True)
    assert result["version"] == "9.9.9"

    # A plugin-contributed local skill outranks every market scope: even
    # overwrite=true refuses, because the market version could never win.
    plugin_dir = env["tmp"] / "plugin-skills" / "local-skill"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "SKILL.md").write_text(
        skill_md("local-skill", "0.2.0", "plugin owned"), encoding="utf-8")
    env["manager"].register_skill_source(
        SkillSource("plugin:test", plugin_dir, 60, layout="single"))
    env["manager"].scan_skills_sync()
    env["adapter"].publish("local-skill", "9.9.10", "from market again")
    with pytest.raises(MarketError, match="更高优先级"):
        await env["market"].install("fakehub", "fake/local-skill", overwrite=True)


# ---------------------------------------------------------------------------
# Uninstall / enable / disable
# ---------------------------------------------------------------------------

async def test_uninstall_removes_files_and_tombstones_registry(env):
    env["adapter"].publish("demo-skill", "1.0.0", "bye")
    await env["market"].install("fakehub", "fake/demo-skill")
    result = env["market"].uninstall("demo-skill")
    assert result["status"] == "removed"
    assert not (env["user_skills"] / "community" / "demo-skill").exists()
    rows = [item for item in env["registry"].list() if item["name"] == "demo-skill"]
    assert rows and rows[0]["status"] == "disabled"
    assert rows[0]["lifecycle"]["state"] == "removed"
    assert (rows[0]["provenance"]["market"]).get("removed_at")
    with pytest.raises(MarketError, match="不是通过技能市场安装"):
        env["market"].uninstall("demo-skill")


async def test_enable_disable_round_trip(env):
    env["adapter"].publish("demo-skill", "1.0.0", "toggle")
    await env["market"].install("fakehub", "fake/demo-skill")
    disabled = env["market"].disable("demo-skill")
    assert disabled["status"] == "disabled"
    assert env["registry"].get("demo-skill", "1.0.0")["status"] == "disabled"
    enabled = env["market"].enable("demo-skill")
    assert enabled["status"] == "active"


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

async def test_update_single_with_version_bump(env):
    env["adapter"].publish("demo-skill", "1.0.0", "v1 body")
    await env["market"].install("fakehub", "fake/demo-skill")
    updates = await env["market"].check_updates()
    assert updates[0]["status"] == "up_to_date"

    env["adapter"].publish("demo-skill", "1.1.0", "v2 body with fixes")
    updates = await env["market"].check_updates()
    assert updates[0]["status"] == "update_available"
    assert updates[0]["latest_version"] == "1.1.0"

    result = await env["market"].update("demo-skill")
    assert result["status"] == "updated"
    assert result["previous_version"] == "1.0.0"
    assert result["version"] == "1.1.0"
    assert "v2 body" in (env["user_skills"] / "community" / "demo-skill" / "SKILL.md").read_text(
        encoding="utf-8")
    active = env["registry"].get("demo-skill", "1.1.0")
    assert active is not None and active["status"] == "active"
    assert env["registry"].get("demo-skill", "1.0.0") is None
    # Provenance round-trip after update: same source identity, new hash.
    provenance = env["market"].provenance("demo-skill")
    assert provenance["provenance"]["market"]["upstream_version"] == "1.1.0"
    assert provenance["provenance"]["market"]["identifier"] == "fake/demo-skill"


async def test_update_all_and_provenance_round_trip(env):
    env["adapter"].publish("skill-a", "1.0.0", "alpha")
    env["adapter"].publish("skill-b", "2.0.0", "beta")
    await env["market"].install("fakehub", "fake/skill-a")
    await env["market"].install("fakehub", "fake/skill-b")
    env["adapter"].publish("skill-a", "1.1.0", "alpha two")
    summary = await env["market"].update_all()
    assert summary["checked"] == 2
    assert summary["updated"] == 1 and summary["up_to_date"] == 1
    assert env["registry"].get("skill-a", "1.1.0")["status"] == "active"
    assert env["registry"].get("skill-b", "2.0.0")["status"] == "active"
    rows = {row["name"]: row for row in env["market"].installed()}
    assert rows["skill-a"]["version"] == "1.1.0"
    assert rows["skill-a"]["origin_kind"] == "marketplace"


# ---------------------------------------------------------------------------
# Offline behaviour: Chinese plain-language errors, UI never blocks
# ---------------------------------------------------------------------------

async def test_offline_chinese_errors(env):
    env["adapter"].publish("demo-skill", "1.0.0", "x")
    env["adapter"].fail = True
    with pytest.raises(MarketUnavailableError, match="网络"):
        await env["market"].install("fakehub", "fake/demo-skill")
    with pytest.raises(MarketUnavailableError, match="网络"):
        await env["market"].detail("fakehub", "fake/demo-skill")
    search = await env["market"].search("demo")
    assert search["status"] == "error"
    assert "fakehub" in search["unavailable_sources"]
    # A second healthy source keeps search useful (partial) while one fails.
    healthy = FakeHubSource("healthy")
    healthy.publish("demo-skill", "1.0.0", "x from healthy")
    env["market"]._injected_adapters = [env["adapter"], healthy]
    partial = await env["market"].search("demo")
    assert partial["status"] == "partial" and partial["count"] == 1
    # Update path: a timeout while refetching the recorded source degrades to
    # a Chinese plain-language error instead of blocking.
    env["adapter"].fail = False
    env["adapter"].timeout = False
    env["market"]._injected_adapters = [env["adapter"]]
    await env["market"].install("fakehub", "fake/demo-skill")
    env["adapter"].timeout = True
    with pytest.raises(MarketUnavailableError, match="超时"):
        await env["market"].update("demo-skill")


# ---------------------------------------------------------------------------
# Local-origin registration (X2 recordings / X5 evolved skills)
# ---------------------------------------------------------------------------

def test_register_local_origin_kinds(env):
    bundle = env["tmp"] / "recorded" / "my-recording"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        skill_md("my-recording", "0.1.0", "recorded by X2"), encoding="utf-8")
    result = env["market"].register_local(
        "my-recording", path=bundle, origin_kind="local_recorded")
    assert result["status"] == "registered"
    provenance = env["market"].provenance("my-recording")
    assert provenance["origin_kind"] == "local_recorded"
    assert provenance["provenance"]["installed_path"] == str(bundle.resolve())
    rows = [row for row in env["market"].installed() if row["name"] == "my-recording"]
    assert rows and rows[0]["origin_kind"] == "local_recorded"

    evolved = env["tmp"] / "evolved" / "my-recording"
    evolved.mkdir(parents=True)
    (evolved / "SKILL.md").write_text(
        skill_md("my-recording", "0.2.0", "evolved by X5"), encoding="utf-8")
    env["market"].register_local("my-recording", path=evolved, origin_kind="local_evolved")
    assert env["registry"].get("my-recording", "0.2.0") is not None
    with pytest.raises(MarketError, match="origin_kind"):
        env["market"].register_local(
            "my-recording", path=evolved, origin_kind="bogus")


# ---------------------------------------------------------------------------
# Sources (taps) — directory taps offline, github taps through the hub
# ---------------------------------------------------------------------------

def test_directory_tap_source_and_management(env):
    tap_dir = env["tmp"] / "tap"
    tap_dir.mkdir()
    (tap_dir / "tapped-skill").mkdir()
    (tap_dir / "tapped-skill" / "SKILL.md").write_text(
        skill_md("tapped-skill", "3.0.0", "from my own tap"), encoding="utf-8")
    market = env["market"]
    entry = market.add_source("my-tap", "directory", path=str(tap_dir))
    assert entry["kind"] == "directory"
    sources = market.list_sources()
    names = {item["name"] for item in sources["sources"]}
    assert {"official", "skills-sh", "clawhub", "github", "my-tap"} <= names

    # The registered tap is reachable through the normal adapter path.
    adapters = market._adapters("my-tap")
    assert len(adapters) == 1 and adapters[0].source_id() == "my-tap"
    assert [meta["identifier"] for meta in adapters[0].search("tapped")] == ["tapped-skill"]
    bundle = adapters[0].fetch("tapped-skill")
    assert bundle["files"]["SKILL.md"].startswith("---")

    with pytest.raises(MarketError, match="内置"):
        market.remove_source("skills-sh")
    assert market.remove_source("my-tap")["removed"] == "my-tap"
    with pytest.raises(MarketError):
        market.remove_source("my-tap")


async def test_directory_tap_is_installable(env):
    tap_dir = env["tmp"] / "tap2"
    (tap_dir / "tapped-skill").mkdir(parents=True)
    (tap_dir / "tapped-skill" / "SKILL.md").write_text(
        skill_md("tapped-skill", "3.1.0", "installable offline tap"), encoding="utf-8")
    market = env["market"]
    market.add_source("my-tap", "directory", path=str(tap_dir))
    installed = await market.install("my-tap", "tapped-skill", scope="user")
    assert installed["version"] == "3.1.0"
    assert installed["source"] == "my-tap"
    assert (env["user_skills"] / "community" / "tapped-skill" / "SKILL.md").is_file()
    assert env["manager"].get_skill("tapped-skill") is not None


def test_hermes_hub_state_forced_under_data_dir(env):
    """The hub taps/lock live under the Atlas data dir, never the real HERMES_HOME."""
    hermes_root = Path("D:/hermes-agent")
    if not hermes_root.is_dir():  # pragma: no cover - fork checkout missing
        pytest.skip("hermes-agent checkout not available")
    import tools.skills_hub as hub_mod

    # ``SKILLS_DIR`` is a PEP 562 dynamic attribute until forced; pop any real
    # override before and after so nothing leaks into other tests.
    hub_mod.__dict__.pop("SKILLS_DIR", None)
    try:
        market = SkillMarket(
            env["registry"], data_dir=env["tmp"], user_skills_dir=env["user_skills"],
            skill_manager=env["manager"], adapters=[env["adapter"]],
            hermes_root=hermes_root,
        )
        taps = market._hermes_taps()
        assert isinstance(taps, list)
        forced = Path(hub_mod.SKILLS_DIR)
        assert forced == env["tmp"] / "skills-hub"
        assert (env["tmp"] / "skills-hub" / ".hub" / "taps.json").is_file()
        market.add_source("github", "github", repo="example-owner/example-repo")
        entries = {tap["repo"] for tap in market._hermes_taps()}
        assert "example-owner/example-repo" in entries
        assert market.remove_source("github:example-owner/example-repo")["removed"] == \
            "github:example-owner/example-repo"
    finally:
        hub_mod.__dict__.pop("SKILLS_DIR", None)


# ---------------------------------------------------------------------------
# Router: auth shape via TestClient (OriginGuard conventions)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(env):
    from atlas.api import skills_market_router as router_module

    router_module.set_market_supplier(lambda: env["market"])
    app = FastAPI()
    app.add_middleware(OriginGuard)
    app.include_router(router_module.router)
    try:
        yield TestClient(app)
    finally:
        router_module.set_market_supplier(None)


def test_router_auth_shape_and_contract_routes(client, env):
    env["adapter"].publish("demo-skill", "1.0.0", "router smoke")
    # A web page from a foreign origin is refused (OriginGuard rule).
    assert client.get(
        "/api/skills/market/search?q=demo",
        headers={"Origin": "https://evil.example"}).status_code == 403
    # Local process (no Origin header) and token-bearing requests pass.
    response = client.get("/api/skills/market/search?q=demo")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    response = client.get(
        "/api/skills/market/search?q=demo",
        headers={"Origin": "https://evil.example", "X-Atlas-Api-Token": TOKEN})
    assert response.status_code == 200

    detail = client.get("/api/skills/market/fakehub/fake/demo-skill")
    assert detail.status_code == 200 and detail.json()["name"] == "demo-skill"
    unknown = client.get("/api/skills/market/fakehub/fake/missing")
    assert unknown.status_code == 503  # Chinese offline-style message for misses
    assert "找不到" in unknown.json()["detail"]["message"]

    installed = client.post(
        "/api/skills/market/install",
        json={"source": "fakehub", "id": "fake/demo-skill", "scope": "user"})
    assert installed.status_code == 200 and installed.json()["status"] == "installed"
    conflict = client.post(
        "/api/skills/market/install", json={"source": "fakehub", "id": "fake/demo-skill"})
    assert conflict.status_code == 409
    assert "overwrite=true" in conflict.json()["detail"]["message"]

    updates = client.get("/api/skills/updates")
    assert updates.status_code == 200 and updates.json()["count"] == 1
    assert client.post("/api/skills/market/update",
                       json={"name": "demo-skill"}).json()["status"] == "up_to_date"
    assert client.post("/api/skills/market/update-all").json()["checked"] == 1

    assert client.post("/api/skills/market/demo-skill/disable").json()["status"] == "disabled"
    assert client.post("/api/skills/market/demo-skill/enable").json()["status"] == "active"
    assert client.get("/api/skills/market/provenance/demo-skill").status_code == 200

    removed = client.delete("/api/skills/demo-skill")
    assert removed.status_code == 200 and removed.json()["status"] == "removed"
    assert client.delete("/api/skills/demo-skill").status_code == 422
