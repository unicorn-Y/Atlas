"""C6 LSP 写路径端到端验收(契约 §3 测试 2)。

FakeLLMServer + 隔离后端(参照 ``test_c1_websocket_acceptance.py`` 的 IsolatedBackend
模式,唯一差别是 atlas.toml 多一段指向 fake LSP server 的 ``[lsp]`` 配置)。脚本化模型
先写干净文件再写入含 ``LSP_BUG`` 的内容,断言 WebSocket 上收到 ``lsp.diagnostics``
事件(server 端映射已并入:内部 type 与 wire 事件同名,``count==0 不发事件``),
且工具结果是 Atlas 的中文报告而不是 Hermes 自带 LSP 层的英文块(双激活保持关闭)。

后端根目录放在 ``D:\\Atlas\\_tmp\\lsp-fixtures`` 下:workspace 门控只放行 git
worktree 内的文件,pytest 系统 tmp_path 会被关掉;``_tmp`` 已被 gitignore。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from websockets.asyncio.client import connect

from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home

FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_lsp_server.py"
ATLAS_ROOT = Path(__file__).resolve().parents[2]  # git 仓库根（h1 工作区即 checkout 根）
FIXTURE_BASE = ATLAS_ROOT / "_tmp" / "lsp-fixtures"


def _resolved_agent_fork_root() -> str | None:
    """Root of the ``agent`` package this test process actually resolves.

    The backend venv's ``.pth`` injects the HOST checkout's stale hermes fork
    into ``sys.path``; whatever the test process imports must win, so the
    resolved fork root goes onto the subprocess PYTHONPATH ahead of any .pth
    path (H1 pinned fork with ``agent.agent_hooks``; PYTHONPATH beats .pth).
    """
    spec = importlib.util.find_spec("agent")
    if spec is None or not spec.submodule_search_locations:
        return None
    return str(Path(list(spec.submodule_search_locations)[0]).resolve().parent)

CLEAN = "alpha = 1\nbeta = 2\n\ndef main():\n    return alpha\n"
BUG_ONE = "alpha = 1\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"


class IsolatedBackend:
    """同 test_c1_websocket_acceptance 的隔离后端,atlas.toml 追加 [lsp] 段。"""

    def __init__(self, root, fake):
        self.root, self.fake = root, fake
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        assert self.port != 8765
        self.url = f"http://127.0.0.1:{self.port}"
        self.events = []
        data = root / "atlas"
        (data / "config").mkdir(parents=True)
        lsp_command = json.dumps([sys.executable, str(FAKE_SERVER),
                                  "--server-id", "fake", "--delay-ms", "60",
                                  "--state-file", str(root / "fake_state.json")])
        (data / "config/atlas.toml").write_text(
            '[models]\ndefault="fake-model"\n'
            f'[models.gateway]\nbase_url="{fake.base_url}"\napi_key="sk-fake-e2e"\n'
            '[[models.custom]]\nid="fake-model"\nname="Fake fixture"\nprovider="openai"\nlitellm_model="openai/fake-model"\nmax_output_tokens=512\n'
            '[agent]\nengine="hermes"\nverify_before_stop=false\n'
            '[tools]\nauto_start=[]\n[tools.servers]\n'
            '[scheduler]\nenabled=false\n'
            '[lsp]\nenabled=true\nwait_timeout=25.0\n'
            'trusted_workspaces=[' + json.dumps(str(ATLAS_ROOT)) + ']\n'
            '[lsp.servers.fake]\ncommand=' + lsp_command + '\nextensions=[".py"]\n',
            encoding="utf-8",
        )
        write_hermes_home(data / "engine", fake.base_url,
                          extra_config="auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n")
        env = dict(os.environ)
        for key in list(env):
            upper_key = key.upper()
            if (any(marker in upper_key for marker in ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH"))
                    or upper_key.startswith("HERMES_SESSION_")
                    or upper_key.endswith("_PROXY")):
                env.pop(key, None)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR"):
            directory = root / key.lower()
            directory.mkdir()
            env[key] = str(directory)
        env.update(ATLAS_DATA_DIR=str(data), HERMES_HOME=str(data / "engine"),
                   ATLAS_SCHEDULER_ENABLED="false", ATLAS_API_TOKEN="c1-isolated-token",
                   ATLAS_API_KEY="sk-fake-e2e", ATLAS_API_BASE=fake.base_url,
                   NO_PROXY="127.0.0.1,localhost", HERMES_TEST_MODE="1")
        env.update(OPENAI_API_BASE=fake.base_url, OPENAI_BASE_URL=fake.base_url, OPENAI_API_KEY="sk-fake-e2e")
        for key in list(env):
            if key.upper().endswith("_PROXY"):
                env.pop(key, None)
        for key in ("HERMES_SCRATCH_DIR",):
            env.pop(key, None)
        launch_root = root / "backend-cwd"
        launch_root.mkdir()
        pythonpath = [str(Path(__file__).resolve().parents[1])]
        agent_fork_root = _resolved_agent_fork_root()
        if agent_fork_root:
            pythonpath.append(agent_fork_root)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath)
        self.log = (root / "backend.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "atlas.server:app", "--host", "127.0.0.1", "--port", str(self.port),
        ], cwd=launch_root, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        self.http = httpx.AsyncClient(base_url=self.url, headers={"x-atlas-api-token": "c1-isolated-token"}, timeout=30)

    async def ready(self):
        for _ in range(150):
            if self.process.poll() is not None:
                raise AssertionError((self.root / "backend.log").read_text()[-3000:])
            try:
                response = await self.http.get("/api/health")
                if response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(.2)
        raise AssertionError("isolated backend did not become ready")

    async def conversation(self):
        response = await self.http.post("/api/conversations", json={"title": "New Conversation"})
        assert response.status_code == 200, response.text
        return response.json()["id"]

    async def run(self, content, *, conversation=None, workspace=None, expected="run.completed", **options):
        import uuid as _uuid

        conversation = conversation or await self.conversation()
        run_id = _uuid.uuid4().hex
        received = []
        try:
            async with connect(self.url.replace("http", "ws", 1) + "/ws/chat",
                               additional_headers={"x-atlas-api-token": "c1-isolated-token"}, max_size=8_000_000) as ws:
                await ws.send(json.dumps({"type": "run.start", "run_id": run_id, "content": content,
                    "conversation_id": conversation, "workspace": str(workspace or self.root / "workspace"),
                    "model": "fake-model", **options}))
                async with asyncio.timeout(120):
                    while True:
                        event = json.loads(await ws.recv())
                        received.append(event)
                        if event.get("run_id") == run_id and event.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
                            break
        except (TimeoutError, asyncio.TimeoutError):
            log_tail = (self.root / "backend.log").read_text(errors="replace")[-2000:]
            raise AssertionError(f"run did not finish; last events: {received[-3:]}\nbackend.log tail:\n{log_tail}")
        self.events.extend(received)
        (self.root / "events.json").write_text(json.dumps(received, ensure_ascii=False, indent=2), encoding="utf-8")
        assert received[-1]["event"] == expected, received[-1]
        return conversation, received

    async def close(self):
        await self.http.aclose()
        import psutil

        try:
            children = psutil.Process(self.process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        self.process.terminate()
        try:
            await asyncio.to_thread(self.process.wait, 15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            await asyncio.to_thread(self.process.wait, 5)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=3)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        self.log.close()


@pytest.fixture()
def e2e_root():
    root = FIXTURE_BASE / f"e2e_{uuid.uuid4().hex[:10]}"
    (root / "workspace").mkdir(parents=True)
    yield root
    if os.environ.get("C6_LSP_E2E_KEEP"):  # 调试时保留现场
        return
    shutil.rmtree(root, ignore_errors=True)


@pytest_asyncio.fixture
async def backend(e2e_root):
    with FakeLLMServer() as fake:
        server = IsolatedBackend(e2e_root, fake)
        try:
            await server.ready()
            yield server
        finally:
            await server.close()


@pytest.mark.asyncio
async def test_write_file_publishes_lsp_diagnostics_ws_event(backend, e2e_root):
    workspace = e2e_root / "workspace"
    target = workspace / "e2e_bug.py"
    target.write_text(CLEAN, encoding="utf-8")  # 干净基线落盘
    state_file = e2e_root / "fake_state.json"

    turns = 0

    def responder(record):
        nonlocal turns
        turns += 1
        if turns == 1:
            # 先读后写:Hermes 的防覆盖闸要求任务见过当前全文
            return ToolCall("read_file", {"path": str(target)})
        if turns == 2:
            return ToolCall("write_file", {"path": str(target), "content": BUG_ONE})
        return Text("buggy version written")

    backend.fake._responder = responder
    conversation, events = await backend.run("write the buggy version", workspace=str(workspace))

    # wire 事件:server 已把内部 lsp.diagnostics 原样透传
    lsp_events = [e for e in events if e.get("event") == "lsp.diagnostics"]
    assert len(lsp_events) == 1, [e.get("event") for e in events]
    data = lsp_events[0]["data"]
    assert data["count"] == 1
    assert data["path"] == "e2e_bug.py"
    assert os.path.isabs(data["workspace"]) and Path(data["workspace"]) == workspace.resolve()
    assert data["diagnostics"] == [{
        "line": 5, "column": 5, "severity": "error", "code": "T999",
        "message": "Fake type error: LSP_BUG on line 5",
    }]

    # 工具结果带 Atlas 中文报告;Hermes 自带 LSP 层的英文块必须缺席(双激活关闭)
    tool_results = [json.dumps(e.get("data", {}).get("result", []), ensure_ascii=False)
                    for e in events if e.get("event") == "tool.completed"
                    and e.get("data", {}).get("name") == "write_file"]
    assert tool_results, [e.get("event") for e in events]
    assert "本次编辑引入的诊断" in tool_results[0]
    assert "LSP diagnostics introduced by this edit" not in tool_results[0]

    # fake server 确实在后端进程里被拉起并完成过 initialize
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state.get("initialized") is True and state.get("pid", 0) > 0
