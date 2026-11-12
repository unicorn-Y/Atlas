"""H7 end-to-end at the gateway level: a real FakeLLM write gated on the channel.

No ``atlas.server`` import (the app factory belongs to another owner): the
``ChannelManager`` + ``GatewayBridge`` pair is wired to a *real* AtlasRuntime
turn through the same seam production uses — ``_handle_run_start``'s
approval callback forwards into :meth:`GatewayBridge.request_approval` when
``bridge.owns_run(run_id)``. The model genuinely calls ``write_file`` under the
default ``ask_writes`` permission mode, the approval request lands back on the
originating channel, and only the channel/desktop decision unblocks the write:

- 回复「允许」→ file written → completion receipt on the channel;
- 回复「拒绝」→ tool blocked, no file, receipt still answers;
- 超时 → denied + explicit timeout notice on the channel;
- desktop resolves the shared future first → channel gets「已在桌面批准」;
- bridge built with an overridden default mode skips the approval entirely.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.channels import ChannelManager
from atlas.channels.contract import ChannelAdapter, MessageEvent, SendResult
from atlas.gateway_service import GatewayBridge
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home

pytest.importorskip("hermes_cli")

REPLY_WAIT = 30.0


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
        self.worker = asyncio.create_task(asyncio.Event().wait())

    async def stop(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()

    async def send(self, chat_id, content, *, reply_to="", attachments=None, metadata=None):
        self.sent.append({"chat_id": chat_id, "content": content, "reply_to": reply_to})
        return SendResult(ok=True, message_id=f"m-{len(self.sent)}")

    async def emit(self, event: MessageEvent):
        return await self._dispatch(event)


@dataclass
class ChannelRun:
    """The run-shape ``GatewayBridge`` relies on (server ``RunState`` subset)."""

    run_id: str
    status: str = "running"
    approval_futures: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


def event(event_id: str, text: str, chat_id: str = "100") -> MessageEvent:
    return MessageEvent(channel="fake", account="", event_id=event_id, chat_id=chat_id,
                        sender_id="owner", text=text)


async def wait_for(condition, timeout: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return bool(condition())


def sent_texts(adapter: FakeAdapter, needle: str) -> list[str]:
    return [item["content"] for item in adapter.sent if needle in item["content"]]


class GatewayHarness:
    """Manager + bridge + real AtlasRuntime write turn, wired like production."""

    def __init__(self, tmp_path: Path, fake: FakeLLMServer, *, timeout: float = 600.0,
                 default_permission_mode: str = "ask_writes") -> None:
        self.tmp_path = tmp_path
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir(exist_ok=True)
        self.manager = ChannelManager(db_path=tmp_path / "channels.sqlite")
        self.manager.register_channel("fake", FakeAdapter)
        self.manager.configure("fake", {"enabled": True}, persist=False)
        self.runs: dict[str, ChannelRun] = {}
        self.submitted: list[dict[str, Any]] = []
        self.answer = {"text": ""}
        self.target = self.workspace / "渠道文件.txt"
        self.bridge = GatewayBridge(
            manager=self.manager,
            db_path=tmp_path / "channels.sqlite",
            submit_run=self._make_submit(),
            get_run=self.runs.get,
            read_answer=self._read_answer,
            create_conversation=self._create_conversation,
            default_workspace=str(self.workspace),
            approval_timeout_seconds=timeout,
            default_permission_mode=default_permission_mode,
        )
        self.manager.set_dispatcher(self.bridge.dispatch)

    async def _create_conversation(self, _key: str, _event: MessageEvent) -> str:
        return "conversation-1"

    async def _read_answer(self, _conversation: str) -> str:
        return self.answer["text"] or "任务完成。"

    def _make_submit(self):
        """Production-shaped submit seam: the approval callback routes into the
        bridge exactly like ``_handle_run_start`` does for channel runs."""

        async def submit(_conn: str, data: dict[str, Any]) -> None:
            self.submitted.append(dict(data))
            run = ChannelRun(run_id=str(data["run_id"]))
            self.runs[run.run_id] = run
            bridge = self.bridge

            async def approval_callback(approval_id: str, tool_name: str,
                                        _args: dict[str, Any]) -> str:
                description = f"Agent 请求执行工具 {tool_name}，需要你的确认。"
                return await bridge.request_approval(run, approval_id, description)

            async def execute() -> None:
                from atlas.engine.atlas_runtime import AtlasRuntime

                models = self.models
                runtime = AtlasRuntime(data_dir=self.tmp_path, model_manager=models)
                events = [event async for event in runtime.run_turn(
                    message=str(data["content"]),
                    conversation_id=str(data["conversation_id"]),
                    workspace=str(self.workspace),
                    history=[],
                    atlas_agent=self.orchestrator,
                    atlas_context=AgentRunContext(
                        cancel_event=run.cancel_event,
                        run_id=run.run_id,
                        conversation_id=str(data["conversation_id"]),
                        workspace=str(self.workspace),
                        permission_mode=str(data["permission_mode"]),
                        approval_callback=approval_callback,
                    ),
                )]
                result = events[-1].get("result") if isinstance(events[-1], dict) else {}
                self.answer["text"] = str((result or {}).get("final_response") or "")
                run.status = "completed"

            run.task = asyncio.create_task(execute())

        return submit

    async def __aenter__(self) -> GatewayHarness:
        FakeAdapter.instances.clear()
        await self.manager.start()
        assert await wait_for(lambda: bool(FakeAdapter.instances)), "adapter 未启动"
        self.adapter = FakeAdapter.instances[-1]
        return self

    async def __aexit__(self, *_exc: object) -> None:
        for run in self.runs.values():
            run.cancel_event.set()
            if run.task is not None:
                run.task.cancel()
        await self.manager.stop()
        self.bridge.sessions.close()
        FakeAdapter.instances.clear()


@pytest.fixture()
def atlas_env(tmp_path, monkeypatch):
    """Each scenario gets an isolated engine home pinned to its FakeLLM."""

    def install(fake: FakeLLMServer) -> SimpleNamespace:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("atlas.config.get_config",
                            lambda: {"tools.servers": {}, "tools.auto_start": []})
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        return models

    return install


def _orchestrator(models: SimpleNamespace):
    from unittest.mock import MagicMock

    mcp = MagicMock()
    mcp.get_tools_for_llm.return_value = []
    mcp.list_tools.return_value = []
    mcp.tool_count = 0
    return AgentOrchestrator(
        models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
    )


def _wire_model(harness: GatewayHarness, models: SimpleNamespace) -> None:
    harness.models = models
    harness.orchestrator = _orchestrator(models)


async def _wait_approval_request(adapter: FakeAdapter) -> None:
    assert await wait_for(
        lambda: bool(sent_texts(adapter, "需要审批")), timeout=REPLY_WAIT,
    ), "渠道没有收到审批请求"


@pytest.mark.asyncio
async def test_channel_write_approved_by_channel_reply(tmp_path, hermes_env):
    """入站任务触发写文件 → 渠道收到审批请求 → 回复允许 → 执行完成并回执."""
    script = [
        ToolCall("write_file", {"path": str(tmp_path / "workspace/渠道文件.txt"),
                                "content": "渠道批准的写入"}),
        Text("写入完成"),
    ]
    with FakeLLMServer(script) as fake:
        harness = GatewayHarness(tmp_path, fake)
        _wire_model(harness, hermes_env(fake))
        async with harness:
            await harness.adapter.emit(event("evt-task", "请写入文件"))
            await _wait_approval_request(harness.adapter)
            # H7 §9.1: channel tasks default to ask_writes at the gateway.
            assert harness.submitted[0]["permission_mode"] == "ask_writes"
            assert harness.submitted[0]["source"] == "channel"

            await harness.adapter.emit(event("evt-reply", "允许"))
            assert await wait_for(
                lambda: any("写入完成" in item["content"] for item in harness.adapter.sent),
                timeout=REPLY_WAIT,
            ), "渠道没有收到完成回执"
            assert harness.target.read_text(encoding="utf-8") == "渠道批准的写入"
            # The channel ack of the approval itself arrives before the receipt.
            assert any("已允许执行。" in item["content"] for item in harness.adapter.sent)
            assert not harness.bridge._approvals


@pytest.mark.asyncio
async def test_channel_write_denied_by_channel_reply(tmp_path, hermes_env):
    script = [
        ToolCall("write_file", {"path": str(tmp_path / "workspace/渠道文件.txt"),
                                "content": "不应写入"}),
        Text("已按您的拒绝取消写入"),
    ]
    with FakeLLMServer(script) as fake:
        harness = GatewayHarness(tmp_path, fake)
        _wire_model(harness, hermes_env(fake))
        async with harness:
            await harness.adapter.emit(event("evt-task", "请写入文件"))
            await _wait_approval_request(harness.adapter)

            await harness.adapter.emit(event("evt-reply", "拒绝"))
            assert await wait_for(
                lambda: any("取消写入" in item["content"] for item in harness.adapter.sent),
                timeout=REPLY_WAIT,
            )
            assert not harness.target.exists(), "拒绝后文件仍被写入"
            assert any("已拒绝执行。" in item["content"] for item in harness.adapter.sent)


@pytest.mark.asyncio
async def test_channel_write_timeout_denies_and_notifies(tmp_path, hermes_env):
    script = [
        ToolCall("write_file", {"path": str(tmp_path / "workspace/渠道文件.txt"),
                                "content": "超时也不该写入"}),
        Text("审批超时后的回答"),
    ]
    with FakeLLMServer(script) as fake:
        harness = GatewayHarness(tmp_path, fake, timeout=0.3)
        _wire_model(harness, hermes_env(fake))
        async with harness:
            await harness.adapter.emit(event("evt-task", "请写入文件"))
            await _wait_approval_request(harness.adapter)

            assert await wait_for(
                lambda: bool(sent_texts(harness.adapter, "审批超时，已拒绝执行。")),
                timeout=REPLY_WAIT,
            )
            assert await wait_for(
                lambda: any("审批超时后的回答" in item["content"]
                            for item in harness.adapter.sent),
                timeout=REPLY_WAIT,
            )
            assert not harness.target.exists()
            assert not next(iter(harness.runs.values())).approval_futures


@pytest.mark.asyncio
async def test_desktop_approval_wins_and_channel_gets_receipt(tmp_path, hermes_env):
    """桌面先批准时渠道收到「已在桌面批准」，写入照常执行。"""
    script = [
        ToolCall("write_file", {"path": str(tmp_path / "workspace/渠道文件.txt"),
                                "content": "桌面批准的写入"}),
        Text("写入完成"),
    ]
    with FakeLLMServer(script) as fake:
        harness = GatewayHarness(tmp_path, fake)
        _wire_model(harness, hermes_env(fake))
        async with harness:
            await harness.adapter.emit(event("evt-task", "请写入文件"))
            await _wait_approval_request(harness.adapter)

            run = next(iter(harness.runs.values()))
            approval_id = next(iter(run.approval_futures))
            run.approval_futures[approval_id].set_result("allow")  # desktop card wins

            assert await wait_for(
                lambda: bool(sent_texts(harness.adapter, "已在桌面批准。")),
                timeout=REPLY_WAIT,
            )
            assert await wait_for(
                lambda: any("写入完成" in item["content"] for item in harness.adapter.sent),
                timeout=REPLY_WAIT,
            )
            assert harness.target.read_text(encoding="utf-8") == "桌面批准的写入"
            # The late channel reply is answered from the dedup memory, not re-run.
            assert await harness.bridge.handle_approval_reply(event("evt-late", "拒绝"))
            assert await wait_for(
                lambda: any("审批已处理" in item["content"] for item in harness.adapter.sent),
            )


@pytest.mark.asyncio
async def test_gateway_default_mode_override_skips_channel_approval(tmp_path, hermes_env):
    """覆盖配置生效：read_only 网关默认下，写请求被静默拒绝，无审批往返。"""
    script = [Text("只读模式下不能写入")]
    with FakeLLMServer(script) as fake:
        harness = GatewayHarness(tmp_path, fake, default_permission_mode="read_only")
        _wire_model(harness, hermes_env(fake))
        async with harness:
            await harness.adapter.emit(event("evt-task", "请写入文件"))
            assert await wait_for(
                lambda: any("只读模式下不能写入" in item["content"]
                            for item in harness.adapter.sent),
                timeout=REPLY_WAIT,
            )
            assert harness.submitted[0]["permission_mode"] == "read_only"
            assert not sent_texts(harness.adapter, "需要审批"), "只读模式不应发起审批"
            assert not harness.target.exists()
