from types import SimpleNamespace

from atlas.agent.run_phases import _loaded_bundle_memory
from atlas.memory.library.store import Page, Entry
from atlas.skills import scenario_bundles
from atlas.skills.scenario_bundles import ScenarioBundleStore


def test_bundle_store_persists_and_loads_named_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_bundles, "DATA_ROOT", tmp_path)
    store = ScenarioBundleStore()
    store.save({
        "name": "research",
        "description": "Research mode",
        "skills": ["research"],
        "memory_collections": ["事/Atlas"],
        "tools": ["browser"],
    })

    preview = store.preview("research", {"research"}, {"事/Atlas"})
    assert preview["conflicts"] == []
    assert preview["active_skills"] == ["research"]
    loaded = store.load("research", {"research"}, {"事/Atlas"})
    assert loaded["loaded"] is True
    assert store.list()["loaded"]["memory_collections"] == ["事/Atlas"]
    assert store.unload()["unloaded"] is True


def test_loaded_bundle_memory_is_injected_only_for_selected_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_bundles, "DATA_ROOT", tmp_path)
    store = ScenarioBundleStore()
    store.save({
        "name": "research", "skills": [], "memory_collections": ["事"], "tools": [],
    })
    store.load("research", set(), {"事"})
    pages = {
        "事/Atlas.md": Page(path="事/Atlas.md", title="Atlas", current=[Entry(text="selected scenario fact")]),
        "人/Ada.md": Page(path="人/Ada.md", title="Ada", current=[Entry(text="unselected fact")]),
    }
    library = SimpleNamespace(store=SimpleNamespace(
        pages=lambda: list(pages),
        read=lambda rel: pages[rel],
    ))

    result = _loaded_bundle_memory(library)
    assert "selected scenario fact" in result["text"]
    assert "unselected fact" not in result["text"]
    assert result["refs"] == ["事/Atlas.md"]


def test_bundle_load_reports_missing_skills_and_memory_without_switching(tmp_path):
    store = ScenarioBundleStore(tmp_path / "scenario-bundles.json")
    store.save({
        "name": "missing", "skills": ["missing-skill"],
        "memory_collections": ["不存在"], "tools": [],
    })

    result = store.load("missing", set(), {"known"})
    assert result["loaded"] is False
    assert {item["type"] for item in result["conflicts"]} == {
        "missing_skill", "unknown_memory_collection",
    }
    assert store.list()["loaded"] is None
