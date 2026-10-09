from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.memory_v1.scenario_actions import apply_step_action, audit_reminder_state


class FakeHttp:
    def __init__(self, responses: list[tuple[int, Any]]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None, owner=False):
        self.calls.append({
            "method": method, "path": path, "json_body": json_body,
            "params": params, "owner": owner,
        })
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {path}")
        status, body = self.responses.pop(0)
        return {"status_code": status, "body": body}


class FakeLifecycle:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.calls: list[str] = []

    def restart(self):
        self.calls.append("restart")
        return {"pid": 12001, "port": 51234, "creation_time": 1234.0, "route": {"provider_id": "custom"}}

    def crash(self):
        self.calls.append("crash")
        return {"pid": 12001, "creation_time": 1234.0, "port": 51234, "terminated": True}

    def start(self):
        self.calls.append("start")
        return {"model_id": "gemini-3.8-flash", "provider_id": "custom", "credential_value_recorded": False}


def make_ctx(
    tmp_path: Path,
    *,
    scenario_id: int = 1,
    runtime_capabilities: frozenset[str] = frozenset(),
    workspace_files: tuple[str, ...] = (),
    turn_index: int = 1,
    user_input: str = "",
    atlas_responses: list[tuple[int, Any]] | None = None,
    memory_responses: list[tuple[int, Any]] | None = None,
    records: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
):
    runtime_root = tmp_path / "runtime"
    workspace = runtime_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    artifact_dir = runtime_root / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    atlas = FakeHttp(atlas_responses or [])
    memory = FakeHttp(memory_responses or [])
    memory.records = lambda facet=None: [r for r in (records or []) if not facet or r.get("facet") == facet]
    return SimpleNamespace(
        scenario_id=scenario_id,
        runtime_capabilities=runtime_capabilities,
        workspace_files=workspace_files,
        step=SimpleNamespace(turn_index=turn_index, user_input=user_input, action=None, action_payload={}),
        atlas=atlas,
        memory=memory,
        lifecycle=FakeLifecycle(workspace),
        workspace=workspace,
        artifact_dir=artifact_dir,
        subject_id="isolated-subject",
        state=state if state is not None else {},
    )


def test_unknown_action_is_unsupported_without_any_side_effect(tmp_path: Path):
    ctx = make_ctx(tmp_path)

    result = apply_step_action("kill_pid", {"pid": 8045}, ctx)

    assert result["status"] == "unsupported"
    assert ctx.atlas.calls == []
    assert ctx.memory.calls == []
    assert ctx.lifecycle.calls == []


def test_transport_exception_text_never_enters_action_evidence(tmp_path: Path):
    ctx = make_ctx(tmp_path)
    ctx.atlas.request = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Authorization: Bearer fake-secret-value")
    )

    result = apply_step_action("switch_model", {"model": "gpt-4o"}, ctx)

    assert result["status"] == "failed"
    assert "fake-secret-value" not in str(result)
    assert result["observations"][0]["response"] == {
        "error_type": "RuntimeError", "detail": "isolated request transport failed",
    }


def test_edit_memory_rejects_ambiguous_match_without_mutation(tmp_path: Path):
    rows = [
        {"record_ref": "memory:a", "record_revision": 2, "facet": "PROFILE", "content": {"value": "杭州"}},
        {"record_ref": "memory:b", "record_revision": 4, "facet": "PROFILE", "content": {"value": "杭州"}},
    ]
    ctx = make_ctx(tmp_path, records=rows)

    result = apply_step_action("edit_memory", {"key": "user.location", "old": "杭州", "new": "苏州"}, ctx)

    assert result["status"] == "failed"
    assert "ambiguous" in result["detail"].lower()
    assert ctx.atlas.calls == []


def test_edit_memory_uses_current_revision_and_verifies_active_projection(tmp_path: Path):
    rows = [{
        "record_ref": "memory:location-1", "record_revision": 7, "facet": "PROFILE",
        "content": {"value": "杭州", "text": "我目前住在杭州", "title": "居住地杭州"},
    }]
    ctx = make_ctx(tmp_path, records=rows, atlas_responses=[
        (200, {"record_ref": "memory:location-1", "record_revision": 7, "facet": "PROFILE", "content": rows[0]["content"]}),
        (200, {"acknowledged": True, "record_ref": "memory:location-1"}),
        (200, {"record_ref": "memory:location-1", "record_revision": 8, "facet": "PROFILE", "lifecycle": "ACTIVE",
               "content": {"value": "苏州", "text": "我目前住在苏州", "title": "居住地苏州", "corrected": {"prev_value": "杭州"}}}),
    ])

    result = apply_step_action("edit_memory", {"key": "user.location", "old": "杭州", "new": "苏州"}, ctx)

    assert result["status"] == "ok"
    correction = ctx.atlas.calls[1]
    assert correction["path"] == "/api/unified-memory/corrections"
    assert correction["json_body"]["expected_revision"] == 7
    assert correction["json_body"]["replacement"] == {"value": "苏州"}
    assert "杭州" not in " ".join(str(result["readback"].get("content", {}).get(k, "")) for k in ("value", "text", "title", "summary"))


