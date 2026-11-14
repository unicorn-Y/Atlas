"""``GET /api/plugins/config-layers``: the HTTP face of the ordered config layers.

``PluginRuntime.config_layers`` composes profile → bundle → row-id patches;
the CLI has ``atlas plugins dump-config``. This route exposes the same
read-only preview to the desktop, and because layer values may carry secrets
it must answer through ``scrub`` — a literal ``sk-...`` row value can survive
in a patch, and the preview must never echo it verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.api.plugins_router import router as plugins_router
from atlas.plugins.runtime import PluginRuntime


def _runtime(tmp_path: Path) -> PluginRuntime:
    installed = tmp_path / "plugins"
    installed.mkdir()
    plugin = installed / "demo"
    plugin.mkdir()
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "description": "demo plugin"}),
        encoding="utf-8",
    )
    return PluginRuntime([installed], tmp_path / "state.json")


def _client(runtime: PluginRuntime) -> TestClient:
    services = AppServices()
    services.plugin_runtime = runtime
    app = FastAPI()
    app.state.services = services
    app.dependency_overrides[get_app_services] = lambda: services
    app.include_router(plugins_router)
    return TestClient(app)


def test_config_layers_route_composes_profile_bundle_and_row_patches(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.put_config_layer("profile", "writer", {
        "row:tool.terminal": {"cmd": "bash"},
        "instructions": {"text": "be brief"},
    })
    runtime.put_config_layer("bundle", "pack", {
        "row:tool.terminal": {"cmd": "pwsh"},
        "row:tool.browser": {"enabled": True},
    })
    runtime.put_config_layer("patches", "local", {
        "row:tool.terminal": {"cmd": "nu"},
    })
    response = _client(runtime).get(
        "/api/plugins/config-layers?profile=writer&bundle=pack",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["profile"] == {"row:tool.terminal": {"cmd": "bash"}, "instructions": {"text": "be brief"}}
    # Later layers replace by row id; the patch wins over bundle and profile.
    assert body["merged"]["tool.terminal"] == {"cmd": "nu"}
    assert body["merged"]["tool.browser"] == {"enabled": True}
    assert body["merged"]["instructions"] == {"text": "be brief"}


def test_config_layers_route_defaults_to_all_layers_without_query(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.put_config_layer("patches", "local", {"row:a": {"v": 1}})
    body = _client(runtime).get("/api/plugins/config-layers").json()
    assert body["patches"] == {"row:a": {"v": 1}}
    assert body["profile"] == {} and body["bundle"] == {}


def test_config_layers_route_scrubs_secret_shaped_values(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    secret = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    runtime.put_config_layer("patches", "local", {"row:relay": {"api_key": secret}})
    body = _client(runtime).get("/api/plugins/config-layers").json()
    assert secret not in json.dumps(body)
    assert secret not in str(body["patches"]["row:relay"]["api_key"])


def test_config_layers_route_without_plugin_runtime_is_503() -> None:
    services = AppServices()
    app = FastAPI()
    app.state.services = services
    app.dependency_overrides[get_app_services] = lambda: services
    app.include_router(plugins_router)
    assert TestClient(app).get("/api/plugins/config-layers").status_code == 503
