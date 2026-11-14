"""SDK JSON-RPC lifecycle: ``session/wait`` settle barrier, ``shutdown`` drain,
and ``session/status`` running/idle notifications (DSH SDK protocol row X25)."""

import asyncio
import json
import queue
from types import SimpleNamespace

import pytest

from atlas.tools import app_server


pytestmark = pytest.mark.unit


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


class _GatedOrchestrator:
    """Run blocks until the class-level gate is set, or the run is cancelled."""

    gate: asyncio.Event | None = None
    hold: bool = False  # True: block until cancelled, ignoring the gate.

    def __init__(self, **_kwargs):
        pass

    async def run(self, _prompt, _conversation_id, **kwargs):
        cancel = kwargs.get("cancel_event")
        if type(self).hold:
            await cancel.wait()
            yield {"type": "chunk", "content": "settled"}
            return
        gate = type(self).gate
        if gate is None:
            yield {"type": "chunk", "content": "instant"}
            return
        gate_wait = asyncio.create_task(gate.wait())
        cancel_wait = asyncio.create_task(cancel.wait())
        try:
            await asyncio.wait(
                {gate_wait, cancel_wait}, return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            gate_wait.cancel()
            cancel_wait.cancel()
            await asyncio.gather(gate_wait, cancel_wait, return_exceptions=True)
        yield {"type": "chunk", "content": "settled"}


class _ModelManager:
    pass


class _PresetStore:
    def __init__(self, _path):
        pass

    def resolve(self, preset_id):
        return {"preset": preset_id}


class _BlockingInput:
    """readline() blocks on a queue, so the harness controls EOF timing."""

    def __init__(self, lines):
        self.lines = queue.Queue()
        for line in lines:
            # A real stream's EOF surfaces as "" from readline(); appending the
            # newline would turn the EOF marker into a (truthy) blank frame.
            self.lines.put(line + chr(10) if line else "")

    def readline(self):
        return self.lines.get()


class _CollectingOutput:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, line):
        self.lines.append(line)
        return len(line)

    def flush(self):
        pass


async def _migration_ready(*_args):
    return SimpleNamespace(status="ready", error=None)


def _install_harness(monkeypatch, tmp_path, stdin, stdout, orchestrator):
    memory = _Memory()
    monkeypatch.setattr(app_server, "_claim_stdio_channel", lambda: (stdin, stdout))
    monkeypatch.setattr("atlas.memory.MemoryStore", lambda: memory)
    monkeypatch.setattr("atlas.agent.AgentOrchestrator", orchestrator)
    monkeypatch.setattr("atlas.models.ModelManager", _ModelManager)
    monkeypatch.setattr("atlas.task_artifacts.AgentPresetStore", _PresetStore)
    monkeypatch.setattr(
        "atlas.config.get_config",
        lambda: SimpleNamespace(db_path=tmp_path / "atlas.db"),
    )
    monkeypatch.setattr(
        "atlas.engine.session_migration.migrate_legacy_sessions", _migration_ready,
    )
    return memory


def _rpc(**payload):
    return json.dumps({"jsonrpc": "2.0", **payload}) + "\n"


async def _collect_until(stdout, predicate, timeout=5.0):
    """Poll collected output until predicate(json lines) is true."""
    async def poll():
        while True:
            messages = [json.loads(line) for line in stdout.lines if line.strip()]
            if predicate(messages):
                return messages
            await asyncio.sleep(0.02)

    return await asyncio.wait_for(poll(), timeout)


@pytest.mark.asyncio
async def test_session_wait_unknown_session_is_rejected(tmp_path, monkeypatch):
    wire = [
        _rpc(id=1, method="initialize", params={"protocolVersion": 1}),
        _rpc(id=2, method="session/wait", params={"session_id": "nope"}),
        "",
    ]
    stdin, stdout = _BlockingInput(wire), _CollectingOutput()
    _install_harness(monkeypatch, tmp_path, stdin, stdout, _GatedOrchestrator)
    await asyncio.wait_for(app_server.serve_stdio(protocol="app-server"), 10)

    messages = [json.loads(line) for line in stdout.lines if line.strip()]
    by_id = {item.get("id"): item for item in messages if "id" in item}
    assert by_id[2]["error"]["code"] == -32002


