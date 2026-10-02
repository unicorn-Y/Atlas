"""/init 契约测试(C6 W2):扫描、提案合并纪律、diff、应用竞态防护、路由。

全部确定性(不调模型、不联网);路由用全新 FastAPI() 注册
``register_init_routes``,不导入 ``atlas.server``。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.commands import (
    apply_proposal,
    build_proposal,
    compute_diff,
    register_init_routes,
    scan_workspace,
)
from atlas.commands.init import MANAGED_BEGIN, MANAGED_END


def _make_workspace(tmp_path: Path) -> Path:
    """合成工作区:package.json 脚本 + Python/TS 源文件 + Makefile + 锁文件。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "package.json").write_text(json.dumps({
        "name": "demo", "version": "0.1.0",
        "scripts": {
            "build": "tsc -p .",
            "test": "vitest run",
            "lint": "eslint .",
            "typecheck": "tsc --noEmit",
        },
    }), encoding="utf-8")
    (ws / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (ws / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "util.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (ws / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "junk.py").write_text("x = 1\n", encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# scan_workspace
# ---------------------------------------------------------------------------


def test_scan_detects_commands_languages_and_managers(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)

    scan = scan_workspace(str(ws))

    names = {item["name"] for item in scan["languages"]}
    counts = {item["name"]: item["count"] for item in scan["languages"]}
    assert "Python" in names and "TypeScript" in names
    assert counts["Python"] == 1  # node_modules 已跳过
    assert scan["package_managers"] == ["npm"]

    assert scan["build_commands"] == ["npm run build (package.json)"]
    assert "npm run test (package.json)" in scan["test_commands"]
    assert "make test (Makefile)" in scan["test_commands"]
    assert scan["lint_commands"] == ["npm run lint (package.json)"]
    assert scan["typecheck_commands"] == ["npm run typecheck (package.json)"]
    # 每条命令都带来源标注
    for key in ("build_commands", "test_commands", "lint_commands", "typecheck_commands"):
        for command in scan[key]:
            assert "(" in command and command.endswith(")")

    assert "app.py" in scan["entrypoints"]
    assert scan["existing"] == {"AGENTS.md": False, "CLAUDE.md": False, ".atlas/rules.md": False}

    # 确定性:两次扫描结果完全一致
    assert scan_workspace(str(ws)) == scan


def test_scan_existing_rule_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("人工规则\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text("claude\n", encoding="utf-8")
    (ws / ".atlas").mkdir()
    (ws / ".atlas" / "rules.md").write_text("rules\n", encoding="utf-8")

    existing = scan_workspace(str(ws))["existing"]

    assert existing == {"AGENTS.md": True, "CLAUDE.md": True, ".atlas/rules.md": True}


# ---------------------------------------------------------------------------
# build_proposal:新文件 / 已有文件合并纪律
# ---------------------------------------------------------------------------


def test_proposal_for_new_workspace(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)

    proposal = build_proposal(str(ws))

    assert proposal["exists"] is False
    assert proposal["existing_content"] == ""
    assert Path(proposal["path"]) == ws / "AGENTS.md"
    content = proposal["proposed_content"]
    assert content.startswith(MANAGED_BEGIN) and content.rstrip().endswith(MANAGED_END)
    assert "## 项目概览" in content
    assert "## 常用命令" in content
    assert "npm run build (package.json)" in content
    assert "## 注意事项" in content
    # 质量标准:精炼(<100 行)、命令带来源、无泛泛建议标题
    assert len(content.splitlines()) < 100


def test_existing_human_content_preserved_only_managed_added(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "package.json").write_text('{"scripts": {"test": "vitest run"}}', encoding="utf-8")
    human = "# 我们团队的手写规则\n\n- 提交信息用中文\n- main 分支禁止 force push\n"
    (ws / "AGENTS.md").write_text(human, encoding="utf-8", newline="")

    proposal = build_proposal(str(ws))

    assert proposal["exists"] is True
    assert proposal["existing_content"] == human
    content = proposal["proposed_content"]
    # 人工内容逐字保留,且位于托管标记之前
    assert content.startswith(human.rstrip("\r\n"))
    assert human.rstrip("\r\n") in content
    assert content.index(human.strip()) < content.index(MANAGED_BEGIN)
    assert content.count(MANAGED_BEGIN) == 1 and content.count(MANAGED_END) == 1
    assert "提交信息用中文" in content
    assert "npm run test (package.json)" in content  # 托管区段补上了扫描到的命令


def test_proposal_refreshes_only_managed_section(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "package.json").write_text('{"scripts": {"test": "vitest run"}}', encoding="utf-8")
    human = "# 手写规则\n"
    stale = (
        f"{human}\n{MANAGED_BEGIN}\n# AGENTS.md\n\n- 旧命令:gone\n{MANAGED_END}\n"
    )
    (ws / "AGENTS.md").write_text(stale, encoding="utf-8", newline="")

    proposal = build_proposal(str(ws))
    content = proposal["proposed_content"]

    assert content.count(MANAGED_BEGIN) == 1 and content.count(MANAGED_END) == 1
    assert content.startswith("# 手写规则")
    assert "旧命令:gone" not in content
    assert "npm run test (package.json)" in content


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


def test_compute_diff_shows_added_and_removed_lines() -> None:
    diff = compute_diff("alpha\nbeta\n", "alpha\ngamma\n")

    assert diff.startswith("---")
    assert "+gamma" in diff
    assert "-beta" in diff


def test_compute_diff_empty_when_identical() -> None:
    assert compute_diff("same\n", "same\n") == ""
    assert compute_diff("", "") == ""


# ---------------------------------------------------------------------------
# apply_proposal:落盘、竞态防护、行尾保留
# ---------------------------------------------------------------------------


def test_apply_writes_new_file_and_is_guarded(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "package.json").write_text('{"scripts": {"build": "tsc"}}', encoding="utf-8")
    proposal = build_proposal(str(ws))

    # 新文件:expected_existing=None 表示"应当不存在"
    ok = apply_proposal(str(ws), proposal["proposed_content"], None)
    assert ok["written"] is True
    assert Path(ok["path"]) == ws / "AGENTS.md"
    assert (ws / "AGENTS.md").read_text(encoding="utf-8") == proposal["proposed_content"]

    # 磁盘已变化(不再是"不存在")→ 拒绝
    stale = apply_proposal(str(ws), proposal["proposed_content"], None)
    assert stale["written"] is False
    assert "文件已被修改" in stale["error"]


def test_apply_rejects_content_mismatch_and_keeps_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("当前真实内容\n", encoding="utf-8")

    result = apply_proposal(str(ws), "提案内容\n", "过期的预期内容\n")

    assert result["written"] is False
    assert "文件已被修改" in result["error"]
    assert (ws / "AGENTS.md").read_text(encoding="utf-8") == "当前真实内容\n"


def test_apply_preserves_crlf_line_endings(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "package.json").write_text('{"scripts": {"test": "vitest run"}}', encoding="utf-8")
    human_crlf = "# 手写规则\r\n\r\n- 中文提交\r\n"
    (ws / "AGENTS.md").write_bytes(human_crlf.encode("utf-8"))

    proposal = build_proposal(str(ws))
    result = apply_proposal(str(ws), proposal["proposed_content"], human_crlf)

    assert result["written"] is True
    raw = (ws / "AGENTS.md").read_bytes().decode("utf-8")
    assert "- 中文提交" in raw
    # 人工段与托管段都是 CRLF(没有混入裸 LF)
    managed_part = raw[raw.index(MANAGED_BEGIN):]
    assert "\r\n" in managed_part
    assert managed_part.count("\n") == managed_part.count("\r\n")


# ---------------------------------------------------------------------------
# 幂等:二次运行提案 == 磁盘内容,diff 为空
# ---------------------------------------------------------------------------


def test_second_run_is_idempotent(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)

    first = build_proposal(str(ws))
    # 全新文件:expected_existing=None 表示"应当不存在"
    assert apply_proposal(str(ws), first["proposed_content"], None)["written"]

    second = build_proposal(str(ws))
    on_disk = (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert second["proposed_content"] == on_disk
    assert second["exists"] is True
    assert compute_diff(second["existing_content"], second["proposed_content"]) == ""


def test_second_run_idempotent_with_crlf_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    human_crlf = "# 手写规则\r\n- 只用 pnpm\r\n"
    (ws / "AGENTS.md").write_bytes(human_crlf.encode("utf-8"))

    first = build_proposal(str(ws))
    assert first["proposed_content"] != first["existing_content"]
    assert apply_proposal(str(ws), first["proposed_content"], first["existing_content"])["written"]

    second = build_proposal(str(ws))
    on_disk = (ws / "AGENTS.md").read_bytes().decode("utf-8")  # 不翻译行尾
    assert second["proposed_content"] == on_disk
    assert compute_diff(second["existing_content"], second["proposed_content"]) == ""


# ---------------------------------------------------------------------------
# workspace 校验
# ---------------------------------------------------------------------------


def test_nonexistent_workspace_errors(tmp_path: Path) -> None:
    missing = tmp_path / "nope"

    try:
        scan_workspace(str(missing))
        raised_scan = False
    except ValueError as exc:
        raised_scan = True
        assert "不存在" in str(exc)
    assert raised_scan

    try:
        build_proposal(str(missing))
        raised_build = False
    except ValueError as exc:
        raised_build = True
        assert "不存在" in str(exc)
    assert raised_build

    result = apply_proposal(str(missing), "x", None)
    assert result["written"] is False
    assert "不存在" in result["error"]
    assert not (missing / "AGENTS.md").exists()  # 不静默建目录


# ---------------------------------------------------------------------------
# 路由(全新 FastAPI,不导入 atlas.server)
# ---------------------------------------------------------------------------


def _fresh_app() -> FastAPI:
    app = FastAPI()
    register_init_routes(app)
    return app


async def test_init_routes_preview_and_apply(tmp_path: Path) -> None:
    ws = _make_workspace(tmp_path)
    app = _fresh_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preview = await client.post("/api/init/preview", json={"workspace": str(ws)})
        assert preview.status_code == 200
        body = preview.json()
        for key in ("path", "exists", "existing_content", "proposed_content", "scan", "diff"):
            assert key in body
        assert body["exists"] is False
        assert MANAGED_BEGIN in body["proposed_content"]
        assert "+# AGENTS.md" in body["diff"]

        applied = await client.post("/api/init/apply", json={
            "workspace": str(ws),
            "content": body["proposed_content"],
            "expected_existing": None,
        })
        assert applied.status_code == 200
        assert applied.json()["written"] is True

        again = await client.post("/api/init/preview", json={"workspace": str(ws)})
        assert again.status_code == 200
        assert again.json()["diff"] == ""  # 幂等

        stale_apply = await client.post("/api/init/apply", json={
            "workspace": str(ws),
            "content": body["proposed_content"],
            "expected_existing": None,  # 文件现已存在 → 竞态防护生效
        })
        assert stale_apply.status_code == 422
        assert "文件已被修改" in stale_apply.json()["detail"]


async def test_init_routes_reject_invalid_workspace(tmp_path: Path) -> None:
    app = _fresh_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post(
            "/api/init/preview", json={"workspace": str(tmp_path / "nope")},
        )
        empty = await client.post("/api/init/preview", json={"workspace": ""})
        apply_missing = await client.post("/api/init/apply", json={
            "workspace": str(tmp_path / "nope"), "content": "x", "expected_existing": None,
        })

    assert missing.status_code == 422
    assert "不存在" in missing.json()["detail"]
    assert empty.status_code == 422
    assert "workspace" in empty.json()["detail"]
    assert apply_missing.status_code == 422
    assert "不存在" in apply_missing.json()["detail"]
