"""The four plugin-patch HTTP endpoints, plus the introspection method.

The module-level tests in ``test_plugin_patch_layer.py`` cover the storage model.
These cover the seam: the routes must refuse what the layer refuses, must reload
after a successful write (a patched ``SKILL.md`` nobody re-read looks like a
no-op), and must answer through the introspection provider.
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


class _FakeServer:
    """Stands in for the server object the router reaches for after a reload."""

    def __init__(self) -> None:
        self.reloads = 0

    async def _reload_extensions(self) -> dict[str, object]:
        self.reloads += 1
        return {"reloaded": True}


def _runtime(tmp_path: Path) -> PluginRuntime:
    installed = tmp_path / "plugins"
    installed.mkdir()
    plugin = installed / "demo"
    plugin.mkdir()
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0", "description": "demo plugin"}),
        encoding="utf-8",
    )
    (plugin / "skills" / "helper").mkdir(parents=True)
    (plugin / "skills" / "helper" / "SKILL.md").write_text("shipped\n", encoding="utf-8")
    return PluginRuntime([installed], tmp_path / "state.json")


def _client(monkeypatch: pytest.MonkeyPatch, runtime: PluginRuntime, tmp_path: Path) -> TestClient:
    server = _FakeServer()
    services = AppServices()
    services.plugin_runtime = runtime
    app = FastAPI()
    app.state.services = services
    app.state.server = server
    app.dependency_overrides[get_app_services] = lambda: services
    app.include_router(plugins_router)

    import atlas.api.plugins_router as module

    monkeypatch.setattr(module, "_server", lambda: server)
    return TestClient(app)


def test_listing_patches_on_a_clean_plugin_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    client = _client(monkeypatch, runtime, tmp_path)
    response = client.get("/api/plugins/demo/patches")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_listing_patches_for_an_unknown_plugin_is_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    client = _client(monkeypatch, _runtime(tmp_path), tmp_path)
    assert client.get("/api/plugins/nope/patches").status_code == 404


def test_writing_a_patch_makes_it_effective_and_reloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A patched file that nobody re-read would look like the edit did nothing."""
    runtime = _runtime(tmp_path)
    client = _client(monkeypatch, runtime, tmp_path)
    response = client.put(
        "/api/plugins/demo/patches",
        json={"path": "skills/helper/SKILL.md", "content": "mine\n", "note": "tweak"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "skills/helper/SKILL.md"
    assert body["reload"]["ok"] is True

    root = Path(runtime.discover()[0]["path"])
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "mine\n"

    read_back = client.get(
        "/api/plugins/demo/file", params={"path": "skills/helper/SKILL.md"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["content"] == "mine\n"


def test_writing_a_patch_without_content_is_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    client = _client(monkeypatch, _runtime(tmp_path), tmp_path)
    response = client.put("/api/plugins/demo/patches", json={"path": "skills/helper/SKILL.md"})
    assert response.status_code == 400


def test_a_traversing_patch_path_is_refused_over_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The path arrives from a request body, so the route must not trust it."""
    client = _client(monkeypatch, _runtime(tmp_path), tmp_path)
    response = client.put(
        "/api/plugins/demo/patches", json={"path": "../../escape.md", "content": "x\n"},
    )
    assert response.status_code == 400
    assert not (tmp_path.parent / "escape.md").exists()


def test_an_identical_patch_is_rejected_over_http(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    client = _client(monkeypatch, _runtime(tmp_path), tmp_path)
    response = client.put(
        "/api/plugins/demo/patches", json={"path": "skills/helper/SKILL.md", "content": "shipped\n"},
    )
    assert response.status_code == 400
    assert "相同" in response.json()["detail"]


def test_reverting_restores_the_shipped_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    client = _client(monkeypatch, runtime, tmp_path)
    client.put(
        "/api/plugins/demo/patches",
        json={"path": "skills/helper/SKILL.md", "content": "mine\n"},
    )
    response = client.delete(
        "/api/plugins/demo/patches", params={"path": "skills/helper/SKILL.md"},
    )
    assert response.status_code == 200, response.text
    root = Path(runtime.discover()[0]["path"])
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "shipped\n"


def test_reverting_without_a_path_clears_every_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    client = _client(monkeypatch, runtime, tmp_path)
    client.put(
        "/api/plugins/demo/patches",
        json={"path": "skills/helper/SKILL.md", "content": "mine\n"},
    )
    response = client.delete("/api/plugins/demo/patches")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert client.get("/api/plugins/demo/patches").json()["count"] == 0


def test_reading_an_unknown_file_is_404(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    client = _client(monkeypatch, _runtime(tmp_path), tmp_path)
    assert client.get(
        "/api/plugins/demo/file", params={"path": "skills/nope/SKILL.md"},
    ).status_code == 404


def test_an_unready_plugin_service_is_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    services = AppServices()
    app = FastAPI()
    app.state.services = services
    app.state.server = _FakeServer()
    app.dependency_overrides[get_app_services] = lambda: services
    app.include_router(plugins_router)
    import atlas.api.plugins_router as module

    monkeypatch.setattr(module, "_server", lambda: app.state.server)
    response = TestClient(app).get("/api/plugins/demo/patches")
    assert response.status_code == 503


def test_the_introspection_method_reports_patches(tmp_path: Path) -> None:
    """``skills.plugin_patches`` — the read-only answer to "did my fix stick"."""
    from atlas.introspect.registry import Context
    from atlas.introspect.providers.skills import PROVIDER

    runtime = _runtime(tmp_path)
    root = Path(runtime.discover()[0]["path"])
    runtime.patch_file("demo", "skills/helper/SKILL.md", "mine\n", note="tweak")

    services = AppServices()
    services.plugin_runtime = runtime
    method = next(one for one in PROVIDER.methods if one.name == "plugin_patches")
    result = method.run(Context(services=services, app=None), {})

    assert result["count"] == 1
    assert result["patched_plugins"] == 1
    assert result["plugins"][0]["plugin"] == "demo"
    assert result["plugins"][0]["patches"][0]["path"] == "skills/helper/SKILL.md"
    assert (root / "skills/helper/SKILL.md").read_text(encoding="utf-8") == "mine\n"
