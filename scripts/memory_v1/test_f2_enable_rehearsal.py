import asyncio
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


def test_user_timezone_allowlist_returns_only_valid_iana_value(tmp_path: Path) -> None:
    source = tmp_path / "atlas.toml"
    source.write_text(
        '[models.gateway]\napi_key = "synthetic-secret"\n'
        '[user]\ntimezone = "Asia/Shanghai"\n',
        encoding="utf-8",
    )

    assert rehearsal.read_user_timezone_allowlist(source) == "Asia/Shanghai"
    assert "synthetic-secret" not in json.dumps(
        {"timezone": rehearsal.read_user_timezone_allowlist(source)}
    )


def test_user_timezone_allowlist_uses_system_fallback_when_absent(tmp_path: Path) -> None:
    source = tmp_path / "atlas.toml"
    source.write_text('[user]\nname = "Local user"\n', encoding="utf-8")

    assert rehearsal.read_user_timezone_allowlist(source) is None
    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.read_user_timezone_allowlist(source.with_name("missing.toml"))


def test_user_timezone_allowlist_rejects_invalid_iana_name(tmp_path: Path) -> None:
    source = tmp_path / "atlas.toml"
    source.write_text('[user]\ntimezone = "Not/A_Timezone"\n', encoding="utf-8")

    with pytest.raises(rehearsal.RehearsalError):
        rehearsal.read_user_timezone_allowlist(source)


@pytest.mark.parametrize(
    ("header", "expected"),
    [('[user]', "Asia/Shanghai"), ('["user"]', "Asia/Shanghai"), ("[[user]]", None)],
)
def test_user_timezone_allowlist_respects_table_boundaries(
        tmp_path: Path, header: str, expected: str | None) -> None:
    source = tmp_path / "atlas.toml"
    source.write_text(f'{header}\ntimezone = "Asia/Shanghai"\n', encoding="utf-8")

    assert rehearsal.read_user_timezone_allowlist(source) == expected


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


def test_isolated_config_carries_only_allowed_user_timezone(tmp_path: Path) -> None:
    data_root = tmp_path / "isolated-atlas"
    rehearsal._write_isolated_atlas_config(
        data_root, enabled=True, service_url="http://127.0.0.1:51123",
        memoryos_root=tmp_path / "MemoryOS", model_id="gemini-3.8-flash",
        atlas_port=51124, user_timezone="Asia/Shanghai",
    )
    config = (data_root / "config" / "atlas.toml").read_text(encoding="utf-8")

    assert "[user]" in config
    assert 'timezone = "Asia/Shanghai"' in config
    assert "credential" not in config.casefold()


def test_chat_start_allows_only_automation_manage_for_reminder_run(tmp_path: Path) -> None:
    message = rehearsal._build_chat_run_start(
        run_id="run-1", conversation_id="conv-1", workspace=tmp_path,
        model_id="gemini-3.8-flash", prompt="natural reminder request",
        permission_mode="full_access", tool_allow=["automation_manage"],
    )

    assert message["permission_mode"] == "full_access"
    assert message["tool_allow"] == ["automation_manage"]
    assert message["content"] == "natural reminder request"


def test_isolated_marker_automation_snapshot_and_due_assertion_are_allowlisted(
        tmp_path: Path) -> None:
    automation_path = tmp_path / "automations.toml"
    automation_path.write_text(
        '[automations.rem-1]\nname = "Reminder: F4E-X1"\nenabled = true\n'
        '[automations.rem-1.trigger]\nkind = "date"\nat = "2026-10-10T09:00:00+08:00"\n'
        '[automations.rem-1.payload]\nmessage = "Send test note F4E-X1"\n'
        '[automations.rem-1.payload.extra]\nsecret = "must-not-escape"\n'
        '[automations.rem-1.source_binding]\nrequest_run_id = "run-1"\n'
        'source_message_ref = "ATLAS_USER_MESSAGE:user-1"\nintent_id = "intent-1"\n',
        encoding="utf-8",
    )
    expected = rehearsal._expected_tomorrow_nine(
        "Asia/Shanghai", now=datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc),
    )

    snapshot = rehearsal._read_isolated_marker_automations(automation_path, "F4E-X1")
    check = rehearsal._verify_marker_automation(
        automation_path, marker="F4E-X1", timezone_name="Asia/Shanghai",
        expected_due=expected, expected_run_id="run-1", expected_enabled=True,
    )

    assert len(snapshot) == 1
    assert snapshot[0]["id"] == "rem-1"
    assert snapshot[0]["source_binding"] == {
        "request_run_id": "run-1", "source_message_ref": "ATLAS_USER_MESSAGE:user-1",
        "intent_id": "intent-1",
    }
    assert "must-not-escape" not in json.dumps(snapshot)
    assert check["passed"] is True
    assert check["automation_binding_unique"] is True
    assert check["due_matches_local_time"] is True
    assert check["stored_trigger_is_aware"] is True


