import pytest

from atlas.task_artifacts import AgentPresetStore

pytestmark = pytest.mark.unit


def test_agent_preset_persists_capability_sets_and_increments_revision(tmp_path) -> None:
    store = AgentPresetStore(tmp_path)
    first = store.put({
        "id": "reviewer", "name": "Reviewer",
        "capabilities": {
            "tools": {"allow": ["local_file", "coding.repo_map"], "deny": ["local_exec"]},
            "skills": ["code-review"], "mcp_servers": [], "mode": "plan", "model": "fast",
        },
    })
    second = store.put({
        **first, "capabilities": {
            "tools": {"allow": ["local_file"], "deny": ["local_exec"]},
            "skills": ["code-review"], "mcp_servers": [], "mode": "plan", "model": "fast",
        },
    })

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert store.get("reviewer")["capabilities"]["tools"]["allow"] == ["local_file"]


def test_agent_preset_rejects_invalid_capability_sets(tmp_path) -> None:
    store = AgentPresetStore(tmp_path)

    with pytest.raises(ValueError, match="tools.allow"):
        store.put({"id": "bad", "name": "Bad", "capabilities": {"tools": {"allow": "shell"}}})


def test_agent_preset_resolve_returns_normalized_capabilities_and_rejects_unknown(tmp_path) -> None:
    store = AgentPresetStore(tmp_path)
    store.put({
        "id": "reviewer", "name": "Reviewer",
        "capabilities": {"tools": {"allow": ["local_file"]}, "skills": ["review"], "mode": "plan"},
    })

    assert store.resolve("reviewer") == {
        "tools": {"allow": ["local_file"], "allow_all": False, "deny": []},
        "skills": ["review"], "mcp_servers": [], "model": "inherit", "mode": "plan",
    }
    assert store.resolve("default")["tools"]["allow_all"] is True
    with pytest.raises(KeyError, match="missing"):
        store.resolve("missing")
