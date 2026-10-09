"""Real API adapters for MEMORY-V1 scenario actions.

Actions use only the isolated clients supplied by ``eval_scenarios``. A
successful result always contains the request/response trace and an authoritative
readback; unsupported product behavior remains a scenario failure.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from scripts.memory_v1.eval_scenarios import ScenarioActionContext


class _ActionFailure(Exception):
    pass


class _Trace:
    def __init__(self, action: str):
        self.action = action
        self.requests: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []

    def call(
        self,
        client: Any,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        owner: bool = False,
    ) -> tuple[int, Any]:
        request: dict[str, Any] = {"method": method.upper(), "path": path}
        if json_body is not None:
            request["json"] = json_body
        if params:
            request["params"] = params
        if owner:
            request["owner_authorization"] = "isolated-owner-token"
        self.requests.append(request)
        try:
            kwargs = {"json_body": json_body, "params": params}
            if owner:
                kwargs["owner"] = True
            response = client.request(method, path, **kwargs)
            status = int(response.get("status_code", 0))
            body = response.get("body")
        except Exception as exc:  # preserve actual failure without leaking credentials
            status = 0
            body = {"error_type": type(exc).__name__, "detail": "isolated request transport failed"}
        self.observations.append({"status_code": status, "response": body})
        return status, body

    def result(self, status: str, *, readback: Any = None, detail: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action": self.action,
            "status": status,
            "request": self.requests,
            "observations": self.observations,
            "readback": readback,
        }
        if detail:
            result["detail"] = detail
        return result


def _ok(status: int) -> bool:
    return 200 <= status < 300


def _body_dict(body: Any) -> dict[str, Any]:
    return body if isinstance(body, dict) else {}


def _as_items(body: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return []
    for key in keys:
        items = body.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _record_content(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("content")
    return value if isinstance(value, dict) else {}


def _find_correction_target(records: list[dict[str, Any]], old: str, key: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("facet", "")).upper() not in {"PROFILE", "PREFERENCE"}:
            continue
        ref = record.get("record_ref")
        content = _record_content(record)
        if not isinstance(ref, str) or not ref.startswith("memory:"):
            continue
        explicit_key = str(record.get("key") or content.get("key") or "")
        active_values = [content.get(name) for name in ("value", "text", "title", "summary")]
        if explicit_key == key or any(value == old for value in active_values):
            matches.append(record)
    return matches


def _active_projection_contains(content: dict[str, Any], value: str) -> bool:
    return any(value and value in str(content.get(name) or "")
               for name in ("value", "text", "title", "summary"))


def _edit_memory(payload: dict[str, Any], ctx: Any, trace: _Trace) -> dict[str, Any]:
    key = str(payload.get("key") or "").strip()
    old = str(payload.get("old") or "").strip()
    new = str(payload.get("new") or "").strip()
    if not key or not old or not new or old == new:
        return trace.result("failed", detail="edit_memory requires distinct key, old, and new values")
    try:
        records = ctx.memory.records()
    except Exception as exc:  # noqa: BLE001
        return trace.result("failed", detail=f"MemoryOS record read failed: {type(exc).__name__}")
    if not isinstance(records, list):
        return trace.result("failed", detail="MemoryOS records returned an invalid result")
    candidates = _find_correction_target(records, old, key)
    if len(candidates) != 1:
        reason = "ambiguous current records match the requested correction" if len(candidates) > 1 else \
            "no current record matches the requested correction"
        return trace.result("failed", detail=f"{reason} (matches={len(candidates)})")
    target_ref = str(candidates[0]["record_ref"])
    encoded_ref = quote(target_ref, safe="")
    status, current = trace.call(ctx.atlas, "GET", f"/api/unified-memory/records/{encoded_ref}")
    if not _ok(status) or not isinstance(current, dict):
        return trace.result("failed", detail=f"current record read failed (HTTP {status})")
    revision = current.get("record_revision")
    if current.get("record_ref") != target_ref or not isinstance(revision, int) or revision < 1:
        return trace.result("failed", detail="current record identity/revision is missing or mismatched")
    content = _record_content(current)
    if not _active_projection_contains(content, old):
        return trace.result("failed", detail="current active record no longer contains the requested old value")
    body = {
        "request_id": f"f1d-correction-{uuid.uuid4()}",
        "target_ref": target_ref,
        "expected_revision": revision,
        "replacement": {"value": new},
        "source": "desktop-correction",
    }
    status, correction = trace.call(ctx.atlas, "POST", "/api/unified-memory/corrections", json_body=body)
    if not _ok(status) or not isinstance(correction, dict) or correction.get("acknowledged") is not True:
        return trace.result("failed", detail=f"correction was not acknowledged (HTTP {status})")
    status, readback = trace.call(ctx.atlas, "GET", f"/api/unified-memory/records/{encoded_ref}")
    if not _ok(status) or not isinstance(readback, dict):
        return trace.result("failed", detail=f"corrected record readback failed (HTTP {status})")
    corrected_content = _record_content(readback)
    if (readback.get("record_ref") != target_ref
            or readback.get("lifecycle") != "ACTIVE"
            or readback.get("record_revision", 0) <= revision
            or corrected_content.get("value") != new
            or _active_projection_contains(corrected_content, old)):
        return trace.result("failed", readback=readback,
                            detail="corrected record readback did not replace the active value")
    return trace.result("ok", readback=readback)


def _switch_model(payload: dict[str, Any], ctx: Any, trace: _Trace) -> dict[str, Any]:
    target = str(payload.get("model") or "").strip()
    if not target:
        return trace.result("failed", detail="switch_model requires a target model id")
    status, models = trace.call(ctx.atlas, "GET", "/api/models")
    if not _ok(status) or not isinstance(models, dict):
        return trace.result("failed", detail=f"model list read failed (HTTP {status})")
    current = models.get("current")
    available = _as_items(models, "models")
    if not any(item.get("id") == target for item in available):
        return trace.result("failed", detail="requested model id is not available; no substitute was selected")
    if current == target:
        return trace.result("failed", detail="requested model is already selected; no model change occurred")
    status, selected = trace.call(ctx.atlas, "POST", "/api/models/select", json_body={"model": target})
    if not _ok(status) or not isinstance(selected, dict) or selected.get("model") != target:
        return trace.result("failed", detail=f"model selection was not acknowledged (HTTP {status})")
    status, readback = trace.call(ctx.atlas, "GET", "/api/models")
    if not _ok(status) or not isinstance(readback, dict) or readback.get("current") != target:
        return trace.result("failed", readback=readback,
                            detail=f"selected model did not read back as {target!r} (HTTP {status})")
    return trace.result("ok", readback={"current": readback.get("current")})


def _capture_control(action: str, ctx: Any, trace: _Trace) -> dict[str, Any]:
    status, before = trace.call(ctx.atlas, "GET", "/api/unified-memory/capture/status")
    if not _ok(status) or not isinstance(before, dict):
        return trace.result("failed", detail=f"capture status read failed (HTTP {status})")
    state = str(before.get("state") or "").upper()
    revision = before.get("revision")
    if not isinstance(revision, int):
        return trace.result("failed", detail="capture status has no integer revision")
    if action == "pause_capture":
        if state != "RUNNING":
            return trace.result("failed", detail=f"capture must be RUNNING before pause (state={state!r})")
        path = "/api/unified-memory/capture/pause"
        body = {"request_id": f"f1d-pause-{uuid.uuid4()}", "expected_revision": revision}
        wanted = "PAUSED"
    else:
        if state != "PAUSED":
            return trace.result("failed", detail=f"capture must be PAUSED before resume (state={state!r})")
        if "sources" not in before or not isinstance(before.get("sources"), list):
            return trace.result("failed", detail="paused capture readback has no original sources to resume")
        path = "/api/unified-memory/capture/start"
        body = {
            "request_id": f"f1d-resume-{uuid.uuid4()}",
            "expected_revision": revision,
            "sources": before["sources"],
        }
        wanted = "RUNNING"
    status, response = trace.call(ctx.atlas, "POST", path, json_body=body)
    if not _ok(status) or not isinstance(response, dict):
        return trace.result("failed", detail=f"capture control request failed (HTTP {status})")
    status, readback = trace.call(ctx.atlas, "GET", "/api/unified-memory/capture/status")
    if (not _ok(status) or not isinstance(readback, dict)
            or str(readback.get("state") or "").upper() != wanted
            or not isinstance(readback.get("revision"), int)
            or readback["revision"] <= revision):
        return trace.result("failed", readback=readback,
                            detail=f"capture status did not transition to {wanted} at a newer revision")
    return trace.result("ok", readback=readback)


def _delete_memory(payload: dict[str, Any], ctx: Any, trace: _Trace) -> dict[str, Any]:
    target = str(payload.get("entity") or "").strip()
    if not target:
        return trace.result("failed", detail="delete_memory requires an entity name")
    status, flag = trace.call(ctx.memory, "GET", "/v1/erasure/flag")
    if not _ok(status) or not isinstance(flag, dict):
        return trace.result("failed", detail=f"hard erase feature flag read failed (HTTP {status})")
    if flag.get("hard_erase_enabled") is not True:
        return trace.result("failed", detail="isolated MemoryOS has hard erase disabled")
    status, found = trace.call(
        ctx.memory, "GET", "/v1/unified/entities",
        params={"query": target, "memory_subject_id": ctx.subject_id, "limit": 200},
    )
    if not _ok(status) or not isinstance(found, dict):
        return trace.result("failed", detail=f"entity lookup failed (HTTP {status})")
    exact: dict[str, dict[str, Any]] = {}
    for entity in _as_items(found, "items"):
        names = [entity.get("canonical_key"), entity.get("canonical_name"), entity.get("name")]
        aliases = _as_items(entity, "aliases")
        names.extend(alias.get("alias") for alias in aliases
                     if str(alias.get("alias_status") or "").upper() != "REVOKED")
        if target in {str(name).strip() for name in names if name is not None}:
            entity_id = entity.get("id")
            if isinstance(entity_id, str) and entity_id:
                exact[entity_id] = entity
    if len(exact) != 1:
        return trace.result("failed", detail=f"entity target is not unique (matches={len(exact)})")
    entity_id, entity = next(iter(exact.items()))
    scope = {"type": "TARGET_SET", "target_set": [f"entity:{entity_id}"]}
    status, preview = trace.call(ctx.memory, "POST", "/v1/erasure/previews", json_body={
        "memory_subject_id": ctx.subject_id, "scope": scope, "mode": "HARD_ERASE",
    })
    preview_id = _body_dict(preview).get("preview_id")
    if not _ok(status) or not isinstance(preview_id, str) or not preview_id:
        return trace.result("failed", detail=f"hard erase preview was not created (HTTP {status})")
    status, request = trace.call(ctx.memory, "POST", "/v1/erasure/requests", json_body={
        "preview_id": preview_id, "reason": f"F1-D scenario {ctx.scenario_id} user-requested deletion",
    })
    erasure_id = _body_dict(request).get("erasure_id")
    if not _ok(status) or not isinstance(erasure_id, str) or not erasure_id:
        return trace.result("failed", detail=f"hard erase request was not created (HTTP {status})")
    status, authorization = trace.call(ctx.memory, "POST", "/v1/erasure/authorizations", owner=True,
                                       json_body={"erasure_id": erasure_id, "mode": "HARD_ERASE",
                                                  "nonce": str(uuid.uuid4())})
    authorization_id = _body_dict(authorization).get("authorization_id")
    if not _ok(status) or not isinstance(authorization_id, str) or not authorization_id:
        return trace.result("failed", detail=f"owner authorization failed (HTTP {status})")
    status, execution = trace.call(ctx.memory, "POST", "/v1/erasure/execute", json_body={
        "erasure_id": erasure_id, "authorization_id": authorization_id,
    })
    if not _ok(status) or not isinstance(execution, dict) or execution.get("status") in {"FAILED", "REJECTED"}:
        return trace.result("failed", detail=f"hard erase execution failed (HTTP {status})")
    status, verification = trace.call(ctx.memory, "POST", "/v1/erasure/verify", json_body={"erasure_id": erasure_id})
    if not _ok(status) or not isinstance(verification, dict) or verification.get("status") != "VERIFIED":
        return trace.result("failed", readback=verification,
                            detail=f"hard erase physical verification did not report VERIFIED (HTTP {status})")
    if not verification.get("layers") or not verification.get("unified_layers"):
        return trace.result("failed", readback=verification,
                            detail="hard erase verification omitted physical or unified layer results")
    for field in ("layers", "unified_layers"):
        for layer in _as_items(verification, field):
            if layer.get("status") not in {"VERIFIED_ZERO", "NOT_APPLICABLE"}:
                return trace.result("failed", readback=verification,
                                    detail=f"hard erase verification contains a non-zero {field} result")
    return trace.result("ok", readback={
        "entity_id": entity_id,
        "preview_id": preview_id,
        "erasure_id": erasure_id,
        "authorization_id": authorization_id,
        "execution_status": execution.get("status"),
        "verification_status": verification.get("status"),
        "verified_layers": len(verification["layers"]),
        "verified_unified_layers": len(verification["unified_layers"]),
    })


def _safe_workspace_file(workspace: Path, name: str) -> bool:
    candidate = workspace / name
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(workspace)
    except (OSError, ValueError):
        return False
    return candidate.is_file()


def _lifecycle_action(action: str, ctx: Any, trace: _Trace) -> dict[str, Any]:
    if action == "restart":
        try:
            restarted = ctx.lifecycle.restart()
        except Exception as exc:  # noqa: BLE001
            return trace.result("failed", detail=f"owned Atlas restart failed: {type(exc).__name__}")
        if (not isinstance(restarted, dict) or not isinstance(restarted.get("pid"), int)
                or not isinstance(restarted.get("port"), int)
                or not isinstance(restarted.get("creation_time"), (int, float))
                or not isinstance(restarted.get("route"), dict)):
            return trace.result("failed", readback=restarted,
                                detail="owned Atlas restart did not return process identity and route readback")
        trace.requests.append({"operation": "lifecycle.restart_owned_atlas"})
        trace.observations.append({"status_code": 200, "response": {"pid": restarted["pid"],
                                                                     "port": restarted["port"],
                                                                     "creation_time": restarted["creation_time"]}})
        return trace.result("ok", readback=restarted)

    if "owned_process_kill" not in ctx.runtime_capabilities:
        return trace.result("failed", detail="kill_process requires the declared owned_process_kill capability")
    workspace = Path(ctx.workspace).resolve()
    lifecycle_workspace = Path(ctx.lifecycle.workspace).resolve()
    artifact_dir = Path(ctx.artifact_dir).resolve()
    if workspace != lifecycle_workspace or workspace.parent != artifact_dir.parent:
        return trace.result("failed", detail="workspace does not match the runner-owned isolated runtime")
    if not ctx.workspace_files:
        return trace.result("failed", detail="owned_process_kill requires declared workspace files")
    pre_crash = {name: _safe_workspace_file(workspace, name) for name in ctx.workspace_files}
    required_completed_file = ctx.workspace_files[0]
    if not pre_crash[required_completed_file]:
        return trace.result("failed", readback={"pre_crash_files": pre_crash},
                            detail="the first declared workspace task file is absent before crash")
    try:
        crashed = ctx.lifecycle.crash()
        if (not isinstance(crashed, dict) or crashed.get("terminated") is not True
                or not isinstance(crashed.get("pid"), int)
                or not isinstance(crashed.get("creation_time"), (int, float))):
            return trace.result("failed", readback={"pre_crash_files": pre_crash, "crash": crashed},
                                detail="owned Atlas lifecycle did not confirm identity-checked crash")
        route = ctx.lifecycle.start()
    except Exception as exc:  # noqa: BLE001
        return trace.result("failed", readback={"pre_crash_files": pre_crash},
                            detail=f"owned Atlas crash/recovery failed: {type(exc).__name__}")
    if not isinstance(route, dict) or route.get("credential_value_recorded") is not False:
        return trace.result("failed", readback={"pre_crash_files": pre_crash, "route": route},
                            detail="restarted isolated Atlas did not return safe verified route metadata")
    trace.requests.append({"operation": "lifecycle.crash_owned_atlas_then_start"})
    trace.observations.append({"status_code": 200, "response": {
        "owned_pid": crashed["pid"], "terminated": True,
        "route_provider_id": route.get("provider_id"),
    }})
    return trace.result("ok", readback={"crash": crashed, "route": route,
                                        "pre_crash_files": pre_crash})


def apply_step_action(action: str, payload: dict[str, Any], ctx: ScenarioActionContext) -> dict[str, Any]:
    """Execute one declared scenario action through the runner's isolated clients."""
    trace = _Trace(action)
    if not isinstance(payload, dict):
        return trace.result("failed", detail="action payload must be an object")
    step_action = getattr(ctx.step, "action", None)
    if step_action is not None and step_action != action:
        return trace.result("failed", detail="adapter action does not match the runner's original step")
    step_payload = getattr(ctx.step, "action_payload", None)
    if step_action is not None and isinstance(step_payload, dict) and step_payload != payload:
        return trace.result("failed", detail="adapter payload does not match the runner's original step payload")
    try:
        if action == "edit_memory":
            return _edit_memory(payload, ctx, trace)
        if action == "switch_model":
            return _switch_model(payload, ctx, trace)
        if action in {"pause_capture", "resume_capture"}:
            return _capture_control(action, ctx, trace)
        if action == "delete_memory":
            return _delete_memory(payload, ctx, trace)
        if action in {"restart", "kill_process"}:
            return _lifecycle_action(action, ctx, trace)
        return trace.result("unsupported", detail=f"no real isolated adapter for action {action!r}")
    except Exception as exc:  # noqa: BLE001
        return trace.result("failed", detail=f"action adapter failed: {type(exc).__name__}")


