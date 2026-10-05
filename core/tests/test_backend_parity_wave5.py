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
from atlas.telegram import TelegramService, TOKEN_KEY


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
async def test_atlas_subtask_inherits_read_only_and_cannot_redelegate(monkeypatch):
    from atlas.agent import AgentOrchestrator

    orchestrator = object.__new__(AgentOrchestrator)
    calls = []

    class FakeMemory:
        async def create_conversation(self, _title): return "child-conversation"
        async def delete_conversation(self, _conversation_id): return None

    async def fake_run(*args, **kwargs):
        calls.append({**kwargs, "_prompt": args[0] if args else kwargs.get("message", "")})
        yield {"type": "chunk", "content": "已完成。"}

    monkeypatch.setattr(orchestrator, "_memory", FakeMemory(), raising=False)
    monkeypatch.setattr(orchestrator, "run", fake_run)
    approval = []

    async def parent_approval(event_id, tool_name, arguments):
        approval.append((event_id, tool_name, arguments))
        return "allow"

    progress = []
    result = await orchestrator._run_atlas_subtask(
        goal="只读检查", context=None, cwd="C:/repo", subtask_id="subtask-a",
        atlas_options={"permission_mode": "read_only", "allowed_paths": ["C:/repo"],
                       "model": "parent-run-model",
                       "approval_callback": parent_approval},
        on_progress=lambda text: progress.append(text),
    )
    assert result["result"] == "已完成。"
    assert "delegate_task" in calls[0]["tool_deny"]
    assert "delegate_parallel" in calls[0]["tool_deny"]
    assert calls[0]["permission_mode"] == "read_only"
    assert calls[0]["model"] == "parent-run-model"
    assert calls[0]["allowed_paths"] == ["C:/repo"]
    # Worker mode: no user memory/skills/planning, and the prompt forbids asking the user.
    assert calls[0]["worker"] is True
    assert "不要向用户提问" in _args_prompt(calls)
    assert progress == ["已完成。"]
    assert await calls[0]["approval_callback"]("approval:x", "write_file", {"path": "x"}) == "allow"
    assert approval[0][2]["subtask_id"] == "subtask-a"


@pytest.mark.asyncio
async def test_atlas_delegation_cancellation_reaches_worker() -> None:
    service = DelegationService(host=None, hooks=Hooks())
    parent_cancel = asyncio.Event()
    started = asyncio.Event()

    async def runner(**kwargs):
        started.set()
        await kwargs["atlas_options"]["cancel_event"].wait()
        return {"status": "cancelled", "result": "已取消", "evidence": []}

    service.atlas_runner = runner
    task = asyncio.create_task(service.delegate_task(
        "长任务", atlas_options={"cancel_event": parent_cancel},
    ))
    await started.wait()
    parent_cancel.set()
    result = await task
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_conversation_extra_roots_persist_and_list(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "atlas.sqlite3")
    await memory.init()
    try:
        conversation_id = await memory.create_conversation("多目录")
        roots = [str((tmp_path / "workspace-a").resolve()), "ssh://host/home/project"]
        assert await memory.update_conversation(conversation_id, extra_roots=roots)
        assert (await memory.get_conversation(conversation_id))["extra_roots"] == roots
        assert await memory.update_conversation(conversation_id, source="telegram")
        assert (await memory.get_conversation(conversation_id))["source"] == "telegram"
        listed = await memory.list_conversations()
        listed_row = next(row for row in listed if row["id"] == conversation_id)
        assert listed_row["extra_roots"] == roots
        assert listed_row["source"] == "telegram"
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


def test_web_extract_rejects_dns_rebinding_between_preflight_and_connect(monkeypatch) -> None:
    import socket

    from atlas.tools.ssrf_transport import _resolved_connect_ips
    from atlas.tools.web_extract import _validate_url

    answers = iter(("93.184.216.34", "10.0.0.5"))

    def resolve(*_args, **_kwargs):
        address = next(answers)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert _validate_url("http://example.com/page", False)
    with pytest.raises(ValueError, match="private or local"):
        _resolved_connect_ips("example.com", 80, False)


