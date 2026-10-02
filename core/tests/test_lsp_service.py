"""Service-level LSP tests (C6A LSP wave, subagent F).

Drives ``atlas.lsp.manager.LSPService`` end-to-end against the executable fake
server (``tests/fakes/fake_lsp_server.py``) plus the pure registry mapping.
Acceptance mapping:

- 验收 3: post-write delta only reports what an edit introduced — clean
  baseline → everything reported, fix → empty, line-shift scenario via
  ``edit_report`` plus a synthetic ``_apply_delta`` regression;
- 验收 4: two diagnostics calls in one workspace reuse ONE server process;
- 验收 6: a missing server binary yields a short Chinese install hint
  (missing is NOT broken — no install attempt, no restart needed);
- 验收 8: ``.py``/``.ts``/``.tsx``/``.mjs`` registry + language-id mapping
  (no real pyright/tsserver — forbidden).

Fixtures live under ``<repo>/_tmp/lsp-fixtures/`` ON PURPOSE: workspace gating
only lets files inside a git worktree through, so pytest's system ``tmp_path``
would be gated off.  ``_tmp`` is gitignored; teardown removes each fixture dir.
Every service is shut down in a ``finally`` (the ``managed_service`` context
manager) so no background loop thread or server process leaks into other tests.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

import atlas.lsp as lsp_facade
from atlas.lsp import LSPService
from atlas.lsp.servers import (
    ServerContext,
    ServerDef,
    SpawnSpec,
    find_server_for_file,
    language_id_for,
)

FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_lsp_server.py"
ATLAS_ROOT = Path(__file__).resolve().parents[2]  # D:\Atlas — git 仓库根
FIXTURE_BASE = ATLAS_ROOT / "_tmp" / "lsp-fixtures"  # 必须在 git 仓库内，否则被 workspace 门控关掉

WAIT_TIMEOUT = 15.0  # 每次诊断预算：冷启动 spawn + 150ms push 都绰绰有余

CLEAN = "alpha = 1\nbeta = 2\n\ndef main():\n    return alpha\n"
BUG_ONE = "alpha = 1\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"  # 标记在 1-based 第 5 行
# 两个标记行：fake 契约只报「首个」标记行（见 c6a-lsp-contract.md 假 LSP server 节）
BUG_TWO = "alpha = LSP_BUG\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"

# 行位移场景：pre 在第 5 行有旧错误；post 在它之前插入一个新错误（旧错误位移到第 6 行）
PRE_EDIT = "a = 1\nb = 2\nc = 3\nd = 4\nvalue_old = LSP_BUG\n"
POST_EDIT = "a = 1\nb = 2\nc = 3\nd = 4\nvalue_new = LSP_BUG\nvalue_old = LSP_BUG\n"


# ---- fixtures / helpers ------------------------------------------------------


@pytest.fixture()
def lsp_dir():
    d = FIXTURE_BASE / f"svc_{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _fake_def() -> ServerDef:
    """契约约定的自定义 ServerDef：resolve_root = 工作区本身；build_spawn 只探测、绝不安装
    （语义同 ``availability.find_binary``：override[0] 存在则整表为命令，否则 PATH 逐个试）。"""

    def build_spawn(root: str, ctx: ServerContext):
        override = (ctx.binary_overrides or {}).get("fake")
        if override:
            if override[0] and os.path.exists(override[0]):
                return SpawnSpec(command=[str(part) for part in override], workspace_root=root, cwd=root)
            return None  # 二进制缺失 → manager 记入 _missing（中文提示），绝不安装、不标 broken
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
    """构造契约签名的 LSPService；退出时必然 shutdown（不留后台线程/进程）。"""
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


def _read_state(state: Path) -> dict:
    return json.loads(state.read_text(encoding="utf-8"))


def _wait_for_state(state: Path, timeout: float = 10.0) -> dict:
    """轮询 fake server 的状态文件（initialize 完成后写入 pid）。"""
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


def _install_singleton(monkeypatch, svc) -> None:
    """把直构的服务挂到门面单例上（D 的门面经 ``get_service()``/``_service`` 取服务）。"""
    monkeypatch.setattr(lsp_facade, "_service", svc, raising=False)
    monkeypatch.setattr(lsp_facade, "get_service", lambda: svc, raising=False)


# ---- 验收 3：delta 只返回新增 --------------------------------------------------


def test_delta_reports_only_new_diagnostics(lsp_dir):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(CLEAN, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        svc.snapshot_baseline(str(target))
        # 干净内容 → 当前 0 条
        assert svc.get_diagnostics_sync(str(target), delta=False) == []

        # 改成含一个 LSP_BUG → delta 恰 1 条 T999
        target.write_text(BUG_ONE, encoding="utf-8")
        diags = svc.get_diagnostics_sync(str(target), delta=True)
        assert len(diags) == 1
        assert diags[0]["code"] == "T999"
        assert diags[0]["range"]["start"]["line"] == 4  # 1-based 第 5 行

        # 干净版重新做 baseline → 含两个 LSP_BUG：fake 契约只报首个标记行 → 恰 1 条
        target.write_text(CLEAN, encoding="utf-8")
        svc.snapshot_baseline(str(target))
        target.write_text(BUG_TWO, encoding="utf-8")
        diags = svc.get_diagnostics_sync(str(target), delta=True)
        assert len(diags) == 1
        assert diags[0]["range"]["start"]["line"] == 0  # 首个标记行

        # 修复 → delta 空
        target.write_text(CLEAN, encoding="utf-8")
        assert svc.get_diagnostics_sync(str(target), delta=True) == []


def test_line_shift_drops_moved_baseline_entries(lsp_dir):
    """纯逻辑回归（不需要真 server）：旧错误整体下移一行（内容不变）时，
    位移后的 baseline 应把它从 delta 中滤掉；位移落到删除区则计入。"""
    with managed_service([str(lsp_dir / "unused.exe")]) as svc:
        target = os.path.abspath(str(lsp_dir / "shift.py"))
        diag = {
            "range": {"start": {"line": 4, "character": 4}, "end": {"line": 4, "character": 11}},
            "severity": 1,
            "code": "T999",
            "source": "fakeserver",
            "message": "Fake type error: LSP_BUG",
        }
        svc._set_delta_baseline(target, [diag])

        moved = dict(diag, range={"start": {"line": 5, "character": 4}, "end": {"line": 5, "character": 11}})
        assert svc._apply_delta(target, [moved], lambda line: line + 1 if line == 4 else None) == []

        # 同一诊断位移进被删除的行区间 → baseline 项丢弃 → 作为「新」出现
        assert svc._apply_delta(target, [moved], lambda line: None) == [moved]


# ---- 验收 4：同 workspace 复用同一 server --------------------------------------


def test_same_workspace_reuses_one_server(lsp_dir):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(BUG_ONE, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        assert svc.get_diagnostics_sync(str(target), delta=False)
        first = _wait_for_state(state)
        client = next(iter(svc._clients.values()))

        assert svc.get_diagnostics_sync(str(target), delta=True)
        second = _read_state(state)

        # state-file 里 pid 不变 → 同一 server 进程；服务里也只有一个活客户端
        assert first["pid"] == second["pid"] and first["pid"] > 0
        assert len(svc._clients) == 1
        assert client in svc._clients.values()


# ---- 验收 6：server 缺失 → 中文提示 -------------------------------------------


def test_missing_binary_gives_chinese_hint(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "bug.py"
    target.write_text(BUG_ONE, encoding="utf-8")
    # 指向必然不存在的可执行文件（契约示例 Z:/... 的确定性等价物）
    missing_cmd = [str(lsp_dir / "definitely" / "not" / "real-binary.exe")]
    with managed_service(missing_cmd) as svc:
        assert svc.enabled_for(str(target)) is True  # 注册表命中 + git 工作区内 → 门控放行
        assert svc.get_diagnostics_sync(str(target)) == []  # 缺失 → 无诊断，绝不安装
        assert svc.enabled_for(str(target)) is True  # 缺失 ≠ broken：装好即用，无需重启

        hint = svc.describe_missing(str(target))
        assert hint and "安装" in hint

        _install_singleton(monkeypatch, svc)
        assert lsp_facade.missing_hint(str(target)) == hint  # 门面同样非空
        assert "安装" in lsp_facade.missing_hint(str(target))


# ---- 验收 8：注册表映射（不起真 server）----------------------------------------


def test_registry_mapping_python_and_ts():
    assert find_server_for_file("a.py").server_id == "pyright"
    assert find_server_for_file("a.ts").server_id == "typescript"
    assert find_server_for_file("a.tsx").server_id == "typescript"
    assert language_id_for("a.py") == "python"
    assert language_id_for("a.tsx") == "typescriptreact"
    assert language_id_for("a.mjs") == "javascript"

    with managed_service(["unused-binary"]) as svc:
        assert svc.handles_extension(".py") is True
        assert svc.handles_extension(".ts") is True
        assert svc.handles_extension(".md") is False


# ---- 验收 3（行位移场景）：edit_report 门面 ------------------------------------


def test_edit_report_lists_only_introduced_diagnostic(lsp_dir, monkeypatch):
    state = lsp_dir / "fake_state.json"
    target = lsp_dir / "edit.py"
    target.write_text(PRE_EDIT, encoding="utf-8")
    with managed_service(_fake_command(state)) as svc:
        _install_singleton(monkeypatch, svc)
        lsp_facade.snapshot_baseline(str(target))  # 预写坏文件后做 baseline

        target.write_text(POST_EDIT, encoding="utf-8")  # 保留旧错 + 在旧行之前新增一个错
        report = lsp_facade.edit_report(str(target), PRE_EDIT, POST_EDIT)

    assert "本次编辑引入的诊断" in report
    # 行位移：旧错误（第 5 行 → 第 6 行）不得计入；只列第 5 行新增那条
    assert report.count("[T999]") == 1
    assert "[5:5]" in report
    assert "[6:" not in report