def test_edit_memory_preserves_revision_conflict_without_claiming_success(tmp_path: Path):
    row = {"record_ref": "memory:location-1", "record_revision": 7, "facet": "PROFILE",
           "content": {"value": "杭州", "text": "我目前住在杭州"}}
    ctx = make_ctx(tmp_path, records=[row], atlas_responses=[
        (200, row),
        (409, {"detail": "revision conflict"}),
    ])

    result = apply_step_action("edit_memory", {"key": "user.location", "old": "杭州", "new": "苏州"}, ctx)

    assert result["status"] == "failed"
    assert ctx.atlas.calls[1]["json_body"]["expected_revision"] == 7
    assert len(ctx.atlas.calls) == 2


def test_switch_model_rejects_missing_target_without_substitution(tmp_path: Path):
    ctx = make_ctx(tmp_path, atlas_responses=[
        (200, {"current": "gemini-3.8-flash", "models": [{"id": "gemini-3.8-flash"}]}),
    ])

    result = apply_step_action("switch_model", {"model": "gpt-4o"}, ctx)

    assert result["status"] == "failed"
    assert len(ctx.atlas.calls) == 1
    assert ctx.atlas.calls[0]["method"] == "GET"


def test_switch_model_requires_readback_of_the_requested_model(tmp_path: Path):
    ctx = make_ctx(tmp_path, atlas_responses=[
        (200, {"current": "gemini-3.8-flash", "models": [{"id": "gemini-3.8-flash"}, {"id": "gpt-4o"}]}),
        (200, {"status": "ok", "model": "gpt-4o"}),
        (200, {"current": "gemini-3.8-flash", "models": [{"id": "gemini-3.8-flash"}, {"id": "gpt-4o"}]}),
    ])

    result = apply_step_action("switch_model", {"model": "gpt-4o"}, ctx)

    assert result["status"] == "failed"
    assert len(ctx.atlas.calls) == 3


def test_delete_memory_requires_unique_real_entity_and_full_hard_erase_verify(tmp_path: Path):
    ctx = make_ctx(tmp_path, memory_responses=[
        (200, {"hard_erase_enabled": True}),
        (200, {"items": [{"id": "entity-42", "canonical_key": "小满", "aliases": []}]}),
        (201, {"preview_id": "preview-1"}),
        (201, {"erasure_id": "erase-1"}),
        (201, {"authorization_id": "authorization-1"}),
        (200, {"erasure_id": "erase-1", "status": "EXECUTED"}),
        (200, {"erasure_id": "erase-1", "status": "VERIFIED", "layers": [{"status": "VERIFIED_ZERO"}],
               "unified_layers": [{"status": "VERIFIED_ZERO"}]}),
    ])

    result = apply_step_action("delete_memory", {"entity": "小满"}, ctx)

    assert result["status"] == "ok"
    paths = [call["path"] for call in ctx.memory.calls]
    assert paths == [
        "/v1/erasure/flag", "/v1/unified/entities", "/v1/erasure/previews",
        "/v1/erasure/requests", "/v1/erasure/authorizations",
        "/v1/erasure/execute", "/v1/erasure/verify",
    ]
    assert ctx.memory.calls[2]["json_body"]["scope"] == {"type": "TARGET_SET", "target_set": ["entity:entity-42"]}
    assert ctx.memory.calls[4]["owner"] is True
    assert ctx.memory.calls[5]["owner"] is False
    assert ctx.memory.calls[6]["owner"] is False


def test_delete_memory_rejects_ambiguous_entity_before_erasure(tmp_path: Path):
    ctx = make_ctx(tmp_path, memory_responses=[
        (200, {"hard_erase_enabled": True}),
        (200, {"items": [
            {"id": "entity-1", "canonical_key": "小满", "aliases": []},
            {"id": "entity-2", "canonical_key": "小满", "aliases": []},
        ]}),
    ])

    result = apply_step_action("delete_memory", {"entity": "小满"}, ctx)

    assert result["status"] == "failed"
    assert len(ctx.memory.calls) == 2


