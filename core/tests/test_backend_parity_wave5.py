from __future__ import annotations

import asyncio
import json

import pytest

from atlas.agent.enrichment import DelegationService
from atlas.memory import MemoryStore
from atlas.projects import ProjectStore
from atlas.tools.web_extract import extract_web
from atlas.tools.custom_tools import CustomToolStore
from atlas.agent.checkpoints import ShadowGitCheckpointStore


class Hooks:
    async def emit(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_atlas_delegation_is_default_and_uses_local_runner() -> None:
    service = DelegationService(host=None, hooks=Hooks())
    calls = []

    async def runner(**kwargs):
        calls.append(kwargs)
        await kwargs["on_progress"]("读取 hello.txt")
        return {"status": "completed", "result": "找到答案", "evidence": []}

    service.atlas_runner = runner
    progress = []
    result = await service.delegate_task(
        "检查文件", cwd="C:/repo", on_progress=lambda *_args: progress.append(_args),
    )

    assert result["backend"] == "atlas"
    assert result["result"] == "找到答案"
    assert calls[0]["cwd"] == "C:/repo"
    assert progress and "读取 hello.txt" in progress[0][1]


@pytest.mark.asyncio
async def test_parallel_atlas_workers_continue_after_one_failure() -> None:
    service = DelegationService(host=None, hooks=Hooks())
    calls = []

    async def runner(**kwargs):
        calls.append(kwargs)
        if kwargs["goal"] == "fail":
            raise RuntimeError("模拟失败")
        return {"status": "completed", "result": kwargs["goal"], "evidence": []}

    service.atlas_runner = runner
    result = await service.delegate_parallel([
        {"title": "甲", "goal": "完成甲"},
        {"title": "乙", "goal": "fail"},
        {"title": "丙", "goal": "完成丙"},
    ])

    assert [item["status"] for item in result["results"]] == [
        "completed", "failed", "completed",
    ]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_conversation_extra_roots_persist_and_list(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "atlas.sqlite3")
    await memory.init()
    try:
        conversation_id = await memory.create_conversation("多目录")
        roots = [str((tmp_path / "workspace-a").resolve()), "ssh://host/home/project"]
        assert await memory.update_conversation(conversation_id, extra_roots=roots)
        assert (await memory.get_conversation(conversation_id))["extra_roots"] == roots
        listed = await memory.list_conversations()
        assert next(row for row in listed if row["id"] == conversation_id)["extra_roots"] == roots
    finally:
        await memory.close()


@pytest.mark.asyncio
async def test_project_sources_index_search_delete_and_instructions(tmp_path) -> None:
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    await projects.init()
    try:
        project = await projects.create_project("资料项目")
        source = await projects.add_source(
            project.project_id, "note", title="部署约定", text="deploy_marker_abc 用于验证搜索。",
        )
        assert source["kind"] == "note"
        assert await projects.search_sources(project.project_id, "deploy_marker_abc")
        assert await projects.set_source_instructions(project.project_id, "先检查部署约定。")
        assert (await projects.get_sources(project.project_id))["instructions"] == "先检查部署约定。"
        assert await projects.delete_source(project.project_id, source["id"])
        assert not await projects.search_sources(project.project_id, "deploy_marker_abc")
        with pytest.raises(ValueError):
            await projects.set_source_instructions(project.project_id, "x" * 8001)
    finally:
        await projects.close()


@pytest.mark.asyncio
async def test_web_extract_strips_chrome_and_rejects_private_addresses(monkeypatch) -> None:
    import socket
    import httpx

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
    ])

    class MockClient:
        def __init__(self, **_kwargs):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="<html><title>Page</title><nav>noise</nav><p>Body words</p></html>")
            ))
        async def __aenter__(self):
            return self.client
        async def __aexit__(self, *_args):
            await self.client.aclose()

    result = await extract_web("https://example.com/", client_factory=MockClient)
    assert result["title"] == "Page"
    assert "Body words" in result["text"]
    assert "noise" not in result["text"]
    with pytest.raises(ValueError, match="内网"):
        await extract_web("http://10.0.0.1/private")


