from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from pathlib import Path

import eval_scenarios as runner
import pytest
import yaml


ORIGINAL_SCENARIO_MANIFEST_SHA256 = (
    "6abdefcaaab706dd690527a2c305defd43f5d53a556315d0553988e38ea8d1fa"
)


def test_original_30_scenario_manifest_is_unchanged() -> None:
    assert len(runner.get_all_scenarios()) == 30
    assert runner.scenario_manifest_sha256() == ORIGINAL_SCENARIO_MANIFEST_SHA256


def test_runtime_capabilities_are_declared_outside_the_canonical_manifest() -> None:
    scenarios = {scenario.id: scenario for scenario in runner.get_all_scenarios()}

    assert scenarios[27].runtime_capabilities == frozenset({"hard_erase"})
    assert scenarios[29].runtime_capabilities == frozenset({"reminder_readonly_audit"})
    assert scenarios[30].runtime_capabilities == frozenset({"workspace_write_tools", "owned_process_kill"})
    assert scenarios[30].workspace_files == ("docs/file1.md", "docs/file2.md", "docs/file3.md")
    assert runner.scenario_manifest_sha256() == ORIGINAL_SCENARIO_MANIFEST_SHA256


def test_hard_erase_flag_follows_declared_capability_not_scenario_number(tmp_path: Path) -> None:
    roots = {
        "ATLAS_DATA_DIR": str(tmp_path / "atlas"),
        "MEMORYOS_DATA_ROOT": str(tmp_path / "memoryos"),
        "MEMORYOS_DB_PATH": str(tmp_path / "memoryos" / "db.sqlite3"),
        "HERMES_HOME": str(tmp_path / "hermes"),
        "WORKSPACE": str(tmp_path / "workspace"),
    }
    declared = replace(runner.get_all_scenarios()[26], id=127)
    same_id_without_capability = replace(declared, runtime_capabilities=frozenset())

    enabled = runner._runtime_environment(
        roots, api_token="token", subject_id="isolated-subject", scenario=declared,
    )
    disabled = runner._runtime_environment(
        roots, api_token="token", subject_id="isolated-subject",
        scenario=same_id_without_capability,
    )

    assert enabled["MEMORYOS_HARD_ERASE_ENABLED"] == "true"
    assert "MEMORYOS_HARD_ERASE_ENABLED" not in disabled


def test_run_start_message_preserves_original_user_input_and_model() -> None:
    scenario = runner.get_all_scenarios()[2]
    step = scenario.steps[1]
    message = runner.build_run_start_message(
        scenario,
        step,
        run_id="run-3-2",
        conversation_id="conversation-3-sess2",
        workspace=Path("D:/Temp/F1-D/workspace"),
    )

    assert message["type"] == "run.start"
    assert message["run_id"] == "run-3-2"
    assert message["content"] == step.user_input
    assert message["model"] == "gemini-3.8-flash"
    assert message["conversation_id"] == "conversation-3-sess2"
    assert Path(message["workspace"]) == Path("D:/Temp/F1-D/workspace").resolve()
    assert message["allowed_paths"] == [str(Path("D:/Temp/F1-D/workspace").resolve())]
    assert step.action_payload["model"] == "gpt-4o"


def test_workspace_tools_follow_declared_capability_instead_of_scenario_number() -> None:
    declared = runner.get_all_scenarios()[29]
    same_id_without_capability = replace(
        declared,
        runtime_capabilities=frozenset(),
        workspace_files=(),
    )
    different_id_with_capability = replace(declared, id=130)
    step = declared.steps[0]

    restricted = runner.build_run_start_message(
        same_id_without_capability,
        step,
        run_id="restricted",
        conversation_id="conversation-restricted",
        workspace=Path("D:/Temp/F1-D/workspace"),
    )
    allowed = runner.build_run_start_message(
        different_id_with_capability,
        step,
        run_id="allowed",
        conversation_id="conversation-allowed",
        workspace=Path("D:/Temp/F1-D/workspace"),
    )

    assert restricted["permission_mode"] == "read_only"
    assert restricted["tool_deny"] == ["*"]
    assert allowed["permission_mode"] == "ask_writes"
    assert allowed["tool_allow"] == ["read_file", "write_file", "patch", "search_files"]


def test_control_action_steps_are_not_sent_as_chat() -> None:
    action_step = runner.get_all_scenarios()[26].steps[0]
    chat_step = runner.get_all_scenarios()[26].steps[1]

    assert runner.is_control_action_step(action_step)
    assert not runner.is_control_action_step(chat_step)
    try:
        runner.build_run_start_message(
            runner.get_all_scenarios()[26],
            action_step,
            run_id="control",
            conversation_id="conversation-control",
            workspace=Path("D:/Temp/F1-D/workspace"),
        )
    except ValueError as exc:
        assert "control action" in str(exc).lower()
    else:
        raise AssertionError("control actions must not be sent to the model as chat")