def test_delete_memory_does_not_claim_success_when_physical_verify_fails(tmp_path: Path):
    ctx = make_ctx(tmp_path, memory_responses=[
        (200, {"hard_erase_enabled": True}),
        (200, {"items": [{"id": "entity-42", "canonical_key": "小满", "aliases": []}]}),
        (201, {"preview_id": "preview-1"}),
        (201, {"erasure_id": "erase-1"}),
        (201, {"authorization_id": "authorization-1"}),
        (200, {"erasure_id": "erase-1", "status": "EXECUTED"}),
        (200, {"erasure_id": "erase-1", "status": "FAILED", "layers": [{"status": "RESIDUAL_FOUND"}],
               "unified_layers": [{"status": "VERIFIED_ZERO"}]}),
    ])

    result = apply_step_action("delete_memory", {"entity": "小满"}, ctx)

    assert result["status"] == "failed"
    assert ctx.memory.calls[-1]["path"] == "/v1/erasure/verify"


def test_kill_process_ignores_payload_pid_and_uses_owned_lifecycle_only(tmp_path: Path):
    ctx = make_ctx(
        tmp_path,
        scenario_id=130,
        runtime_capabilities=frozenset({"owned_process_kill"}),
        workspace_files=("docs/file1.md", "docs/file2.md", "docs/file3.md"),
        turn_index=3,
    )
    first_file = ctx.workspace / "docs" / "file1.md"
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_text("first real file", encoding="utf-8")
    payload = {"completed_steps": ["file1.md", "file2.md", "file3.md"], "pid": 8045, "target_pid": 8045}

    result = apply_step_action("kill_process", payload, ctx)

    assert result["status"] == "ok"
    assert ctx.lifecycle.calls == ["crash", "start"]
    assert "pid" not in result["request"]
    assert result["readback"]["pre_crash_files"]["docs/file1.md"] is True
    assert result["readback"]["pre_crash_files"]["docs/file2.md"] is False


def test_kill_process_requires_declared_capability_even_for_scenario_30(tmp_path: Path):
    ctx = make_ctx(
        tmp_path,
        scenario_id=30,
        workspace_files=("docs/file1.md", "docs/file2.md", "docs/file3.md"),
        turn_index=3,
    )
    first_file = ctx.workspace / "docs" / "file1.md"
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_text("first real file", encoding="utf-8")

    result = apply_step_action("kill_process", {"pid": 8045}, ctx)

    assert result["status"] == "failed"
    assert ctx.lifecycle.calls == []
    assert "capability" in result["detail"].lower()


@pytest.mark.parametrize("turn_index", [1, 2, 3])
def test_reminder_audit_never_marks_missing_real_automation_as_success(tmp_path: Path, turn_index: int):
    ctx = make_ctx(tmp_path, scenario_id=29, turn_index=turn_index,
                   user_input="明天上午9点提醒我交报告" if turn_index == 1 else "取消明天上午交报告的那个提醒",
                   atlas_responses=[(200, {"automations": []})],
                   state={"reminder_audit_baseline": {
                       "atlas_automations": {"status_code": 200, "body": {"automations": []}},
                       "memory_intents": [],
                   }})

    result = audit_reminder_state(ctx)

    assert result["status"] == "failed"
    assert result["observations"][0]["status_code"] == 200


def test_capture_pause_and_resume_use_current_revision_and_original_sources(tmp_path: Path):
    pause_ctx = make_ctx(tmp_path / "pause", atlas_responses=[
        (200, {"state": "RUNNING", "revision": 5, "sources": [{"kind": "session", "value": "chat"}]}),
        (200, {"state": "PAUSED", "revision": 6}),
        (200, {"state": "PAUSED", "revision": 6, "sources": [{"kind": "session", "value": "chat"}]}),
    ])
    pause = apply_step_action("pause_capture", {}, pause_ctx)
    assert pause["status"] == "ok"
    assert pause_ctx.atlas.calls[1]["json_body"]["expected_revision"] == 5

    resume_ctx = make_ctx(tmp_path / "resume", atlas_responses=[
        (200, {"state": "PAUSED", "revision": 6, "sources": [{"kind": "session", "value": "chat"}]}),
        (200, {"state": "RUNNING", "revision": 7}),
        (200, {"state": "RUNNING", "revision": 7, "sources": [{"kind": "session", "value": "chat"}]}),
    ])
    resume = apply_step_action("resume_capture", {}, resume_ctx)
    assert resume["status"] == "ok"
    assert resume_ctx.atlas.calls[1]["json_body"] == {
        "request_id": resume_ctx.atlas.calls[1]["json_body"]["request_id"],
        "expected_revision": 6,
        "sources": [{"kind": "session", "value": "chat"}],
    }


