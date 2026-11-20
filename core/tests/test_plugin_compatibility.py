from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from atlas.plugins.compatibility import ATLAS_VERSION, range_satisfies
from atlas.plugins.runtime import PluginRuntime

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("version_range", "version", "expected"), [
    (">=0.1.0 <1.0.0", "0.1.0", True),
    ("0", "0.1.0", True),
    ("0.0.1 - 1.0.0", "0.1.0", True),
    ("~1", "1.5.0", True),
    ("^0", "0.1.0", True),
    ("^0.2.3", "0.2.9", True),
    ("^0.2.3", "0.3.0", False),
    ("~1.2", "1.2.9", True),
    ("1.2", "1.2.9", True),
    ("1.2", "1.3.0", False),
    ("1.2.x || >=2.0.0 <3", "2.4.0", True),
    ("^1.2.3", "1.3.0-beta.1", False),
    ("^1.2.3-beta.1", "1.2.3-beta.2", True),
    ("workspace:^1.0.0", "1.2.0", True),
])
def test_npm_semver_ranges(version_range: str, version: str, expected: bool):
    assert range_satisfies(version, version_range) is expected


def test_runtime_version_uses_atlas_package_version():
    import atlas

    assert ATLAS_VERSION == atlas.__version__


def _plugin(tmp_path, *, version="1.2.3", peer="^9.0.0"):
    root = tmp_path / "plugins" / "host-mismatch"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({
        "name": "host-mismatch", "version": version,
        "peerDependencies": {"atlas": peer},
        "mcpServers": {"fixture-mcp": {"command": "fixture-mcp"}},
    }), encoding="utf-8")
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: isolated acceptance fixture\n---\ndemo skill",
        encoding="utf-8",
    )
    return root


class _FixtureMCP:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def get_server_names(self):
        return list(self.connected)

    async def _connect_server(self, config):
        self.connected.append(config.name)

    async def disconnect_server(self, name):
        self.disconnected.append(name)
        self.connected.remove(name)


def test_peer_mismatch_blocks_validation_and_loading_until_exact_explicit_exemption(tmp_path):
    root = _plugin(tmp_path)
    runtime = PluginRuntime([root.parent], tmp_path / "plugin-state.json")
    issue = runtime.discover()[0]["compatibility"]
    assert issue == {
        "name": "host-mismatch", "version": "1.2.3", "runtime_version": ATLAS_VERSION,
        "peers": {"atlas": "^9.0.0"}, "exempted": False,
    }
    validation = runtime.validate(root)
    assert validation["valid"] is False
    assert any(item["code"] == "atlas_peer_incompatible" for item in validation["diagnostics"])
    blocked = asyncio.run(runtime.load_all())
    assert blocked["loaded"] == []
    assert blocked["skipped"] == [{"name": "host-mismatch", "reason": "incompatible peerDependencies",
                                    "compatibility": issue}]

    with pytest.raises(ValueError, match="acceptRisk=true"):
        runtime.grant_compatibility_exemption(
            "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=False,
        )
    exempted = runtime.grant_compatibility_exemption(
        "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=True,
    )
    assert exempted and exempted["exempted"] is True
    assert runtime.validate(root)["valid"] is True
    loaded = asyncio.run(runtime.load_all())
    assert loaded["loaded"] == ["host-mismatch"]

    (root / "plugin.json").write_text(json.dumps({
        "name": "host-mismatch", "version": "1.2.4",
        "peerDependencies": {"atlas": "^9.0.0"},
    }), encoding="utf-8")
    assert runtime.discover()[0]["compatibility"]["exempted"] is False
    with pytest.raises(ValueError, match="stale"):
        runtime.grant_compatibility_exemption(
            "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=True,
        )