def test_isolated_marker_automation_cancel_assertion_requires_disabled_record(
        tmp_path: Path) -> None:
    automation_path = tmp_path / "automations.toml"
    automation_path.write_text(
        '[automations.rem-1]\nname = "Reminder: F4E-X2"\nenabled = false\n'
        '[automations.rem-1.trigger]\nkind = "date"\nat = "2026-10-10T09:00:00+08:00"\n'
        '[automations.rem-1.payload]\nmessage = "Send test note F4E-X2"\n'
        '[automations.rem-1.source_binding]\nrequest_run_id = "run-1"\n'
        'source_message_ref = "ATLAS_USER_MESSAGE:user-1"\nintent_id = "intent-1"\n',
        encoding="utf-8",
    )
    expected = rehearsal._expected_tomorrow_nine(
        "Asia/Shanghai", now=datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc),
    )

    check = rehearsal._verify_marker_automation(
        automation_path, marker="F4E-X2", timezone_name="Asia/Shanghai",
        expected_due=expected, expected_run_id="run-1", expected_enabled=False,
    )

    assert check["passed"] is True
    assert check["enabled"] is False


def test_isolated_marker_automation_rejects_duplicate_matches(tmp_path: Path) -> None:
    automation_path = tmp_path / "automations.toml"
    lines = []
    for automation_id in ("rem-1", "rem-2"):
        lines.extend([
            f"[automations.{automation_id}]",
            f'name = "Reminder: F4E-X3 {automation_id}"',
            "enabled = true",
            f"[automations.{automation_id}.trigger]",
            'kind = "date"',
            'at = "2026-10-10T09:00:00+08:00"',
            f"[automations.{automation_id}.payload]",
            'message = "Send test note F4E-X3"',
            f"[automations.{automation_id}.source_binding]",
            'request_run_id = "run-1"',
            'source_message_ref = "ATLAS_USER_MESSAGE:user-1"',
            'intent_id = "intent-1"',
            "",
        ])
    automation_path.write_text("\n".join(lines), encoding="utf-8")
    expected = rehearsal._expected_tomorrow_nine(
        "Asia/Shanghai", now=datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc),
    )

    check = rehearsal._verify_marker_automation(
        automation_path, marker="F4E-X3", timezone_name="Asia/Shanghai",
        expected_due=expected, expected_run_id="run-1", expected_enabled=True,
    )

    assert check["matching_automation_count"] == 2
    assert check["passed"] is False
    assert check["automation_binding_unique"] is False


def test_marker_automation_rejects_naive_stored_trigger(tmp_path: Path) -> None:
    automation_path = tmp_path / "automations.toml"
    automation_path.write_text(
        '[automations.rem-1]\nname = "Reminder: F4E-X4"\nenabled = true\n'
        '[automations.rem-1.trigger]\nkind = "date"\nat = "2026-10-10T09:00:00"\n'
        '[automations.rem-1.payload]\nmessage = "Send test note F4E-X4"\n'
        '[automations.rem-1.source_binding]\nrequest_run_id = "run-1"\n'
        'source_message_ref = "ATLAS_USER_MESSAGE:user-1"\nintent_id = "intent-1"\n',
        encoding="utf-8",
    )
    expected = rehearsal._expected_tomorrow_nine(
        "Asia/Shanghai", now=datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc),
    )

    check = rehearsal._verify_marker_automation(
        automation_path, marker="F4E-X4", timezone_name="Asia/Shanghai",
        expected_due=expected, expected_run_id="run-1", expected_enabled=True,
    )

    assert check["passed"] is False
    assert check["stored_trigger_is_aware"] is False
    assert check["due_matches_utc_instant"] is False


def _write_isolated_memoryos_lifecycle_db(path: Path, *, lifecycle: str = "ACTIVE",
                                          speaker_role: str = "USER",
                                          run_id: str = "run-1",
                                          source_ref: str = "ATLAS_USER_MESSAGE:user-1",
                                          intent_due: str = "2026-10-10T01:00:00+00:00") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE unified_source_objects("
            "subject_id TEXT, source_kind TEXT, source_object_id TEXT,"
            "source_revision INTEGER, source_event_id TEXT, lifecycle TEXT);"
            "CREATE TABLE evidence_events("
            "memory_subject_id TEXT, source_event_id TEXT, event_type TEXT, payload_json TEXT);"
            "CREATE TABLE unified_intents("
            "subject_id TEXT, intent_id TEXT, lifecycle TEXT, revision INTEGER,"
            "user_source_ref TEXT, source_state TEXT, action_json TEXT, due_at TEXT,"
            "automation_id TEXT);"
        )
        conn.execute(
            "INSERT INTO unified_source_objects VALUES(?,?,?,?,?,?)",
            ("f2-c-isolated", "ATLAS_USER_MESSAGE", "user-1", 1,
             "atlas:ATLAS_USER_MESSAGE:user-1:1:UPSERT", "ACTIVE"),
        )
        payload = {"observation": {
            "source_kind": "ATLAS_USER_MESSAGE", "speaker_role": speaker_role,
            "occurred_at": "2026-10-09T01:00:00+00:00",
            "metadata": {"request_run_id": run_id},
            "content": {"text": "synthetic private user message"},
        }}
        conn.execute(
            "INSERT INTO evidence_events VALUES(?,?,?,?)",
            ("f2-c-isolated", "atlas:ATLAS_USER_MESSAGE:user-1:1:UPSERT",
             "OBSERVATION", json.dumps(payload)),
        )
        conn.execute(
            "INSERT INTO unified_intents VALUES(?,?,?,?,?,?,?,?,?)",
            ("f2-c-isolated", "intent-1", lifecycle, 1, source_ref, "VERIFIED",
             json.dumps({"kind": "REMINDER", "message": "Finish F4E-X5"}),
             intent_due, "rem-1"),
        )


