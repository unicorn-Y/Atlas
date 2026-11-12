"""The standing-grant lifecycle and the permission preset table.

An ``allow_always`` decision used to be append-only: the grant was written and
then invisible, so a user could neither audit nor undo what one dialog handed
away. These tests pin the read/revoke/clear half and the preset resolution that
the UI offers, including the fail-closed cases.
"""

from __future__ import annotations

import json

import pytest

from atlas import approval_policy as ap


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the grant file at a temp path; the live install is never touched."""
    target = tmp_path / "engine" / "approval-permissions.json"
    monkeypatch.setattr(ap, "_path", lambda: target)
    return target


@pytest.fixture()
def scopes(tmp_path):
    return {
        "file": ap.permission_scope(str(tmp_path), "local_file", {"path": "a.txt"}, "a.txt"),
        "proc": ap.permission_scope(str(tmp_path), "local_process", {"cmd": "ls"}, None),
    }


def test_listing_starts_empty(store):
    assert ap.grants() == []


def test_grant_is_idempotent(store, scopes):
    ap.grant(scopes["file"])
    ap.grant(scopes["file"])
    assert len(ap.grants()) == 1
    assert ap.is_allowed(scopes["file"])


def test_listing_returns_what_was_granted(store, scopes):
    ap.grant(scopes["file"])
    ap.grant(scopes["proc"])
    listed = ap.grants()
    assert len(listed) == 2
    assert {item["tool"] for item in listed} == {"local_file", "local_process"}
    assert all(item["kind"] == "exact_call" for item in listed)


def test_store_file_is_readable_json(store, scopes):
    ap.grant(scopes["file"])
    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["grants"]) == 1


def test_revoke_by_tool(store, scopes):
    ap.grant(scopes["file"])
    ap.grant(scopes["proc"])
    assert ap.revoke(tool="local_file") == 1
    assert not ap.is_allowed(scopes["file"])
    assert ap.is_allowed(scopes["proc"])


def test_revoke_by_fingerprint(store, scopes):
    ap.grant(scopes["file"])
    removed = ap.revoke(request_fingerprint=scopes["file"]["request_fingerprint"])
    assert removed == 1
    assert ap.grants() == []


def test_revoke_by_workspace(store, scopes, tmp_path):
    ap.grant(scopes["file"])
    assert ap.revoke(workspace=str(tmp_path)) == 1
    assert ap.grants() == []


def test_revoke_without_a_filter_does_nothing(store, scopes):
    """A malformed call must not be read as "revoke everything"."""
    ap.grant(scopes["file"])
    assert ap.revoke() == 0
    assert len(ap.grants()) == 1


def test_revoke_of_a_non_matching_filter_leaves_the_file_alone(store, scopes):
    ap.grant(scopes["file"])
    before = store.read_text(encoding="utf-8")
    assert ap.revoke(tool="never_granted") == 0
    assert store.read_text(encoding="utf-8") == before


def test_clear_removes_every_grant(store, scopes):
    ap.grant(scopes["file"])
    ap.grant(scopes["proc"])
    assert ap.clear() == 2
    assert ap.grants() == []
    assert ap.clear() == 0


def test_grant_rejects_an_unbounded_scope(store):
    with pytest.raises(ValueError):
        ap.grant(None)


def test_symlinked_store_is_refused(store, scopes, tmp_path):
    store.parent.mkdir(parents=True, exist_ok=True)
    real = tmp_path / "elsewhere.json"
    real.write_text('{"version": 1, "grants": []}', encoding="utf-8")
    try:
        store.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted here")
    with pytest.raises(OSError):
        ap.grant(scopes["file"])


# --- presets -----------------------------------------------------------------


def test_preset_names_and_modes():
    assert set(ap.PERMISSION_PRESETS) == {"observe", "ask", "trusted", "free"}
    assert ap.PERMISSION_PRESETS["observe"]["mode"] == "read_only"
    assert ap.PERMISSION_PRESETS["ask"]["mode"] == "ask_writes"
    assert ap.PERMISSION_PRESETS["trusted"]["mode"] == "auto_file"
    assert ap.PERMISSION_PRESETS["free"]["mode"] == "full_access"


def test_every_preset_carries_a_sentence_for_the_ui():
    for name, body in ap.PERMISSION_PRESETS.items():
        assert body["label"], name
        assert body["sentence"], name
        assert isinstance(body["allow_always"], bool), name


def test_preset_lookup_is_case_insensitive():
    assert ap.preset("FREE")["mode"] == "full_access"
    assert ap.preset("  Observe ")["mode"] == "read_only"


def test_unknown_preset_falls_back_to_default():
    assert ap.preset("nonsense")["name"] == ap.DEFAULT_PRESET
    assert ap.preset(None)["name"] == ap.DEFAULT_PRESET
    assert ap.preset("")["name"] == ap.DEFAULT_PRESET


def test_preset_returns_a_copy_not_the_table_entry():
    body = ap.preset("free")
    body["mode"] = "tampered"
    assert ap.PERMISSION_PRESETS["free"]["mode"] == "full_access"


def test_preset_for_mode_maps_back_to_a_name():
    assert ap.preset_for_mode("read_only")["name"] == "observe"
    assert ap.preset_for_mode("ask_writes")["name"] == "ask"
    assert ap.preset_for_mode("auto_file")["name"] == "trusted"
    assert ap.preset_for_mode("full_access")["name"] == "free"


def test_preset_for_an_unknown_mode_is_the_safe_default():
    assert ap.preset_for_mode("yolo")["name"] == ap.DEFAULT_PRESET
    assert ap.preset_for_mode(None)["name"] == ap.DEFAULT_PRESET


def test_default_preset_asks_before_writing():
    """The default must not be the permissive one."""
    assert ap.PERMISSION_PRESETS[ap.DEFAULT_PRESET]["mode"] != "full_access"
