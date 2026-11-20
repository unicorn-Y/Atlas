"""ACP session/configuration methods stay in the ACP JSON-RPC surface."""

import io
import json
import hashlib
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atlas.tools import app_server
import atlas.tools.local_execution as _local_execution
from tests.fakes.fake_llm_provider import (
    DropMidStream, FakeLLMServer, StallMidStream, Text, ToolCall, write_atlas_home,
)
from tests.test_engine_model_wiring import _ProviderKeyManager


pytestmark = pytest.mark.unit


def test_real_acp_subprocess_cancel_discards_partial_attempt_and_persists_audit(tmp_path):
    from tests.test_app_server_sdk_subprocess_attempts import _isolated_app_server_env

    old_sent = threading.Event()
    with FakeLLMServer([
        StallMidStream("OLD answer", after_chars=3, seconds=30, text_chunk_sent=old_sent),
    ]) as fake:
        env = _isolated_app_server_env(tmp_path, fake)
        tokenizer_cache = Path(tempfile.gettempdir()) / "data-gym-cache"
        tokenizer_asset = tokenizer_cache / hashlib.sha1(
            b"https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
        ).hexdigest()
        if not tokenizer_asset.is_file():
            pytest.skip("offline ACP cancellation probe requires the pre-cached public cl100k tokenizer asset")
        env["TIKTOKEN_CACHE_DIR"] = str(tokenizer_cache)

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        process = subprocess.Popen(
            [sys.executable, "-m", "atlas.cli", "acp", "--workspace", str(workspace)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        )
        messages: list[dict] = []
        messages_lock = threading.Lock()
        received: queue.Queue[dict | None] = queue.Queue()
        stderr_tail: list[str] = []

        def read_stdout():
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                with messages_lock:
                    messages.append(message)
                received.put(message)
            received.put(None)

        def read_stderr():
            assert process.stderr is not None
            for line in process.stderr:
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-40]

        stdout_thread = threading.Thread(target=read_stdout, name="acp-test-stdout", daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, name="acp-test-stderr", daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        def send(message):
            assert process.stdin is not None
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def wait_for_response(request_id: int, timeout: float = 30) -> dict:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = received.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if message is None:
                    break
                if message.get("id") == request_id:
                    return message
            raise AssertionError({
                "missing_response_id": request_id,
                "messages": messages[-30:],
                "stderr_tail": stderr_tail[-20:],
                "process_exit": process.poll(),
            })

        session_id = None
        natural_exit = False
        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
            assert "result" in wait_for_response(1)
            send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(workspace)}})
            session_result = wait_for_response(2)["result"]
            session_id = session_result["sessionId"]
            send({
                "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": "cancel after OLD starts"}]},
            })
            assert old_sent.wait(timeout=20), {
                "provider_requests": len(fake.main_requests()),
                "process_exit": process.poll(),
                "stderr_tail": stderr_tail[-20:],
            }
            assert len(fake.main_requests()) == 1
            # The fixture signal means the provider flushed the SSE bytes. Give the
            # real HTTP consumer one bounded scheduler turn to deliver that chunk
            # into the model attempt; the persisted partial_text assertion below is
            # the authoritative check that it was actually consumed before cancel.
            threading.Event().wait(0.1)
            send({"jsonrpc": "2.0", "id": 4, "method": "session/cancel", "params": {"sessionId": session_id}})
            cancel_response = wait_for_response(4)
            assert cancel_response.get("result", {}).get("cancelled") is True
            prompt_response = wait_for_response(3)
            assert prompt_response["result"]["stopReason"] == "cancelled"
            process.stdin.close()
            assert process.wait(timeout=15) == 0
            natural_exit = True
        finally:
            if process.poll() is None:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)

        assert natural_exit, "ACP subprocess did not exit naturally after stdin EOF"
        with messages_lock:
            observed = list(messages)
        old_updates = [
            message for message in observed
            if message.get("method") == "session/update"
            and "OLD" in str(((message.get("params") or {}).get("update") or {}).get("content") or "")
        ]
        assert old_updates == []
        assert len(fake.main_requests()) == 1

        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "atlas" / "engine" / "state.db") as db:
            transcript = db.get_messages_as_conversation(session_id)
            audit = db.list_session_events(session_id, after_seq=0, limit=1000)
        assistant_text = [str(row.get("content") or "") for row in transcript if row.get("role") == "assistant"]
        attempt_rows = [row for row in audit if row.get("event_type") == "model/attempt"]
        assert all("OLD" not in text for text in assistant_text)
        assert any(
            row["payload"].get("status") == "discarded"
            and row["payload"].get("category") == "cancelled"
            and str(row["payload"].get("partial_text") or "").startswith("OLD")
            for row in attempt_rows
        ), [{key: (row.get("payload") or {}).get(key) for key in
             ("status", "category", "partial_text", "text", "output", "attempt_id")}
            for row in attempt_rows]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"outcome": {"outcome": "selected", "optionId": "allow_once"}}, True),
        ({"outcome": {"outcome": "selected", "optionId": "reject_once"}}, False),
        ({"outcome": {"outcome": "selected", "optionId": "unknown"}}, False),
        ({"outcome": {"outcome": "cancelled"}}, False),
        ({"outcome": "selected"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_acp_permission_response_is_fail_closed(result, expected):
    assert app_server._acp_permission_allowed(result) is expected


class _Memory:
    def __init__(self):
        self.rows = {}

    async def init(self):
        pass

    async def close(self):
        pass

    async def save_conversation_metadata(self, conversation_id, *, title_hint=""):
        self.rows.setdefault(conversation_id, {
            "id": conversation_id, "title": title_hint, "workspace": None,
            "metadata": "{}", "updated_at": "2026-11-14T00:00:00Z",
        })

    async def get_conversation(self, conversation_id):
        return self.rows.get(conversation_id)

    async def update_conversation(self, conversation_id, **values):
        row = self.rows[conversation_id]
        for key, value in values.items():
            if key == "metadata":
                value = json.dumps(value)
            row[key] = value
        return True

    async def list_conversations(self, limit=50):
        rows = list(self.rows.values())
        return rows if limit is None else rows[:limit]


class _Orchestrator:
    last_approval = None

    def __init__(self, **_kwargs):
        pass

    async def run(self, _prompt, _conversation_id, **kwargs):
        type(self).last_approval = await kwargs["approval_callback"](
            "approval:tool-1", "write_file", {"path": "note.txt"},
        )
        yield {"type": "chunk", "content": "done"}


class _ACPAskUserOrchestrator:
    last_answer = None

    def __init__(self, **_kwargs):
        pass

    async def run(self, _prompt, _conversation_id, **kwargs):
        type(self).last_answer = await kwargs["input_callback"](
            "input:tool-1", "What should I enter?", ["one", "two"],
        )
        yield {"type": "chunk", "content": type(self).last_answer}


class _AttemptRollbackOrchestrator:
    def __init__(self, **_kwargs):
        pass

    async def run(self, _prompt, _conversation_id, **_kwargs):
        yield {"type": "chunk", "content": "OLD", "attempt": 1, "attempt_id": "attempt-old"}
        yield {"type": "message.rollback", "attempt": 1, "attempt_id": "attempt-old"}
        yield {"type": "chunk", "content": "NEW", "attempt": 2, "attempt_id": "attempt-new"}
        yield {"type": "model_attempt_committed", "attempt": 2, "attempt_id": "attempt-new"}


class _ModelManager:
    pass


class _PresetStore:
    def __init__(self, _path):
        pass

    def resolve(self, preset_id):
        return {"preset": preset_id}


class _KernelPresetStore:
    def __init__(self, _path):
        pass

    def resolve(self, _preset_id):
        return {
            "tools": {"allow_all": True, "allow": [], "deny": []},
            "skills": [], "mcp_servers": [], "plugins": [], "plugin_allow_all": False,
            "mode": "act", "model": "fake-model",
        }


class _QueueInput:
    def __init__(self, lines):
        self.lines = queue.Queue()
        for line in lines:
            self.lines.put(line + "\n")

    def readline(self):
        return self.lines.get()


class _PermissionOutput:
    def __init__(self, input_stream, *, selected):
        self.input = input_stream
        self.selected = selected
        self.lines = []

    def write(self, line):
        self.lines.append(line)
        message = json.loads(line)
        if message.get("method") == "session/request_permission":
            self.input.lines.put(json.dumps({
                "jsonrpc": "2.0", "id": message["id"],
                "result": {"outcome": {"outcome": "selected", "optionId": self.selected}},
            }) + "\n")
        elif message.get("id") == 3:
            self.input.lines.put("")
        return len(line)

    def flush(self):
        pass


class _ACPAttemptOutput(_PermissionOutput):
    def write(self, line):
        result = super().write(line)
        message = json.loads(line)
        if message.get("id") == 2 and isinstance(message.get("result"), dict):
            self.input.lines.put(json.dumps({
                "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                "params": {
                    "sessionId": message["result"]["sessionId"],
                    "prompt": [{"type": "text", "text": "retry"}],
                },
            }) + "\n")
        return result


class _FakeUuid:
    hex = "0123456789abcdef0123456789abcdef"

    def __str__(self):
        return "conv-acp-test"


@pytest.mark.asyncio
async def test_acp_session_list_resume_and_permission_config_round_trip(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    wire = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": 1}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                   "params": {"cwd": cwd}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "session/list", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "session/set_config_option",
                   "params": {"sessionId": "conv-acp-test", "configId": "permissionPreset",
                              "value": "observe"}}),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "session/close",
                   "params": {"sessionId": "conv-acp-test"}}),
        json.dumps({"jsonrpc": "2.0", "id": 6, "method": "session/resume",
                   "params": {"sessionId": "conv-acp-test", "cwd": cwd, "mcpServers": []}}),
        json.dumps({"jsonrpc": "2.0", "id": 7, "method": "session/set_config_option",
                   "params": {"sessionId": "conv-acp-test", "configId": "model", "value": "x"}}),
        json.dumps({"jsonrpc": "2.0", "id": 8, "method": "session/resume",
                   "params": {"sessionId": "conv-acp-test", "cwd": str(tmp_path.parent.resolve()),
                              "mcpServers": []}}),
        "",
    ])
    stdin, stdout = io.StringIO(wire), io.StringIO()
    memory = _Memory()
    memory.rows["ordinary-conversation"] = {
        "id": "ordinary-conversation", "title": "private", "workspace": cwd,
        "metadata": "{}", "updated_at": "2026-11-14T00:00:00Z",
    }
    monkeypatch.setattr(app_server.uuid, "uuid4", _FakeUuid)
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (stdin, stdout))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _Orchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(
        db_path=tmp_path / "atlas.db", local_execution_permission_mode="full_access",
    ))
    async def migrate(*_args):
        return _migration_ready()

    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)

    await app_server.serve_stdio(protocol="acp")

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    by_id = {item["id"]: item for item in responses if "id" in item}
    assert by_id[1]["result"]["agentCapabilities"]["sessionCapabilities"]["resume"] == {}
    assert by_id[2]["result"]["sessionId"] == "conv-acp-test"
    listed = by_id[3]["result"]["sessions"]
    assert [item["sessionId"] for item in listed] == ["conv-acp-test"]
    assert by_id[4]["result"]["configOptions"][0]["currentValue"] == "observe"
    assert by_id[5]["result"] == {}
    assert by_id[6]["result"]["configOptions"][0]["currentValue"] == "observe"
    assert by_id[7]["error"]["code"] == -32602
    assert by_id[8]["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_app_server_rejects_acp_session_list_method(tmp_path, monkeypatch):
    wire = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": 1}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "session/list", "params": {}}),
        "",
    ])
    stdin, stdout = io.StringIO(wire), io.StringIO()
    memory = _Memory()
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (stdin, stdout))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _Orchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)

    async def migrate(*_args):
        return _migration_ready()

    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
    await app_server.serve_stdio(protocol="app-server")

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    by_id = {item["id"]: item for item in responses if "id" in item}
    assert by_id[2]["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_acp_approval_waits_for_client_and_rejects_reject_once(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd}},
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
         "params": {"sessionId": "conv-acp-test", "prompt": [{"type": "text", "text": "write"}]}},
    ]
    rpc_in = _QueueInput([json.dumps(line) for line in lines])
    rpc_out = _PermissionOutput(rpc_in, selected="reject_once")
    memory = _Memory()
    monkeypatch.setattr(app_server.uuid, "uuid4", _FakeUuid)
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (rpc_in, rpc_out))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _Orchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(
        db_path=tmp_path / "atlas.db", local_execution_permission_mode="full_access",
    ))

    async def migrate(*_args):
        return _migration_ready()

    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
    _Orchestrator.last_approval = None

    await app_server.serve_stdio(protocol="acp")

    messages = [json.loads(line) for line in rpc_out.lines]
    permission = next(item for item in messages if item.get("method") == "session/request_permission")
    assert permission["params"]["sessionId"] == "conv-acp-test"
    assert {item["optionId"] for item in permission["params"]["options"]} == {
        "allow_once", "reject_once",
    }
    assert _Orchestrator.last_approval == "deny"
    assert next(item for item in messages if item.get("id") == 3)["result"]["stopReason"] == "end_turn"


