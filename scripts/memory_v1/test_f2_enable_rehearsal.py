import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.memory_v1 import f2_enable_rehearsal as rehearsal


def _sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE evidence_events(recorded_at TEXT, event_type TEXT, payload_json TEXT)")


def test_sqlite_backup_is_read_only_consistent_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "production-source.sqlite3"
    target = tmp_path / "isolated" / "snapshot.sqlite3"
    _sqlite(source)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO evidence_events VALUES(?,?,?)",
            ("2026-10-01T00:00:00+00:00", "CHAT", "private marker"),
        )

    result = rehearsal.sqlite_backup_readonly(source, target, protected_roots=[])
    assert result["integrity_check"] == "ok"
    assert result["snapshot_method"] == "sqlite_backup_api_read_only_source"
    assert result["source_hash_changed_during_copy"] is False
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT COUNT(*) FROM evidence_events").fetchone()[0] == 1
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.sqlite_backup_readonly(source, target, protected_roots=[])


def test_database_summary_contains_aggregates_only(tmp_path: Path) -> None:
    database = tmp_path / "snapshot.sqlite3"
    _sqlite(database)
    with sqlite3.connect(database) as conn:
        conn.executemany(
            "INSERT INTO evidence_events VALUES(?,?,?)",
            [
                ("2026-10-08T12:00:00+00:00", "CHAT", '{"text":"private marker"}'),
                ("2026-09-01T12:00:00+00:00", "private marker", '{"text":"older"}'),
            ],
        )

    summary = rehearsal.database_summary(
        database, now=datetime(2026, 10, 9, tzinfo=timezone.utc), recent_days=30,
    )
    encoded = json.dumps(summary)
    assert summary["evidence_events"]["total"] == 2
    assert summary["evidence_events"]["recent_30_day_count"] == 1
    assert summary["evidence_events"]["by_event_type"] == {"CHAT": 1, "OTHER": 1}
    assert "private marker" not in encoded
    assert "older" not in encoded


def test_isolated_settings_allowlist_excludes_credential_values(tmp_path: Path) -> None:
    source = tmp_path / "user-settings.json"
    secret = "synthetic-secret-must-not-escape"
    source.write_text(json.dumps({
        "memory_model": "gemini-3.8-flash",
        "custom_models": [{
            "id": "gemini-3.8-flash", "name": "Gemini Flash", "provider": "custom",
            "litellm_model": "gemini/gemini-3.8-flash", "category": "fast",
            "credential_value": secret,
        }],
        "providers": {"custom": {
            "base_url": "http://127.0.0.1:8045/v1",
            "keys": [{"id": "credential-id", "label": "primary", "value": secret}],
            "api_key": secret,
        }},
        "api_key": secret,
    }), encoding="utf-8")

    isolated = rehearsal.build_isolated_user_settings(source, memory_model="gemini-3.8-flash")
    encoded = json.dumps(isolated)
    assert secret not in encoded
    assert "api_key" not in encoded
    assert isolated["memory_model"] == "gemini-3.8-flash"
    assert isolated["providers"]["custom"]["keys"] == [
        {"id": "credential-id", "label": "primary"},
    ]


def test_isolated_settings_rejects_proxy_url_with_query_data(tmp_path: Path) -> None:
    source = tmp_path / "user-settings.json"
    source.write_text(json.dumps({
        "custom_models": [{"id": "gemini", "provider": "custom"}],
        "providers": {"custom": {
            "base_url": "http://127.0.0.1:8045/v1?token=must-not-be-copied",
            "keys": [{"id": "credential-id"}],
        }},
    }), encoding="utf-8")

    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.build_isolated_user_settings(source, memory_model="gemini")


def test_run_root_cannot_overlap_checkout_or_memoryos_data(tmp_path: Path) -> None:
    atlas_root = tmp_path / "Atlas"
    memoryos_root = tmp_path / "MemoryOSData"
    atlas_root.mkdir()
    memoryos_root.mkdir()
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.assert_run_root_isolated(
            atlas_root / "run", repo_root=atlas_root, protected_roots=[memoryos_root],
        )
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.assert_run_root_isolated(
            memoryos_root / "run", repo_root=atlas_root, protected_roots=[memoryos_root],
        )


def test_isolated_config_and_settings_stay_under_the_cloned_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "isolated-atlas"
    rehearsal._write_isolated_atlas_config(
        data_root, enabled=True, service_url="http://127.0.0.1:51123",
        memoryos_root=tmp_path / "MemoryOS", model_id="gemini-3.8-flash", atlas_port=51124,
    )
    config = (data_root / "config" / "atlas.toml").read_text(encoding="utf-8")
    assert "enabled = true" in config
    assert "db_path = \"./data/atlas.db\"" in config
    assert "127.0.0.1:51123" in config