@pytest.mark.asyncio
async def test_rewind_restores_messages_and_files_then_redo_restores_both(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from atlas import server

    memory = MemoryStore(tmp_path / "memory.sqlite3")
    await memory.init()
    checkpoint_store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "result.txt"
    target.write_text("before", encoding="utf-8")
    conversation_id = await memory.create_conversation("rewind")
    first = await memory.save_message(conversation_id, "user", "first", {"run_id": "run-1"})
    await memory.save_message(conversation_id, "assistant", "first done", {"run_id": "run-1"})
    checkpoint_one = checkpoint_store.create_checkpoint(workspace, ["result.txt"], run_id="run-1")
    checkpoint_one["created_at"] = "2025-01-01T00:00:00Z"
    (checkpoint_store.storage_dir / checkpoint_one["id"] / "manifest.json").write_text(
        json.dumps(checkpoint_one), encoding="utf-8",
    )
    target.write_text("round one", encoding="utf-8")
    await memory.save_message(conversation_id, "user", "second", {"run_id": "run-2"})
    await memory.save_message(conversation_id, "assistant", "second done", {"run_id": "run-2"})
    checkpoint_two = checkpoint_store.create_checkpoint(workspace, ["result.txt"], run_id="run-2")
    checkpoint_two["created_at"] = "2025-01-02T00:00:00Z"
    (checkpoint_store.storage_dir / checkpoint_two["id"] / "manifest.json").write_text(
        json.dumps(checkpoint_two), encoding="utf-8",
    )
    target.write_text("round two", encoding="utf-8")

    monkeypatch.setattr(server, "memory", memory)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(checkpoints=checkpoint_store))
    monkeypatch.setattr(server.runtime_mgr, "runs", {})
    try:
        result = await server.rewind_conversation(
            conversation_id, {"message_id": first, "files": True},
        )
        assert result["removed_messages"] == 4
        assert target.read_text(encoding="utf-8") == "before"
        assert await memory.get_conversation_messages(conversation_id) == []

        await server.redo_conversation_rewind(conversation_id, result["rewind_id"])
        assert target.read_text(encoding="utf-8") == "round two"
        messages = await memory.get_conversation_messages(conversation_id)
        assert [item["content"] for item in messages] == [
            "first", "first done", "second", "second done",
        ]
        assert (await server.list_conversation_rewinds(conversation_id))[0]["redone"] is True
    finally:
        await memory.close()


@pytest.mark.asyncio
async def test_custom_tools_create_execute_disable_validate_and_timeout(tmp_path):
    store = CustomToolStore(tmp_path / "tools")
    tool = store.create({
        "id": "echo-json", "name": "回显", "description": "回传输入内容",
        "command": [__import__("sys").executable, "echo.py"],
        "input_schema": {"type": "object", "properties": {"value": {"type": "string"}},
                         "required": ["value"], "additionalProperties": False},
        "script_name": "echo.py",
        "script": "import json,sys; print(json.dumps(json.load(sys.stdin)))",
    })
    result = await store.execute(tool["id"], {"value": "ok"})
    assert result["result"] == {"value": "ok"}
    store.update(tool["id"], {"enabled": False})
    assert store.model_tools() == []
    with pytest.raises(ValueError, match="停用"):
        await store.execute(tool["id"], {"value": "ok"})
    with pytest.raises(ValueError, match="编号"):
        store.create({"id": "../bad"})

    store.create({
        "id": "slow-run", "name": "慢任务", "description": "超时检查",
        "command": [__import__("sys").executable, "slow.py"], "timeout_s": 0.1,
        "input_schema": {"type": "object"}, "script_name": "slow.py",
        "script": "import time; time.sleep(5)",
    })
    timed_out = await store.execute("slow-run", {})
    assert timed_out["is_error"] is True
    assert "超时" in timed_out["error"]
