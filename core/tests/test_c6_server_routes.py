"""C6 server integration tests (W6): /init 路由、消息最新分页、LSP 状态/诊断路由、
/review 拦截，以及新增队列事件（lsp.diagnostics / review.findings）的 wire 透传。

httpx ASGITransport 风格，与 test_c4_wiring.py 一致；所有路径都在 tmp_path 与
conftest 临时目录内。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import ModuleType, SimpleNamespace

from httpx import ASGITransport, AsyncClient
import pytest

from atlas import server
from atlas.lsp.types import Diagnostic
from atlas.memory import MemoryStore
from atlas.task_artifacts import TomlRecordStore

_init_routes_registered = False


def _ensure_init_routes() -> None:
    """镜像 lifespan 启动注册：ASGITransport 不跑 lifespan，测试里手动挂一次。"""
    global _init_routes_registered
    if not _init_routes_registered:
        from atlas.commands.init import register_init_routes

        register_init_routes(server.app)
        _init_routes_registered = True


def _install_fake_review_engine(monkeypatch, *, collect_error: str | None = None) -> dict:
    """契约一致的 atlas.review.engine 替身（W3 模块未落地时也能验证 W6 拦截逻辑）。

    通过 monkeypatch.setitem(sys.modules, ...) 注入，不往磁盘写任何模块。
    """
    calls: dict = {}
    engine = ModuleType("atlas.review.engine")

    def is_review_request(content: str) -> bool:
        return content.lstrip().startswith("/review")

    def parse_scope(content: str) -> dict:
        return {"scope": "working_tree", "ref": None,
                "user_prompt": content[len("/review"):].strip()}

    def collect_diff(workspace: str, scope: dict) -> dict:
        calls["collect_diff"] = (workspace, dict(scope))
        if collect_error:
            raise ValueError(collect_error)
        return {"diff_text": "--- a/src/app.py\n+++ b/src/app.py\n+boom\n",
                "stat": "src/app.py | 1 +", "scope_label": "当前未提交改动",
                "truncated": False}

    def build_dispatch_prompt(scope_result: dict, user_prompt: str) -> str:
        calls["build_dispatch_prompt"] = (dict(scope_result), user_prompt)
        return f"[审查派发] {scope_result['scope_label']}：{user_prompt}"

    engine.is_review_request = is_review_request
    engine.parse_scope = parse_scope
    engine.collect_diff = collect_diff
    engine.build_dispatch_prompt = build_dispatch_prompt
    monkeypatch.setitem(sys.modules, "atlas.review.engine", engine)
    return calls


def _patch_run_env(monkeypatch, tmp_path: Path, *, with_memory: MemoryStore | None = None):
    """_handle_run_start 的最小环境：可捕获 _execute_run 入参的 runtime_mgr。"""
    runtime = server.RuntimeManager()
    sent: list[dict] = []

    async def spy_send(conn_id: str, envelope: dict) -> None:
        sent.append(envelope)

    async def spy_send_run(run, envelope: dict, fallback_conn_id: str) -> None:
        sent.append(envelope)

    monkeypatch.setattr(runtime, "send", spy_send)
    monkeypatch.setattr(runtime, "send_run", spy_send_run)
    monkeypatch.setattr(server, "memory", with_memory)
    monkeypatch.setattr(server, "runtime_mgr", runtime)
    monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="model"))
    monkeypatch.setattr(server, "_task_store", lambda kind: TomlRecordStore(tmp_path / "data", kind))
    return runtime, sent


# ---------------------------------------------------------------------------
# /init 路由（W2 已交付：atlas/commands/init.py 在盘上）
# ---------------------------------------------------------------------------

async def test_init_preview_and_apply_routes(tmp_path: Path) -> None:
    _ensure_init_routes()
    workspace = tmp_path / "proj"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.pytest.ini_options]\naddopts = "-q"\n',
        encoding="utf-8",
    )
    (workspace / "app.py").write_text("print('demo')\n", encoding="utf-8")
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post("/api/init/preview", json={"workspace": str(workspace)})
        body = preview.json()
        # W2 语义：preview 对"文件不存在"给 ""，而 apply 用 None 表示"应当不存在"。
        expected_existing = body["existing_content"] if body["exists"] else None
        applied = await client.post("/api/init/apply", json={
            "workspace": str(workspace), "content": body["proposed_content"],
            "expected_existing": expected_existing,
        })
        conflict = await client.post("/api/init/apply", json={
            "workspace": str(workspace), "content": body["proposed_content"],
            "expected_existing": "drifted content",
        })

    assert preview.status_code == 200
    assert set(body) >= {"path", "exists", "existing_content", "proposed_content", "scan"}
    assert Path(body["path"]).parent == workspace  # path 指向提案文件 AGENTS.md
    assert body["scan"]["languages"], "扫描应识别出 Python 项目"
    assert "AGENTS.md" in body["proposed_content"]
    assert applied.status_code == 200
    assert applied.json()["written"] is True
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == body["proposed_content"]
    assert conflict.status_code == 422  # expected_existing 漂移 → 拒绝写入


async def test_init_preview_rejects_missing_workspace(tmp_path: Path) -> None:
    _ensure_init_routes()
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/init/preview", json={"workspace": str(tmp_path / "nope")},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]  # 中文错误信息


# ---------------------------------------------------------------------------
# 消息分页：默认返回最新 limit 条（升序），before_id 取更早一页
# ---------------------------------------------------------------------------

async def test_messages_pagination_returns_newest_window(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conv = await store.create_conversation("pager")
    ids = [await store.save_message(conv, "user", f"m{i}") for i in range(250)]
    monkeypatch.setattr(server, "memory", store)

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        default = await client.get(f"/api/conversations/{conv}/messages")
        before = await client.get(f"/api/conversations/{conv}/messages",
                                  params={"before_id": ids[150]})
        window = await client.get(f"/api/conversations/{conv}/messages",
                                  params={"limit": 40})
        missing = await client.get("/api/conversations/nope/messages")

    assert default.status_code == 200
    body = default.json()
    assert isinstance(body, list) and len(body) == 100  # 响应仍是纯数组
    assert [m["content"] for m in body] == [f"m{i}" for i in range(150, 250)]
    assert body[0]["id"] == ids[150]
    assert set(body[0]) >= {"id", "role", "content", "metadata", "created_at"}
    assert before.status_code == 200
    assert [m["content"] for m in before.json()] == [f"m{i}" for i in range(50, 150)]
    assert [m["content"] for m in window.json()] == [f"m{i}" for i in range(210, 250)]
    assert missing.status_code == 404
    await store.close()


async def test_messages_before_id_unknown_returns_empty(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conv = await store.create_conversation("pager2")
    await store.save_message(conv, "user", "only")
    monkeypatch.setattr(server, "memory", store)
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/conversations/{conv}/messages",
                                params={"before_id": "no-such-id"})
    assert resp.status_code == 200
    assert resp.json() == []
    await store.close()


# ---------------------------------------------------------------------------
# LSP 状态路由（探测打到真实 PATH，只断言响应结构）
# ---------------------------------------------------------------------------

async def test_lsp_status_route_shape() -> None:
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/lsp/status")
        with_ws = await client.get("/api/lsp/status", params={"workspace": str(Path.cwd())})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["servers"], list) and body["servers"]
    for entry in body["servers"]:
        assert set(entry) == {"id", "languages", "available", "hint"}
        assert isinstance(entry["id"], str) and entry["id"]
        assert isinstance(entry["languages"], list)
        assert isinstance(entry["available"], bool)
        assert isinstance(entry["hint"], str)
        assert entry["available"] or entry["hint"], "不可用的服务必须带中文安装提示"
    assert with_ws.status_code == 200


# ---------------------------------------------------------------------------
# /review 拦截（atlas.review.engine 由替身按契约提供）
# ---------------------------------------------------------------------------

async def test_review_intercept_rewrites_run(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    calls = _install_fake_review_engine(monkeypatch)
    runtime, _sent = _patch_run_env(monkeypatch, tmp_path)

    captured: dict = {}

    async def no_run(conn_id, run, content, model_id, **kwargs):
        captured.update(run=run, content=content)

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "review-run", "content": "/review 重点看回归风险",
        "workspace": str(workspace), "profile_id": "architect",
        "tool_allow": ["write_file"], "tool_deny": ["read_file"],
    })
    await runtime.runs["review-run"].task

    assert calls["collect_diff"][0] == str(workspace)
    assert calls["build_dispatch_prompt"][0]["scope_label"] == "当前未提交改动"
    assert calls["build_dispatch_prompt"][1] == "重点看回归风险"
    assert captured["content"] == "[审查派发] 当前未提交改动：重点看回归风险"
    run = captured["run"]
    # 集成决策 D1（v2）：父运行也是 read_only——只读门禁按显式 tool_allow 放行
    # delegate/submit/review_command，写操作结构性拒绝且不弹审批卡。
    assert run.profile_id is None
    assert run.tool_allow == ["delegate_task", "submit_findings", "local_file", "review_command",
                              "coding.repo_map", "coding.ast_grep.run", "read_office"]
    assert run.tool_deny == []
    assert run.read_only is True
    assert run.permission_mode == "read_only"
    assert run.user_input == captured["content"]
    assert run.workspace == str(workspace)


async def test_review_intercept_rejects_non_git_workspace(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _install_fake_review_engine(
        monkeypatch, collect_error="当前目录不是 git 仓库，无法读取改动。")
    runtime, sent = _patch_run_env(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_execute_run", lambda *a, **k: None)

    await server._handle_run_start("test", {
        "run_id": "review-nogit", "content": "/review", "workspace": str(plain),
    })

    assert "review-nogit" not in runtime.runs
    failed = [env for env in sent if env["event"] == "run.failed"]
    assert failed and "不是 git 仓库" in failed[-1]["data"]["detail"]


async def test_review_intercept_rejects_ssh_workspace(tmp_path: Path, monkeypatch) -> None:
    _install_fake_review_engine(monkeypatch)
    runtime, sent = _patch_run_env(monkeypatch, tmp_path)

    await server._handle_run_start("test", {
        "run_id": "review-ssh", "content": "/review", "workspace": "ssh://host/srv",
    })

    assert "review-ssh" not in runtime.runs
    failed = [env for env in sent if env["event"] == "run.failed"]
    assert failed and "本机" in failed[-1]["data"]["detail"]


async def test_review_intercept_rejects_missing_workspace(tmp_path: Path, monkeypatch) -> None:
    _install_fake_review_engine(monkeypatch)
    runtime, sent = _patch_run_env(monkeypatch, tmp_path)

    await server._handle_run_start("test", {"run_id": "review-nows", "content": "/review"})

    assert "review-nows" not in runtime.runs
    failed = [env for env in sent if env["event"] == "run.failed"]
    assert failed and "本机" in failed[-1]["data"]["detail"]


async def test_review_intercept_uses_conversation_workspace(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conv = await store.create_conversation("review conv")
    repo = tmp_path / "repo"
    repo.mkdir()
    await store.update_conversation(conv, workspace=str(repo))
    calls = _install_fake_review_engine(monkeypatch)
    runtime, _sent = _patch_run_env(monkeypatch, tmp_path, with_memory=store)

    async def no_run(conn_id, run, content, model_id, **kwargs):
        pass

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "review-conv", "conversation_id": conv, "content": "/review",
    })
    await runtime.runs["review-conv"].task

    assert calls["collect_diff"][0] == str(repo)


async def test_review_intercept_leaves_normal_message(tmp_path: Path, monkeypatch) -> None:
    calls = _install_fake_review_engine(monkeypatch)
    runtime, _sent = _patch_run_env(monkeypatch, tmp_path)

    captured: dict = {}

    async def no_run(conn_id, run, content, model_id, **kwargs):
        captured.update(run=run, content=content)

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "plain-run", "content": "普通消息，不是审查指令",
        "workspace": str(tmp_path),
    })
    await runtime.runs["plain-run"].task

    assert "collect_diff" not in calls
    assert captured["content"] == "普通消息，不是审查指令"
    assert captured["run"].profile_id is None
    assert captured["run"].tool_allow is None


async def test_review_intercept_degrades_when_module_missing(tmp_path: Path, monkeypatch) -> None:
    # W3 的 atlas.review.engine 未落地时（sys.modules 置 None 使 import 必然失败），
    # /review 正文按普通消息放行，run.start 绝不能被拖垮。
    monkeypatch.setitem(sys.modules, "atlas.review.engine", None)
    runtime, _sent = _patch_run_env(monkeypatch, tmp_path)

    captured: dict = {}

    async def no_run(conn_id, run, content, model_id, **kwargs):
        captured.update(run=run, content=content)

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "missing-run", "content": "/review", "workspace": str(tmp_path),
    })
    await runtime.runs["missing-run"].task

    assert "missing-run" in runtime.runs
    assert captured["content"] == "/review"
    assert captured["run"].profile_id is None


async def test_review_intercept_with_real_engine(tmp_path: Path, monkeypatch) -> None:
    """W3 模块已交付：用真实 atlas.review.engine 走通拦截（真实 git diff）。"""
    pytest.importorskip("atlas.review.engine")
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "atlas-test@example.invalid")
    git("config", "user.name", "Atlas Test")
    (repo / "app.py").write_text("print('base')\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "initial")
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    runtime, _sent = _patch_run_env(monkeypatch, tmp_path)
    captured: dict = {}

    async def no_run(conn_id, run, content, model_id, **kwargs):
        captured.update(run=run, content=content)

    monkeypatch.setattr(server, "_execute_run", no_run)
    await server._handle_run_start("test", {
        "run_id": "review-real", "content": "/review 重点看回归",
        "workspace": str(repo),
    })
    await runtime.runs["review-real"].task

    assert "app.py" in captured["content"]  # 真实 diff 进入了派发提示词
    assert "delegate_task" in captured["content"] and "submit_findings" in captured["content"]
    run = captured["run"]
    assert run.profile_id is None
    assert run.permission_mode == "read_only"
    assert run.read_only is True
    assert "review_command" in run.tool_allow


# ---------------------------------------------------------------------------
# 诊断路由（_run_changes 与 atlas.lsp.diagnostics_for 均打替身）
# ---------------------------------------------------------------------------

async def test_run_diagnostics_route_shape(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    (workspace / "src").mkdir(parents=True)
    monkeypatch.setattr(server, "_run_changes", lambda run_id, workspace_root=None: {
        "run_id": run_id, "files": [
            {"path": "src/app.py", "workspace": str(workspace), "status": "modified",
             "additions": 1, "deletions": 0, "diff": ""},
            {"path": "README.md", "workspace": str(workspace), "status": "added",
             "additions": 2, "deletions": 0, "diff": ""},
        ],
    })

    probed: list[str] = []

    def fake_diagnostics_for(path: str, *, delta: bool = False) -> list[Diagnostic]:
        probed.append(path)
        if path.endswith("app.py"):
            return [Diagnostic(file=path, line=12, column=5, severity="error",
                               code="T999", message="boom", source="test")]
        return []

    monkeypatch.setattr("atlas.lsp.diagnostics_for", fake_diagnostics_for)
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/runs/run-1/diagnostics")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-1"
    assert [(f["path"], f["count"]) for f in body["files"]] == [
        ("src/app.py", 1), ("README.md", 0),  # count 0 也返回
    ]
    assert probed[0] == str(workspace / "src" / "app.py")
    assert body["files"][0]["diagnostics"] == [
        {"line": 12, "column": 5, "severity": "error", "code": "T999", "message": "boom"},
    ]
    assert body["files"][1]["diagnostics"] == []


async def test_run_diagnostics_skips_ssh_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "_run_changes", lambda run_id, workspace_root=None: {
        "run_id": run_id, "files": [
            {"path": "a.py", "workspace": "/x", "status": "modified",
             "additions": 0, "deletions": 0, "diff": ""},
        ],
    })
    runtime = server.RuntimeManager()
    run = server.RunState("ssh-run", "conv", "model")
    run.workspace = "ssh://host/srv"
    runtime.runs["ssh-run"] = run
    monkeypatch.setattr(server, "runtime_mgr", runtime)
    probed: list[str] = []

    def fake_diagnostics_for(path: str, *, delta: bool = False) -> list[Diagnostic]:
        probed.append(path)
        return []

    monkeypatch.setattr("atlas.lsp.diagnostics_for", fake_diagnostics_for)
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/runs/ssh-run/diagnostics")

    assert resp.status_code == 200
    assert resp.json() == {"run_id": "ssh-run", "files": []}
    assert probed == []


# ---------------------------------------------------------------------------
# 队列事件 → wire 事件映射（_execute_run 的透传分支）
# ---------------------------------------------------------------------------

async def test_new_queue_events_reach_wire_unchanged(tmp_path: Path, monkeypatch) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.init()
    conv = await store.create_conversation("events")

    class Orchestrator:
        async def run(self, **kwargs):
            yield {"type": "lsp.diagnostics",
                   "data": {"path": "a.py", "count": 2, "diagnostics": []}}
            yield {"type": "review.findings", "data": {"scope": "working_tree", "findings": []}}
            yield {"type": "unknown.c6.event", "data": {"secret": True}}  # 维持现状：不上 wire
            yield {"type": "chunk", "content": "answer"}
            yield {"type": "done"}

    async def _noop_hook(event_name, payload, cwd=None, emit=None):
        return []

    monkeypatch.setattr(server, "memory", store)
    monkeypatch.setattr(server, "orchestrator", Orchestrator())
    monkeypatch.setattr(server, "_hook_store",
                        lambda: SimpleNamespace(execute=_noop_hook))
    runtime = server.RuntimeManager()
    sent: list[dict] = []

    async def spy_send_run(run, envelope: dict, fallback_conn_id: str) -> None:
        sent.append(envelope)

    monkeypatch.setattr(runtime, "send_run", spy_send_run)
    monkeypatch.setattr(server, "runtime_mgr", runtime)

    run = server.RunState("map-run", conv, "model")
    await server._execute_run("test", run, "go", "model")

    events = [env["event"] for env in sent]
    assert "lsp.diagnostics" in events and "review.findings" in events
    diag = next(env for env in sent if env["event"] == "lsp.diagnostics")
    assert diag["data"] == {"path": "a.py", "count": 2, "diagnostics": []}
    findings = next(env for env in sent if env["event"] == "review.findings")
    assert findings["data"] == {"scope": "working_tree", "findings": []}
    assert "unknown.c6.event" not in events
    assert "message.completed" in events and "run.completed" in events
    await store.close()