def test_run_event_summary_does_not_turn_failed_runs_into_success() -> None:
    summary = runner.summarize_run_events(
        "run-failed",
        [
            {"run_id": "run-failed", "event": "message.completed", "data": {"content": "partial"}},
            {"run_id": "run-failed", "event": "run.failed", "data": {"category": "model", "detail": "provider error"}},
        ],
    )

    assert summary["status"] == "failed"
    assert summary["assistant_response"] == "partial"
    assert summary["terminal_event"] == "run.failed"


def test_dry_run_writes_only_a_plan_without_fabricated_execution(tmp_path: Path) -> None:
    result_path = tmp_path / "plan.json"
    scenario = runner.get_all_scenarios()[2]
    asyncio.run(runner.run_evaluation_suite(
        [scenario],
        isolated_dir=tmp_path / "isolated",
        output_path=result_path,
        dry_run=True,
    ))
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    record = payload["scenarios"][0]["records"][0]

    assert payload["metadata"]["execution_mode"] == "plan_only"
    assert record["user_input"] == scenario.steps[0].user_input
    assert "assistant_response" not in record
    assert "observer_output" not in record
    assert record["execution_status"] == "not_run"


def test_results_cannot_be_written_outside_temp_even_before_real_start() -> None:
    output_path = Path(r"D:\Atlas\scenario-runner-must-not-write.json")
    try:
        asyncio.run(runner.run_evaluation_suite(
            [runner.get_all_scenarios()[0]],
            isolated_dir=Path(r"D:\Temp\unused-plan-root"),
            output_path=output_path,
            dry_run=True,
        ))
    except RuntimeError as exc:
        assert "D:\\Temp" in str(exc)
    else:
        raise AssertionError("runner must refuse output outside D:\\Temp")
    assert not output_path.exists()