def _write_lifecycle_automation(path: Path, *, marker: str = "F4E-X5",
                                enabled: bool = True) -> None:
    path.write_text(
        '[automations.rem-1]\nname = "Reminder: ' + marker + '"\n'
        f'enabled = {str(enabled).lower()}\n'
        '[automations.rem-1.trigger]\nkind = "date"\n'
        'at = "2026-10-10T01:00:00+00:00"\n'
        '[automations.rem-1.payload]\nmessage = "Finish ' + marker + '"\n'
        '[automations.rem-1.source_binding]\nrequest_run_id = "run-1"\n'
        'source_message_ref = "ATLAS_USER_MESSAGE:user-1"\nintent_id = "intent-1"\n',
        encoding="utf-8",
    )


def test_memoryos_intent_verification_uses_real_user_source_and_run(tmp_path: Path) -> None:
    database = tmp_path / "memoryos.sqlite3"
    automation_path = tmp_path / "automations.toml"
    _write_isolated_memoryos_lifecycle_db(database)
    _write_lifecycle_automation(automation_path)
    record = rehearsal._read_isolated_marker_automations(automation_path, "F4E-X5")[0]
    intent = rehearsal._read_isolated_intent(database, intent_id="intent-1")
    source = rehearsal._read_isolated_user_source(
        database, source_message_ref="ATLAS_USER_MESSAGE:user-1", expected_run_id="run-1",
    )
    expected = rehearsal._expected_tomorrow_nine(
        "Asia/Shanghai", now=datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc),
    )

    check = rehearsal._verify_marker_intent(
        record=record, intent=intent, source=source, marker="F4E-X5",
        expected_run_id="run-1", expected_lifecycle="ACTIVE", expected_due=expected,
    )

    assert check["passed"] is True
    assert check["observer_settled"] is True
    assert check["source_message_ref_nonempty"] is True
    assert check["source_message_is_user_message_from_run"] is True
    assert "synthetic private user message" not in json.dumps(source)


@pytest.mark.parametrize(
    ("speaker_role", "run_id"), [("ASSISTANT", "run-1"), ("USER", "other-run")],
)
def test_memoryos_source_verification_rejects_non_user_or_other_run(
        tmp_path: Path, speaker_role: str, run_id: str) -> None:
    database = tmp_path / "memoryos.sqlite3"
    _write_isolated_memoryos_lifecycle_db(
        database, speaker_role=speaker_role, run_id=run_id,
    )

    source = rehearsal._read_isolated_user_source(
        database, source_message_ref="source:ATLAS_USER_MESSAGE:user-1",
        expected_run_id="run-1",
    )

    assert source["source_message_ref"] == "ATLAS_USER_MESSAGE:user-1"
    assert source["source_message_matches_run"] is False


def test_reminder_wait_requires_active_then_cancelled_intent_settlement(tmp_path: Path) -> None:
    database = tmp_path / "memoryos.sqlite3"
    automation_path = tmp_path / "automations.toml"
    _write_isolated_memoryos_lifecycle_db(database)
    _write_lifecycle_automation(automation_path)

    created = asyncio.run(rehearsal._wait_for_marker_automation(
        automation_path, memoryos_db=database, marker="F4E-X5",
        timezone_name="Asia/Shanghai", expected_run_id="run-1", expected_enabled=True,
        expected_lifecycle="ACTIVE", timeout=0,
    ))
    assert created["passed"] is True
    assert created["deduplication_verified"] is True
    assert created["observer_settled"] is True

    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE unified_intents SET lifecycle='CANCELLED', revision=2")
    _write_lifecycle_automation(automation_path, enabled=False)
    due = rehearsal._parse_aware_timestamp(created["expected_due_utc"])
    cancelled = asyncio.run(rehearsal._wait_for_marker_automation(
        automation_path, memoryos_db=database, marker="F4E-X5",
        timezone_name="Asia/Shanghai", expected_run_id="run-1", expected_enabled=False,
        expected_lifecycle="CANCELLED", expected_due=due, timeout=0,
    ))

    assert cancelled["passed"] is True
    assert cancelled["intent_lifecycle"] == "CANCELLED"
    assert cancelled["observer_settled"] is True


def test_automation_store_is_sibling_of_configured_database(tmp_path: Path) -> None:
    database = tmp_path / "atlas-data" / "data" / "atlas.db"

    assert rehearsal._automation_store_path(database) == database.parent / "automations.toml"


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

