"""config.provenance: per-key layer attribution for the combined introspection
surface (DSH ``--dump-config`` per-layer provenance row X32).

The provider must mirror ``AtlasConfig.get`` resolution order without changing
what any layer returns, and every echoed value must go through ``scrub``.
"""

import json
from types import SimpleNamespace

import pytest

from atlas.config import AtlasConfig
from atlas.introspect.providers import config as config_provider


pytestmark = pytest.mark.unit


def _install(monkeypatch, *, raw, base, override=None, session=None,
             project=None, session_id=None, project_id=None):
    cfg = AtlasConfig(raw, base=base)
    monkeypatch.setattr(config_provider, "_config", lambda: cfg)

    import atlas.project_context as context_module
    import atlas.project_settings as settings_module

    monkeypatch.setattr(context_module, "current_config_override", lambda: override)
    monkeypatch.setattr(context_module, "current_session_id", lambda: session_id)
    monkeypatch.setattr(context_module, "current_project_id", lambda: project_id)
    monkeypatch.setattr(context_module, "project_config_ignored", lambda: False)
    monkeypatch.setattr(settings_module, "load_session_config", lambda sid: dict(session or {}))
    monkeypatch.setattr(settings_module, "load_project_config", lambda pid: dict(project or {}))


def test_key_defined_only_in_atlas_toml_attribution(monkeypatch):
    _install(
        monkeypatch,
        raw={"server": {"port": 8765}},
        base={"server": {"port": 8765}},
    )
    result = config_provider._provenance(None, {"key": "server.port"})
    assert result["found"] is True
    assert result["winner"] == "atlas.toml"
    assert result["effective_value"] == 8765
    layers = {row["layer"]: row for row in result["layers"]}
    assert layers["atlas.toml"]["present"] is True
    assert layers["expert-overlay"]["present"] is False


def test_key_defined_only_in_expert_overlay_attribution(monkeypatch):
    _install(
        monkeypatch,
        raw={"gateway": {"base_url": "https://overlay.example/v1"}},
        base={},
    )
    result = config_provider._provenance(None, {"key": "gateway.base_url"})
    assert result["winner"] == "expert-overlay"
    assert result["effective_value"] == "https://overlay.example/v1"


def test_overlay_overriding_atlas_toml_value_wins_attribution(monkeypatch):
    _install(
        monkeypatch,
        raw={"server": {"port": 9999}},
        base={"server": {"port": 8765}},
    )
    result = config_provider._provenance(None, {"key": "server.port"})
    assert result["winner"] == "expert-overlay"
    assert result["effective_value"] == 9999
    layers = {row["layer"]: row for row in result["layers"]}
    assert layers["atlas.toml"]["present"] is True
    assert layers["atlas.toml"]["value"] == 8765


def test_project_layer_wins_over_file_layers(monkeypatch):
    _install(
        monkeypatch,
        raw={"server": {"port": 8765}},
        base={"server": {"port": 8765}},
        project={"server": {"port": 9000}},
        project_id="proj-1",
    )
    result = config_provider._provenance(None, {"key": "server.port"})
    assert result["winner"] == "project"
    assert result["effective_value"] == 9000


def test_session_layer_wins_over_project(monkeypatch):
    _install(
        monkeypatch,
        raw={"server": {"port": 8765}},
        base={"server": {"port": 8765}},
        project={"server": {"port": 9000}},
        session={"server": {"port": 9100}},
        session_id="sess-1",
        project_id="proj-1",
    )
    result = config_provider._provenance(None, {"key": "server.port"})
    assert result["winner"] == "session"
    assert result["effective_value"] == 9100


def test_request_override_wins_over_everything(monkeypatch):
    _install(
        monkeypatch,
        raw={"server": {"port": 8765}},
        base={"server": {"port": 8765}},
        project={"server": {"port": 9000}},
        session={"server": {"port": 9100}},
        override={"server": {"port": 9200}},
        session_id="sess-1",
        project_id="proj-1",
    )
    result = config_provider._provenance(None, {"key": "server.port"})
    assert result["winner"] == "request-override"
    assert result["effective_value"] == 9200


def test_unset_key_reports_not_found(monkeypatch):
    _install(monkeypatch, raw={}, base={})
    result = config_provider._provenance(None, {"key": "tools.servers.rea.command"})
    assert result["found"] is False
    assert result["winner"] is None
    assert all(row["present"] is False for row in result["layers"])


def test_secret_values_are_scrubbed_in_every_layer(monkeypatch):
    secret = "sk-plaintext-do-not-echo"
    _install(
        monkeypatch,
        raw={"gateway": {"keys": {"bocha": secret}}},
        base={"gateway": {"keys": {"bocha": secret}}},
        project={"gateway": {"keys": {"bocha": secret}}},
        project_id="proj-1",
    )
    result = config_provider._provenance(None, {"key": "gateway.keys.bocha"})
    blob = json.dumps(result, ensure_ascii=False, default=str)
    assert secret not in blob
    assert result["winner"] == "project"
    assert set(str(result["effective_value"])) <= set("*") or secret not in blob


def test_empty_key_argument_is_rejected():
    result = config_provider._provenance(None, {"key": "  "})
    assert result["found"] is False
    assert result["layers"] == []


def test_provider_manifest_exposes_provenance():
    manifest = config_provider.PROVIDER.manifest()
    methods = {item["name"] for item in manifest["methods"]}
    assert {"keys", "get", "layers", "provenance", "paths"} <= methods