def test_low_level_load_and_shared_contribution_projection_gate_side_effects(tmp_path):
    from atlas.agent.capabilities import AgentCapabilityRegistry

    root = _plugin(tmp_path)
    runtime = PluginRuntime([root.parent], tmp_path / "plugin-state.json")
    base_manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    base_manifest["peerDependencies"] = {"atlas": "^0.1.0"}
    (root / "plugin.json").write_text(json.dumps(base_manifest), encoding="utf-8")
    runtime._state["sources"]["host-mismatch"] = {
        "plugin_name": "host-mismatch",
        "entry": {"strict": False, "peerDependencies": {"atlas": "^9.0.0"}},
    }
    capabilities = AgentCapabilityRegistry()
    mcp = _FixtureMCP()

    assert runtime.discover()[0]["compatibility"]["peers"] == {"atlas": "^9.0.0"}

    async def scenario():
        with pytest.raises(ValueError, match="compatibility"):
            await runtime._load_one(
                root, plugin_name="host-mismatch", hook_bus=None,
                mcp_client=mcp, capabilities=capabilities,
            )
        assert capabilities.discover() == []
        assert mcp.connected == []
        assert runtime.enabled_contributions() == []

        runtime.grant_compatibility_exemption(
            "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=True,
        )
        report = await runtime.load_all(mcp_client=mcp, capabilities=capabilities)
        assert report["loaded"] == ["host-mismatch"]
        assert [row["name"] for row in capabilities.discover()] == [
            "plugin.host-mismatch.skill.demo",
        ]
        assert mcp.connected == ["fixture-mcp"]
        assert runtime.enabled_contributions()[0]["skills"]

        runtime.revoke_compatibility_exemption("host-mismatch", "1.2.3", ATLAS_VERSION)
        revoked = await runtime.reload("host-mismatch")
        assert revoked["ok"] is False
        assert "host-mismatch" not in runtime._loaded
        assert capabilities.discover() == []
        assert mcp.connected == []
        assert mcp.disconnected == ["fixture-mcp"]

        runtime.grant_compatibility_exemption(
            "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=True,
        )
        assert (await runtime.load_all(mcp_client=mcp, capabilities=capabilities))["loaded"] == ["host-mismatch"]
        (root / "plugin.json").write_text(json.dumps({
            "name": "host-mismatch", "version": "1.2.4",
            "peerDependencies": {"atlas": "^9.0.0"},
            "mcpServers": {"fixture-mcp": {"command": "fixture-mcp"}},
        }), encoding="utf-8")
        upgraded = await runtime.reload("host-mismatch")
        assert upgraded["ok"] is False
        assert "host-mismatch" not in runtime._loaded
        assert capabilities.discover() == []
        assert mcp.connected == []
        assert mcp.disconnected == ["fixture-mcp", "fixture-mcp"]

    asyncio.run(scenario())


def test_plugin_exemption_api_requires_accept_risk_and_scopes_runtime(monkeypatch, tmp_path):
    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices

    root = _plugin(tmp_path)
    runtime = PluginRuntime([root.parent], tmp_path / "plugin-state.json")
    async def reload_extensions():
        return {"loaded": [], "skipped": []}

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", reload_extensions)
    services = AppServices(plugin_runtime=runtime)

    async def scenario():
        with pytest.raises(HTTPException) as missing:
            await plugins_router.grant_plugin_compatibility_exemption(
                services, "host-mismatch", {"pluginVersion": "1.2.3", "runtimeVersion": ATLAS_VERSION},
            )
        assert missing.value.status_code == 422
        body = await plugins_router.grant_plugin_compatibility_exemption(
            services, "host-mismatch", {
                "pluginVersion": "1.2.3", "runtimeVersion": ATLAS_VERSION, "acceptRisk": True,
            },
        )
        assert body["compatibility"]["exempted"] is True
        with pytest.raises(HTTPException) as stale:
            await plugins_router.grant_plugin_compatibility_exemption(
                services, "host-mismatch", {
                    "pluginVersion": "1.2.3", "runtimeVersion": "9.9.9", "acceptRisk": True,
                },
            )
        assert stale.value.status_code == 409

    asyncio.run(scenario())


def test_isolated_http_api_grant_loads_and_revoke_disposes_plugin(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices

    root = _plugin(tmp_path)
    runtime = PluginRuntime([root.parent], tmp_path / "isolated-plugin-state.json")
    capabilities = AgentCapabilityRegistry()
    mcp = _FixtureMCP()

    async def apply_plugins():
        return await runtime.load_all(mcp_client=mcp, capabilities=capabilities)

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", apply_plugins)
    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=runtime)
    app.include_router(plugins_router.router)

    with TestClient(app) as client:
        mismatch = client.get("/api/plugins").json()["plugins"][0]["compatibility"]
        assert mismatch["exempted"] is False
        missing_risk = client.post("/api/plugins/host-mismatch/compatibility-exemption", json={
            "pluginVersion": "1.2.3", "runtimeVersion": ATLAS_VERSION,
        })
        assert missing_risk.status_code == 422

        granted = client.post("/api/plugins/host-mismatch/compatibility-exemption", json={
            "pluginVersion": "1.2.3", "runtimeVersion": ATLAS_VERSION, "acceptRisk": True,
        })
        assert granted.status_code == 200
        assert granted.json()["compatibility"]["exempted"] is True
        assert granted.json()["report"]["loaded"] == ["host-mismatch"]
        assert [row["name"] for row in capabilities.discover()] == [
            "plugin.host-mismatch.skill.demo",
        ]
        assert mcp.connected == ["fixture-mcp"]

        revoked = client.request(
            "DELETE", "/api/plugins/host-mismatch/compatibility-exemption", json={
                "pluginVersion": "1.2.3", "runtimeVersion": ATLAS_VERSION,
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["report"]["loaded"] == []
        assert revoked.json()["report"]["skipped"][0]["reason"] == "incompatible peerDependencies"
        assert capabilities.discover() == []
        assert mcp.connected == []
        assert mcp.disconnected == ["fixture-mcp"]


def _marketplace_fixture(tmp_path, *, base_peer, entry_peer):
    marketplace = tmp_path / "marketplace"
    plugin = marketplace / "plugin-source"
    (plugin / "skills" / "demo").mkdir(parents=True)
    (plugin / "skills" / "demo" / "SKILL.md").write_text("market skill", encoding="utf-8")
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "manifest-name", "version": "1.0.0",
        "peerDependencies": {"atlas": base_peer},
    }), encoding="utf-8")
    (marketplace / "marketplace.json").write_text(json.dumps({"plugins": [{
        "name": "market-alias", "source": "plugin-source", "strict": False,
        "peerDependencies": {"atlas": entry_peer},
    }]}), encoding="utf-8")
    runtime = PluginRuntime([tmp_path / "installed"], tmp_path / "market-state.json")
    runtime._state["marketplaces"]["local"] = {"type": "local", "path": str(marketplace)}
    return runtime


