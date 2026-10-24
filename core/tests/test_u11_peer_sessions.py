from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from atlas.agent.tool_catalog import model_facing_tools
from atlas.agent import peer_inbox
from atlas.memory import MemoryStore


def test_peer_proposal_tools_and_parent_link_persist(tmp_path: Path) -> None:
    fake_agent = SimpleNamespace(
        _mcp=None, _custom_tools=None, _local_execution=None, _computer_use=None,
        _web=None, _projects=None, _skills=None, _memory=None, _delegation=None,
    )
    names = {item["function"]["name"] for item in model_facing_tools(fake_agent)}
    assert {"propose_new_session", "read_session", "send_to_session"} <= names

    async def scenario() -> None:
        memory = MemoryStore(tmp_path / "peer.sqlite3")
        await memory.init()
        parent = await memory.create_conversation("主会话")
        await memory.update_conversation(parent, workspace=str(tmp_path))
        child = await memory.create_conversation("并行子会话")
        await memory.update_conversation(
            child, parent_conversation_id=parent, workspace=str(tmp_path),
        )
        persisted = await memory.get_conversation(child)
        assert persisted["parent_conversation_id"] == parent
        assert persisted["workspace"] == str(tmp_path)
        await memory.close()

    asyncio.run(scenario())


def test_peer_inbox_persists_messages_and_unread_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(peer_inbox, "_path", lambda: tmp_path / "peer-inbox.sqlite3")
    sent = peer_inbox.send_peer_message("parent", "child", "主会话", "请发我进度")
    assert sent["sender_conversation_id"] == "parent"
    unread = peer_inbox.list_peer_messages("child", unread_only=True)
    assert len(unread) == 1 and unread[0]["content"] == "请发我进度"
    assert peer_inbox.mark_peer_messages_read("child", [sent["id"]]) == 1
    assert peer_inbox.list_peer_messages("child", unread_only=True) == []
