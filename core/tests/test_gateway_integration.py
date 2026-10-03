"""Gateway integration (W10) — ChannelManager → GatewayBridge → real run → delivery.

The whole inbound pipeline is real: the app's lifespan-wired ChannelManager +
GatewayBridge + ``_handle_run_start`` + memory + FakeLLM. Only the transport is
scripted (a FakeAdapter registered on the live manager), so the test proves the
exact seams the server ships:

- inbound event → gating/routing → dispatcher → session resolution
  (``channel_sessions`` sqlite map, idempotent per session key) → run →
  answer delivered back through the outbound queue → ``adapter.send``;
- completion/failure are the only two reply points (no per-token flooding);
- heartbeat tick through the real HeartbeatService host seams, plus the W1↔W4
  reconcile (``heartbeat-<agent_id>`` automations) and the automation engine's
  injected hooks (heartbeat_tick / dispatch_turn) over DBOS.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from atlas.channels import ChannelManager
from atlas.channels.contract import ChannelAdapter, MessageEvent, SendResult
from atlas.persistent_agents import session_key

from tests.fakes.fake_llm_provider import FakeLLMServer, Text

pytest.importorskip("dbos")

# The lifespan launches DBOS inside the test-loop's default executor; function
# loops would kill that pool on exit (see test_automation_engine.py's note), so
# the whole module shares one event loop.
pytestmark = pytest.mark.asyncio(loop_scope="module")

REPLY_WAIT = 30.0  # run + queue drain + delivery interval (0.5s) headroom


class FakeAdapter(ChannelAdapter):
    """Transport double: records outbound sends, emits scripted inbound events."""

    name = "fake"
    instances: ClassVar[list[FakeAdapter]] = []

    def __init__(self, config, dispatcher):
        super().__init__(config, dispatcher)
        self.sent: list[dict[str, Any]] = []
        self.worker: asyncio.Task | None = None
        type(self).instances.append(self)

    async def start(self):
        if self.config.get("behaviour") == "auth_fail":
            from atlas.channels import AdapterAuthError

            raise AdapterAuthError("令牌无效")
        self.worker = asyncio.create_task(asyncio.Event().wait())

    async def stop(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()

    async def send(self, chat_id, content, *, reply_to="", attachments=None, metadata=None):
        self.sent.append({
            "chat_id": chat_id, "content": content,
            "reply_to": reply_to, "metadata": dict(metadata or {}),
        })
        return SendResult(ok=True, message_id=f"m-{len(self.sent)}")

    async def emit(self, event: MessageEvent):
        return await self._dispatch(event)


def make_event(event_id: str, *, chat_id: str, text: str, thread_id: str = "") -> MessageEvent:
    return MessageEvent(
        channel="fake", account="", event_id=event_id, chat_id=chat_id,
        sender_id="42", text=text, thread_id=thread_id,
    )


async def wait_for(condition, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return bool(condition())


@pytest.fixture(scope="module")
def fake_llm():
    with FakeLLMServer() as fake:
        yield fake


@pytest.fixture(scope="module")
async def app_client(tmp_path_factory: pytest.TempPathFactory, fake_llm: FakeLLMServer):
    """The real app under lifespan, with the fake adapter attached to its manager.

    Module-scoped on the module's shared loop: DBOS 3.0 binds its process-global
    thread pool to the first event loop that touches it, so booting the app per
    test plays destroy/restore roulette with that pool between tests (the
    RuntimeError-after-shutdown trap documented in test_automation_engine.py).
    One lifespan per module boots once and tears DBOS down exactly once at
    module end, so the next test file starts from a clean process-global state.
    """
    from atlas import config
    from atlas.telegram import TelegramService

    mp = pytest.MonkeyPatch()
    tmp_path = tmp_path_factory.mktemp("gateway-int")
    (tmp_path / "workspace").mkdir()
    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[models]\ndefault=\"fake-model\"\n"
        f"[models.gateway]\nbase_url=\"{fake_llm.base_url}\"\napi_key=\"sk-fake-w10\"\n"
        "[[models.custom]]\nid=\"fake-model\"\nname=\"Fake fixture\"\nprovider=\"openai\"\n"
        "litellm_model=\"openai/fake-model\"\nmax_output_tokens=512\n"
        "[agent]\nverify_before_stop=false\n"
        "[tools]\nauto_start=[]\n[tools.servers]\n"
        "[scheduler]\nenabled=false\n",
        encoding="utf-8",
    )
    mp.setattr(config, "CONFIG_PATH", config_path)
    mp.setattr(config, "DATA_ROOT", data_root)
    mp.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    mp.setattr(config, "_config", None)
    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        mp.delenv(key, raising=False)
    mp.setattr(TelegramService, "start", lambda _self: None)

    try:
        import atlas.server as server

        FakeAdapter.instances.clear()
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with server.lifespan(server.app):
                manager: ChannelManager = server.channel_manager
                assert manager is not None and server.gateway_bridge is not None
                manager.register_channel("fake", FakeAdapter)
                manager.configure("fake", {"enabled": True}, persist=False)
                # Restart the manager so the fake channel gets a supervisor; the
                # gateway bridge / dispatcher survive unchanged.
                await manager.stop()
                await manager.start()
                # start() only spawns the supervisor task — the adapter is
                # constructed on its first tick, so wait for that beat.
                assert await wait_for(lambda: bool(FakeAdapter.instances)), (
                    "supervisor 没有实例化 fake adapter"
                )
                yield SimpleNamespace_(ac, server, fake_llm, FakeAdapter.instances[-1])
        FakeAdapter.instances.clear()
    finally:
        mp.undo()
        # Belt and braces: leave no process-global DBOS behind for the next
        # file, whatever the lifespan teardown managed to do.
        from dbos import DBOS

        DBOS.destroy(destroy_registry=True)


@pytest.fixture(autouse=True)
def _fresh_transport(app_client: SimpleNamespace_):
    """Per-test isolation on the module-shared transport double."""
    app_client.adapter.sent.clear()
    yield


class SimpleNamespace_:
    """Bundle the pieces a test needs (client, server module, adapter)."""

    def __init__(self, client, server, fake_llm, adapter):
        self.client = client
        self.server = server
        self.fake_llm = fake_llm
        self.adapter = adapter


def _spy_on_submit(bridge) -> list[dict[str, Any]]:
    """Record every run.start payload the bridge submits (conversation ids)."""
    original = bridge._submit_run
    captured: list[dict[str, Any]] = []

    async def spy(conn_id, data):
        captured.append(dict(data))
        await original(conn_id, data)

    bridge._submit_run = spy
    return captured


async def test_inbound_event_runs_and_replies_on_channel(app_client) -> None:
    bundle = app_client
    server = bundle.server
    bridge = server.gateway_bridge
    captured = _spy_on_submit(bridge)
    bundle.fake_llm._responder = lambda _record: Text("渠道任务已完成，摘要如下。")

    await bundle.adapter.emit(make_event("evt-1", chat_id="100", text="帮我做个摘要", thread_id="t-9"))
    assert await wait_for(lambda: bool(bundle.adapter.sent), timeout=REPLY_WAIT)

    # Exactly one completion reply, back on the originating channel/thread.
    assert len(bundle.adapter.sent) == 1
    reply = bundle.adapter.sent[0]
    assert reply["chat_id"] == "100"
    assert reply["reply_to"] == "t-9"
    assert "渠道任务已完成，摘要如下。" in reply["content"]

    # The run went through the real _handle_run_start ("channel" conn).
    assert len(captured) == 1
    assert captured[0]["conversation_id"]
    assert captured[0]["source"] == "channel"

    # Session lineage: durable map keyed by the W1 session_key grammar.
    expected_key = session_key("main", channel="fake", account="", peer="100")
    assert bridge.sessions.get(expected_key) == captured[0]["conversation_id"]


async def test_same_session_key_reuses_conversation(app_client) -> None:
    bundle = app_client
    bridge = bundle.server.gateway_bridge
    captured = _spy_on_submit(bridge)

    await bundle.adapter.emit(make_event("evt-a1", chat_id="200", text="第一句"))
    assert await wait_for(lambda: len(captured) == 1, timeout=REPLY_WAIT)
    first_key = session_key("main", channel="fake", peer="200")
    first_conversation = bridge.sessions.get(first_key)

    await bundle.adapter.emit(make_event("evt-a2", chat_id="200", text="第二句"))
    assert await wait_for(lambda: len(captured) == 2, timeout=REPLY_WAIT)
    # Same channel+peer → same session key → same conversation (idempotent map).
    assert bridge.sessions.get(first_key) == first_conversation
    assert captured[1]["conversation_id"] == first_conversation

    await bundle.adapter.emit(make_event("evt-b1", chat_id="300", text="另一个人"))
    assert await wait_for(lambda: len(captured) == 3, timeout=REPLY_WAIT)
    other_key = session_key("main", channel="fake", peer="300")
    assert bridge.sessions.get(other_key) not in (None, first_conversation)

    # The sqlite channel_sessions table holds exactly one row per session key.
    import sqlite3

    with sqlite3.connect(str(bundle.server.get_config().db_path.parent / "channels.sqlite")) as db:
        rows = db.execute(
            "SELECT session_key, conversation_id FROM channel_sessions"
        ).fetchall()
    mapping = dict(rows)
    assert mapping[first_key] == first_conversation
    assert len(rows) == len(mapping)  # no duplicate rows per key


async def test_run_failure_answers_with_one_failure_summary(app_client) -> None:
    bundle = app_client
    from tests.fakes.fake_llm_provider import Error

    bundle.fake_llm._responder = lambda _record: Error(status=500, message="scripted failure")

    await bundle.adapter.emit(make_event("evt-f1", chat_id="400", text="会失败的请求"))
    assert await wait_for(lambda: bool(bundle.adapter.sent), timeout=REPLY_WAIT)
    assert len(bundle.adapter.sent) == 1  # failure answers once, no retry spam
    assert "任务执行失败" in bundle.adapter.sent[0]["content"]


async def test_heartbeat_tick_and_automation_reconcile_over_live_app(app_client) -> None:
    bundle = app_client
    server = bundle.server
    from atlas.api.agent_router import get_agent_service
    from atlas.automation import get_automation_engine
    from atlas.automation.store import normalize_record
    from atlas.heartbeat import TickResult

    agents = get_agent_service()
    agents.create({
        "id": "agent-hb", "name": "Heartbeat Agent", "model": "fake-model",
        "agent": {"workspace": "", "enabled": True},
    })
    agents.set_heartbeat("agent-hb", {"enabled": True})
    bundle.fake_llm._responder = lambda _record: Text("NO_REPLY")

    # HeartbeatService.tick through the real host seams (config from the agent
    # registry, turn through the orchestrator, delivery skipped on NO_REPLY).
    result = await server.heartbeat_service.tick("agent-hb", "event")
    assert isinstance(result, TickResult)
    assert result.status == "ran"
    assert result.delivered is False
    assert server.heartbeat_service.session_key("agent-hb") == "agent:agent-hb:heartbeat"

    # W1↔W4 reconcile: enabled heartbeat → heartbeat-<agent_id> automation.
    engine = get_automation_engine()
    await server._reconcile_agent_heartbeats(agents, engine)
    record = engine.store.get("heartbeat-agent-hb")
    assert record is not None
    assert record["owner_agent_id"] == "agent-hb"
    assert record["trigger"]["kind"] == "interval"
    assert record["trigger"]["every_seconds"] == 1800.0
    assert record["payload"]["kind"] == "heartbeat"
    assert record["payload"]["agent_id"] == "agent-hb"
    assert record["delivery"]["mode"] == "none"
    assert record["enabled"] is True

    # Idempotent: a second reconcile leaves the stored record untouched.
    before = engine.store.get("heartbeat-agent-hb")["updated_at"]
    await asyncio.sleep(0.01)
    await server._reconcile_agent_heartbeats(agents, engine)
    assert engine.store.get("heartbeat-agent-hb")["updated_at"] == before

    # Automation → heartbeat injection actually fires over DBOS and settles ok.
    assert await wait_for(
        lambda: (engine.store.get("heartbeat-agent-hb") or {}).get("state", {}).get("last_status")
        == "ok",
        timeout=REPLY_WAIT,
    )

    # Disabling the heartbeat reconciles the automation away.
    agents.set_heartbeat("agent-hb", {"enabled": False})
    await server._reconcile_agent_heartbeats(agents, engine)
    assert engine.store.get("heartbeat-agent-hb") is None


async def test_automation_dispatch_turn_injection_reaches_model(app_client) -> None:
    bundle = app_client
    from atlas.automation import get_automation_engine
    from atlas.automation.store import normalize_record

    engine = get_automation_engine()
    saved = engine.store.put(normalize_record({
        "id": "probe-turn", "name": "probe agent turn",
        "trigger": {"kind": "interval", "every_seconds": 3600},
        "payload": {"kind": "agent_turn", "message": "自动化问候"},
        "delivery": {"mode": "none"},
    }))
    await engine.sync_automation(saved)

    # The interval loop fires immediately → dispatch_turn seam → orchestrator
    # (conversation automation-<id>) → fake LLM → outcome written back.
    assert await wait_for(
        lambda: (engine.store.get("probe-turn") or {}).get("state", {}).get("last_status") == "ok",
        timeout=REPLY_WAIT,
    )
    prompts = "".join(str(item.get("messages", [{}])[-1].get("content", ""))
                      for item in bundle.fake_llm.main_requests())
    assert "自动化问候" in prompts