def test_reminder_audit_tracks_real_create_cancel_and_empty_run_receipts(tmp_path: Path):
    automation = {"id": "auto-report-1", "name": "明天上午9点交报告", "enabled": True,
                  "revision": 1, "trigger": {"schedule": "tomorrow 09:00"}}
    baseline = {"reminder_audit_baseline": {
        "atlas_automations": {"status_code": 200, "body": {"automations": []}},
        "memory_intents": [],
    }, "reminder_audit_history": [],
      "last_run": {"tool_calls": [{"name": "automation_create"}]}}
    ctx = make_ctx(tmp_path, scenario_id=29, turn_index=1, user_input="明天上午9点提醒我交报告",
                   state=baseline, atlas_responses=[(200, {"automations": [automation]})])
    created = audit_reminder_state(ctx)
    assert created["status"] == "ok"
    ctx.state["reminder_audit_history"].append(created)

    cancelled = {**automation, "enabled": False, "status": "cancelled", "revision": 2}
    ctx.step.turn_index = 2
    ctx.step.user_input = "取消明天上午交报告的那个提醒"
    ctx.state["last_run"] = {"tool_calls": [{"name": "automation_cancel"}]}
    ctx.atlas.responses = [(200, {"automations": [cancelled]})]
    second = audit_reminder_state(ctx)
    assert second["status"] == "ok"
    ctx.state["reminder_audit_history"].append(second)

    ctx.step.turn_index = 3
    ctx.step.user_input = "好的"
    ctx.atlas.responses = [(200, {"automations": [cancelled]}), (200, {"runs": []})]
    third = audit_reminder_state(ctx)
    assert third["status"] == "ok"
    assert third["readback"]["run_receipt_count"] == 0


def test_reminder_audit_accepts_observer_created_and_cancelled_automation_without_tool(
    tmp_path: Path,
):
    automation = {
        "id": "um-intent-pipeline-report", "name": "提醒：交报告", "enabled": True,
        "trigger": {"kind": "date", "at": "2026-10-10T09:00:00+08:00"},
    }
    intent = {"facet": "INTENT", "record_ref": "intent-pipeline-report",
              "lifecycle": "ACTIVE", "content": {"text": "交报告"}}
    baseline = {"reminder_audit_baseline": {
        "atlas_automations": {"status_code": 200, "body": {"automations": []}},
        "memory_intents": [],
    }, "reminder_audit_history": [], "last_run": {"tool_calls": []}}
    ctx = make_ctx(
        tmp_path, scenario_id=29, turn_index=1, user_input="明天提醒我交报告",
        state=baseline, atlas_responses=[(200, {"automations": [automation]})],
        records=[intent],
    )

    created = audit_reminder_state(ctx)
    assert created["status"] == "ok"
    ctx.state["reminder_audit_history"].append(created)

    cancelled = {**automation, "enabled": False}
    ctx.step.turn_index = 2
    ctx.step.user_input = "取消明天交报告的提醒"
    ctx.state["last_run"] = {"tool_calls": []}
    ctx.atlas.responses = [(200, {"automations": [cancelled]})]
    ctx.memory.records = lambda facet=None: [{**intent, "lifecycle": "CANCELLED"}]
    second = audit_reminder_state(ctx)
    assert second["status"] == "ok"
    ctx.state["reminder_audit_history"].append(second)

    ctx.step.turn_index = 3
    ctx.step.user_input = "好的"
    ctx.atlas.responses = [(200, {"automations": [cancelled]}), (200, {"runs": []})]
    third = audit_reminder_state(ctx)
    assert third["status"] == "ok"
    assert third["readback"]["run_receipt_count"] == 0


def test_reminder_audit_requires_tool_evidence_for_store_change(tmp_path: Path):
    baseline = {"reminder_audit_baseline": {
        "atlas_automations": {"status_code": 200, "body": {"automations": []}},
        "memory_intents": [],
    }, "last_run": {"tool_calls": []}}
    ctx = make_ctx(tmp_path, scenario_id=29, turn_index=1, user_input="明天提醒我交报告",
                   state=baseline,
                   atlas_responses=[(200, {"automations": [
                       {"id": "auto-report-1", "name": "明天交报告", "enabled": True}
                   ]})])

    result = audit_reminder_state(ctx)

    assert result["status"] == "failed"
    assert result["readback"]["created_ids"] == ["auto-report-1"]