@pytest.mark.asyncio
async def test_acp_free_text_input_fails_explicitly_without_waiting_or_permission(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd}},
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
         "params": {"sessionId": "conv-acp-test", "prompt": [{"type": "text", "text": "ask"}]}},
    ]
    rpc_in = _QueueInput([json.dumps(item) for item in lines])
    rpc_out = _PermissionOutput(rpc_in, selected="allow_once")
    memory = _Memory()
    monkeypatch.setattr(app_server.uuid, "uuid4", _FakeUuid)
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (rpc_in, rpc_out))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _ACPAskUserOrchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(
        db_path=tmp_path / "atlas.db", local_execution_permission_mode="full_access",
    ))

    async def migrate(*_args):
        return _migration_ready()

    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
    await app_server.serve_stdio(protocol="acp")

    messages = [json.loads(line) for line in rpc_out.lines if line.strip()]
    assert _ACPAskUserOrchestrator.last_answer == (
        "This ACP v1 adapter does not support free-text elicitation; use Atlas app-server input/request."
    )
    assert not any(item.get("method") in {"input/request", "session/request_permission"}
                   for item in messages)
    assert next(item for item in messages if item.get("id") == 3)["result"]["stopReason"] == "end_turn"


@pytest.mark.asyncio
async def test_acp_does_not_stream_discarded_attempt_text(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    rpc_in = _QueueInput([json.dumps(item) for item in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": 1}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd}},
        {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
         "params": {"sessionId": "conv-acp-test", "prompt": [{"type": "text", "text": "retry"}]}},
    ]])
    rpc_out = _PermissionOutput(rpc_in, selected="reject_once")
    memory = _Memory()
    monkeypatch.setattr(app_server.uuid, "uuid4", _FakeUuid)
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (rpc_in, rpc_out))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _AttemptRollbackOrchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(
        db_path=tmp_path / "atlas.db", local_execution_permission_mode="full_access",
    ))

    async def migrate(*_args):
        return _migration_ready()

    monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
    await app_server.serve_stdio(protocol="acp")

    messages = [json.loads(line) for line in rpc_out.lines if line.strip()]
    chunks = [item["params"]["update"]["content"]["text"] for item in messages
              if item.get("method") == "session/update"
              and item["params"]["update"].get("sessionUpdate") == "agent_message_chunk"]
    assert chunks == ["NEW"]
    assert next(item for item in messages if item.get("id") == 3)["result"]["stopReason"] == "end_turn"