@pytest.mark.asyncio
async def test_web_extract_caps_text_redirect_checks_and_reports_missing_captions(monkeypatch):
    import socket
    import httpx

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
    ])

    class RedirectClient:
        def __init__(self, **_kwargs):
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
            ))
        async def __aenter__(self): return self.client
        async def __aexit__(self, *_args): await self.client.aclose()

    with pytest.raises(ValueError, match="内网"):
        await extract_web("https://example.com/redirect", client_factory=RedirectClient)

    class LongClient:
        def __init__(self, **_kwargs):
            body = "<title>Long</title><article>" + ("正文内容" * 20_000) + "</article>"
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, text=body)
            ))
        async def __aenter__(self): return self.client
        async def __aexit__(self, *_args): await self.client.aclose()

    clipped = await extract_web("https://example.com/long", client_factory=LongClient)
    assert len(clipped["text"]) == 60_000
    assert clipped["truncated"] is True
    async def no_captions(_url): return "", "这个视频没有可读取的字幕。"
    monkeypatch.setattr("atlas.tools.web_extract._video_captions", no_captions)
    missing = await extract_web("https://www.youtube.com/watch?v=caption-missing")
    assert missing["kind"] == "video"
    assert "没有可读取的字幕" in missing["text"]


@pytest.mark.asyncio
async def test_bilibili_captions_are_fetched_through_ssrf_checked_requests(monkeypatch):
    import socket
    import httpx

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])

    def client_factory(**kwargs):
        def respond(request):
            if request.url.host == "www.bilibili.com":
                return httpx.Response(200, text=(
                    'window.__INITIAL_STATE__={"videoData":{"bvid":"BV-test","cid":4,'
                    '"subtitle":{"list":[{"lan":"zh-CN",'
                    '"subtitle_url":"//captions.bilibili.com/caption.json"}]}}};'
                ))
            return httpx.Response(200, json={"body": [
                {"content": "第一句字幕"}, {"content": "第二句字幕"},
            ]})
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    result = await extract_web(
        "https://www.bilibili.com/video/BV-test", client_factory=client_factory,
    )
    assert result["kind"] == "video"
    assert result["text"] == "第一句字幕\n第二句字幕"


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
    from tests.fakes.session_store import save_memory_fixture_message

    first = await save_memory_fixture_message(memory, conversation_id, "user", "first", {"run_id": "run-1"})
    await save_memory_fixture_message(memory, conversation_id, "assistant", "first done", {"run_id": "run-1"})
    checkpoint_one = checkpoint_store.create_checkpoint(workspace, ["result.txt"], run_id="run-1")
    checkpoint_one["created_at"] = "2025-01-01T00:00:00Z"
    (checkpoint_store.storage_dir / checkpoint_one["id"] / "manifest.json").write_text(
        json.dumps(checkpoint_one), encoding="utf-8",
    )
    target.write_text("round one", encoding="utf-8")
    await save_memory_fixture_message(memory, conversation_id, "user", "second", {"run_id": "run-2"})
    await save_memory_fixture_message(memory, conversation_id, "assistant", "second done", {"run_id": "run-2"})
    checkpoint_two = checkpoint_store.create_checkpoint(workspace, ["result.txt"], run_id="run-2")
    checkpoint_two["created_at"] = "2025-01-02T00:00:00Z"
    (checkpoint_store.storage_dir / checkpoint_two["id"] / "manifest.json").write_text(
        json.dumps(checkpoint_two), encoding="utf-8",
    )
    target.write_text("round two", encoding="utf-8")

    monkeypatch.setattr(server, "memory", memory)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(checkpoints=checkpoint_store))
    monkeypatch.setattr(server.runtime_mgr, "runs", {})
    # H5: rewind/redo/list live on the conversations router now; their store
    # and checkpoint seams are still resolved through atlas.server.
    from atlas.api.conversations_router import (
        list_conversation_rewinds,
        redo_conversation_rewind,
        rewind_conversation,
    )

    services = SimpleNamespace(memory=None)
    try:
        result = await rewind_conversation(
            services, conversation_id, {"message_id": first, "files": True},
        )
        assert result["removed_messages"] == 4
        assert target.read_text(encoding="utf-8") == "before"
        assert await memory.get_conversation_messages(conversation_id) == []

        await redo_conversation_rewind(services, conversation_id, result["rewind_id"])
        assert target.read_text(encoding="utf-8") == "round two"
        messages = await memory.get_conversation_messages(conversation_id)
        assert [item["content"] for item in messages] == [
            "first", "first done", "second", "second done",
        ]
        assert (await list_conversation_rewinds(services, conversation_id))[0]["redone"] is True
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


