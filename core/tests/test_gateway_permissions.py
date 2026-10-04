"""Channel approval replies remain usable while the ordinary drain is busy."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from atlas.channels import ChannelManager
from atlas.channels.contract import MessageEvent
from atlas.config import AtlasConfig
from atlas.gateway_service import GatewayBridge
from atlas.persistent_agents.store import validate_profile_record
from atlas.server import RunState


def event(text: str, event_id: str = "task", **changes) -> MessageEvent:
    return MessageEvent(channel="fake", account="", event_id=event_id, chat_id="chat",
                        sender_id=changes.pop("sender_id", "owner"), text=text, **changes)


class RecordingManager(ChannelManager):
    def __init__(self, db_path: Path):
        super().__init__(db_path=db_path)
        self.sent: list[str] = []
        self.approval_sent = asyncio.Event()

    async def send(self, channel, chat_id, content, **kwargs):
        self.sent.append(content)
        if "需要审批" in content:
            self.approval_sent.set()


def bridge_fixture(tmp_path, *, timeout=1):
    manager = RecordingManager(tmp_path / "channels.sqlite")
    runs = {}
    output = tmp_path / "渠道文件.txt"
    submitted = []

    async def create_conversation(_key, _event):
        return "conversation"

    async def read_answer(_conversation):
        return "写入完成" if output.exists() else "已拒绝写入"

    async def submit(_connection, data):
        submitted.append(data)
        run = RunState(data["run_id"], data["conversation_id"], "fake")
        runs[run.run_id] = run

        async def execute():
            choice = await bridge.request_approval(run, "write-1", "写入渠道文件.txt")
            if choice == "allow":
                output.write_text("中文内容", encoding="utf-8")
            run.status = "completed"

        run.task = asyncio.create_task(execute())

    bridge = GatewayBridge(manager=manager, db_path=tmp_path / "channels.sqlite",
                           submit_run=submit, get_run=runs.get, read_answer=read_answer,
                           create_conversation=create_conversation,
                           approval_timeout_seconds=timeout)
    manager.set_dispatcher(bridge.dispatch)
    return manager, bridge, runs, output, submitted


async def close_fixture(manager, bridge):
    await manager.stop()
    bridge.sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, writes", [("允许", True), ("拒绝", False)])
async def test_channel_reply_unblocks_busy_drain_and_is_deduplicated(tmp_path, reply, writes):
    manager, bridge, runs, output, submitted = bridge_fixture(tmp_path)
    try:
        sink = manager._event_sink()
        await sink(event("请写入文件"))
        await asyncio.wait_for(manager.approval_sent.wait(), 1)
        assert manager._drain_task and not manager._drain_task.done()
        await sink(event(reply, "approval-reply"))
        await sink(event(reply, "approval-reply"))
        await asyncio.wait_for(manager._drain_task, 1)
        assert output.exists() is writes
        assert len(submitted) == 1
        assert submitted[0]["permission_mode"] == "ask_writes"
        assert manager.ingress.has_tombstone("fake", "", "approval-reply")
        assert manager.sent[-1] == ("写入完成" if writes else "已拒绝写入")
        assert not next(iter(runs.values())).approval_futures
        assert not bridge._origins and not bridge._approvals
        await sink(event("拒绝", "late-after-complete"))
        assert len(submitted) == 1
    finally:
        await close_fixture(manager, bridge)


@pytest.mark.asyncio
async def test_channel_timeout_denies_and_notifies(tmp_path):
    manager, bridge, runs, output, _ = bridge_fixture(tmp_path, timeout=0.02)
    try:
        await bridge.dispatch(event("请写入"), None)
        assert not output.exists()
        assert "审批超时，已拒绝执行。" in manager.sent
        assert not next(iter(runs.values())).approval_futures
    finally:
        await close_fixture(manager, bridge)


@pytest.mark.asyncio
async def test_desktop_first_wins_and_channel_receives_receipt(tmp_path):
    manager, bridge, runs, output, _ = bridge_fixture(tmp_path)
    task = asyncio.create_task(bridge.dispatch(event("请写入"), None))
    try:
        await asyncio.wait_for(manager.approval_sent.wait(), 1)
        run = next(iter(runs.values()))
        run.approval_futures["write-1"].set_result("allow")
        assert await bridge.handle_approval_reply(event("拒绝", "late"))
        await asyncio.wait_for(task, 1)
        assert output.exists()
        assert "已在桌面批准。" in manager.sent
    finally:
        await close_fixture(manager, bridge)


@pytest.mark.asyncio
async def test_other_sender_cannot_answer_origin_approval(tmp_path):
    manager, bridge, _, output, _ = bridge_fixture(tmp_path, timeout=0.03)
    task = asyncio.create_task(bridge.dispatch(event("请写入"), None))
    try:
        await asyncio.wait_for(manager.approval_sent.wait(), 1)
        assert not await bridge.handle_approval_reply(event("允许", "foreign", sender_id="other"))
        await asyncio.wait_for(task, 1)
        assert not output.exists()
    finally:
        await close_fixture(manager, bridge)


def test_permission_defaults_and_binding_agent_overrides(tmp_path):
    manager, bridge, _, _, _ = bridge_fixture(tmp_path)
    try:
        assert AtlasConfig().gateway_default_permission_mode == "ask_writes"
        assert AtlasConfig().local_execution_permission_mode == "full_access"
        configured = AtlasConfig({"gateway": {"default_permission_mode": "read_only"}})
        assert configured.gateway_default_permission_mode == "read_only"
        assert AtlasConfig().gateway_approval_timeout_seconds == 600
        bridge._get_agent = lambda _id: {"agent": {"permission_mode": "read_only"}}
        manager.set_bindings([{"agent_id": "ops", "channel": "fake", "account": "",
                               "peer_id": "chat", "permission_mode": "ask_each"}])
        assert bridge.permission_mode(event("task"), "ops") == "ask_each"
        manager.set_bindings([])
        assert bridge.permission_mode(event("task"), "ops") == "read_only"
        assert bridge.permission_mode(event("task"), None) == "ask_writes"
        profile = validate_profile_record({"name": "ops", "kind": "persistent", "agent": {
            "permission_mode": "read_only", "channels": [{"channel": "fake", "target": "chat",
                                                           "permission_mode": "ask_each"}],
        }})
        assert profile["agent"]["permission_mode"] == "read_only"
        assert profile["agent"]["channels"][0]["permission_mode"] == "ask_each"
    finally:
        manager.ingress.close()
        manager.delivery.close()
        bridge.sessions.close()
