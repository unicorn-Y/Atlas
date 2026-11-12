"""C6 LSP 写路径接线测试(契约 §3 / §2.1)。

覆盖:干净基线 → 编辑引入错误(报告 + 事件 count==1)→ 修复后为空;
旧行仅移动不算新增;LSP 不可用时写文件照常成功;count==0 不发事件;
Hermes 自带 agent.lsp 层在 Atlas 进程内保持休眠(只有一个 LSP 服务处理写);
以及 write_file / patch 经真实 ``bind_atlas_tools`` handler 路径的接缝。

Fake server 复用 ``tests/fakes/fake_lsp_server.py``(文本含 ``LSP_BUG`` 报一个
T999 错误)。fixture 目录放在 ``D:\\Atlas\\_tmp\\lsp-fixtures`` 下:workspace 门控
只放行 git worktree 内的文件,pytest 系统 tmp_path 会被关掉。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import atlas.lsp as lsp_facade
from atlas.engine import lsp_bridge
from atlas.engine.tool_registry import _active_contexts, bind_atlas_tools
from atlas.lsp import LSPService
from atlas.lsp.servers import ServerContext, ServerDef, SpawnSpec

FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_lsp_server.py"
ATLAS_ROOT = Path(__file__).resolve().parents[2]  # D:\Atlas — git 仓库根
FIXTURE_BASE = ATLAS_ROOT / "_tmp" / "lsp-fixtures"  # 必须在 git 仓库内，否则被 workspace 门控关掉

WAIT_TIMEOUT = 15.0  # 每次诊断预算：冷启动 spawn + fake server 的 150ms push 都绰绰有余

CLEAN = "alpha = 1\nbeta = 2\n\ndef main():\n    return alpha\n"
BUG_ONE = "alpha = 1\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"  # 标记在 1-based 第 5 行
CLEAN_V2 = "beta = 2\nalpha = 1\n\ndef main():\n    return alpha\n"  # 内容变了但仍无错误
# 行位移场景：pre 第 5 行有旧错误；post 在它之前新增一个错误（旧错误位移到第 6 行）
PRE_EDIT = "a = 1\nb = 2\nc = 3\nd = 4\nvalue_old = LSP_BUG\n"
POST_EDIT = "a = 1\nb = 2\nc = 3\nd = 4\nvalue_new = LSP_BUG\nvalue_old = LSP_BUG\n"


# ---- fixtures / helpers ------------------------------------------------------


@pytest.fixture()
def lsp_dir():
    d = FIXTURE_BASE / f"bridge_{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _fake_def() -> ServerDef:
    """自定义 ServerDef：resolve_root = 工作区本身；build_spawn 只探测、绝不安装。"""

    def build_spawn(root: str, ctx: ServerContext):
        override = (ctx.binary_overrides or {}).get("fake")
        if override:
            if override[0] and os.path.exists(override[0]):
                return SpawnSpec(command=[str(part) for part in override], workspace_root=root, cwd=root)
            return None  # 二进制缺失 → manager 记入 _missing，绝不安装、不标 broken
        return None

    return ServerDef(
        server_id="fake",
        extensions=(".py",),
        resolve_root=lambda fp, ws: ws,
        build_spawn=build_spawn,
        description="fake LSP for bridge tests",
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
        # 显式信任 D:\Atlas 本身：用例不依赖 pytest 的启动 cwd（信任默认关闭）
        trusted_workspaces=[str(ATLAS_ROOT)],
        **overrides,
    )
    try:
        yield svc
    finally:
        svc.shutdown()


def _install_singleton(monkeypatch, svc) -> None:
    """把直构的服务挂到门面单例上（桥经 ``atlas.lsp.get_service()`` 取服务）。"""
    monkeypatch.setattr(lsp_facade, "_service", svc, raising=False)
    monkeypatch.setattr(lsp_facade, "get_service", lambda: svc, raising=False)


def _make_runtime(lsp_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        event_queue=asyncio.Queue(), workspace=str(lsp_dir),
        conversation_id="bridge-session", file_edit_counts={},
    )


def _drain_event(queue: asyncio.Queue) -> dict | None:
    if queue.empty():
        return None
    return queue.get_nowait()


def _leading_json(result: str) -> dict:
    """原生工具结果是 JSON + 报告块(契约:非空报告以空行拼在尾部);只解析前导 JSON。"""
    decoder = json.JSONDecoder()
    details, _end = decoder.raw_decode(result)
    assert isinstance(details, dict)
    return details


# ---- 门控与 Hermes 双激活 ------------------------------------------------------


def test_lsp_applicable_rejects_only_ssh():
    assert lsp_bridge.lsp_applicable(str(ATLAS_ROOT)) is True
    assert lsp_bridge.lsp_applicable("") is True
    assert lsp_bridge.lsp_applicable("ssh://build-host/srv/project") is False


def test_atlas_lsp_tier_stays_dormant_in_atlas(monkeypatch, lsp_dir):
    """venv 里的 hermes-agent 自带 agent.lsp(hermes 配置默认 enabled=True)在 Atlas
    进程内必须休眠：get_service 被桥替换为 None-returning,且从不创建自己的服务单例。"""
    import agent.lsp as hermes_lsp  # noqa: PLC0415 — 延迟导入,避免无关测试付出导入成本

    lsp_bridge._neutralize_hermes_lsp()
    assert hermes_lsp.get_service is lsp_bridge._hermes_lsp_disabled
    assert hermes_lsp.get_service() is None

    # LSP 关闭(门面返回 None)时桥全程为空操作,Hermes 侧依旧零服务
    monkeypatch.setattr(lsp_facade, "get_service", lambda: None, raising=False)
    target = lsp_dir / "dormant.py"
    target.write_text(CLEAN, encoding="utf-8")
    lsp_bridge.snapshot_before_write(str(target))
    runtime = _make_runtime(lsp_dir)
    report = lsp_bridge.report_after_edit(runtime, str(target), CLEAN, BUG_ONE)
    assert report == ""
    assert hermes_lsp._service is None and not hermes_lsp._services_by_home


# ---- 场景 1 + 2：引入错误上报,修复后为空 ----------------------------------------


@pytest.mark.asyncio
async def test_introduced_error_reports_and_emits_then_fix_is_silent(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        runtime = _make_runtime(lsp_dir)

        # 干净基线 → 编辑引入一个错误
        lsp_bridge.snapshot_before_write(str(target))
        target.write_text(BUG_ONE, encoding="utf-8")
        report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, runtime, str(target), CLEAN, BUG_ONE,
            loop=asyncio.get_running_loop(),
        )

        assert "本次编辑引入的诊断" in report
        assert "[T999]" in report and "[5:" in report
        event = _drain_event(runtime.event_queue)
        assert event is not None and event["type"] == "lsp.diagnostics"
        data = event["data"]
        assert data["count"] == 1
        assert data["path"] == "bug.py"
        assert os.path.isabs(data["workspace"])
        assert data["diagnostics"] == [{
            "line": 5, "column": 5, "severity": "error", "code": "T999",
            "message": "Fake type error: LSP_BUG on line 5",
        }]
        # 只有这一个 LSP 服务处理了这次写；Hermes 层保持休眠
        import agent.lsp as hermes_lsp  # noqa: PLC0415

        assert hermes_lsp.get_service() is None and hermes_lsp._service is None
        assert lsp_facade.get_service() is svc

        # 修复文件 → 报告为空,不再发事件
        lsp_bridge.snapshot_before_write(str(target))
        target.write_text(CLEAN, encoding="utf-8")
        fix_report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, runtime, str(target), BUG_ONE, CLEAN,
        )
        assert fix_report == ""
        assert runtime.event_queue.empty()


# ---- 场景 3：旧错误仅移动行号不算新增 -------------------------------------------


@pytest.mark.asyncio
async def test_line_shift_not_reported_as_new(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "shift.py"
    target.write_text(PRE_EDIT, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        runtime = _make_runtime(lsp_dir)

        lsp_bridge.snapshot_before_write(str(target))
        target.write_text(POST_EDIT, encoding="utf-8")
        report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, runtime, str(target), PRE_EDIT, POST_EDIT,
            loop=asyncio.get_running_loop(),
        )

        # 只报第 5 行新增那条；位移到第 6 行的旧错误不计入
        assert "本次编辑引入的诊断" in report
        assert report.count("[T999]") == 1
        assert "[5:5]" in report and "[6:" not in report
        event = _drain_event(runtime.event_queue)
        assert event is not None and event["data"]["count"] == 1
        assert event["data"]["diagnostics"][0]["line"] == 5


# ---- 场景 4：LSP 不可用时写文件照常成功 -----------------------------------------


@pytest.mark.asyncio
async def test_missing_server_writes_succeed_with_empty_report(lsp_dir, monkeypatch):
    missing_cmd = [str(lsp_dir / "definitely" / "not" / "real-binary.exe")]
    target = lsp_dir / "bug.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(missing_cmd) as svc:
        _install_singleton(monkeypatch, svc)
        runtime = _make_runtime(lsp_dir)

        lsp_bridge.snapshot_before_write(str(target))  # 不得崩
        target.write_text(BUG_ONE, encoding="utf-8")   # 写操作照常完成
        report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, runtime, str(target), CLEAN, BUG_ONE,
        )

        assert report == ""
        assert target.read_text(encoding="utf-8") == BUG_ONE
        assert runtime.event_queue.empty()


# ---- 场景 5：count==0 不发事件 --------------------------------------------------


@pytest.mark.asyncio
async def test_zero_new_diagnostics_emit_no_event(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "clean.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        runtime = _make_runtime(lsp_dir)

        lsp_bridge.snapshot_before_write(str(target))
        target.write_text(CLEAN_V2, encoding="utf-8")  # 内容变了但没有新诊断
        report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, runtime, str(target), CLEAN, CLEAN_V2,
        )

        assert report == ""
        assert runtime.event_queue.empty()


# ---- 桥的容错：事件通道坏了也不外抛 ----------------------------------------------


@pytest.mark.asyncio
async def test_broken_event_channel_degrades_to_empty_report(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target_a = lsp_dir / "bug_a.py"
    target_b = lsp_dir / "bug_b.py"
    for target in (target_a, target_b):
        target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)

        # 没有事件队列 → 不发事件,报告文本照常返回
        quiet = SimpleNamespace(event_queue=None, workspace=str(lsp_dir))
        lsp_bridge.snapshot_before_write(str(target_a))
        target_a.write_text(BUG_ONE, encoding="utf-8")
        quiet_report = await asyncio.to_thread(
            lsp_bridge.report_after_edit, quiet, str(target_a), CLEAN, BUG_ONE,
            loop=asyncio.get_running_loop(),
        )
        assert "本次编辑引入的诊断" in quiet_report and quiet.event_queue is None

        # 事件入队失败(坏 loop)→ 按契约整个返回 "",绝不外抛
        broken = SimpleNamespace(event_queue=asyncio.Queue(), workspace=str(lsp_dir))
        lsp_bridge.snapshot_before_write(str(target_b))
        target_b.write_text(BUG_ONE, encoding="utf-8")
        assert await asyncio.to_thread(
            lsp_bridge.report_after_edit, broken, str(target_b), CLEAN, BUG_ONE,
            loop=object(),
        ) == ""


# ---- 真实 bind_atlas_tools handler 路径 -----------------------------------------


@contextmanager
def bound_handler_context(lsp_dir: Path, loop: asyncio.AbstractEventLoop):
    """按 test_c1_tool_workspace 的模式绑定真实 handler；退出时恢复注册表与上下文。"""
    import tools.file_tools  # noqa: F401 — 确保 hermes 文件工具已注册
    from tools.registry import registry

    class Agent:
        def _model_facing_tools(self):
            return []

    agent = Agent()
    runtime = _make_runtime(lsp_dir)
    session_id = runtime.conversation_id
    _active_contexts[session_id] = (agent, runtime, loop)
    registry_copy = dict(registry._tools)
    try:
        bind_atlas_tools(agent, runtime, loop)
        yield registry, runtime
    finally:
        _active_contexts.pop(session_id, None)
        registry._tools.clear()
        registry._tools.update(registry_copy)


@pytest.mark.asyncio
async def test_write_file_handler_appends_report_and_event(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "native_new.py"  # 新文件：绕开 Hermes 的整写防覆盖拒绝
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("write_file").handler
            result = await asyncio.to_thread(
                handler, {"path": str(target), "content": BUG_ONE},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(result)
            assert not details.get("error"), result
            assert "本次编辑引入的诊断" in result
            assert target.read_text(encoding="utf-8") == BUG_ONE
            event = _drain_event(runtime.event_queue)
            assert event is not None and event["type"] == "lsp.diagnostics"
            assert event["data"]["count"] == 1 and event["data"]["path"] == "native_new.py"


@pytest.mark.asyncio
async def test_patch_handler_reports_like_write_file(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "native_patch.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("patch").handler
            result = await asyncio.to_thread(
                handler,
                {"path": str(target), "old_string": "return alpha", "new_string": "return LSP_BUG"},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(result)
            assert not details.get("error"), result
            assert "本次编辑引入的诊断" in result
            assert "LSP_BUG" in target.read_text(encoding="utf-8")
            event = _drain_event(runtime.event_queue)
            assert event is not None and event["data"]["count"] == 1
            assert event["data"]["path"] == "native_patch.py"


@pytest.mark.asyncio
async def test_denied_write_reports_nothing(lsp_dir, monkeypatch):
    """被拒的写(Hermes 防覆盖:任务从未读过该文件)不拼报告、不发事件。"""
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "native_refused.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("write_file").handler
            result = await asyncio.to_thread(
                handler, {"path": str(target), "content": BUG_ONE},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(result)
            assert details.get("error"), result
            assert target.read_text(encoding="utf-8") == CLEAN  # 未被改动
            assert "本次编辑引入的诊断" not in result
            assert runtime.event_queue.empty()


# ---- path-less V4A 多文件补丁（C6R） ---------------------------------------------
#
# V4A whole-repo patch 没有顶层 path：seam 必须复用 Hermes 自己的 V4A header 解析
# 拿到 touched files，逐文件 baseline → 逐文件 delta，逐文件发 lsp.diagnostics 事件，
# 结果尾部拼一段合并的中文诊断；零新增诊断的文件保持沉默；Delete/非文本文件不崩。


def _v4a_patch(*ops: str) -> str:
    return "*** Begin Patch\n" + "\n".join(ops) + "\n*** End Patch"


_V4A_INTRODUCE = ("@@", " def main():", "-    return alpha", "+    return LSP_BUG")
_V4A_FIX = ("@@", " def main():", "-    return LSP_BUG", "+    return alpha")


def test_v4a_touched_paths_resolves_workspace_relative(lsp_dir):
    """header 路径按 workspace 解析；非 V4A 参数与 traversal header 都返回空。"""
    from atlas.engine.tool_registry import _v4a_touched_paths

    runtime = _make_runtime(lsp_dir)
    patch = _v4a_patch("*** Update File: rel.py", "*** Delete File: sub/gone.txt")
    assert _v4a_touched_paths({"mode": "patch", "patch": patch}, runtime) == [
        str(lsp_dir / "rel.py"), str(lsp_dir / "sub" / "gone.txt"),
    ]
    assert _v4a_touched_paths({"mode": "replace", "path": "x.py"}, runtime) == []
    assert _v4a_touched_paths({"patch": "*** Begin Patch\n*** End Patch"}, runtime) == []
    assert _v4a_touched_paths(
        {"mode": "patch", "patch": "*** Begin Patch\n*** Update File: ../evil.py\n*** End Patch"},
        runtime,
    ) == []


@pytest.mark.asyncio
async def test_v4a_patch_handler_reports_and_emits(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "v4a_one.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("patch").handler
            patch = _v4a_patch(f"*** Update File: {target.as_posix()}", *_V4A_INTRODUCE)
            result = await asyncio.to_thread(
                handler, {"mode": "patch", "patch": patch},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(result)
            assert not details.get("error"), result
            assert any("v4a_one.py" in str(p) for p in details.get("files_modified", []))
            assert "本次 V4A 多文件补丁引入的诊断" in result
            assert "[T999]" in result
            assert "return LSP_BUG" in target.read_text(encoding="utf-8")
            event = _drain_event(runtime.event_queue)
            assert event is not None and event["type"] == "lsp.diagnostics"
            assert event["data"]["count"] == 1
            assert event["data"]["path"] == "v4a_one.py"


@pytest.mark.asyncio
async def test_v4a_multi_file_only_dirty_reports_and_delete_is_safe(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    dirty = lsp_dir / "v4a_dirty.py"
    quiet = lsp_dir / "v4a_quiet.py"
    notes = lsp_dir / "v4a_notes.txt"
    dirty.write_text(CLEAN, encoding="utf-8")
    quiet.write_text(CLEAN, encoding="utf-8")
    notes.write_text("scratch\n", encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("patch").handler
            patch = _v4a_patch(
                f"*** Update File: {dirty.as_posix()}", *_V4A_INTRODUCE,
                f"*** Update File: {quiet.as_posix()}", "@@", "-alpha = 1",
                "+alpha = 1  # touched, still clean",
                f"*** Delete File: {notes.as_posix()}",
            )
            result = await asyncio.to_thread(
                handler, {"mode": "patch", "patch": patch},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(result)
            assert not details.get("error"), result
            section = result[result.find("本次 V4A 多文件补丁引入的诊断"):]
            assert section.startswith("本次 V4A 多文件补丁引入的诊断")
            assert "v4a_dirty.py" in section          # 脏文件报告
            assert "v4a_quiet.py" not in section      # 零新增诊断保持沉默
            assert "v4a_notes.txt" not in section     # 删除的文件不崩、不上报
            assert not notes.exists()
            assert "return LSP_BUG" in dirty.read_text(encoding="utf-8")
            events = []
            while not runtime.event_queue.empty():
                events.append(runtime.event_queue.get_nowait())
            assert len(events) == 1 and events[0]["type"] == "lsp.diagnostics"
            assert events[0]["data"]["path"] == "v4a_dirty.py"


@pytest.mark.asyncio
async def test_v4a_fix_patch_is_silent(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "v4a_fix.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        with bound_handler_context(lsp_dir, asyncio.get_running_loop()) as (registry, runtime):
            handler = registry.get_entry("patch").handler
            introduce = await asyncio.to_thread(
                handler,
                {"mode": "patch", "patch": _v4a_patch(f"*** Update File: {target.as_posix()}", *_V4A_INTRODUCE)},
                session_id=runtime.conversation_id,
            )
            assert "本次 V4A 多文件补丁引入的诊断" in introduce
            assert _drain_event(runtime.event_queue) is not None
            fix = await asyncio.to_thread(
                handler,
                {"mode": "patch", "patch": _v4a_patch(f"*** Update File: {target.as_posix()}", *_V4A_FIX)},
                session_id=runtime.conversation_id,
            )
            details = _leading_json(fix)
            assert not details.get("error"), fix
            assert "本次 V4A 多文件补丁引入的诊断" not in fix
            assert "return LSP_BUG" not in target.read_text(encoding="utf-8")
            assert runtime.event_queue.empty()
