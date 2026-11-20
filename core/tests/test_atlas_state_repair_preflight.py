from __future__ import annotations

import os
import sqlite3

import pytest

from atlas.engine.state import atlas_state_repair


@pytest.mark.unit
def test_preflight_ignores_sqlite_sidecar_removed_during_probe(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    db_path.write_bytes(b"sqlite fixture")
    shm_path = tmp_path / "state.db-shm"
    shm_path.write_bytes(b"ephemeral sqlite shared memory")
    monkeypatch.setattr(atlas_state_repair, "get_atlas_home", lambda: str(tmp_path))
    original_access = os.access
    removed = False

    def access(path, mode, *args, **kwargs):
        nonlocal removed
        if os.fspath(path) == os.fspath(shm_path):
            if not removed:
                removed = True
                shm_path.unlink()
            return False
        return original_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(atlas_state_repair.os, "access", access)

    atlas_state_repair.preflight_db_writability(db_path)

    assert removed
    assert not shm_path.exists()


@pytest.mark.unit
def test_preflight_still_rejects_present_unwritable_sqlite_sidecar(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    db_path.write_bytes(b"sqlite fixture")
    shm_path = tmp_path / "state.db-shm"
    shm_path.write_bytes(b"unwritable sqlite shared memory")
    monkeypatch.setattr(atlas_state_repair, "get_atlas_home", lambda: str(tmp_path))
    original_access = os.access

    def access(path, mode, *args, **kwargs):
        if os.fspath(path) == os.fspath(shm_path):
            return False
        return original_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(atlas_state_repair.os, "access", access)
    monkeypatch.setattr(atlas_state_repair.os, "chmod", lambda *_args, **_kwargs: None)

    with pytest.raises(sqlite3.OperationalError, match="state.db is not writable"):
        atlas_state_repair.preflight_db_writability(db_path)

    assert shm_path.exists()