def test_production_change_flag_is_derived_from_source_hashes() -> None:
    before = {"atlas_db": "a", "memoryos_db": "b", "settings_source": "c"}
    assert rehearsal._source_files_modified(before, dict(before)) is False
    changed = dict(before, settings_source="d")
    assert rehearsal._source_files_modified(before, changed) is True
    assert rehearsal._source_files_modified(before, None) is None
    assert rehearsal._source_files_modified(before, {"atlas_db": "a"}) is None


def test_source_hashes_cover_wal_settings_and_atlas_config(tmp_path: Path) -> None:
    atlas_db = tmp_path / "atlas.db"
    memoryos_db = tmp_path / "memoryos.sqlite3"
    settings = tmp_path / "user-settings.json"
    config = tmp_path / "atlas.toml"
    for path in (atlas_db, memoryos_db, settings, config):
        path.write_text("baseline", encoding="utf-8")
    atlas_wal = atlas_db.with_name(atlas_db.name + "-wal")
    before = rehearsal._source_hashes(
        atlas_db=atlas_db, memoryos_db=memoryos_db, settings_source=settings,
        atlas_config_source=config,
    )
    assert before["atlas_db_wal"] == "absent"
    assert before["memoryos_db_wal"] == "absent"
    atlas_wal.write_text("wal change", encoding="utf-8")
    config.write_text("config change", encoding="utf-8")
    after = rehearsal._source_hashes(
        atlas_db=atlas_db, memoryos_db=memoryos_db, settings_source=settings,
        atlas_config_source=config,
    )
    assert rehearsal._source_files_modified(before, after) is True
    assert before["atlas_db_wal"] != after["atlas_db_wal"]
    assert before["atlas_config_source"] != after["atlas_config_source"]


def test_parent_model_probe_roots_bind_to_isolated_data(tmp_path: Path) -> None:
    atlas_data = tmp_path / "atlas-clone"
    memoryos_data = tmp_path / "memoryos-clone"
    memoryos_db = memoryos_data / "db" / "memoryos.sqlite3"
    hermes_home = tmp_path / "hermes-clone"
    keys = ("ATLAS_ROOT", "ATLAS_DATA_DIR", "MEMORYOS_DATA_ROOT", "MEMORYOS_DB_PATH", "HERMES_HOME")
    before = {key: rehearsal.os.environ.get(key) for key in keys}
    try:
        rehearsal._bind_parent_process_to_isolated_roots(
            atlas_data=atlas_data, memoryos_data=memoryos_data,
            memoryos_db=memoryos_db, hermes_home=hermes_home,
        )
        assert rehearsal.os.environ["ATLAS_DATA_DIR"] == str(atlas_data)
        assert rehearsal.os.environ["MEMORYOS_DATA_ROOT"] == str(memoryos_data)
        assert rehearsal.os.environ["MEMORYOS_DB_PATH"] == str(memoryos_db)
        assert rehearsal.os.environ["HERMES_HOME"] == str(hermes_home)
    finally:
        for key, value in before.items():
            if value is None:
                rehearsal.os.environ.pop(key, None)
            else:
                rehearsal.os.environ[key] = value


def test_unavailable_proxy_token_estimate_has_explicit_conservative_bound() -> None:
    estimate = rehearsal._conservative_payload_token_bound(12345)
    assert estimate == {
        "estimated_payload_tokens_upper_bound": 12345,
        "token_estimate_kind": "conservative_utf8_byte_upper_bound",
        "tokenizer_exact": False,
    }


def test_partial_checkpoint_retains_only_completed_sanitized_report(tmp_path: Path) -> None:
    report = {
        "status": "in_progress",
        "credentials_recorded": False,
        "stages": {"sqlite_backup": {"integrity_check": "ok"}},
    }
    rehearsal._checkpoint(tmp_path, report, "sqlite_backup")
    checkpoint = json.loads(
        (tmp_path / "F2-C-lifecycle-rehearsal.partial.json").read_text(encoding="utf-8")
    )
    assert checkpoint["checkpoint_completed_stage"] == "sqlite_backup"
    assert checkpoint["stages"]["sqlite_backup"]["integrity_check"] == "ok"
    assert checkpoint["credentials_recorded"] is False


def test_server_cleanup_requires_all_three_atlas_exits_and_both_ports_closed() -> None:
    clean = [
        {"phase": phase, "atlas_exit_code": 0,
         "atlas_listener_after_cleanup": False,
         "memoryos_listener_after_cleanup": False}
        for phase in ("enable_chat", "restart", "rollback")
    ]
    assert rehearsal._server_cleanup_passed(clean) is True
    assert rehearsal._server_cleanup_passed(clean[:2]) is False
    assert rehearsal._server_cleanup_passed([
        {**entry, "atlas_listener_after_cleanup": True} if entry["phase"] == "restart" else entry
        for entry in clean
    ]) is False
    assert rehearsal._server_cleanup_passed([
        {**entry, "memoryos_listener_after_cleanup": True} if entry["phase"] == "enable_chat" else entry
        for entry in clean
    ]) is False

