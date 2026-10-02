"""Independent C1 acceptance over a real isolated HTTP/WebSocket backend.

Only the provider is scripted. The server, session store, runtime, tools and
event protocol run in a separate process and never use the developer's port.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from websockets.asyncio.client import connect

from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, StallMidStream, write_hermes_home


class IsolatedBackend:
    def __init__(self, root, fake, *, fake_mcp=False):
        self.root, self.fake = root, fake
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        assert self.port != 8765
        self.url = f"http://127.0.0.1:{self.port}"
        self.events = []
        data = root / "atlas"
        (data / "config").mkdir(parents=True)
        (data / "config/atlas.toml").write_text(
            '[models]\ndefault="fake-model"\n'
            f'[models.gateway]\nbase_url="{fake.base_url}"\napi_key="sk-fake-e2e"\n'
            '[[models.custom]]\nid="fake-model"\nname="Fake fixture"\nprovider="openai"\nlitellm_model="openai/fake-model"\nmax_output_tokens=512\n'
            '[agent]\nengine="hermes"\nverify_before_stop=false\n'
            '[tools]\nauto_start=[]\n[tools.servers]\n'
            '[scheduler]\nenabled=false\n', encoding="utf-8",
        )
        write_hermes_home(data / "engine", fake.base_url, extra_config="auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n")
        if fake_mcp:
            config_path = data / "config/atlas.toml"
            config_path.write_text(config_path.read_text().replace("auto_start=[]", 'auto_start=["c1-fake"]'), encoding="utf-8")
            with (data / "config/atlas.toml").open("a", encoding="utf-8") as config:
                config.write('\n[tools.servers.c1-fake]\ncommand=' + json.dumps(sys.executable)
                    + '\nargs=[' + json.dumps(str(Path(__file__).parent / "fakes/fake_mcp_server.py")) + ']\n'
                    + '[tools.servers.c1-fake.env]\nATLAS_FAKE_MCP_MARKER=' + json.dumps(str(root / "mcp-marker.txt")) + '\n')
        env = dict(os.environ)
        for key in list(env):
            upper_key = key.upper()
            if (any(marker in upper_key for marker in ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH"))
                    or upper_key.startswith("HERMES_SESSION_")
                    or upper_key.endswith("_PROXY")):
                env.pop(key, None)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR"):
            directory = root / key.lower()
            directory.mkdir()
            env[key] = str(directory)
        env.update(ATLAS_DATA_DIR=str(data), HERMES_HOME=str(data / "engine"),
                   ATLAS_SCHEDULER_ENABLED="false", ATLAS_API_TOKEN="c1-isolated-token",
                   ATLAS_API_KEY="sk-fake-e2e", ATLAS_API_BASE=fake.base_url,
                   NO_PROXY="127.0.0.1,localhost", HERMES_TEST_MODE="1")
        env.update(OPENAI_API_BASE=fake.base_url, OPENAI_BASE_URL=fake.base_url, OPENAI_API_KEY="sk-fake-e2e")
        for key in list(env):
            if key.upper().endswith("_PROXY"):
                env.pop(key, None)
        for key in ("HERMES_SCRATCH_DIR",):
            env.pop(key, None)
        launch_root = root / "backend-cwd"
        launch_root.mkdir()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        self.log = (root / "backend.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "atlas.server:app", "--host", "127.0.0.1", "--port", str(self.port),
        ], cwd=launch_root, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        self.http = httpx.AsyncClient(base_url=self.url, headers={"x-atlas-api-token": "c1-isolated-token"}, timeout=30)

    async def ready(self):
        for _ in range(150):
            if self.process.poll() is not None:
                raise AssertionError((self.root / "backend.log").read_text()[-3000:])
            try:
                response = await self.http.get("/api/health")
                if response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(.2)
        raise AssertionError("isolated backend did not become ready")

    async def conversation(self):
        response = await self.http.post("/api/conversations", json={"title": "New Conversation"})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    async def run(self, content, *, conversation=None, workspace=None, respond=None, expected="run.completed", **options):
        conversation = conversation or await self.conversation()
        run_id = uuid.uuid4().hex
        received = []
        async with connect(self.url.replace("http", "ws", 1) + "/ws/chat",
                           additional_headers={"x-atlas-api-token": "c1-isolated-token"}, max_size=8_000_000) as ws:
            await ws.send(json.dumps({"type": "run.start", "run_id": run_id, "content": content,
                "conversation_id": conversation, "workspace": str(workspace or self.root / "workspace"),
                "model": "fake-model", **options}))
            async with asyncio.timeout(90):
                while True:
                    event = json.loads(await ws.recv())
                    received.append(event)
                    if respond:
                        await respond(ws, event)
                    if event.get("run_id") == run_id and event.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
                        break
        self.events.extend(received)
        (self.root / "events.json").write_text(json.dumps(self.events, ensure_ascii=False, indent=2), encoding="utf-8")
        assert received[-1]["event"] == expected, received[-1]
        return conversation, received

    async def close(self):
        await self.http.aclose()
        import psutil

        try:
            children = psutil.Process(self.process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        self.process.terminate()
        try:
            await asyncio.to_thread(self.process.wait, 15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            await asyncio.to_thread(self.process.wait, 5)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=3)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        self.log.close()


@pytest_asyncio.fixture
async def backend(tmp_path):
    (tmp_path / "workspace").mkdir()
    with FakeLLMServer() as fake:
        server = IsolatedBackend(tmp_path, fake)
        try:
            await server.ready()
            yield server
        finally:
            await server.close()


@pytest.mark.asyncio
async def test_websocket_multiturn_keeps_tool_transcript(backend):
    target = backend.root / "workspace/fixture.txt"
    target.write_text("TRANSCRIPT_FIXTURE", encoding="utf-8")
    first = True
    def responder(record):
        nonlocal first
        if first:
            first = False
            return ToolCall("read_file", {"path": str(target)})
        return Text("first turn complete")
    backend.fake._responder = responder
    conversation, events = await backend.run("read the fixture")
    before = len(backend.fake.main_requests())
    await backend.run("continue with prior evidence", conversation=conversation)
    request = backend.fake.main_requests()[before]["messages"]
    assert any(item.get("tool_calls") for item in request)
    assert any(item["role"] == "tool" and "TRANSCRIPT_FIXTURE" in str(item["content"]) for item in request)
    assert {"tool.started", "tool.completed", "message.delta", "run.completed"} <= {e["event"] for e in events}


@pytest.mark.asyncio
async def test_websocket_more_than_ten_tool_rounds(backend):
    target = backend.root / "workspace/fixture.txt"
    target.write_text("rounds", encoding="utf-8")
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("terminal", {"command": f"Write-Output 'round-{count}'", "shell": "powershell"}) if count <= 12 else Text("twelve complete")
    backend.fake._responder = responder
    _, events = await backend.run("perform twelve independent round checks")
    assert count == 13
    assert len([item for item in events if item["event"] == "tool.completed"]) == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
async def test_websocket_native_patch_preserves_newlines(backend, newline):
    target = backend.root / "workspace/fixture.txt"
    target.write_bytes(newline.join([b"first", b"cat cat", b"last", b""]))
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("patch", {"path": str(target), "old_string": "cat", "new_string": "dog", "replace_all": True}) if count == 1 else Text("patched")
    backend.fake._responder = responder
    _, events = await backend.run("patch the fixture")
    assert target.read_bytes() == newline.join([b"first", b"dog dog", b"last", b""])
    assert any(item["event"] == "tool.completed" for item in events)


@pytest.mark.asyncio
async def test_websocket_compression_retains_real_todos_and_continues(backend):
    config = backend.root / "atlas/engine/config.yaml"
    config.write_text(config.read_text().replace("128000", "64000") +
        "  compression:\n    provider: custom\n    model: fake-model\n"
        f"    base_url: {backend.fake.base_url}\n    api_key: sk-fake-e2e\n", encoding="utf-8")
    backend.fake.context_length = 64000  # Hermes' minimum supported window.
    backend.fake.prompt_tokens_fn = lambda body: len(json.dumps(body, ensure_ascii=False)) // 2
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        if count == 1:
            return ToolCall("tool_call", {"calls": [{"name": "todo_list", "arguments": {"todos": [
                {"id": "active-fixture", "content": "preserve websocket requirement", "status": "in_progress"}
            ]}}]})
        if count <= 11:
            return ToolCall("terminal", {"command": f"Write-Output '{count}: ' ; Write-Output ('fixture-context ' * 1600)", "shell": "powershell"})
        return Text("continued after real compression")
    backend.fake._responder = responder
    _, events = await backend.run("preserve the active todo and gather long context")
    assert any(item["event"] == "run.compaction.progress" for item in events)
    assert backend.fake.aux_requests()
    main_requests = [item for item in backend.fake.requests if item["kind"] == "main"]
    assert "preserve websocket requirement" in str(main_requests[-1]["body"]), "active todo must survive into the final post-compression request"
    assert any(item["event"] == "run.todos" for item in events)


@pytest.mark.asyncio
async def test_websocket_c2_tools_and_context_handoff_chain(backend):
    workspace = backend.root / "workspace"
    image = workspace / "fixture.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    ))
    target = workspace / "fuzzy.txt"
    target.write_text("first line\nold middle\nlast line\n", encoding="utf-8")
    config = backend.root / "atlas/engine/config.yaml"
    config.write_text(config.read_text(encoding="utf-8").replace(
        "  default: fake-model\n", "  default: fake-model\n  supports_vision: true\n",
    ), encoding="utf-8")

    script = [
        ToolCall("read_file", {"path": str(image)}),
        ToolCall("read_file", {"path": str(target)}),
        ToolCall("patch", {"path": str(target), "old_string": "first line\nold middle\nlast line", "new_string": "first line\nnew middle\nlast line"}),
        *[
            call
            for index in range(6)
            for call in (
                ToolCall("read_file", {"path": str(target)}),
                ToolCall("write_file", {"path": str(target), "content": f"edited {index}"}),
            )
        ],
        Text("file tools finished"),
    ]
    backend.fake._script = script
    conversation, first = await backend.run(
        "Read the image, patch the file, and revise that file repeatedly.",
        permission_mode="full_access",
    )
    assert target.read_text(encoding="utf-8") == "edited 5"
    assert any(item["event"] == "tool.completed" and item["data"].get("name") == "read_file"
               for item in first)
    image_result = next(
        item["data"]["result"] for item in first
        if item["event"] == "tool.completed"
        and item["data"].get("name") == "read_file"
    )
    assert image_result.get("_multimodal") is True
    assert any(
        item["event"] == "tool.completed" and item["data"].get("name") == "write_file"
        and "反复修改同一文件" in str(item["data"].get("result"))
        for item in first
    )
    assert any("image_url" in str(request["messages"]) for request in backend.fake.main_requests())

    compacted = await backend.http.post(
        f"/api/conversations/{conversation}/compact", json={"focus_topic": "Continue the file edit"},
    )
    assert compacted.status_code == 200, compacted.text
    assert compacted.json().get("compressed") is True, compacted.json()
    backend.fake._aux = lambda _record: Text(
        "当前目标/约束：完成文件修改\n已完成：读取图片并编辑\n正在做/阻塞：无\n"
        "关键决定：保留目标文件\n下一步：结束任务\n关键文件：fuzzy.txt"
    )
    backend.fake.push(ToolCall("new_context_window", {}), Text("done after context handoff"))
    _, second = await backend.run(
        "Continue from the compressed session and finish.", conversation=conversation,
        permission_mode="full_access",
    )
    switched = next(item for item in second if item["event"] == "context.window.switched")
    assert all(label in str(switched["data"]) for label in (
        "当前目标/约束", "已完成", "正在做/阻塞", "关键决定", "下一步", "关键文件",
    ))
    assert second[-1]["event"] == "run.completed"
    assert any(item["event"] == "message.completed"
               and item["data"].get("content") == "done after context handoff"
               for item in second)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,choice,should_write", [
    ("read_only", None, False), ("ask_writes", "allow", True), ("ask_writes", "deny", False),
])
async def test_websocket_permissions_and_approvals(backend, mode, choice, should_write):
    target = backend.root / "workspace/permission.txt"
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("write_file", {"path": str(target), "content": "allowed fixture"}) if count == 1 else Text("permission checked")
    backend.fake._responder = responder
    async def approve(ws, event):
        if event["event"] == "approval.required":
            assert choice
            await ws.send(json.dumps({"type": "approval.response", "run_id": event["run_id"],
                "event_id": event["data"]["approval_id"], "choice": choice}))
    _, events = await backend.run("write fixture under chosen permission", permission_mode=mode, respond=approve)
    assert target.exists() is should_write
    if choice:
        assert any(event["event"] == "approval.required" for event in events)
    assert any(event["event"] == "tool.completed" for event in events)


@pytest.mark.asyncio
async def test_websocket_allowed_workspace_blocks_sibling(backend):
    target = backend.root / "outside.txt"
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("write_file", {"path": str(target), "content": "outside"}) if count == 1 else Text("boundary checked")
    backend.fake._responder = responder
    _, events = await backend.run("check allowed workspace", allowed_paths=[str(backend.root / "workspace")])
    assert not target.exists()
    assert any(item["event"] == "tool.completed" and item["data"].get("is_error") for item in events)


@pytest.mark.asyncio
async def test_websocket_steering_queue_and_stop(backend):
    first = True
    def responder(record):
        nonlocal first
        if first:
            first = False
            return ToolCall("terminal", {"command": "Start-Sleep -Milliseconds 800; Write-Output fixture", "shell": "powershell"})
        return Text("steering consumed")
    backend.fake._responder = responder
    sent = False
    async def steer(ws, event):
        nonlocal sent
        if event["event"] == "tool.started" and not sent:
            sent = True
            for text in ("STEER_FIXTURE_ONE", "STEER_FIXTURE_TWO"):
                await ws.send(json.dumps({"type": "run.steer", "run_id": event["run_id"], "content": text, "event_id": uuid.uuid4().hex}))
    _, events = await backend.run("start a task so steering can queue", respond=steer)
    requests = backend.fake.main_requests()
    assert "STEER_FIXTURE_ONE" in str(requests[-1]) and "STEER_FIXTURE_TWO" in str(requests[-1])
    assert len([event for event in events if event["event"] == "run.steered"]) == 2
    backend.fake._responder = lambda record: StallMidStream(seconds=20)
    async def cancel(ws, event):
        if event["event"] == "run.started":
            await ws.send(json.dumps({"type": "run.cancel", "run_id": event["run_id"]}))
    await backend.run("cancel the isolated stream", respond=cancel, expected="run.cancelled")


@pytest.mark.asyncio
async def test_websocket_immediate_redirect_fork_branch_switch_undo_redo(backend):
    requests = 0
    def respond(record):
        nonlocal requests
        requests += 1
        return StallMidStream(text="partial response before redirect", after_chars=12, seconds=20) if requests == 1 else Text(
            "redirect accepted" if requests == 2 else "branch response complete")
    backend.fake._responder = respond
    conversation = await backend.conversation()
    run_id = uuid.uuid4().hex
    events = []
    redirected = False
    async with connect(backend.url.replace("http", "ws", 1) + "/ws/chat",
                       additional_headers={"x-atlas-api-token": "c1-isolated-token"}, max_size=8_000_000) as ws:
        await ws.send(json.dumps({"type": "run.start", "run_id": run_id, "content": "start redirect fixture",
            "conversation_id": conversation, "workspace": str(backend.root / "workspace"), "model": "fake-model"}))
        async with asyncio.timeout(90):
            while True:
                event = json.loads(await ws.recv())
                events.append(event)
                if event.get("event") == "message.delta" and not redirected:
                    redirected = True
                    await ws.send(json.dumps({"type": "run.steer", "run_id": run_id,
                        "event_id": "immediate-fixture", "content": "TURN_TO_FIXTURE", "immediate": True}))
                if event.get("run_id") == run_id and event.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
                    break
    assert redirected
    ack = next(item for item in events if item["event"] == "run.steered")
    assert ack["data"].get("immediate") is True
    assert any(item["event"] == "message.delta" for item in events)

    messages = (await backend.http.get(f"/api/conversations/{conversation}/messages")).json()
    through = next(item["id"] for item in reversed(messages) if item["role"] == "assistant")
    fork_response = await backend.http.post(f"/api/conversations/{conversation}/fork", json={"through_message_id": through})
    assert fork_response.status_code == 201, fork_response.text
    fork_id = fork_response.json()["id"]
    tree = (await backend.http.get(f"/api/conversations/{conversation}/branches")).json()
    assert any(item["id"] == fork_id and item["parent_session_id"] == conversation for item in tree)
    await backend.run("continue on the child branch", conversation=fork_id)
    child_messages = (await backend.http.get(f"/api/conversations/{fork_id}/messages")).json()
    last_user = next(item["id"] for item in reversed(child_messages) if item["role"] == "user")
    rewind = await backend.http.post(f"/api/conversations/{fork_id}/rewind", json={"message_id": last_user, "files": False})
    assert rewind.status_code == 200, rewind.text
    assert not any(item["id"] == last_user for item in (await backend.http.get(f"/api/conversations/{fork_id}/messages")).json())
    redo = await backend.http.post(f"/api/conversations/{fork_id}/rewind/{rewind.json()['rewind_id']}/redo")
    assert redo.status_code == 200, redo.text
    assert any(item["id"] == last_user for item in (await backend.http.get(f"/api/conversations/{fork_id}/messages")).json())


@pytest.mark.asyncio
async def test_websocket_plan_permission_goal_and_failed_child_redelivery(backend):
    script = [
        Text("plan ready"),
        ToolCall("delegate_task", {"tasks": [{"title": "fixture child", "goal": "return OK"}],
            "max_concurrency": 1, "verify": {"criteria": "the result must contain OK"}}),
        Text("first attempt lacks the required result"),
        Text("OK after redelivery"),
        Text("goal complete after verified redelivery"),
    ]
    parent_delegated = False
    child_attempts = set()
    verifier_attempts = 0
    def respond(record):
        nonlocal parent_delegated, verifier_attempts
        messages = record["body"].get("messages", [])
        current_prompt = next((str(item.get("content", "")) for item in reversed(messages)
                               if item.get("role") == "user"), "")
        if "plan this fixture" in current_prompt:
            return script[0]
        if "验收并行任务" in current_prompt or "复验并行任务" in current_prompt:
            verifier_attempts += 1
            return Text(
                '{"verified":false,"note":"The first attempt did not contain OK."}'
                if verifier_attempts == 1 else
                '{"verified":true,"note":"The result contains OK."}'
            )
        if "return OK" in current_prompt or "fixture child" in current_prompt:
            retry = "Verifier feedback (single retry)" in current_prompt
            child_attempts.add("retry" if retry else "initial")
            return script[3] if retry else script[2]
        if "delegated task" in current_prompt.lower() and not parent_delegated:
            parent_delegated = True
            return script[1]
        return script[4]
    backend.fake._responder = respond
    auxiliary_calls = 0
    def respond_aux(_record):
        nonlocal auxiliary_calls
        auxiliary_calls += 1
        return Text(
            '{"goal":"plan fixture","subtasks":[{"id":"step1","title":"Inspect fixture","verification":"fixture inspected"}]}'
            if auxiliary_calls == 1 else
            '{"results":[{"id":"step1","completed":true,"evidence":"fixture inspected"}]}'
            if auxiliary_calls == 2 else
            '{"verdict":"done","reason":"The delegated result was verified."}'
        )
    backend.fake._aux = respond_aux
    conversation = await backend.conversation()
    plan_approved = False
    async def approve_plan(ws, event):
        nonlocal plan_approved
        if event["event"] == "run.plan.proposed":
            plan_approved = True
            await ws.send(json.dumps({"type": "run.plan.approve", "run_id": event["run_id"],
                "event_id": event["data"]["event_id"]}))
    _, plan_events = await backend.run("plan this fixture", conversation=conversation,
        mode="plan", permission_mode="plan", respond=approve_plan)
    assert plan_events[-1]["event"] == "run.completed"
    assert any(item["event"] == "run.plan.proposed" for item in plan_events)
    assert plan_approved
    goal = await backend.http.post(f"/api/conversations/{conversation}/goal",
        json={"command": "Complete the delegated task and verify its result."})
    assert goal.status_code == 200, goal.text
    assert goal.json()["goal"]["status"] == "active"

    async def approve_each_tool(ws, event):
        if event["event"] == "approval.required":
            await ws.send(json.dumps({"type": "approval.response", "run_id": event["run_id"],
                "event_id": event["data"]["approval_id"], "choice": "allow"}))
    _, events = await backend.run(goal.json()["prompt"], conversation=conversation,
        permission_mode="ask_each", respond=approve_each_tool)
    group = next((item for item in events if item["event"] == "subtask.group_completed"), None)
    assert group is not None
    assert parent_delegated
    assert group["data"]["results"][0]["accepted"] is True, group["data"]["results"]
    assert group["data"]["results"][0]["status"] == "completed"
    assert child_attempts == {"initial", "retry"}
    assert verifier_attempts == 2
    assert any(item["event"] == "approval.required" for item in events)
    assert any(item["event"] == "goal.updated" and item["data"]["status"] == "done" for item in events)


@pytest.mark.asyncio
async def test_websocket_pause_blocks_next_provider_turn_until_resume(backend):
    count = 0
    started_marker = backend.root / "workspace/pause-command-started.txt"
    completed_marker = backend.root / "workspace/pause-command-completed.txt"
    def responder(record):
        nonlocal count
        count += 1
        command = (
            f"[IO.File]::WriteAllText('{started_marker}', 'started'); "
            "Start-Sleep -Milliseconds 1000; "
            f"[IO.File]::WriteAllText('{completed_marker}', 'completed'); "
            "Write-Output PAUSE_FIXTURE"
        )
        return ToolCall("terminal", {"command": command, "shell": "powershell"}) if count == 1 else Text("RESUMED_FINAL_FIXTURE")

    backend.fake._responder = responder
    conversation = await backend.conversation()
    run_id = uuid.uuid4().hex
    events = []
    pause_request_count = None
    async with connect(backend.url.replace("http", "ws", 1) + "/ws/chat",
                       additional_headers={"x-atlas-api-token": "c1-isolated-token"}, max_size=8_000_000) as ws:
        await ws.send(json.dumps({"type": "run.start", "run_id": run_id, "content": "pause between tool and final turn",
            "conversation_id": conversation, "workspace": str(backend.root / "workspace"), "model": "fake-model"}))
        async with asyncio.timeout(90):
            while True:
                event = json.loads(await ws.recv())
                events.append(event)
                if event.get("run_id") != run_id:
                    continue
                if event["event"] == "tool.started":
                    async with asyncio.timeout(10):
                        while not started_marker.exists():
                            await asyncio.sleep(0.02)
                    await ws.send(json.dumps({"type": "run.pause", "run_id": run_id}))
                elif event["event"] == "run.paused":
                    pause_request_count = len(backend.fake.main_requests())
                    async with asyncio.timeout(10):
                        while not completed_marker.exists():
                            await asyncio.sleep(0.02)
                    await asyncio.sleep(0.5)
                    assert len(backend.fake.main_requests()) == pause_request_count, (
                        "provider entered another model turn while the WebSocket run was paused"
                    )
                    await ws.send(json.dumps({"type": "run.resume", "run_id": run_id}))
                elif event["event"] == "run.completed":
                    break
                elif event["event"] in {"run.failed", "run.cancelled"}:
                    pytest.fail(f"paused run ended unexpectedly: {event}")

    assert pause_request_count == 1
    assert len(backend.fake.main_requests()) == 2
    assert any(item["event"] == "run.resumed" for item in events)
    assert any(item["event"] == "tool.completed" and not item["data"].get("is_error") for item in events)
    assert any(item["event"] == "message.completed" and "RESUMED_FINAL_FIXTURE" in str(item["data"].get("content")) for item in events)


@pytest.mark.asyncio
async def test_websocket_cancel_while_paused_ends_without_another_provider_turn(backend):
    started_marker = backend.root / "workspace/cancel-command-started.txt"
    completed_marker = backend.root / "workspace/cancel-command-completed.txt"
    command = (
        f"[IO.File]::WriteAllText('{started_marker}', 'started'); "
        "Start-Sleep -Milliseconds 1000; "
        f"[IO.File]::WriteAllText('{completed_marker}', 'completed')"
    )
    backend.fake._responder = lambda record: ToolCall(
        "terminal", {"command": command, "shell": "powershell"},
    )
    conversation = await backend.conversation()
    run_id = uuid.uuid4().hex
    request_count_at_pause = None
    async with connect(backend.url.replace("http", "ws", 1) + "/ws/chat",
                       additional_headers={"x-atlas-api-token": "c1-isolated-token"}, max_size=8_000_000) as ws:
        await ws.send(json.dumps({"type": "run.start", "run_id": run_id,
            "content": "cancel while paused", "conversation_id": conversation,
            "workspace": str(backend.root / "workspace"), "model": "fake-model"}))
        async with asyncio.timeout(90):
            while True:
                event = json.loads(await ws.recv())
                if event.get("run_id") != run_id:
                    continue
                if event["event"] == "tool.started":
                    async with asyncio.timeout(10):
                        while not started_marker.exists():
                            await asyncio.sleep(0.02)
                    await ws.send(json.dumps({"type": "run.pause", "run_id": run_id}))
                elif event["event"] == "run.paused":
                    request_count_at_pause = len(backend.fake.main_requests())
                    async with asyncio.timeout(10):
                        while not completed_marker.exists():
                            await asyncio.sleep(0.02)
                    await asyncio.sleep(0.2)
                    assert len(backend.fake.main_requests()) == request_count_at_pause
                    await ws.send(json.dumps({"type": "run.cancel", "run_id": run_id}))
                elif event["event"] in {"run.cancelled", "run.completed", "run.failed"}:
                    assert event["event"] == "run.cancelled", event
                    break

    assert request_count_at_pause == 1
    assert len(backend.fake.main_requests()) == 1


@pytest.mark.asyncio
async def test_websocket_rewind_restores_files_and_hermes_session(backend):
    target = backend.root / "workspace/rewind.txt"
    target.write_text("original", encoding="utf-8")
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        if count == 1:
            return ToolCall("read_file", {"path": str(target)})
        if count == 2:
            return ToolCall("write_file", {"path": str(target), "content": "mutated"})
        return Text("UNIQUE_REWOUND_FIXTURE")
    backend.fake._responder = responder
    conversation, events = await backend.run("checkpoint fixture")
    assert target.read_text() == "mutated"
    messages = (await backend.http.get(f"/api/conversations/{conversation}/messages")).json()
    user = next(item for item in messages if item["role"] == "user")
    response = await backend.http.post(f"/api/conversations/{conversation}/rewind", json={"message_id": user["id"], "files": True})
    assert response.status_code == 200, response.text
    assert target.read_text() == "original"
    redo = await backend.http.post(f"/api/conversations/{conversation}/rewind/{response.json()['rewind_id']}/redo")
    assert redo.status_code == 200, redo.text
    assert target.read_text() == "mutated"
    again = await backend.http.post(f"/api/conversations/{conversation}/rewind", json={"message_id": user["id"], "files": True})
    assert again.status_code == 200, again.text
    assert target.read_text() == "original"
    before = len(backend.fake.main_requests())
    backend.fake._responder = lambda record: Text("resumed after rewind")
    await backend.run("new turn after rewind", conversation=conversation)
    assert "UNIQUE_REWOUND_FIXTURE" not in str(backend.fake.main_requests()[before])


@pytest.mark.asyncio
async def test_websocket_native_write_guard_rejects_unread_and_changed_files(backend):
    target = backend.root / "workspace/write-guard.txt"
    target.write_text("original fixture", encoding="utf-8")
    calls = [
        ToolCall("write_file", {"path": str(target), "content": "unread clobber"}),
        ToolCall("read_file", {"path": str(target)}),
        ToolCall("write_file", {"path": str(target), "content": "read then written"}),
        ToolCall("read_file", {"path": str(target)}),
        ToolCall("write_file", {"path": str(target), "content": "stale clobber"}),
    ]
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        if count == 2:
            assert target.read_text(encoding="utf-8") == "original fixture"
        if count == 5:
            assert target.read_text(encoding="utf-8") == "read then written"
            target.write_text("external changed fixture", encoding="utf-8")
        return calls[count - 1] if count <= len(calls) else Text("write guard checked")
    backend.fake._responder = responder
    _, events = await backend.run("verify native overwrite behavior using isolated files")
    writes = [event for event in events if event["event"] == "tool.completed" and event["data"].get("name") == "write_file"]
    assert [event["data"]["is_error"] for event in writes] == [True, False, True]
    assert target.read_text(encoding="utf-8") == "external changed fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding,bom", [("utf-8", b"\xef\xbb\xbf"), ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
async def test_websocket_native_edits_preserve_bom_encoding_and_crlf(backend, encoding, bom):
    target = backend.root / "workspace/encoded.txt"
    target.write_bytes(bom + "Málaga 東京 before\r\n".encode(encoding))
    calls = [
        ToolCall("read_file", {"path": str(target)}),
        ToolCall("patch", {"path": str(target), "old_string": "before", "new_string": "after"}),
        ToolCall("read_file", {"path": str(target)}),
        ToolCall("write_file", {"path": str(target), "content": "Málaga 東京 final\n"}),
    ]
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        if count == 3:
            assert target.read_bytes() == bom + "Málaga 東京 after\r\n".encode(encoding)
        return calls[count - 1] if count <= len(calls) else Text("encoding preserved")
    backend.fake._responder = responder
    _, events = await backend.run("read patch and rewrite the isolated BOM fixture")
    assert not any(event["data"].get("is_error") for event in events if event["event"] == "tool.completed")
    assert target.read_bytes() == bom + "Málaga 東京 final\r\n".encode(encoding)


@pytest.mark.asyncio
async def test_websocket_atlas_parallel_children_are_independent(backend):
    parent_calls = 0
    def responder(record):
        nonlocal parent_calls
        messages = record["body"]["messages"]
        last_user = next((item for item in reversed(messages) if item["role"] == "user"), {})
        text = str(last_user.get("content", ""))
        if "fixture child alpha" in text:
            assert "PARENT_PRIVATE_FIXTURE" not in str(messages)
            return Text("alpha child complete")
        if "fixture child beta" in text:
            assert "PARENT_PRIVATE_FIXTURE" not in str(messages)
            return Text("beta child complete")
        parent_calls += 1
        if parent_calls == 1:
            return ToolCall("delegate_task", {"tasks": [{"title": "alpha", "goal": "fixture child alpha"}, {"title": "beta", "goal": "fixture child beta"}], "background": False})
        return Text("both children reviewed")
    backend.fake._responder = responder
    _, events = await backend.run("PARENT_PRIVATE_FIXTURE delegate two independent tasks")
    kinds = [event["event"] for event in events]
    assert kinds.count("subtask.started") == 2
    assert kinds.count("subtask.completed") == 2
    assert any("alpha child complete" in str(event) for event in events)
    assert any("beta child complete" in str(event) for event in events)
    conversations = (await backend.http.get("/api/conversations")).json()
    assert len(conversations) == 1


@pytest.mark.asyncio
async def test_websocket_calls_only_local_fake_mcp(tmp_path):
    (tmp_path / "workspace").mkdir()
    with FakeLLMServer() as fake:
        server = IsolatedBackend(tmp_path, fake, fake_mcp=True)
        try:
            await server.ready()
            calls = 0
            def responder(record):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return ToolCall("tool_search", {"queries": ["c1 fake ping"]})
                if calls > 2:
                    return Text("fake mcp done")
                return ToolCall("tool_call", {"calls": [{"name": "mcp__c1_fake__ping", "arguments": {}}]})
            fake._responder = responder
            _, events = await server.run("invoke the local fake MCP ping")
            assert (tmp_path / "mcp-marker.txt").read_text() == "ping"
            assert any("pong from local fake MCP" in str(item) for item in events)
        finally:
            await server.close()


@pytest.mark.asyncio
async def test_websocket_kanban_tools_keep_real_board_and_card_lifecycle(backend):
    board_id = "isolated-c1-board"
    count = 0
    task_id = None
    def responder(record):
        nonlocal count, task_id
        count += 1
        if count == 1:
            return ToolCall("tool_search", {"queries": ["kanban_create_board kanban_create_task"]})
        if count == 2:
            name, arguments = "kanban_create_board", {"name": "Isolated fixture", "board_id": board_id}
        elif count == 3:
            name, arguments = "kanban_create_task", {"board_id": board_id, "title": "KANBAN_REAL_FIXTURE"}
        elif count == 4:
            response = httpx.get(backend.url + f"/api/kanban/boards/{board_id}/tasks", headers={"x-atlas-api-token": "c1-isolated-token"}, timeout=10)
            response.raise_for_status()
            task_id = response.json()["tasks"][0]["id"]
            name, arguments = "kanban_update_task", {"board_id": board_id, "task_id": task_id, "status": "running"}
        elif count == 5:
            name, arguments = "kanban_update_task", {"board_id": board_id, "task_id": task_id, "status": "done", "output": "KANBAN_OUTPUT_FIXTURE"}
        elif count == 6:
            name, arguments = "kanban_list", {"board_id": board_id}
        else:
            return Text("board and card lifecycle checked")
        return ToolCall("tool_call", {"calls": [{"name": name, "arguments": arguments}]})
    backend.fake._responder = responder
    _, events = await backend.run("exercise the retained Atlas coordination board tools")
    boards = (await backend.http.get("/api/kanban/boards")).json()
    assert any(board["id"] == board_id for board in (boards.get("boards", []) if isinstance(boards, dict) else boards))
    tasks = (await backend.http.get(f"/api/kanban/boards/{board_id}/tasks")).json()["tasks"]
    assert len(tasks) == 1 and tasks[0]["status"] == "done"
    assert tasks[0]["output"] == "KANBAN_OUTPUT_FIXTURE"
    assert "KANBAN_REAL_FIXTURE" in str(events) and "KANBAN_OUTPUT_FIXTURE" in str(events)






@pytest.mark.asyncio
async def test_websocket_old_file_and_exec_actions_have_real_terminal_equivalents(backend):
    workspace = backend.root / "workspace"
    target = workspace / "actions.txt"
    target.write_text("first", encoding="utf-8")
    quoted_python = "'" + sys.executable.replace("'", "''") + "'"
    commands = [
        "New-Item -ItemType Directory -Path action-dir | Out-Null; Write-Output CREATED_DIR",
        "[IO.File]::AppendAllText((Join-Path (Get-Location) 'actions.txt'), ' second'); Get-Content actions.txt",
        "Copy-Item actions.txt action-dir/copied.txt; Move-Item action-dir/copied.txt action-dir/moved.txt; Get-Content action-dir/moved.txt",
        "Get-ChildItem action-dir | Select-Object Name,Length | ConvertTo-Json -Compress",
        "Get-Item actions.txt | Select-Object Name,Length,LastWriteTime | ConvertTo-Json -Compress",
        "[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path (Get-Location) 'actions.txt')))",
        "Remove-Item action-dir/moved.txt; Write-Output DELETED_COPY",
        f"& {quoted_python} -c 'import sys; print(repr(sys.argv[1:]))' 'argument space' 'literal$(not-expression)'",
    ]
    expected_cwd = str(workspace.resolve()).replace("'", "''")
    cwd_guard = f"$ErrorActionPreference='Stop'; if ((Get-Location).Path -ne '{expected_cwd}') {{ throw 'Acceptance workspace mismatch' }}; "
    commands = [cwd_guard + command for command in commands]
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("terminal", {"command": commands[count - 1], "shell": "powershell"}) if count <= len(commands) else Text("all old file actions checked")
    backend.fake._responder = responder
    _, events = await backend.run("check append mkdir copy move delete list stat binary reads and exact argv")
    assert target.read_text() == "first second"
    assert (workspace / "action-dir").is_dir()
    assert not (workspace / "action-dir/moved.txt").exists()
    outputs = [str(event["data"]) for event in events if event["event"] == "tool.completed"]
    assert len(outputs) == len(commands)
    assert "moved.txt" in outputs[3] and "Length" in outputs[4]
    assert "Zmlyc3Qgc2Vjb25k" in outputs[5]
    assert "argument space" in outputs[7] and "literal$(not-expression)" in outputs[7]


@pytest.mark.asyncio
async def test_websocket_all_old_git_actions_use_isolated_local_remote(backend):
    workspace = backend.root / "workspace"
    remote = backend.root / "bare-origin.git"
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, env=env, capture_output=True)
    for args in (["init", "-b", "main"], ["config", "user.name", "C1 fixture"], ["config", "user.email", "fixture@example.invalid"], ["remote", "add", "origin", str(remote)]):
        subprocess.run(["git", *args], cwd=workspace, check=True, env=env, capture_output=True)
    (workspace / "git-fixture.txt").write_text("git evidence", encoding="utf-8")
    commands = ["git status --short", "git add git-fixture.txt", "git diff --cached",
        "git commit -m fixture", "git log --oneline -1", "git branch acceptance-branch",
        "git push -u origin main", "git fetch origin", "git pull --rebase origin main"]
    expected_cwd = str(workspace.resolve()).replace("'", "''")
    expected_remote = str(remote).replace("'", "''")
    git_guard = (f"$ErrorActionPreference='Stop'; if ((Get-Location).Path -ne '{expected_cwd}') {{ throw 'Acceptance workspace mismatch' }}; "
                 f"if ((git remote get-url origin) -ne '{expected_remote}') {{ throw 'Acceptance remote mismatch' }}; ")
    commands = [git_guard + command for command in commands]
    count = 0
    def responder(record):
        nonlocal count
        count += 1
        return ToolCall("terminal", {"command": commands[count - 1], "shell": "powershell"}) if count <= len(commands) else Text("all nine git actions checked")
    backend.fake._responder = responder
    _, events = await backend.run("exercise nine old git actions against a local bare fixture remote")
    outputs = [str(event["data"]) for event in events if event["event"] == "tool.completed"]
    assert len(outputs) == 9
    assert "git-fixture.txt" in outputs[0] and "git evidence" in outputs[2]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
    origin_head = subprocess.check_output(["git", "rev-parse", "refs/heads/main"], cwd=remote, text=True).strip()
    assert head == origin_head
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=workspace, text=True).strip() == ""
    assert "acceptance-branch" in subprocess.check_output(["git", "branch", "--list"], cwd=workspace, text=True)


@pytest.mark.asyncio
async def test_websocket_office_read_and_native_file_discovery(backend):
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation
    workspace = backend.root / "workspace"
    document = Document()
    document.add_paragraph("DOCX_REAL_FIXTURE")
    document.save(workspace / "fixture.docx")
    workbook = Workbook()
    workbook.active.append(["XLSX_REAL_FIXTURE", 17])
    workbook.save(workspace / "fixture.xlsx")
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "PPTX_REAL_FIXTURE"
    presentation.save(workspace / "fixture.pptx")
    calls = [
        ToolCall("read_file", {"path": str(workspace / "fixture.docx")}),
        ToolCall("read_file", {"path": str(workspace / "fixture.xlsx")}),
        ToolCall("read_file", {"path": str(workspace / "fixture.pptx")}),
        ToolCall("search_files", {"path": str(workspace), "target": "files", "pattern": "fixture.*"}),
    ]
    index = 0
    def responder(record):
        nonlocal index
        index += 1
        return calls[index - 1] if index <= len(calls) else Text("office and glob checked")
    backend.fake._responder = responder
    _, events = await backend.run("read all three office fixtures and discover filenames")
    output = str([event for event in events if event["event"] == "tool.completed"])
    assert "DOCX_REAL_FIXTURE" in output and "XLSX_REAL_FIXTURE" in output
    assert "PPTX_REAL_FIXTURE" in output
    search = next(event for event in events if event["event"] == "tool.completed" and event["data"].get("name") == "search_files")
    assert all(name in str(search["data"]["result"]) for name in ("fixture.docx", "fixture.xlsx", "fixture.pptx"))