def test_isolation_setup_never_copies_the_repository_atlas_config(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    runner.enforce_isolation(isolated)

    copied_config = isolated / "atlas_data" / "config" / "atlas.toml"
    assert not copied_config.exists()


def test_isolated_hermes_config_sets_aux_timeouts_without_fallbacks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", r"D:\Users\someone\hermes")
    isolated_home = tmp_path / "F1-D-hermes" / "hermes_home"

    config_path = runner._write_isolated_hermes_config(isolated_home)
    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config_path == isolated_home / "config.yaml"
    assert parsed == {
        "fallback_providers": [],
        "fallback_model": [],
        "auxiliary": {
            "memory_observe": {"timeout": 120, "fallback_chain": []},
            "memory_reflect": {"timeout": 120, "fallback_chain": []},
        },
    }
    assert "someone" not in config_path.read_text(encoding="utf-8")
    assert os.environ["HERMES_HOME"] == r"D:\Users\someone\hermes"


def test_s27_runner_does_not_invent_a_precondition_turn(tmp_path: Path, monkeypatch) -> None:
    scenario = replace(runner.get_all_scenarios()[26], id=127)
    observed_inputs: list[str] = []

    async def fake_step(_scenario, step, **_kwargs):
        observed_inputs.append(step.user_input)
        return {"user_input": step.user_input, "execution_status": "completed"}

    class Memory:
        def records(self, facet=None):
            return []

    monkeypatch.setattr(runner, "run_scenario_step", fake_step)
    result = asyncio.run(runner.run_scenario(
        scenario,
        runtime_root=tmp_path / "runtime",
        atlas=object(),
        memory=Memory(),
        lifecycle=SimpleNamespace(runtime_root=tmp_path / "runtime"),
        workspace=tmp_path / "runtime" / "workspace",
        subject_id="isolated-s27",
    ))

    assert observed_inputs == [step.user_input for step in scenario.steps]
    assert len(result["records"]) == len(scenario.steps)
    assert "preconditions" not in result
    assert runner.scenario_manifest_sha256() == ORIGINAL_SCENARIO_MANIFEST_SHA256


def test_declared_workspace_files_are_seeded_without_scenario_number_gate(tmp_path: Path, monkeypatch) -> None:
    scenario = replace(runner.get_all_scenarios()[29], id=130)

    async def fake_step(_scenario, step, **_kwargs):
        return {"user_input": step.user_input, "execution_status": "completed"}

    class Memory:
        def records(self, facet=None):
            return []

    monkeypatch.setattr(runner, "run_scenario_step", fake_step)
    workspace = tmp_path / "runtime" / "workspace"
    asyncio.run(runner.run_scenario(
        scenario,
        runtime_root=tmp_path / "runtime",
        atlas=object(),
        memory=Memory(),
        lifecycle=SimpleNamespace(runtime_root=tmp_path / "runtime"),
        workspace=workspace,
        subject_id="isolated-workspace",
    ))

    actual_files = {
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert actual_files == set(scenario.workspace_files)
    assert all((workspace / name).read_text(encoding="utf-8").startswith("# ")
               for name in scenario.workspace_files)


def test_s29_audits_each_real_turn_and_keeps_unsupported_as_failure(tmp_path: Path, monkeypatch) -> None:
    scenario = replace(runner.get_all_scenarios()[28], id=129)
    audit_calls: list[tuple[int, int]] = []
    adapter = ModuleType("scripts.memory_v1.scenario_actions")

    def audit_reminder_state(ctx):
        history = ctx.state["reminder_audit_history"]
        audit_calls.append((ctx.step.turn_index, len(history)))
        return {"action": "reminder_readonly_audit", "status": "unsupported"}

    adapter.audit_reminder_state = audit_reminder_state
    monkeypatch.setitem(sys.modules, "scripts.memory_v1.scenario_actions", adapter)

    async def fake_step(_scenario, step, *, state, **_kwargs):
        state["last_run"] = {"run_id": f"run-{step.turn_index}", "status": "completed", "events": []}
        return {"user_input": step.user_input, "execution_status": "completed"}

    class Atlas:
        def request(self, method, path):
            assert method == "GET" and path == "/api/automations"
            return {"status_code": 200, "body": {"items": []}}

    class Memory:
        def records(self, facet=None):
            assert facet in (None, "INTENT")
            return []

    monkeypatch.setattr(runner, "run_scenario_step", fake_step)
    result = asyncio.run(runner.run_scenario(
        scenario,
        runtime_root=tmp_path / "runtime",
        atlas=Atlas(),
        memory=Memory(),
        lifecycle=SimpleNamespace(runtime_root=tmp_path / "runtime"),
        workspace=tmp_path / "runtime" / "workspace",
        subject_id="isolated-s29",
    ))

    assert audit_calls == [(1, 0), (2, 1), (3, 2)]
    assert result["execution_status"] == "failed"
    assert len(result["final_state"]["reminder_audit_history"]) == 3
    assert result["final_state"]["reminder_audit_baseline"]["atlas_automations"]["status_code"] == 200
    assert all(step["reminder_audit"]["status"] == "unsupported" for step in result["records"])


def test_capture_evidence_reports_isolated_source_ids_ack_and_context_overlap(tmp_path: Path) -> None:
    atlas_data = tmp_path / "atlas_data"
    outbox = atlas_data / "outbox" / "unified_outbox.sqlite3"
    outbox.parent.mkdir(parents=True)
    envelope = {
        "observation": {
            "source_kind": "ATLAS_USER_MESSAGE", "source_object_id": "msg-1",
            "source_revision": "1", "speaker_role": "USER",
            "epistemic_kind": "USER_ASSERTED", "occurred_at": "2026-10-09T10:00:00+00:00",
            "source_timezone": "+00:00", "time_status": "KNOWN",
            "content": {"session_id": "conversation-1", "text": "secret user text"},
        },
        "context": {"runtime_session_id": "conversation-1"},
    }
    with sqlite3.connect(outbox) as conn:
        conn.execute(
            "CREATE TABLE outbox_events (id INTEGER PRIMARY KEY, source_event_id TEXT, "
            "payload_json TEXT, content_hash TEXT, state TEXT, created_at TEXT, acked_at TEXT, last_error TEXT)"
        )
        conn.execute(
            "INSERT INTO outbox_events VALUES (1,?,?,?,?,?,?,?)",
            ("atlas:ATLAS_USER_MESSAGE:msg-1:1:UPSERT", json.dumps(envelope), "hash-1",
             "ACKED", "created", "acked", None),
        )

    after = runner._read_capture_source_events(atlas_data, "conversation-1")
    evidence = runner._capture_evidence_delta(
        {"status": "ok", "events": []}, after,
        [{"ref_id": "memory:record-1"}],
        [{"record_ref": "memory:record-1"}],
    )

    assert after["events"][0]["source_event_id"] == "atlas:ATLAS_USER_MESSAGE:msg-1:1:UPSERT"
    assert after["events"][0]["state"] == "ACKED"
    assert "text" not in after["events"][0]
    assert evidence["ack_status"] == "all_acked"
    assert evidence["same_run_record_refs_in_assembled_context"] == ["memory:record-1"]