def _automation_items(body: Any) -> list[dict[str, Any]]:
    return _as_items(body, "automations", "items")


def _automation_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("automation_id") or "")


def _automation_text(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _tool_names(last_run: Any) -> set[str]:
    if not isinstance(last_run, dict):
        return set()
    calls = last_run.get("tool_calls") or []
    names: set[str] = set()
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, str):
                names.add(call.lower())
            elif isinstance(call, dict):
                name = call.get("name") or call.get("tool_name") or call.get("tool")
                if isinstance(name, str):
                    names.add(name.lower())
    return names


def _intent_items(ctx: Any) -> list[dict[str, Any]]:
    records = ctx.memory.records(facet="INTENT")
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def audit_reminder_state(ctx: ScenarioActionContext) -> dict[str, Any]:
    """Read-only S29 audit across actual AutomationStore and MemoryOS intent records.

    The runner captures a pre-turn-1 baseline, then invokes this after each real
    chat. A missing creation, missing cancellation transition, or unreadable run
    receipts remains a failure; an empty final store alone never proves success.
    """
    trace = _Trace("reminder_readonly_audit")
    turn = int(ctx.step.turn_index)
    status, current_body = trace.call(ctx.atlas, "GET", "/api/automations")
    if not _ok(status) or not isinstance(current_body, dict):
        return trace.result("failed", detail=f"AutomationStore read failed (HTTP {status})")
    current = _automation_items(current_body)
    try:
        intents = _intent_items(ctx)
    except Exception as exc:  # noqa: BLE001
        return trace.result("failed", detail=f"MemoryOS intent read failed: {type(exc).__name__}")
    intent_ids = {str(item.get("record_ref") or item.get("id") or "") for item in intents}
    history = ctx.state.get("reminder_audit_history") or []
    baseline = ctx.state.get("reminder_audit_baseline")
    if not isinstance(baseline, dict):
        return trace.result("failed", readback={"turn": turn, "automation_count": len(current),
                                                "intent_ids": sorted(item for item in intent_ids if item)},
                            detail="runner did not capture a pre-turn AutomationStore/intent baseline")
    base_response = baseline.get("atlas_automations")
    if not isinstance(base_response, dict) or base_response.get("status_code") != 200:
        return trace.result("failed", detail="pre-turn AutomationStore baseline is unavailable")
    baseline_items = _automation_items(base_response.get("body"))
    baseline_ids = {_automation_id(item) for item in baseline_items}
    base_intents = baseline.get("memory_intents")
    if not isinstance(base_intents, list):
        return trace.result("failed", detail="pre-turn MemoryOS intent baseline is unavailable")
    baseline_intent_ids = {str(item.get("record_ref") or item.get("id") or "")
                           for item in base_intents if isinstance(item, dict)}
    term = "报告" if "报告" in str(ctx.step.user_input) else ""

    if turn == 1:
        names = _tool_names(ctx.state.get("last_run"))
        creation_tools = {name for name in names if any(word in name for word in ("automation", "reminder", "schedule", "cron"))}
        created = [item for item in current
                   if _automation_id(item) and _automation_id(item) not in baseline_ids
                   and (not term or term in _automation_text(item))]
        new_intents = [item for item in intents
                       if str(item.get("record_ref") or item.get("id") or "") not in baseline_intent_ids
                       and (not term or term in _automation_text(item))]
        if (len(created) != 1 or not creation_tools
                or created[0].get("enabled") is False
                or str(created[0].get("status") or created[0].get("state") or "").lower()
                in {"cancelled", "canceled", "deleted", "disabled", "paused"}):
            return trace.result("failed", readback={"turn": turn, "created_ids": [_automation_id(item) for item in created],
                                                    "creation_tool_names": sorted(creation_tools)},
                                detail="real chat did not create one matching AutomationStore record through a reminder tool")
        selected = created[0]
        result = trace.result("ok", readback={"turn": turn, "created": selected,
                                              "new_intent_refs": [str(item.get("record_ref") or item.get("id")) for item in new_intents],
                                              "intent_ids": sorted(item for item in intent_ids if item),
                                              "automation_count": len(current)})
        return result

    first = next((item for item in history if isinstance(item, dict)
                  and item.get("action") == "reminder_readonly_audit"
                  and isinstance(item.get("readback"), dict)
                  and item["readback"].get("turn") == 1), None)
    created = first.get("readback", {}).get("created") if first else None
    created_id = _automation_id(created) if isinstance(created, dict) else ""
    if not created_id:
        return trace.result("failed", readback={"turn": turn, "automation_count": len(current)},
                            detail="no verified turn-1 created reminder exists in audit history")

    current_item = next((item for item in current if _automation_id(item) == created_id), None)
    if turn == 2:
        cancellation_tools = {name for name in _tool_names(ctx.state.get("last_run"))
                              if any(word in name for word in ("automation", "reminder", "schedule", "cron"))}
        cancelled = current_item is None
        if current_item is not None:
            state = str(current_item.get("status") or current_item.get("state") or "").lower()
            cancelled = current_item.get("enabled") is False or state in {
                "cancelled", "canceled", "deleted", "disabled", "paused",
            }
        if not cancelled or not cancellation_tools:
            return trace.result("failed", readback={"turn": turn, "automation_id": created_id,
                                                    "still_present": current_item is not None,
                                                    "cancellation_tool_names": sorted(cancellation_tools)},
                                detail="real chat did not cancel/delete the same reminder through a tool")
        result = trace.result("ok", readback={"turn": turn, "automation_id": created_id,
                                              "cancelled_or_deleted": True,
                                              "current_status": current_item.get("status") if current_item else "DELETED",
                                              "current_enabled": current_item.get("enabled") if current_item else None,
                                              "intent_ids": sorted(item for item in intent_ids if item)})
        return result

    second = next((item for item in history if isinstance(item, dict)
                   and item.get("action") == "reminder_readonly_audit"
                   and isinstance(item.get("readback"), dict)
                   and item["readback"].get("turn") == 2), None)
    if not second or second.get("status") != "ok" or second.get("readback", {}).get("automation_id") != created_id:
        return trace.result("failed", readback={"turn": turn, "automation_id": created_id},
                            detail="turn-2 cancellation of the same reminder was not verified")
    status, runs_body = trace.call(ctx.atlas, "GET", f"/api/automations/{created_id}/runs")
    if not _ok(status):
        return trace.result("failed", readback={"turn": turn, "automation_id": created_id},
                            detail=f"same-reminder run receipt read failed (HTTP {status})")
    runs = _as_items(runs_body, "runs", "items")
    if runs:
        return trace.result("failed", readback={"turn": turn, "automation_id": created_id,
                                                "run_receipt_count": len(runs)},
                            detail="cancelled reminder has a recorded run receipt")
    if current_item is not None and (current_item.get("enabled") is not False
                                     and str(current_item.get("status") or current_item.get("state") or "").lower()
                                     not in {"cancelled", "canceled", "deleted", "disabled", "paused"}):
        return trace.result("failed", readback={"turn": turn, "automation_id": created_id,
                                                "current_status": current_item.get("status"),
                                                "current_enabled": current_item.get("enabled")},
                            detail="cancelled reminder became active again")
    return trace.result("ok", readback={"turn": turn, "automation_id": created_id,
                                        "run_receipt_count": 0,
                                        "cancelled_or_deleted": current_item is None or current_item.get("enabled") is False
                                        or str(current_item.get("status") or current_item.get("state") or "").lower()
                                        in {"cancelled", "canceled", "deleted", "disabled", "paused"}})
