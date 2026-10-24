"""Interface-level verification for Atlas UI wave 5.

Set ATLAS_ROOT to an isolated scratch profile before running this check.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from atlas.api import conversations_router, diagnostics_router, runtime_ws_router, tools_router, workspace_router
from atlas.api.conversations_router import ConversationGoalCommandRequest, ConversationUiMetadataRequest
from atlas.api.tools_router import update_terminal_buffer
from atlas.kernel.tools import kernel_tool_schemas, read_terminal_buffers
from atlas.tools.mcp_client import MCPClient


def check_interrupt_queue_and_read_terminal() -> None:
    ws_paths = {getattr(route, "path", "") for route in runtime_ws_router.router.routes}
    assert any("ws" in path.lower() for path in ws_paths)
    assert "run.cancel" in Path("frontend/src/renderer/store/useAtlasStore.ts").read_text(encoding="utf-8")
    queue_ui = Path("frontend/src/renderer/components/ConversationQueuePanel.tsx").read_text(encoding="utf-8")
    assert all(text in queue_ui for text in ("待发送的消息", "立即发送这条消息", "删除这条待发消息"))
    schemas = {item["function"]["name"]: item["function"] for item in kernel_tool_schemas(include_workflow=False)}
    assert "read_terminal" in schemas
    buffers = {"conversation:terminal-1": "one\ntwo\nthree", "other:terminal-1": "x"}
    assert read_terminal_buffers(buffers, "conversation:terminal-1", 2)[0]["text"] == "two\nthree"
    assert read_terminal_buffers(buffers, "terminal-1", 1)[0]["text"] == "three"
    assert "untrusted terminal data" in schemas["read_terminal"]["description"]
    assert ws_paths


async def check_metadata_and_migration() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u5-meta-") as temp:
        with patch("atlas.config.DATA_ROOT", Path(temp)):
            await conversations_router.put_conversation_ui_metadata(ConversationUiMetadataRequest(metadata={
                "atlas.sidebar.labels": {"c1": "blue"}, "atlas.sidebar.custom-groups": [{"id": "g1"}],
                "atlas.sidebar.order": ["c1"], "atlas.sidebar.unread": ["c1"],
            }))
            saved = await conversations_router.get_conversation_ui_metadata()
        metadata = saved["metadata"]
        assert metadata["atlas.sidebar.labels"]["c1"] == "blue"
        assert metadata["atlas.sidebar.custom-groups"][0]["id"] == "g1"
        assert metadata["atlas.sidebar.order"] == ["c1"] and metadata["atlas.sidebar.unread"] == ["c1"]


async def check_workspace_search() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u5-search-") as temp:
        root = Path(temp)
        (root / ".gitignore").write_text("ignored-keep.ts\n", encoding="utf-8")
        (root / "a-keep.ts").write_text("", encoding="utf-8")
        (root / "b-keep.ts").write_text("", encoding="utf-8")
        (root / "ignored-keep.ts").write_text("", encoding="utf-8")
        with patch.object(workspace_router._server(), "_workspace_path", return_value=(root, root)):
            result = await workspace_router.workspace_search(SimpleNamespace(), str(root), "keep", limit=1)
            assert len(result["files"]) == 1 and result["files"][0]["name"] == "a-keep.ts"
            try:
                await workspace_router.workspace_search(SimpleNamespace(), str(root), "keep", limit=201)
            except Exception as exc:
                assert getattr(exc, "status_code", None) == 422
            else:
                raise AssertionError("workspace search accepted a limit above the cap")


async def check_message_search_and_goal_controls() -> None:
    memory = SimpleNamespace(get_conversation=lambda _id: asyncio.sleep(0, result={"id": "u5"}))
    with tempfile.TemporaryDirectory(prefix="atlas-u5-session-") as temp:
        services = SimpleNamespace(memory=memory)
        with patch("atlas.config.DATA_ROOT", Path(temp)), patch(
            "atlas.engine.session_sync.read_session_all_messages", return_value=[
                {"id": "m1", "role": "user", "content": "needle in transcript"},
                {"id": "m2", "role": "assistant", "content": "response"},
            ],
        ):
            matches = await conversations_router.search_conversation_messages(services, "u5", "needle", 10)
            assert matches["results"][0]["id"] == "m1" and "needle" in matches["results"][0]["snippet"]
        with patch("atlas.config.DATA_ROOT", Path(temp)):
            created = await conversations_router.run_conversation_goal_command(services, "u5", ConversationGoalCommandRequest(command="Finish the U5 check"))
            assert created["goal"]["text"] == "Finish the U5 check"
            paused = await conversations_router.run_conversation_goal_command(services, "u5", ConversationGoalCommandRequest(command="pause"))
            assert paused["goal"]["status"] == "paused"
            resumed = await conversations_router.run_conversation_goal_command(services, "u5", ConversationGoalCommandRequest(command="resume"))
            assert resumed["goal"]["status"] == "active"
            cleared = await conversations_router.run_conversation_goal_command(services, "u5", ConversationGoalCommandRequest(command="clear"))
            assert cleared["goal"] is None


async def check_file_restore_snapshot() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u5-restore-") as temp:
        root = Path(temp)
        target = root / "sample.txt"
        target.write_text("current", encoding="utf-8")

        class Checkpoints:
            def create_checkpoint(self, base: Path, paths: list[str], *, run_id: str) -> dict[str, str]:
                assert target.read_text(encoding="utf-8") == "current"
                return {"id": "checkpoint-before-restore"}

        services = SimpleNamespace(orchestrator=SimpleNamespace(checkpoints=Checkpoints()))
        body = json.dumps({"root": str(root), "path": "sample.txt", "version": "git:" + "a" * 40}).encode()

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request({"type": "http", "method": "POST", "headers": []}, receive)
        with patch.object(workspace_router._server(), "_workspace_path", return_value=(root, target)), patch(
            "atlas.api.workspace_router._history_bytes", new=AsyncMock(return_value=(b"previous", True)),
        ):
            result = await workspace_router.restore_workspace_history(services, request)
        assert result["restored"] and result["checkpoint_id"] == "checkpoint-before-restore"
        assert target.read_text(encoding="utf-8") == "previous"


def check_mcp_and_ui_surfaces() -> None:
    client = MCPClient()
    client._configured_configs = {"filesystem": SimpleNamespace(name="filesystem", enabled=True, transport="stdio", command="python")}
    client._server_status["filesystem"] = {"state": "connecting", "blocking_reason": None, "tool_discovery": "pending"}
    status = client.get_runtime_status()
    server = next(item for item in status["servers"] if item["name"] == "filesystem")
    assert server["state"] == "connecting" and server["tool_count"] == 0
    ui = Path("frontend/src/renderer/components/settings/McpServersPanel.tsx").read_text(encoding="utf-8")
    assert "setInterval" in ui and "连接中" in ui and "blocking_reason" in ui
    palette = Path("frontend/src/renderer/components/Palette.tsx").read_text(encoding="utf-8")
    assert "runAlt" in palette and "altKey" in palette
    sidebar = Path("frontend/src/renderer/shell/Sidebar.tsx").read_text(encoding="utf-8")
    assert "正文搜索结果" in sidebar and "onJumpMessage" in sidebar
    files = Path("frontend/src/renderer/shell/panels/FilesPanel.tsx").read_text(encoding="utf-8")
    assert "本会话访问的文件" in files and "查看 diff" in files
    assert any(getattr(route, "path", "") == "/api/diagnostics" for route in diagnostics_router.router.routes)
    assert any(getattr(route, "path", "") == "/api/workspace/history/restore" for route in workspace_router.router.routes)
    assert any(getattr(route, "path", "") == "/api/terminal/buffer" for route in tools_router.router.routes)
    assert ConversationUiMetadataRequest(metadata={"migrated": True}).metadata["migrated"]


async def main() -> None:
    check_interrupt_queue_and_read_terminal()
    await update_terminal_buffer({"tab_id": "u5:terminal-1", "text": "user command\nuser output"})
    assert read_terminal_buffers(tools_router._terminal_buffers, "u5:terminal-1", 2)[0]["text"] == "user command\nuser output"
    await check_metadata_and_migration()
    await check_workspace_search()
    await check_message_search_and_goal_controls()
    await check_file_restore_snapshot()
    check_mcp_and_ui_surfaces()
    print("U5 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