@pytest.mark.asyncio
async def test_acp_kernel_attempt_stream_returns_only_committed_attempt(tmp_path, monkeypatch):
    from atlas.models import ModelManager as AtlasModelManager

    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", "2")
    monkeypatch.setenv("ATLAS_MODEL_RETRY_BUDGET_SECONDS", "30")
    monkeypatch.setattr("atlas.engine.kernel.model_call.asyncio.sleep", AsyncMock())

    with FakeLLMServer([
        DropMidStream("OLD answer", after_chars=3),
        Text("NEW answer", chunk_chars=4),
    ]) as fake:
        home = tmp_path / "hermes"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        provider = _ProviderKeyManager(fake.base_url, current="fake-model")

        class FixtureModelManager(AtlasModelManager):
            def __init__(self):
                super().__init__(default_model="fake-model")
                self._models = [{
                    "id": "fake-model", "name": "fake-model", "provider": "atlas-fixture",
                    "atlas_provider": "atlas-fixture", "litellm_model": "openai/fake-model",
                    "native_model": "fake-model", "max_output_tokens": 256,
                }]
                self._current = "fake-model"

            def provider_config(self, provider_id):
                return provider.provider_config(provider_id)

            def resolve_api_key(self, provider_id):
                return provider.resolve_api_key(provider_id)

            def credential_pool(self, provider_id):
                return provider.credential_pool(provider_id)

            def get_api_mode_override(self, provider_id):
                return provider.get_api_mode_override(provider_id)

            def get_api_mode_probe(self, provider_id):
                return provider.get_api_mode_probe(provider_id)

            def model_availability(self, _model_id):
                return {"available": True}

        cwd = str(tmp_path.resolve())
        rpc_in = _QueueInput([json.dumps(item) for item in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd}},
        ]])
        rpc_out = _ACPAttemptOutput(rpc_in, selected="reject_once")
        memory = _Memory()
        monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (rpc_in, rpc_out))
        monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
        monkeypatch.setattr("atlas.models.ModelManager", FixtureModelManager)
        monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _KernelPresetStore)
        monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path / "data")

        async def migrate(*_args):
            return _migration_ready()

        monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
        await app_server.serve_stdio(protocol="acp")

        messages = [json.loads(line) for line in rpc_out.lines if line.strip()]
        chunks = [item["params"]["update"]["content"]["text"] for item in messages
                  if item.get("method") == "session/update"
                  and item["params"]["update"].get("sessionUpdate") == "agent_message_chunk"]
        prompt_responses = [item for item in messages if item.get("id") == 3]
        assert prompt_responses and "result" in prompt_responses[-1], {
            "prompt_response": prompt_responses[-1] if prompt_responses else None,
            "updates": [item.get("params", {}).get("update", {}).get("sessionUpdate")
                        for item in messages if item.get("method") == "session/update"],
        }
        prompt_result = prompt_responses[-1]["result"]
        assert len(fake.main_requests()) == 2, {"prompt_result": prompt_result}
        assert chunks and "".join(chunks) == "NEW answer"
        assert "OLD" not in "".join(chunks)
        assert prompt_result["stopReason"] == "end_turn"

        from atlas.engine.session_sync import read_session_model_messages
        from hermes_state import SessionDB

        conversation_id = next(item["result"]["sessionId"] for item in messages if item.get("id") == 2)
        rows = read_session_model_messages(tmp_path / "data" / "engine", conversation_id)
        with SessionDB(db_path=tmp_path / "data" / "engine" / "state.db") as db:
            audit = db.list_session_events(conversation_id, after_seq=0, limit=1000)
        assistant_text = "".join(
            str(row.get("content") or "") for row in rows if row.get("role") == "assistant"
        )
        assert "NEW answer" in assistant_text
        assert "OLD answer" not in assistant_text
        assert any(
            row.get("event_type") == "model/attempt"
            and row["payload"].get("status") == "discarded"
            and str(row["payload"].get("partial_text") or "").startswith("OLD")
            for row in audit
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("selected", "should_write"), [
    ("reject_once", False),
    ("allow_once", True),
])
async def test_acp_kernel_permission_decision_controls_real_tool_side_effect(
    tmp_path, monkeypatch, selected, should_write,
):
    from atlas.models import ModelManager as AtlasModelManager

    target = tmp_path / "must-not-be-created.txt"
    data_root = tmp_path / "data"
    data_root.mkdir()
    with FakeLLMServer([
        ToolCall("local_file", {
            "action": "write", "path": str(target), "content": "ACP_REJECTED_WRITE",
        }),
        Text("ACP_REJECTION_HANDLED"),
    ]) as fake:
        home = tmp_path / "hermes"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        provider = _ProviderKeyManager(fake.base_url, current="fake-model")

        class FixtureModelManager(AtlasModelManager):
            def __init__(self):
                super().__init__(default_model="fake-model")
                self._models = [{
                    "id": "fake-model", "name": "fake-model", "provider": "atlas-fixture",
                    "atlas_provider": "atlas-fixture", "litellm_model": "openai/fake-model",
                    "native_model": "fake-model", "max_output_tokens": 256,
                }]
                self._current = "fake-model"

            def provider_config(self, provider_id):
                return provider.provider_config(provider_id)

            def resolve_api_key(self, provider_id):
                return provider.resolve_api_key(provider_id)

            def credential_pool(self, provider_id):
                return provider.credential_pool(provider_id)

            def get_api_mode_override(self, provider_id):
                return provider.get_api_mode_override(provider_id)

            def get_api_mode_probe(self, provider_id):
                return provider.get_api_mode_probe(provider_id)

            def model_availability(self, _model_id):
                return {"available": True}

        cwd = str(tmp_path.resolve())
        rpc_in = _QueueInput([json.dumps(item) for item in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd}},
            {"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
             "params": {"sessionId": "conv-acp-test", "prompt": [{"type": "text", "text": "write file"}]}},
        ]])
        rpc_out = _PermissionOutput(rpc_in, selected=selected)
        memory = _Memory()
        class StableSessionUuid:
            hex = "0123456789abcdef0123456789abcdef"

            def __str__(self):
                return "conv-acp-test"

        monkeypatch.setattr(app_server.uuid, "uuid4", StableSessionUuid)
        monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (rpc_in, rpc_out))
        monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
        monkeypatch.setattr("atlas.models.ModelManager", FixtureModelManager)
        monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _KernelPresetStore)
        monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)

        async def migrate(*_args):
            return _migration_ready()

        monkeypatch.setattr("atlas.engine.session_migration.migrate_legacy_sessions", migrate)
        await app_server.serve_stdio(protocol="acp")

        messages = [json.loads(line) for line in rpc_out.lines if line.strip()]
        permissions = [item for item in messages if item.get("method") == "session/request_permission"]
        assert len(permissions) == 1, {
            "outgoing": [(item.get("method"), item.get("id")) for item in messages],
            "provider_requests": len(fake.main_requests()),
            "provider_tool_names": [
                call.get("function", {}).get("name")
                for request in fake.main_requests()
                for call in request.get("tool_calls", [])
            ],
            "prompt_stop_reason": next((item.get("result", {}).get("stopReason")
                                        for item in messages if item.get("id") == 3), None),
            "prompt_error": next((item.get("error") for item in messages if item.get("id") == 3), None),
        }
        permission = permissions[0]
        assert permission["id"].startswith("acp-permission-")
        assert permission["params"]["sessionId"] == "conv-acp-test"
        prompt_result = next(item for item in messages if item.get("id") == 3 and "result" in item)
        assert prompt_result["result"]["stopReason"] == "end_turn"
        assert target.exists() is should_write
        if should_write:
            assert target.read_text(encoding="utf-8") == "ACP_REJECTED_WRITE"
        requests = fake.main_requests()
        assert len(requests) == 2
        tool_messages = [row for row in requests[1]["messages"] if row.get("role") == "tool"]
        assert tool_messages and str(tool_messages[-1].get("content", "")).strip()


def _migration_ready():
    return SimpleNamespace(status="ready", error=None)
