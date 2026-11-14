"""ACP session/configuration methods stay in the ACP JSON-RPC surface."""

import io
import json
import queue
from types import SimpleNamespace

import pytest

from atlas.tools import app_server


pytestmark = pytest.mark.unit


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


class _ModelManager:
    pass


class _PresetStore:
    def __init__(self, _path):
        pass

    def resolve(self, preset_id):
        return {"preset": preset_id}


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


class _FakeUuid:
    hex = "fake-id"

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
    monkeypatch.setattr(app_server.uuid, "uuid4", lambda: "conv-acp-test")
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (stdin, stdout))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", _Orchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(db_path=tmp_path / "atlas.db"))
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
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(db_path=tmp_path / "atlas.db"))

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


def _migration_ready():
    return SimpleNamespace(status="ready", error=None)