@pytest.mark.asyncio
async def test_session_wait_on_idle_session_returns_immediately(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    wire = [
        _rpc(id=1, method="initialize", params={"protocolVersion": 1}),
        _rpc(id=2, method="session/start", params={"workspace": cwd}),
        _rpc(id=3, method="session/wait", params={"session_id": "sid"}),
        "",
    ]
    stdin, stdout = _BlockingInput(wire), _CollectingOutput()
    _install_harness(monkeypatch, tmp_path, stdin, stdout, _GatedOrchestrator)
    monkeypatch.setattr(app_server.uuid, "uuid4", lambda: "sid")
    await asyncio.wait_for(app_server.serve_stdio(protocol="app-server"), 10)

    messages = [json.loads(line) for line in stdout.lines if line.strip()]
    by_id = {item.get("id"): item for item in messages if "id" in item}
    assert by_id[2]["result"]["session_id"] == "sid"
    assert by_id[3]["result"] == {}


@pytest.mark.asyncio
async def test_session_wait_blocks_until_run_settles_with_status_notifications(
    tmp_path, monkeypatch,
):
    cwd = str(tmp_path.resolve())
    wire = [
        _rpc(id=1, method="initialize", params={"protocolVersion": 1}),
        _rpc(id=2, method="session/start", params={"workspace": cwd}),
        _rpc(id=3, method="session/prompt", params={"session_id": "sid", "prompt": "work"}),
        _rpc(id=4, method="session/wait", params={"session_id": "sid"}),
        # EOF is delivered later: a pre-loaded EOF would drain the server and
        # cancel the gated run before it settles.
    ]
    stdin, stdout = _BlockingInput(wire), _CollectingOutput()
    _install_harness(monkeypatch, tmp_path, stdin, stdout, _GatedOrchestrator)
    _GatedOrchestrator.gate = asyncio.Event()
    monkeypatch.setattr(app_server.uuid, "uuid4", lambda: "sid")

    server = asyncio.create_task(app_server.serve_stdio(protocol="app-server"))
    # The reader consumed prompt + wait and both are pending on the gate.
    await asyncio.sleep(0.15)
    _GatedOrchestrator.gate.set()

    messages = await _collect_until(
        stdout,
        lambda items: any(item.get("id") == 4 for item in items),
    )
    stdin.lines.put("")
    await asyncio.wait_for(server, 10)

    by_id = {item.get("id"): item for item in messages if "id" in item}
    statuses = [item for item in messages if item.get("method") == "session/status"]
    assert [item["params"]["status"] for item in statuses] == ["running", "idle"]
    assert all(item["params"]["session_id"] == "sid" for item in statuses)
    # The settle barrier resolved only after the run produced its text.
    assert by_id[3]["result"]["text"] == "settled"
    assert by_id[3]["result"]["status"] == "completed"
    assert by_id[4]["result"] == {}


@pytest.mark.asyncio
async def test_shutdown_acknowledges_and_drains_active_run(tmp_path, monkeypatch):
    cwd = str(tmp_path.resolve())
    wire = [
        _rpc(id=1, method="initialize", params={"protocolVersion": 1}),
        _rpc(id=2, method="session/start", params={"workspace": cwd}),
        _rpc(id=3, method="session/prompt", params={"session_id": "sid", "prompt": "work"}),
        _rpc(id=4, method="shutdown"),
        "",
    ]
    stdin, stdout = _BlockingInput(wire), _CollectingOutput()
    _install_harness(monkeypatch, tmp_path, stdin, stdout, _GatedOrchestrator)
    _GatedOrchestrator.hold = True  # run only finishes via cancel
    monkeypatch.setattr(app_server.uuid, "uuid4", lambda: "sid")

    await asyncio.wait_for(app_server.serve_stdio(protocol="app-server"), 10)

    messages = [json.loads(line) for line in stdout.lines if line.strip()]
    by_id = {item.get("id"): item for item in messages if "id" in item}
    assert by_id[4]["result"] == {}
    assert by_id[3]["result"]["status"] == "cancelled"
    statuses = [item for item in messages if item.get("method") == "session/status"]
    assert [item["params"]["status"] for item in statuses] == ["running", "idle"]
    # The drain settled the active run and flushed its response before the
    # process ended (shutdown ack is queued at request time, the cancelled
    # run's receipt during drain — both must be present).
    id_responses = [item.get("id") for item in messages if "id" in item]
    assert sorted(id_responses) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_acp_protocol_rejects_app_server_lifecycle_methods(tmp_path, monkeypatch):
    wire = [
        _rpc(id=1, method="initialize", params={"protocolVersion": 1}),
        _rpc(id=2, method="session/wait", params={"sessionId": "x"}),
        _rpc(id=3, method="shutdown"),
        "",
    ]
    stdin, stdout = _BlockingInput(wire), _CollectingOutput()
    _install_harness(monkeypatch, tmp_path, stdin, stdout, _GatedOrchestrator)
    await asyncio.wait_for(app_server.serve_stdio(protocol="acp"), 10)

    messages = [json.loads(line) for line in stdout.lines if line.strip()]
    by_id = {item.get("id"): item for item in messages if "id" in item}
    assert by_id[2]["error"]["code"] == -32601
    assert by_id[3]["error"]["code"] == -32601
