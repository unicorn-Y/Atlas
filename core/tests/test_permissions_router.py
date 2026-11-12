"""The standing-grant HTTP surface: list, revoke, clear, presets.

Before this router existed, ``allow_always`` could only be *created*. A user who
clicked it once had no way to see what they had handed over, and no way to take
it back short of finding the JSON on disk. These tests hold the read and undo
halves in place.

Grants are built through ``permission_scope`` rather than by hand: the store only
accepts ``kind == "exact_call"`` rows with a workspace and a fingerprint, so a
hand-rolled dict would make these tests pass against a format the runtime never
writes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.application import create_app


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture()
def store(tmp_path, monkeypatch) -> Path:
    """A throwaway approval store; the router reads it through ``_path``."""
    import atlas.approval_policy as policy

    path = tmp_path / "approval-permissions.json"
    monkeypatch.setattr(policy, "_path", lambda: path)
    return path


@pytest.fixture()
def client(store) -> TestClient:
    app = create_app(lifespan=_noop_lifespan, services=AppServices())
    return TestClient(app)


def _grant(tool: str = "write_file", resource: str = "a.txt", workspace: str | None = None) -> None:
    import atlas.approval_policy as policy

    scope = policy.permission_scope(
        workspace or str(Path.cwd()), tool, {"path": resource}, resource
    )
    assert scope is not None
    policy.grant(scope)


def test_the_empty_state_is_a_list_and_not_an_error(client) -> None:
    body = client.get("/api/permissions").json()
    assert body["count"] == 0
    assert body["grants"] == []
    assert body["by_tool"] == {}
    assert body["default_preset"] == "ask"


def test_a_grant_appears_in_the_list(client) -> None:
    _grant()
    body = client.get("/api/permissions").json()
    assert body["count"] == 1
    assert body["grants"][0]["kind"] == "exact_call"
    assert body["grants"][0]["tool"] == "write_file"
    assert body["grants"][0]["request_fingerprint"]


def test_the_list_groups_by_tool(client) -> None:
    _grant("write_file", "a.txt")
    _grant("run_command", "ls")
    body = client.get("/api/permissions").json()
    assert body["count"] == 2
    assert body["by_tool"] == {"run_command": 1, "write_file": 1}


def test_a_filterless_revoke_is_rejected_rather_than_wiping_everything(client) -> None:
    """Wiping every permission a user ever granted must be an explicit choice;
    a client that forgets its filter must not silently get "all"."""
    _grant()
    response = client.post("/api/permissions/revoke", json={})
    assert response.status_code == 400
    assert "request_fingerprint" in response.json()["detail"]
    assert client.get("/api/permissions").json()["count"] == 1


def test_revoking_by_fingerprint_removes_only_that_grant(client) -> None:
    _grant("write_file", "a.txt")
    _grant("run_command", "ls")
    fingerprint = client.get("/api/permissions").json()["grants"][0]["request_fingerprint"]
    body = client.post(
        "/api/permissions/revoke", json={"request_fingerprint": fingerprint}
    ).json()
    assert body["removed"] == 1
    assert body["count"] == 1


def test_revoking_by_tool_removes_every_call_of_that_tool(client) -> None:
    _grant("write_file", "a.txt")
    _grant("write_file", "b.txt")
    _grant("run_command", "ls")
    body = client.post("/api/permissions/revoke", json={"tool": "write_file"}).json()
    assert body["removed"] == 2
    assert body["count"] == 1
    assert body["grants"][0]["tool"] == "run_command"


def test_clear_reports_how_much_was_there(client) -> None:
    _grant("write_file", "a.txt")
    _grant("run_command", "ls")
    body = client.post("/api/permissions/clear").json()
    assert body["removed"] == 2
    assert body["count"] == 0


def test_clearing_an_empty_store_says_zero_and_does_not_fail(client) -> None:
    body = client.post("/api/permissions/clear").json()
    assert body["removed"] == 0
    assert body["count"] == 0


def test_the_preset_table_is_offered_without_touching_grants(client) -> None:
    _grant()
    body = client.get("/api/permissions/presets").json()
    assert [item["name"] for item in body["presets"]] == ["observe", "ask", "trusted", "free"]
    assert body["default"] == "ask"
    # Reading the table must not be a mutation.
    assert client.get("/api/permissions").json()["count"] == 1


def test_one_preset_resolves_to_a_permission_mode(client) -> None:
    body = client.get("/api/permissions/presets/trusted").json()
    assert body["exact"] is True
    assert body["resolved"]["mode"] == "auto_file"


def test_an_unknown_preset_falls_back_and_says_so(client) -> None:
    body = client.get("/api/permissions/presets/nonsense").json()
    assert body["requested"] == "nonsense"
    assert body["exact"] is False
    assert body["resolved"]["name"] == "ask"


def test_a_client_can_ask_what_a_preset_means_before_applying_it(client) -> None:
    body = client.post("/api/permissions/presets/resolve", json={"preset": "free"}).json()
    assert body["resolved"]["mode"] == "full_access"


def test_every_preset_maps_to_a_real_permission_mode(client) -> None:
    """A preset that resolves to a mode the engine does not know would be a
    runtime failure rather than a UI one, so the whole table is checked."""
    valid = {"full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only"}
    for item in client.get("/api/permissions/presets").json()["presets"]:
        assert item["mode"] in valid, item


def test_the_free_preset_still_declares_the_origin_guard(client) -> None:
    """``free`` removes approval prompts; it must not remove the origin guard.

    The preset's own sentence is the contract shown to the user, so it has to
    keep saying the guard applies. A preset that quietly stopped mentioning it
    would read as a bypass even if the code still enforced it.
    """
    presets = {item["name"]: item for item in client.get("/api/permissions/presets").json()["presets"]}
    assert presets["free"]["mode"] == "full_access"
    assert "origin_guard" in presets["free"]["sentence"]
    # No preset may carry a field that purports to switch the guard off.
    for item in presets.values():
        for key in item:
            assert "bypass" not in key.lower()
            assert key.lower() not in {"skip_origin_guard", "origin_guard", "disable_guard"}
