"""Tests for the PDF export path, hook modes, and plugin hot reload.

These cover the three capabilities added on top of the existing office tool set:
LibreOffice-backed export/recalc/render, the three-mode ``HookBus``, and
``PluginRuntime.reload``. Each test is written so it passes on a machine without
LibreOffice or the optional rasteriser — the absence paths are part of the
contract, not an excuse to skip.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# LibreOffice surface
# --------------------------------------------------------------------------- #


def test_status_is_answerable_without_a_binary(monkeypatch):
    """``status()`` must never raise, installed or not.

    The agent calls this to decide whether to attempt an export, so an
    uninstalled machine has to come back as data with an actionable hint rather
    than an exception the model cannot act on.
    """
    from atlas import libreoffice

    monkeypatch.setattr(libreoffice, "find_soffice", lambda: None)
    result = libreoffice.status()

    assert result["available"] is False
    assert result["binary"] is None
    assert result["can_export_pdf"] is False
    assert "LibreOffice" in result["hint"]


def test_export_pdf_reports_missing_source_before_touching_soffice(monkeypatch):
    """A bad path is rejected as data, and soffice is never spawned for it."""
    from atlas import libreoffice

    spawned: list[list[str]] = []

    def _record(arguments, **_kwargs):
        spawned.append(arguments)
        raise AssertionError("soffice must not run for a missing file")

    monkeypatch.setattr(libreoffice, "_run", _record)
    result = libreoffice.export_pdf("no-such-file-here.docx")

    assert result["ok"] is False
    assert "不存在" in result["error"]
    assert spawned == []


def test_export_rejects_a_format_that_cannot_become_a_pdf():
    """A .png has no PDF projection, so the error names the supported inputs."""
    from atlas import libreoffice

    result = libreoffice.export_pdf(str(Path(__file__).with_suffix(".png")))

    assert result["ok"] is False


def test_every_exportable_suffix_maps_to_pdf():
    """The export table is the contract the tool description promises."""
    from atlas import libreoffice

    for suffix in (".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods",
                   ".pptx", ".ppt", ".odp", ".csv"):
        assert libreoffice._EXPORTABLE[suffix] == "pdf", suffix


def test_run_strips_credentials_from_the_child_environment(monkeypatch):
    """soffice gets an allow-listed env, so API keys cannot leak into a subprocess."""
    from atlas import libreoffice

    captured: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(arguments, **kwargs):  # noqa: ANN001, ANN003
        captured["env"] = kwargs.get("env", {})
        return _Completed()

    monkeypatch.setenv("ATLAS_SECRET_API_KEY", "sk-should-not-propagate")
    monkeypatch.setenv("PATH", "C:\\Windows")
    monkeypatch.setattr(libreoffice.subprocess, "run", _fake_run)
    libreoffice._run(["--version"])

    env = captured["env"]
    assert isinstance(env, dict)
    assert "ATLAS_SECRET_API_KEY" not in env
    assert "PATH" in env


@pytest.mark.skipif(
    not pytest.importorskip("atlas.libreoffice").is_available(),
    reason="LibreOffice is not installed on this machine",
)
def test_libreoffice_round_trip_writes_a_real_pdf(tmp_path):
    """End to end: a real docx in, a real PDF out with a %PDF header."""
    pytest.importorskip("docx")
    from atlas import libreoffice
    from atlas.office import create_document

    create_document(str(tmp_path), {
        "path": "probe.docx",
        "blocks": [{"type": "paragraph", "text": "Atlas export probe."}],
    })
    result = libreoffice.export_pdf(str(tmp_path / "probe.docx"))

    assert result["ok"] is True, result
    data = Path(result["path"]).read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) > 1000


# --------------------------------------------------------------------------- #
# HookBus modes
# --------------------------------------------------------------------------- #


def test_serial_is_still_the_default_and_still_ignores_return_values():
    """Existing registrations must keep their exact old meaning."""
    from atlas.agent.enrichment import HookBus

    seen: list[str] = []
    bus = HookBus()
    bus.register("before_model", lambda **_kw: seen.append("a") or {"prompt": "hijacked"})
    bus.register("before_model", lambda **_kw: seen.append("b"))

    errors = asyncio.run(bus.emit("before_model", prompt="original"))

    assert errors == []
    assert seen == ["a", "b"]
    assert bus.last_payload["prompt"] == "original"


def test_waterfall_lets_a_later_handler_rewrite_the_payload():
    """This is the only way a hook can change what the agent is about to do."""
    from atlas.agent.enrichment import HookBus

    bus = HookBus()
    bus.register("before_model", lambda **kw: {"prompt": kw["prompt"] + " [audited]"},
                 mode="waterfall")
    forwarded: list[str] = []

    class _Observer:
        def __call__(self, **kw):
            forwarded.append(kw["prompt"])

    bus.register("before_model", _Observer())

    asyncio.run(bus.emit("before_model", prompt="hello"))

    assert forwarded == ["hello [audited]"]
    assert bus.last_payload["prompt"] == "hello [audited]"


def test_waterfall_treats_a_none_return_as_no_opinion():
    """Most handlers observe; only a dict return may replace the payload."""
    from atlas.agent.enrichment import HookBus

    bus = HookBus()
    bus.register("before_model", lambda **_kw: None, mode="waterfall")

    asyncio.run(bus.emit("before_model", prompt="keep me"))

    assert bus.last_payload["prompt"] == "keep me"


def test_parallel_handlers_overlap_instead_of_stacking():
    """Four 0.15 s handlers must take ~0.15 s, not 0.6 s."""
    from atlas.agent.enrichment import HookBus

    async def _sleep(**_kw):
        await asyncio.sleep(0.15)

    bus = HookBus()
    for _ in range(4):
        bus.register("after_tool", _sleep, mode="parallel")

    started = time.monotonic()
    asyncio.run(bus.emit("after_tool"))
    elapsed = time.monotonic() - started

    assert elapsed < 0.4, f"parallel handlers serialised: {elapsed:.2f}s"


def test_a_failing_hook_never_blocks_the_others_or_raises():
    """Telemetry must not be able to break a turn."""
    from atlas.agent.enrichment import HookBus

    ran: list[str] = []

    def _boom(**_kw):
        raise RuntimeError("hook exploded")

    bus = HookBus()
    bus.register("agent_stop", _boom)
    bus.register("agent_stop", lambda **_kw: ran.append("survivor"))

    errors = asyncio.run(bus.emit("agent_stop"))

    assert [item["error"] for item in errors] == ["hook exploded"]
    assert ran == ["survivor"]


def test_an_unknown_mode_is_rejected_at_registration():
    """Failing loudly beats silently running the wrong semantics."""
    from atlas.agent.enrichment import HookBus

    with pytest.raises(ValueError, match="Unknown hook mode"):
        HookBus().register("agent_stop", lambda **_kw: None, mode="waterfall-ish")


# --------------------------------------------------------------------------- #
# Plugin hot reload
# --------------------------------------------------------------------------- #


def _write_plugin(root: Path, skills: dict[str, str]) -> Path:
    plugin = root / "demo"
    (plugin / "skills").mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "0.0.1"}), encoding="utf-8",
    )
    for name, body in skills.items():
        (plugin / "skills" / name).mkdir(parents=True, exist_ok=True)
        (plugin / "skills" / name / "SKILL.md").write_text(body, encoding="utf-8")
    return plugin


def test_reload_picks_up_edits_without_a_restart(tmp_path):
    """The whole point: read the new file contents, not the cached ones."""
    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.plugins.runtime import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# Alpha\nv1"})
    caps = AgentCapabilityRegistry()
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    asyncio.run(runtime.load_all(capabilities=caps))

    (plugin / "skills" / "alpha" / "SKILL.md").write_text("# Alpha\nv2", encoding="utf-8")
    result = asyncio.run(runtime.reload("demo"))

    assert result["ok"] is True, result
    assert asyncio.run(caps.invoke("plugin.demo.skill.alpha"))["content"] == "# Alpha\nv2"


def test_reload_replaces_capabilities_instead_of_duplicating_them(tmp_path):
    """``register`` rejects duplicates, so stale entries must be removed by source."""
    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.plugins.runtime import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# A"})
    caps = AgentCapabilityRegistry()
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    asyncio.run(runtime.load_all(capabilities=caps))
    assert caps.sources() == {"plugin:demo": 1}

    (plugin / "skills" / "beta").mkdir(parents=True)
    (plugin / "skills" / "beta" / "SKILL.md").write_text("# B", encoding="utf-8")
    asyncio.run(runtime.reload("demo"))

    assert caps.sources() == {"plugin:demo": 2}


def test_reload_drops_capabilities_a_plugin_no_longer_ships(tmp_path):
    """Shrinking the skill list must actually shrink the registry."""
    import shutil

    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.plugins.runtime import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# A", "beta": "# B"})
    caps = AgentCapabilityRegistry()
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    asyncio.run(runtime.load_all(capabilities=caps))
    assert caps.sources() == {"plugin:demo": 2}

    shutil.rmtree(plugin / "skills" / "beta")
    asyncio.run(runtime.reload("demo"))

    assert caps.sources() == {"plugin:demo": 1}


def test_reload_of_an_unknown_plugin_reports_not_found(tmp_path):
    """A typo is an answerable outcome, not a crash."""
    from atlas.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")

    result = asyncio.run(runtime.reload("ghost"))

    assert result["ok"] is False
    assert "not found" in result["error"]


def test_a_broken_edit_keeps_the_previous_loaded_state(tmp_path):
    """A half-written plugin.json must not silently disable a working plugin."""
    from atlas.plugins.runtime import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# A"})
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    asyncio.run(runtime.load_all())
    before = runtime._loaded["demo"]

    (plugin / "plugin.json").write_text("{ this is not json", encoding="utf-8")
    result = asyncio.run(runtime.reload("demo"))

    assert result["ok"] is False
    assert runtime._loaded["demo"] == before


def test_unregister_source_only_touches_its_own_entries():
    """Removing a plugin's capabilities must not disturb another plugin's."""
    from atlas.agent.capabilities import AgentCapabilityRegistry

    caps = AgentCapabilityRegistry()
    caps.register("plugin.a.skill.x", description="", handler=lambda _i: None,
                  source="plugin:a")
    caps.register("plugin.b.skill.y", description="", handler=lambda _i: None,
                  source="plugin:b")

    assert caps.unregister_source("plugin:a") == 1
    assert caps.sources() == {"plugin:b": 1}


# --------------------------------------------------------------------------- #
# The HTTP surface for reload
# --------------------------------------------------------------------------- #


def _client_with(runtime):  # noqa: ANN001, ANN202
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient

    from atlas.api.app_services import AppServices
    from atlas.api.application import create_app

    @asynccontextmanager
    async def _noop(_app):
        yield

    return TestClient(create_app(lifespan=_noop, services=AppServices(plugin_runtime=runtime)))


def test_reload_endpoint_answers_404_for_an_unknown_plugin(tmp_path):
    """A typo must not read as a broken edit — the two send you to different places."""
    from atlas.plugins import PluginRuntime

    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    with _client_with(runtime) as client:
        response = client.post("/api/plugins/ghost/reload")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_reload_endpoint_answers_400_for_a_corrupt_manifest(tmp_path):
    """A plugin that *is* there but does not parse is a different answer."""
    from atlas.plugins import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# A"})
    (plugin / "plugin.json").write_text("{ broken", encoding="utf-8")
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    with _client_with(runtime) as client:
        response = client.post("/api/plugins/demo/reload")

    assert response.status_code == 400
    assert "plugin.json" in response.json()["detail"]


def test_reload_endpoint_refuses_a_path_traversal_name(tmp_path):
    """``name`` reaches a filesystem lookup, so it must not escape the roots."""
    from atlas.plugins import PluginRuntime

    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")
    with _client_with(runtime) as client:
        response = client.post("/api/plugins/..%2F..%2Fetc/reload")

    assert response.status_code in {400, 404}
    assert response.status_code != 200


def test_hook_bus_unregister_removes_only_that_handler():
    """Identity removal is exact; a look-alike handler must survive."""
    from atlas.agent.enrichment import HOOK_POINTS, HookBus

    point = HOOK_POINTS[0]

    def first(**_payload):
        return None

    def second(**_payload):
        return None

    bus = HookBus()
    bus.register(point, first)
    bus.register(point, second)

    assert bus.unregister(point, second) is True
    assert bus.unregister(point, second) is False
    assert bus._hooks[point] == [first]


def test_forget_owner_clears_one_plugins_hooks_and_leaves_others():
    """Reload must not drop a *different* plugin's hooks.

    Every plugin's hook closure is created by the same nested ``_handler``
    function, so they all share one ``__qualname__``; only the owner tag tells
    them apart. Getting this wrong would silently unhook unrelated plugins.
    """
    from atlas.agent.enrichment import HOOK_POINTS, HookBus

    point = HOOK_POINTS[0]
    bus = HookBus()

    def make(owner: str):
        def _handler(**_payload):
            return None

        _handler.__atlas_owner__ = owner
        return _handler

    kept = make("plugin:b")
    stale = make("plugin:a")
    bus.register(point, kept)
    bus.register(point, stale)

    assert bus.forget_owner("plugin:a") == 1
    assert bus._hooks[point] == [kept]
    assert bus.forget_owner("plugin:a") == 0
    assert bus.forget_owner("") == 0


def test_repeated_reload_does_not_pile_up_capabilities_or_hooks(tmp_path):
    """Three reloads must leave exactly what one load left.

    This is the failure the whole ``reload`` path exists to avoid: without the
    removal steps, the second load would hit ``register``'s duplicate refusal and
    the hook bus would fire the same handler three times.
    """
    import asyncio

    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.agent.enrichment import HOOK_POINTS, HookBus
    from atlas.plugins import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# Alpha v1"})
    hook_dir = plugin / "hooks"
    hook_dir.mkdir()
    (hook_dir / "hooks.json").write_text(
        json.dumps({"hooks": [{"point": HOOK_POINTS[0], "command": ["cmd", "/c", "exit", "0"]}]}),
        encoding="utf-8",
    )

    caps = AgentCapabilityRegistry()
    bus = HookBus()
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")

    async def run():
        await runtime.load_all(hook_bus=bus, capabilities=caps)
        for _ in range(3):
            result = await runtime.reload("demo")
            assert result["ok"] is True
        return caps.sources(), len(bus._hooks[HOOK_POINTS[0]])

    sources, hook_count = asyncio.run(run())
    assert sources == {"plugin:demo": 1}
    assert hook_count == 1


def test_reload_publishes_the_edited_skill_body(tmp_path):
    """The point of the feature: an edited file is live without a restart."""
    import asyncio

    from atlas.agent.capabilities import AgentCapabilityRegistry
    from atlas.plugins import PluginRuntime

    plugin = _write_plugin(tmp_path, {"alpha": "# Alpha v1"})
    skill = plugin / "skills" / "alpha" / "SKILL.md"
    caps = AgentCapabilityRegistry()
    runtime = PluginRuntime(plugin_dirs=[tmp_path], state_path=tmp_path / "state.json")

    async def call():
        result = caps.invoke("plugin.demo.skill.alpha", {})
        return await result if hasattr(result, "__await__") else result

    async def run():
        await runtime.load_all(hook_bus=None, capabilities=caps)
        before = json.dumps(await call(), ensure_ascii=False)
        skill.write_text("# Alpha v2 EDITED", encoding="utf-8")
        await runtime.reload("demo")
        after = json.dumps(await call(), ensure_ascii=False)
        return before, after

    before, after = asyncio.run(run())
    assert "v1" in before
    assert "v2 EDITED" in after
    assert "v1" not in after
