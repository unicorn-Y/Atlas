from __future__ import annotations

import asyncio

import pytest

from atlas.agent.enrichment import DelegationService
from atlas.memory import MemoryStore


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