@pytest.mark.asyncio
async def test_telegram_auth_task_completion_and_token_secrecy(tmp_path):
    import httpx

    credentials = {}
    requests = []

    def client_factory(**kwargs):
        async def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"username": "atlas_bot"}})
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    submitted = []

    async def submit(text, user_id, _service):
        submitted.append((text, user_id))
        return {"summary": "任务完成\n\n改动文件数：2"}

    service = TelegramService(
        tmp_path / "telegram.json", credentials=DictCredentials(credentials),
        submit_task=submit, client_factory=client_factory,
    )
    settings = service.update_settings({
        "enabled": True, "allowed_user_ids": [42], "default_workspace": str(tmp_path),
        "bot_token": "secret-token",
    })
    assert settings["bot_token_set"] is True
    assert "secret-token" not in json.dumps(settings)
    assert "secret-token" not in (tmp_path / "telegram.json").read_text(encoding="utf-8")
    assert await service.test_token() == {"username": "atlas_bot"}
    assert "secret-token" in str(requests[0].url)

    await service.process_update({"update_id": 1, "message": {
        "from": {"id": 99}, "text": "不允许运行",
    }})
    await service.process_update({"update_id": 2, "message": {
        "from": {"id": 42}, "text": "整理项目报告",
    }})
    await asyncio.sleep(0.02)
    assert submitted == [("整理项目报告", 42)]
    sent = [request for request in requests if "/sendMessage" in str(request.url)]
    assert sent
    assert "任务完成" in sent[-1].content.decode("utf-8")
    assert "secret-token" not in repr(sent[-1].headers)


@pytest.mark.asyncio
async def test_telegram_approval_callback_is_bound_to_user_and_expires(tmp_path):
    credentials = DictCredentials({TOKEN_KEY: "secret"})
    sent = []

    class MockResponse:
        def raise_for_status(self): pass
        def json(self): return {"ok": True, "result": {}}

    class MockClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def post(self, _url, **kwargs):
            sent.append(kwargs["json"])
            return MockResponse()

    service = TelegramService(
        tmp_path / "telegram.json", credentials=credentials,
        client_factory=lambda **_kwargs: MockClient(),
    )
    service.update_settings({"allowed_user_ids": [42]})
    future = await service.request_approval(42, "run-1", "approval-1", "写文件")
    keyboard = sent[0]["reply_markup"]["inline_keyboard"][0]
    callback_id = keyboard[0]["callback_data"]
    assert len(callback_id) <= 10
    await service.process_update({"callback_query": {
        "id": "cb-1", "from": {"id": 99}, "data": callback_id,
    }})
    assert not future.done()
    await service.process_update({"callback_query": {
        "id": "cb-2", "from": {"id": 42}, "data": callback_id,
    }})
    assert future.result() == "allow"


def test_keyring_store_degrades_without_echoing_or_persisting_secret(monkeypatch):
    import builtins

    from atlas.telegram import KeyringCredentialStore

    original_import = builtins.__import__

    def without_keyring(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_keyring)
    store = KeyringCredentialStore()
    assert store.get(TOKEN_KEY) is None
    with pytest.raises(RuntimeError, match="系统凭据库"):
        store.set(TOKEN_KEY, "secret")


class DictCredentials:
    def __init__(self, values): self.values = values
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)



def _args_prompt(calls):
    return str(calls[0]["_prompt"])


@pytest.mark.asyncio
async def test_unknown_executor_name_runs_on_atlas() -> None:
    """Models sometimes pass executor "default"; that must not be treated as an external Agent."""
    from types import SimpleNamespace

    from atlas.agent.enrichment import DelegationService, HookBus

    service = DelegationService(SimpleNamespace(backends={}), HookBus())
    seen = []

    async def runner(**kwargs):
        seen.append(kwargs["goal"])
        return {"status": "completed", "result": "ok"}

    service.atlas_runner = runner
    result = await service.delegate_task("数行数", backend="default")
    assert result["backend"] == "atlas" and seen == ["数行数"]
