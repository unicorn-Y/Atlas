"""K1 phase G3: fake-model daily-path verification over the real HTTP/WS surface.

One scenario per test. Each drives a fresh isolated ``atlas.server`` subprocess
(ephemeral port, isolated data dirs, scheduler off) through ``/ws/chat``
``run.start`` with the loopback fake LLM provider scripting minimal tool-call
plans, and asserts on the event stream plus final on-disk / API state.

Covers K1 taskbook scenarios 1-6 and 12-15. Scenarios 7-11 (X2 browser,
computer-use fake driver, X4 market, X2 recordings, X5 candidates) live in
``test_k1_daily_paths_x2x4x5.py`` and are xfail-pending Phase F wiring.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from tests.fakes.fake_llm_provider import Error, StallMidStream, Text, ToolCall
from tests.fakes.k1_harness import (  # noqa: F401  (k1_backend is a fixture)
    TERMINAL_EVENTS,
    k1_backend,
    last_user_text,
    ws_run,
)


def _git(workspace, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=str(workspace), check=True, capture_output=True, env=env)


def _completed(events, name):
    return [e for e in events if e["event"] == "tool.completed" and e["data"].get("name") == name]


def _has_message(events, needle):
    return any(e["event"] == "message.completed" and needle in str(e["data"].get("content"))
               for e in events)


def _completed_any(events, names):
    return [e for e in events if e["event"] == "tool.completed" and e["data"].get("name") in names]


# ---------------------------------------------------------------------------
# 1. new session -> pick workspace -> edit via tools -> read diff -> /review -> fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_edit_diff_review_then_fix(k1_backend):  # noqa: F811
    backend = k1_backend
    workspace = backend.root / "gitws"
    workspace.mkdir()
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.name", "K1 fixture")
    _git(workspace, "config", "user.email", "k1@example.invalid")
    target = workspace / "app.txt"
    target.write_text("line one\ncat line\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "baseline")

    # -- new session, workspace picked, file edited through tools, diff read --
    turns = {"n": 0}

    def edit_responder(record):
        turns["n"] += 1
        if turns["n"] == 1:
            return ToolCall("patch", {"path": str(target), "old_string": "cat line",
                                      "new_string": "dog line"})
        if turns["n"] == 2:
            return ToolCall("terminal", {"command": "git --no-pager diff", "shell": "powershell"})
        return Text("edit complete, diff shown")

    backend.fake._responder = edit_responder
    conversation, events = await backend.run("edit app.txt and show me the diff",
                                             workspace=str(workspace))
    assert "dog line" in target.read_text(encoding="utf-8")
    patches = _completed(events, "patch")
    assert patches and not patches[0]["data"].get("is_error")
    diff_calls = _completed_any(events, {"terminal", "local_shell"})
    assert diff_calls, events
    assert "dog line" in str(diff_calls[0]["data"])

    # -- /review: intercepted, read-only reviewer child, findings event --
    finding = {"file": "app.txt", "line": 2, "range": None, "severity": "major",
               "title": "K1_FINDING dog line is wrong", "explanation": "it must read fixed line",
               "evidence": "-cat line\n+dog line", "suggested_fix": "write fixed line"}
    findings = json.dumps([finding], ensure_ascii=False)
    review = {"dispatched": False, "submitted": False}

    def review_responder(record):
        text = last_user_text(record)
        if "独立代码审查" in text and "用户请求审查" not in text:
            # reviewer child: the goal is exactly the reviewer brief
            return Text(findings)
        if "用户请求审查" in text and not review["dispatched"]:
            review["dispatched"] = True
            return ToolCall("delegate_task", {"tasks": [{"title": "review working tree",
                "goal": "独立代码审查：审查工作区未提交改动，只输出 findings JSON 数组"}],
                "background": False, "agent": "general", "permission_mode": "read_only"})
        if review["dispatched"] and not review["submitted"]:
            review["submitted"] = True
            return ToolCall("submit_findings", {"findings_json": findings,
                "scope": "working_tree", "scope_label": "工作区未提交改动"})
        return Text("审查完成：blocker 0 条，major 1 条，minor 0 条。")

    backend.fake._responder = review_responder
    backend.fake._aux = lambda record: (
        Text('{"goal":"审查工作区未提交改动","subtasks":[{"id":"review",'
             '"title":"派出审查员并提交 findings","verification":"findings JSON 数组已提交"}]}')
        if "goal and subtasks" in json.dumps(record, ensure_ascii=False)
        else Text("Fake summary of the earlier conversation."))
    _, review_events = await backend.run("/review", conversation=conversation,
                                         workspace=str(workspace))
    assert review_events[-1]["event"] == "run.completed", review_events[-1]
    assert review["dispatched"] and review["submitted"]
    findings_events = [e for e in review_events if e["event"] == "review.findings"]
    assert findings_events and "K1_FINDING" in str(findings_events[0])
    assert not any(e["event"] == "approval.required" for e in review_events), \
        "review runs are read-only and must not raise approval cards"

    # -- fix the finding in a follow-up run on the same conversation --
    fixes = {"n": 0}

    def fix_responder(record):
        fixes["n"] += 1
        if fixes["n"] == 1:
            return ToolCall("patch", {"path": str(target), "old_string": "dog line",
                                      "new_string": "fixed line"})
        return Text("K1_FIX_APPLIED")

    backend.fake._responder = fix_responder
    _, fix_events = await backend.run("fix the review finding in app.txt",
                                      conversation=conversation, workspace=str(workspace))
    assert fix_events[-1]["event"] == "run.completed", fix_events[-1]
    assert "fixed line" in target.read_text(encoding="utf-8")
    assert _has_message(fix_events, "K1_FIX_APPLIED")


# ---------------------------------------------------------------------------
# 2. long task crossing auto-compaction, then continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_long_task_compacts_then_continues(k1_backend):  # noqa: F811
    backend = k1_backend
    config = backend.root / "atlas/engine/config.yaml"
    config.write_text(config.read_text().replace("128000", "64000") +
        "  compression:\n    provider: custom\n    model: fake-model\n"
        f"    base_url: {backend.fake.base_url}\n    api_key: sk-fake-e2e\n", encoding="utf-8")
    backend.fake.context_length = 64000  # Hermes' minimum supported window.
    backend.fake.prompt_tokens_fn = lambda body: len(json.dumps(body, ensure_ascii=False)) // 2
    turns = {"n": 0}

    def responder(record):
        turns["n"] += 1
        if turns["n"] <= 12:
            return ToolCall("terminal", {"command": "Write-Output ('fixture-context ' * 2600)",
                                         "shell": "powershell"})
        return Text("K1_COMPACT_CONTINUED")

    backend.fake._responder = responder
    _, events = await backend.run("K1_COMPACT gather lots of context and finish", timeout=150)
    assert turns["n"] >= 13
    assert any(e["event"] == "run.compaction.progress" for e in events), \
        "a long task must surface an auto-compaction event"
    assert backend.fake.aux_requests(), "compression summary must be requested from the provider"
    request_log = backend.fake.requests
    last_aux = max(i for i, item in enumerate(request_log) if item["kind"] == "aux")
    assert any(item["kind"] == "main" for item in request_log[last_aux:]), \
        "the run must continue with real model turns after compaction"
    assert _has_message(events, "K1_COMPACT_CONTINUED")
    assert events[-1]["event"] == "run.completed"


# ---------------------------------------------------------------------------
# 3. steer (mid-run user message) / queue / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_steer_queue_and_stop(k1_backend):  # noqa: F811
    backend = k1_backend
    first = {"done": False}

    def responder(record):
        if not first["done"]:
            first["done"] = True
            return ToolCall("terminal", {
                "command": "Start-Sleep -Milliseconds 800; Write-Output K1",
                "shell": "powershell"})
        return Text("K1_STEER_CONSUMED")

    backend.fake._responder = responder
    sent = {"done": False}

    async def steer(ws, event):
        if event["event"] == "tool.started" and not sent["done"]:
            sent["done"] = True
            for text in ("K1_STEER_ONE", "K1_STEER_TWO"):
                await ws.send(json.dumps({"type": "run.steer", "run_id": event["run_id"],
                                          "content": text, "event_id": uuid.uuid4().hex}))

    _, events = await backend.run("start a task so the steering messages can queue",
                                  respond=steer)
    requests = backend.fake.main_requests()
    assert "K1_STEER_ONE" in str(requests[-1]) and "K1_STEER_TWO" in str(requests[-1]), \
        "both queued steering messages must reach the next model turn"
    assert len([e for e in events if e["event"] == "run.steered"]) == 2

    backend.fake._responder = lambda record: StallMidStream(seconds=20)

    async def cancel(ws, event):
        if event["event"] == "run.started":
            await ws.send(json.dumps({"type": "run.cancel", "run_id": event["run_id"]}))

    _, stopped = await backend.run("stop this run mid-stream", respond=cancel,
                                   expected="run.cancelled")
    assert stopped[-1]["event"] == "run.cancelled"


# ---------------------------------------------------------------------------
# 4. plan mode -> approve -> execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_plan_mode_approve_then_execute(k1_backend):  # noqa: F811
    backend = k1_backend
    plan_target = backend.root / "workspace/plan-output.txt"
    approved = {"v": False}
    executed = {"v": False}

    def responder(record):
        if not approved["v"]:
            return Text("K1_PLAN_READY: 1) write plan-output.txt 2) confirm")
        if not executed["v"]:
            executed["v"] = True
            return ToolCall("write_file", {"path": str(plan_target),
                                           "content": "K1_PLANNED_AND_APPROVED"})
        return Text("K1_PLAN_EXECUTED")

    backend.fake._responder = responder

    async def approve(ws, event):
        if event["event"] == "run.plan.proposed":
            approved["v"] = True
            await ws.send(json.dumps({"type": "run.plan.approve", "run_id": event["run_id"],
                                      "event_id": event["data"]["event_id"]}))

    _, events = await backend.run("plan writing the K1 output file, then do it",
                                  mode="plan", permission_mode="plan", respond=approve)
    assert any(e["event"] == "run.plan.proposed" for e in events)
    assert approved["v"], "the plan proposal must be approvable over the socket"
    assert plan_target.read_text(encoding="utf-8") == "K1_PLANNED_AND_APPROVED", \
        "after approval the plan must execute with real write tools"
    assert _has_message(events, "K1_PLAN_EXECUTED")
    assert events[-1]["event"] == "run.completed"


# ---------------------------------------------------------------------------
# 5. parallel subagents (two delegate_task calls in one script) + verifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_parallel_subagents_with_verifier_acceptance(k1_backend):  # noqa: F811
    backend = k1_backend
    delegated = {"v": False}

    def responder(record):
        text = last_user_text(record)
        if "验收并行任务" in text:
            return Text('{"verified":true,"note":"both results contain OK"}')
        if "CHILD_ALPHA" in text:
            return Text("alpha OK")
        if "CHILD_BETA" in text:
            return Text("beta OK")
        if not delegated["v"]:
            delegated["v"] = True
            return ToolCall("delegate_task", {"tasks": [
                {"title": "alpha", "goal": "CHILD_ALPHA return OK"},
                {"title": "beta", "goal": "CHILD_BETA return OK"}],
                "background": False, "max_concurrency": 2,
                "verify": {"criteria": "each result must contain OK"}})
        return Text("K1_BOTH_CHILDREN_ACCEPTED")

    backend.fake._responder = responder
    _, events = await backend.run("delegate two parallel children and verify them")
    worker_starts = [e for e in events if e["event"] == "subtask.started"
                     and e["data"].get("agent") == "general" and e["data"].get("group_id")]
    assert len(worker_starts) == 2, [e["data"] for e in worker_starts]
    group = next(e for e in events if e["event"] == "subtask.group_completed")
    results = group["data"]["results"]
    assert len(results) == 2 and all(item.get("status") == "completed" for item in results), results
    assert all(item.get("accepted") is True for item in results), results
    assert _has_message(events, "K1_BOTH_CHILDREN_ACCEPTED")
    assert events[-1]["event"] == "run.completed"


# ---------------------------------------------------------------------------
# 6. background terminal process -> completion notification event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_background_process_completion_notification(k1_backend):  # noqa: F811
    backend = k1_backend
    done_marker = backend.root / "workspace/bg-done.txt"
    wait_marker = backend.root / "workspace/bg-wait-done.txt"
    command = ("Write-Output K1_BG_READY; Start-Sleep -Milliseconds 500; "
               f"[IO.File]::WriteAllText('{done_marker}', 'done'); Write-Output K1_BG_DONE")
    # The second turn blocks on the marker so the run is still live when the
    # background job's completion notification is delivered.
    wait_command = (
        f"$deadline=(Get-Date).AddSeconds(20); "
        f"while(-not (Test-Path '{done_marker}') -and (Get-Date) -lt $deadline) "
        "{ Start-Sleep -Milliseconds 100 }; "
        f"[IO.File]::WriteAllText('{wait_marker}', 'waited'); Write-Output K1_BG_WAITED")
    turns = {"n": 0}

    def responder(record):
        turns["n"] += 1
        if turns["n"] == 1:
            return ToolCall("terminal", {"command": command, "shell": "powershell",
                "background": True, "notify": True, "watch_patterns": ["K1_BG_DONE"]})
        if turns["n"] == 2:
            return ToolCall("terminal", {"command": wait_command, "shell": "powershell"})
        return Text("K1_BG_DISPATCHED")

    backend.fake._responder = responder

    def process_finished(events):
        return any(e["event"] == "process.completed" for e in events)

    _, events = await ws_run(backend,
        "start the long job in the background and wait for its completion notification",
        keep_reading=process_finished, timeout=150)
    assert wait_marker.exists(), "the foreground wait turn must observe the background result"
    assert _has_message(events, "K1_BG_DISPATCHED")
    completed = [e for e in events if e["event"] == "process.completed"]
    assert completed and completed[0]["data"].get("exit_code") == 0, \
        [e["event"] for e in events]
    notifications = [e for e in events if e["event"] == "process.notification"]
    assert any("K1_BG_DONE" in str(e["data"]) for e in notifications), \
        [e["event"] for e in events]


# ---------------------------------------------------------------------------
# 12. model/provider switch mid-conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_model_switch_mid_conversation(k1_backend):  # noqa: F811
    backend = k1_backend
    added = await backend.http.post("/api/models/custom", json={
        "id": "fake-model-b", "name": "Fake B", "provider": "openai",
        "litellm_model": "openai/fake-model-b", "max_output_tokens": 512})
    assert added.status_code in (200, 201), added.text

    backend.fake._responder = lambda record: Text("K1_FIRST_MODEL_TURN")
    conversation, events = await backend.run("turn one on the default model")
    first_request = backend.fake.main_requests()[0]
    assert first_request["model"] == "openai/fake-model", first_request["model"]
    assert _has_message(events, "K1_FIRST_MODEL_TURN")

    switched = await backend.http.post("/api/models/select", json={"model": "fake-model-b"})
    assert switched.status_code == 200 and switched.json()["model"] == "fake-model-b", switched.text
    listing = (await backend.http.get("/api/models")).json()
    assert listing["current"] == "fake-model-b"

    backend.fake._responder = lambda record: Text("K1_SECOND_MODEL_TURN")
    before = len(backend.fake.main_requests())
    _, second = await ws_run(backend, "turn two after switching", conversation=conversation,
                             model=None, workspace=str(backend.root / "workspace"))
    second_request = backend.fake.main_requests()[before]
    assert second_request["model"].endswith("fake-model-b"), second_request["model"]
    assert any(item.get("role") == "user" and "turn one" in str(item.get("content", ""))
               for item in second_request["messages"]), \
        "the switched run must keep the conversation history"
    assert _has_message(second, "K1_SECOND_MODEL_TURN")


# ---------------------------------------------------------------------------
# 13. permission modes: ask_writes blocks write until approve; read_only blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,choice,should_write", [
    ("read_only", None, False),
    ("ask_writes", "allow", True),
    ("ask_writes", "deny", False),
])
async def test_daily_permission_modes_gate_writes(k1_backend, mode, choice, should_write):  # noqa: F811
    backend = k1_backend
    target = backend.root / "workspace/k1-permission.txt"
    called = {"v": False}

    def responder(record):
        if not called["v"]:
            called["v"] = True
            return ToolCall("write_file", {"path": str(target), "content": "K1_PERMISSION_FIXTURE"})
        return Text("K1_PERMISSION_CHECKED")

    backend.fake._responder = responder

    async def decide(ws, event):
        if event["event"] == "approval.required":
            await ws.send(json.dumps({"type": "approval.response", "run_id": event["run_id"],
                "event_id": event["data"]["approval_id"], "choice": choice or "deny"}))

    _, events = await backend.run("write the K1 permission fixture", permission_mode=mode,
                                  respond=decide)
    assert target.exists() is should_write
    writes = _completed(events, "write_file")
    if should_write:
        assert any(e["event"] == "approval.required" for e in events)
        assert writes and not writes[0]["data"].get("is_error")
    else:
        blocked = writes or [e for e in events if e["event"] == "tool.completed"
                             and e["data"].get("is_error")]
        assert blocked, "the write must surface as a refused tool result"
        assert any(e["event"] == "approval.required" for e in events) is (mode == "ask_writes")
    terminal_ok = events[-1]["event"] in TERMINAL_EVENTS and events[-1]["event"] != "run.failed"
    assert terminal_ok, events[-1]


# ---------------------------------------------------------------------------
# 14. restart persistence: same data dir, new app instance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_restart_preserves_conversations_settings_and_state(tmp_path):
    from tests.fakes.fake_llm_provider import FakeLLMServer
    from tests.fakes.k1_harness import RestartableBackend
    from tests.test_c1_websocket_acceptance import IsolatedBackend

    (tmp_path / "workspace").mkdir()
    with FakeLLMServer() as fake:
        first_root = tmp_path / "run-a"
        server = IsolatedBackend(first_root, fake)
        try:
            await server.ready()
            fake._responder = lambda record: Text("K1_PERSISTED_REPLY")
            conversation, events = await server.run("persist me across restart",
                                                    workspace=str(tmp_path / "workspace"))
            assert any(e["event"] == "message.completed"
                       and "K1_PERSISTED_REPLY" in str(e["data"].get("content")) for e in events)
            selected = await server.http.post("/api/models/select", json={"model": "fake-model"})
            assert selected.status_code == 200, selected.text
        finally:
            await server.close()

        # "restart": a brand-new app instance over a copy of the same data directory.
        second_root = tmp_path / "run-b"
        shutil.copytree(first_root / "atlas", second_root / "atlas")
        (second_root / "workspace").mkdir()
        restarted = RestartableBackend(second_root, fake)
        try:
            await restarted.ready()
            conversations = (await restarted.http.get("/api/conversations")).json()
            assert any(item["id"] == conversation for item in conversations), conversations
            messages = (await restarted.http.get(
                f"/api/conversations/{conversation}/messages")).json()
            assert any("persist me across restart" in str(item.get("content")) for item in messages)
            assert any("K1_PERSISTED_REPLY" in str(item.get("content")) for item in messages)
            models = (await restarted.http.get("/api/models")).json()
            assert models["current"] == "fake-model"

            fake._responder = lambda record: Text("K1_AFTER_RESTART")
            _, again = await ws_run(restarted, "continue after restart", conversation=conversation,
                                    workspace=str(tmp_path / "workspace"))
            assert _has_message(again, "K1_AFTER_RESTART"), again
            assert again[-1]["event"] == "run.completed"
        finally:
            await restarted.close()


# ---------------------------------------------------------------------------
# 15. 429 -> 500 -> disconnect-class recovery: the run recovers or fails gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_provider_faults_recover_gracefully(tmp_path):
    from tests.fakes.fake_llm_provider import FakeLLMServer
    from tests.test_c1_websocket_acceptance import IsolatedBackend

    (tmp_path / "workspace").mkdir()
    script = [Error(status=429, retry_after=0.2), Error(status=500),
              Text("K1_RECOVERED_AFTER_FAULTS")]
    with FakeLLMServer(script) as fake:
        server = IsolatedBackend(tmp_path, fake)
        # Widen the retry budget before the app finishes booting so the scripted
        # faults are survivable instead of immediately fatal.
        engine_config = tmp_path / "atlas/engine/config.yaml"
        engine_config.write_text(
            engine_config.read_text(encoding="utf-8").replace(
                "api_max_retries: 1", "api_max_retries: 4"), encoding="utf-8")
        try:
            await server.ready()
            _, events = await server.run("survive provider faults and finish")
            assert events[-1]["event"] == "run.completed", events[-1]
            assert any(e["event"] == "message.completed"
                       and "K1_RECOVERED_AFTER_FAULTS" in str(e["data"].get("content"))
                       for e in events)
            statuses = server.fake.main_requests()
            assert len(statuses) >= 3, "the fake provider must have seen the retried requests"
        finally:
            await server.close()
