"""Windows lifecycle regression for the LSP stack (C6A LSP wave, subagent F).

Acceptance mapping:

- 验收 5: ``release_workspace`` shuts the fake server down (pid polled until the
  process is gone) and is idempotent (second release returns 0);
- 验收 7: graceful service shutdown (protocol handshake → process exit), the
  kill path (a server that ignores ``shutdown`` is hard-killed after the
  graceful window), and orphan-tree cleanup (``taskkill /T`` takes child AND
  grandchild);
- facade ``shutdown_service()`` (the atexit hook) is idempotent.

Kill-path tests inject the subprocess into ``LSPClient._proc`` directly — a
sanctioned simplification: a stub that never answers ``initialize`` would
otherwise block ``start()`` for INITIALIZE_TIMEOUT (45s) and blow the per-test
budget.  The graceful handshake itself is covered by the fake-server tests here
and in ``test_lsp_client.py``.

Process-liveness probes use psutil when available, with a ``taskkill /F``
fallback per the taskbook (a live process exits 0; a dead one reports
"不存在"/not found).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from atlas.lsp import LSPService
from atlas.lsp._proc import kill_process_tree, windows_hide_flags
from atlas.lsp.client import LSPClient
from atlas.lsp.servers import ServerContext, ServerDef, SpawnSpec

try:
    import psutil
except ImportError:  # pragma: no cover — venv has psutil; fallback keeps the suite portable
    psutil = None

FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_lsp_server.py"
ATLAS_ROOT = Path(__file__).resolve().parents[2]  # D:\Atlas — git 仓库根
FIXTURE_BASE = ATLAS_ROOT / "_tmp" / "lsp-fixtures"  # 必须在 git 仓库内，否则被 workspace 门控关掉

WAIT_TIMEOUT = 15.0

BUG_ONE = "alpha = 1\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"

# 永不退出、可写 stdin 的占位进程（不说 LSP 话；EOF 后低速空转，测试总会先杀掉它）
STUB_CODE = (
    "import sys, time\n"
    "sys.stderr.write('stub-ready\\n'); sys.stderr.flush()\n"
    "while True:\n"
    "    sys.stdin.buffer.read1(1)\n"
    "    time.sleep(0.01)\n"
)

# 会 fork 一个孙进程再把自身 pid 对写出去的子进程（验证 taskkill /T 的进程树清理）
CHILD_CODE = textwrap.dedent(
    """
    import subprocess, sys, time
    from pathlib import Path
    grand = subprocess.Popen([sys.executable, "-c", "import time\\nwhile True:\\n    time.sleep(0.05)"])
    Path(sys.argv[1]).write_text(str(grand.pid), encoding="utf-8")
    while True:
        time.sleep(0.05)
    """
).strip()


# ---- fixtures / helpers ------------------------------------------------------


@pytest.fixture()
def lsp_dir():
    d = FIXTURE_BASE / f"lc_{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _fake_def() -> ServerDef:
    def build_spawn(root: str, ctx: ServerContext):
        override = (ctx.binary_overrides or {}).get("fake")
        if override:
            if override[0] and os.path.exists(override[0]):
                return SpawnSpec(command=[str(part) for part in override], workspace_root=root, cwd=root)
            return None
        found = shutil.which("fake-lsp") or shutil.which("fake")
        if not found:
            return None
        return SpawnSpec(command=[found], workspace_root=root, cwd=root)

    return ServerDef(
        server_id="fake",
        extensions=(".py",),
        resolve_root=lambda fp, ws: ws,
        build_spawn=build_spawn,
        description="fake LSP for tests",
    )


def _fake_command(state: Path) -> list[str]:
    return [sys.executable, str(FAKE_SERVER), "--server-id", "fake", "--state-file", str(state)]


@contextmanager
def managed_service(command, **overrides):
    svc = LSPService(
        enabled=True,
        wait_mode="document",
        wait_timeout=WAIT_TIMEOUT,
        install_strategy="manual",
        binary_overrides={"fake": list(command)},
        extra_servers=[_fake_def()],
        trusted_workspaces=[str(ATLAS_ROOT)],  # 不依赖 pytest 启动 cwd 的信任判定
        **overrides,
    )
    try:
        yield svc
    finally:
        svc.shutdown()


def _read_state(state: Path) -> dict:
    return json.loads(state.read_text(encoding="utf-8"))


def _wait_for_state(state: Path, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = _read_state(state)
        except (OSError, ValueError):
            data = {}
        if data.get("pid"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"fake server 未写入状态文件: {state}")


def _pid_alive(pid: int) -> bool:
    if psutil is not None:
        try:
            return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except psutil.NoSuchProcess:
            return False
        except psutil.Error:
            return True  # 查询被拒 → 视为存活（宁可误报存活也不假通过）
    # 回退探针：taskkill /F 对活进程返回 0（顺带终止它），对已死进程报「不存在」
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, creationflags=flags)
    if proc.returncode == 0:
        return True
    out = f"{proc.stdout}\n{proc.stderr}"
    return not ("不存在" in out or "not found" in out.lower())


def wait_pid_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


def _stub_client(lsp_dir: Path) -> LSPClient:
    return LSPClient(
        server_id="stub",
        workspace_root=str(lsp_dir),
        command=[sys.executable, "-c", STUB_CODE],
        cwd=str(lsp_dir),
    )


async def _spawn_stub(extra_args: list[str] | None = None) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        STUB_CODE,
        *(extra_args or []),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        creationflags=windows_hide_flags(),
    )


# ---- 验收 7（优雅退出）：协议握手 → 进程消失 ------------------------------------


def test_graceful_service_shutdown_terminates_server(lsp_dir):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(BUG_ONE, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        assert svc.get_diagnostics_sync(str(target), delta=False)  # 客户端跑起来
        pid = _wait_for_state(state)["pid"]
    # with 退出即 svc.shutdown()：轮询 state-file 里的 pid 直到进程死（上限 10s）
    assert wait_pid_gone(pid, timeout=10.0)
    assert _read_state(state).get("shutdown") is True  # 优雅握手确实发生了


# ---- 验收 5：release_workspace 关停 server 且幂等 ------------------------------


def test_release_workspace_stops_server_and_is_idempotent(lsp_dir):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(BUG_ONE, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        assert svc.get_diagnostics_sync(str(target), delta=False)
        pid = _wait_for_state(state)["pid"]
        root = next(iter(svc._clients.values())).workspace_root

        released = svc.release_workspace(root)
        assert released >= 1
        assert wait_pid_gone(pid, timeout=10.0)
        assert svc.release_workspace(root) == 0  # 幂等：再 release 同 root 返回 0


# ---- 验收 7（kill 路径）：ignore shutdown → grace 超时 → taskkill ---------------


@pytest.mark.asyncio
async def test_shutdown_kill_path_after_ignored_graceful_request(lsp_dir):
    proc = await _spawn_stub()
    client = _stub_client(lsp_dir)
    client._proc = proc
    # 模拟已完成 initialize 的运行态：优雅请求发给 stub（被无视）→ 2s 超时 → 1s grace → kill
    client._state = "running"
    client._reader_task = asyncio.create_task(asyncio.sleep(3600))
    started = time.monotonic()
    try:
        await asyncio.wait_for(client.shutdown(), timeout=15)
        elapsed = time.monotonic() - started
        await asyncio.wait_for(proc.wait(), timeout=5)
        assert proc.returncode is not None
        assert wait_pid_gone(proc.pid, timeout=5.0)
        assert elapsed >= 2.0  # 走完了优雅等待窗口，不是上来就杀
        assert client.state == "stopped" and not client.is_running
    finally:
        kill_process_tree(proc.pid)  # 失败路径也不留孤儿


@pytest.mark.asyncio
async def test_cleanup_process_kills_stub(lsp_dir):
    proc = await _spawn_stub()
    client = _stub_client(lsp_dir)
    client._proc = proc  # 手工注入：跳过 45s 的 initialize 握手
    try:
        await asyncio.wait_for(client._cleanup_process(), timeout=10)
        await asyncio.wait_for(proc.wait(), timeout=5)
        assert proc.returncode is not None
        assert wait_pid_gone(proc.pid, timeout=5.0)
        assert client._proc is None  # cleanup 收尾干净
    finally:
        kill_process_tree(proc.pid)


# ---- 验收 7（孤儿清理）：进程树整体收割 ----------------------------------------


@pytest.mark.asyncio
async def test_cleanup_kills_whole_process_tree(lsp_dir):
    pidfile = lsp_dir / "grandchild.pid"
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        CHILD_CODE,
        str(pidfile),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        creationflags=windows_hide_flags(),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not pidfile.exists():
        await asyncio.sleep(0.05)
    assert pidfile.exists(), "孙进程未在预算内启动"
    grand_pid = int(pidfile.read_text(encoding="utf-8"))

    client = _stub_client(lsp_dir)
    client._proc = proc
    try:
        await asyncio.wait_for(client._cleanup_process(), timeout=10)
        await asyncio.wait_for(proc.wait(), timeout=5)
        assert proc.returncode is not None
        assert wait_pid_gone(proc.pid, timeout=5.0)
        # taskkill /T 连孙进程一起收掉：无存活子进程
        assert wait_pid_gone(grand_pid, timeout=10.0)
    finally:
        kill_process_tree(proc.pid)


# ---- atexit 钩子：shutdown_service() 幂等 -------------------------------------


def test_facade_shutdown_service_is_idempotent(monkeypatch):
    import atlas.lsp as facade

    facade.shutdown_service()  # 清场：不依赖其他用例留下的全局单例
    try:

        def _factory(cls):
            return LSPService(enabled=True, wait_mode="document", wait_timeout=5.0, install_strategy="manual")

        monkeypatch.setattr(facade.LSPService, "create_from_config", classmethod(_factory))
        svc = facade.get_service()
        assert isinstance(svc, LSPService) and svc.is_active()

        facade.shutdown_service()
        facade.shutdown_service()  # 连调两次不抛
        assert facade._service is None
    finally:
        facade.shutdown_service()