def test_marketplace_effective_peer_manifest_controls_validate_install_identity_and_enable(tmp_path):
    runtime = _marketplace_fixture(tmp_path, base_peer="^9.0.0", entry_peer="^0.1.0")

    validation = runtime.validate_marketplace_plugin("local", "market-alias")
    assert validation["valid"] is True
    installed = runtime.install_marketplace_plugin("local", "market-alias")
    assert installed["name"] == "market-alias"
    plugin = runtime.discover()[0]
    assert plugin["name"] == "market-alias"
    assert plugin["compatibility"] is None

    async def scenario():
        assert await runtime.set_enabled("market-alias", True)
        report = await runtime.load_all()
        assert report["loaded"] == ["market-alias"]

    asyncio.run(scenario())


def test_marketplace_overlay_mismatch_blocks_validation_and_install_before_copy(tmp_path):
    runtime = _marketplace_fixture(tmp_path, base_peer="^0.1.0", entry_peer="^9.0.0")
    validation = runtime.validate_marketplace_plugin("local", "market-alias")
    assert validation["valid"] is False
    assert any(row["code"] == "atlas_peer_incompatible" for row in validation["diagnostics"])
    with pytest.raises(ValueError, match="compatibility"):
        runtime.install_marketplace_plugin("local", "market-alias")
    assert not (tmp_path / "installed" / "market-alias").exists()


def test_failed_http_reload_refreshes_shared_skill_sources_after_version_upgrade(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.api import plugins_router
    from atlas.api.app_services import AppServices
    from atlas.skills import SkillManager, plugin_skill_sources

    root = _plugin(tmp_path)
    runtime = PluginRuntime([root.parent], tmp_path / "plugin-state.json")
    capabilities = AgentCapabilityRegistry()
    mcp = _FixtureMCP()
    skills = SkillManager(tmp_path / "empty-atlas-skills")
    runtime.grant_compatibility_exemption(
        "host-mismatch", "1.2.3", ATLAS_VERSION, accept_risk=True,
    )

    def refresh_shared_sources():
        contributions = runtime.enabled_contributions()
        by_plugin = {
            item["name"]: [Path(path) for path in item["skills"]]
            for item in contributions
        }
        skills.replace_skill_sources("plugin:", plugin_skill_sources(by_plugin))

    import atlas.server as server
    monkeypatch.setattr(server, "_refresh_extension_sources", refresh_shared_sources)
    async def reload_extensions():
        report = await runtime.load_all(mcp_client=mcp, capabilities=capabilities)
        refresh_shared_sources()
        return report

    monkeypatch.setattr(plugins_router._server(), "_reload_extensions", reload_extensions)
    async def initial_load():
        return await runtime.load_all(mcp_client=mcp, capabilities=capabilities)
    assert asyncio.run(initial_load())["loaded"] == ["host-mismatch"]
    refresh_shared_sources()
    assert any(name.startswith("plugin:host-mismatch:") for name in skills._sources)
    assert "demo" in skills._index
    assert mcp.connected == ["fixture-mcp"]

    (root / "plugin.json").write_text(json.dumps({
        "name": "host-mismatch", "version": "1.2.4",
        "peerDependencies": {"atlas": "^9.0.0"},
        "mcpServers": {"fixture-mcp": {"command": "fixture-mcp"}},
    }), encoding="utf-8")
    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=runtime)
    app.include_router(plugins_router.router)
    with TestClient(app) as client:
        response = client.post("/api/plugins/host-mismatch/reload")
        assert response.status_code == 400
    assert "host-mismatch" not in runtime._loaded
    assert capabilities.discover() == []
    assert mcp.connected == []
    assert mcp.disconnected == ["fixture-mcp"]
    assert not any(name.startswith("plugin:host-mismatch:") for name in skills._sources)
    assert "demo" not in skills._index
