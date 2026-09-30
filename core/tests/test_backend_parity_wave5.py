from __future__ import annotations

import asyncio

import pytest

from atlas.agent.enrichment import DelegationService
from atlas.memory import MemoryStore
from atlas.projects import ProjectStore
from atlas.tools.web_extract import extract_web


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
