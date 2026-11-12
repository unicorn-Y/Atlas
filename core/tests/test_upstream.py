"""组件追新（atlas.upstream）：清单解析、合并、验证判定、设置与接口。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from atlas.upstream import check, forks, inventory, postmerge, provenance, staging
from atlas.upstream.classify import normalize_pip, npm_category, pip_category
from atlas.upstream.model import HELD, LATEST, OUTDATED, Component

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 来源标注
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("header", "repo", "sha", "path"), [
    ("# Ported from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:\n"
     "# agent/error_classifier.py (MIT, (c) Nous Research).\n",
     "NousResearch/hermes-agent", "663362680b6ffa4fbffeb58f6682564239a1953b",
     "agent/error_classifier.py"),
    ("# Ported from NousResearch/hermes-agent agent/lsp/client.py @ 562ad75baec0 (MIT).\n",
     "NousResearch/hermes-agent", "562ad75baec0", "agent/lsp/client.py"),
    ('"""x\n\n# Ported from NousResearch/hermes-agent @ c8301ea6c9 '
     "(plugins/platforms/wecom/x.py)\n",
     "NousResearch/hermes-agent", "c8301ea6c9", "plugins/platforms/wecom/x.py"),
    ("# Ported from NousResearch/hermes-agent@e287231:agent/review_engine.py (MIT).\n",
     "NousResearch/hermes-agent", "e287231", "agent/review_engine.py"),
    ("# Vendored from mastra-ai/mastra commit 9c2e4c7cde40a4321112e24affd1750e9be827f9, "
     "packages/memory/src/observer-agent.ts.\n",
     "mastra-ai/mastra", "9c2e4c7cde40a4321112e24affd1750e9be827f9",
     "packages/memory/src/observer-agent.ts"),
    ('"""Guards.\n\nPorted from OpenClaw (source freeze ``3e5560873a4``):\n\n'
     "- ``src/infra/heartbeat-active-hours.ts`` -> x\n",
     "openclaw/openclaw", "3e5560873a4", "src/infra/heartbeat-active-hours.ts"),
])
def test_parse_header_formats(header: str, repo: str, sha: str, path: str) -> None:
    record = provenance.parse_header(header, "core/x.py")
    assert record is not None
    assert (record.repo, record.sha, record.path) == (repo, sha, path)


def test_profiles_do_not_share_staging_workspace(tmp_path: Path) -> None:
    from atlas.upstream.staging import staging_root

    repo = tmp_path / "Atlas"
    first = staging_root(repo, tmp_path / "profile-one" / "upstream")
    second = staging_root(repo, tmp_path / "profile-two" / "upstream")
    assert first != second
    assert first == tmp_path / "profile-one" / "upstream" / "staging"
    assert second == tmp_path / "profile-two" / "upstream" / "staging"


def test_parse_header_ignores_mentions_without_commit() -> None:
    assert provenance.parse_header('"""Normalized (ported from the hermes handler)."""\n') is None
    assert provenance.parse_header("import os\n") is None


def test_replace_sha_only_touches_header() -> None:
    text = "# Ported from a/b@1111111111 x/y.py\nvalue = '1111111111'\n"
    record = provenance.parse_header(text, "f.py")
    assert record is not None
    out = provenance.replace_sha(text, record, "2" * 40)
    assert out.splitlines()[0].endswith(f"a/b@{'2' * 40} x/y.py")
    assert out.splitlines()[1] == "value = '1111111111'"


def test_scan_repo_finds_ported_files(tmp_path: Path) -> None:
    pkg = tmp_path / "core" / "atlas"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("# Ported from o/r@abcdef1234: src/a.py (MIT)\n", encoding="utf-8")
    (pkg / "b.py").write_text("x = 1\n", encoding="utf-8")
    tests = pkg / "tests"
    tests.mkdir()
    (tests / "c.py").write_text("# Ported from o/r@abcdef1234: src/c.py\n", encoding="utf-8")
    found = provenance.scan(tmp_path)
    assert [record.file for record in found] == ["core/atlas/a.py"]


# ---------------------------------------------------------------------------
# 分类与版本改写
# ---------------------------------------------------------------------------

def test_classification_defaults_cover_new_packages() -> None:
    assert normalize_pip("Foo_Bar.baz") == "foo-bar-baz"
    assert pip_category("browser-use") == "automation"
    assert pip_category("something-new") == "backend"
    assert pip_category("pytest", "dev") == "dev"
    assert npm_category("@radix-ui/react-dialog") == "desktop"
    assert npm_category("@types/node", dev=True) == "dev"
    assert npm_category("electron", dev=True) == "runtime"


def test_set_pip_pin_rewrites_exact_pins_only(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('deps = [\n  "browser-use==0.13.10",\n  "fastapi>=0.115.0",\n'
                         '  "uvicorn[standard]==0.30.0",\n]\n', encoding="utf-8")
    assert staging.set_pip_pin(pyproject, "browser_use", "0.13.11")
    assert not staging.set_pip_pin(pyproject, "fastapi", "1.0")
    assert staging.set_pip_pin(pyproject, "uvicorn", "0.31.0")
    text = pyproject.read_text(encoding="utf-8")
    assert '"browser-use==0.13.11"' in text
    assert '"fastapi>=0.115.0"' in text
    assert '"uvicorn[standard]==0.31.0"' in text


def test_set_atlas_pin(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    old = "a" * 40
    pyproject.write_text('[tool.atlas.engine]\nrepository = "x"\ncommit = "' + old
                         + '"\n\n[tool.ruff]\n', encoding="utf-8")
    staging.set_git_pin(pyproject, old, "b" * 40)
    text = pyproject.read_text(encoding="utf-8")
    assert f'commit = "{"b" * 40}"' in text
    # The rewrite must not disturb the rest of the file: the surrounding section
    # carries the fork URL and the ruff config that later stages still read.
    assert "[tool.ruff]" in text and 'repository = "x"' in text


def test_npm_spec_keeps_range_style() -> None:
    assert staging.npm_spec("^1.2.3", "2.0.0") == "^2.0.0"
    assert staging.npm_spec("~1.2.3", "1.3.0") == "~1.3.0"
    assert staging.npm_spec("1.2.3", "2.0.0") == "2.0.0"


def test_set_npm_version_updates_manifest_allow_scripts_and_mcp(tmp_path: Path) -> None:
    ws = staging.Workspace(repo=tmp_path, hermes_main=tmp_path, root=tmp_path / "s",
                           data=tmp_path / "d")
    (ws.atlas / "config").mkdir(parents=True)
    (ws.atlas / "package.json").write_text(json.dumps(
        {"dependencies": {"electron": "44.4.5"}, "allowScripts": {"electron@44.4.5": True}}),
        encoding="utf-8")
    (ws.atlas / "frontend").mkdir()
    (ws.atlas / "frontend" / "package.json").write_text(json.dumps(
        {"dependencies": {"@playwright/mcp": "0.0.45", "react": "^18.3.1"}}), encoding="utf-8")
    (ws.atlas / "config" / "atlas.example.toml").write_text(
        'args = ["--yes", "@playwright/mcp@0.0.45"]\n', encoding="utf-8")
    staging.set_npm_version(ws, {"name": "electron", "latest": "44.7.0",
                                 "locations": ["package.json"], "detail": {}})
    staging.set_npm_version(ws, {"name": "@playwright/mcp", "latest": "0.0.83",
                                 "locations": ["frontend/package.json"],
                                 "detail": {"mcp_refs": [{"file": "atlas.example.toml",
                                                          "version": "0.0.45"}]}})
    staging.set_npm_version(ws, {"name": "react", "latest": "19.3.0",
                                 "locations": ["frontend/package.json"], "detail": {}})
    root = json.loads((ws.atlas / "package.json").read_text(encoding="utf-8"))
    assert root["dependencies"]["electron"] == "44.7.0"
    assert root["allowScripts"] == {"electron@44.7.0": True}
    front = json.loads((ws.atlas / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert front["dependencies"] == {"@playwright/mcp": "0.0.83", "react": "^19.3.0"}
    assert "@playwright/mcp@0.0.83" in (ws.atlas / "config" / "atlas.example.toml").read_text(
        encoding="utf-8")


# ---------------------------------------------------------------------------
# 合并
# ---------------------------------------------------------------------------

def test_merge_text_combines_non_overlapping_changes() -> None:
    base = "a\nb\nc\nd\ne\n"
    ours = "a\nATLAS\nc\nd\ne\n"
    theirs = "a\nb\nc\nd\nUPSTREAM\n"
    merged, clean = forks.merge_text(ours, base, theirs)
    assert clean
    assert merged == "a\nATLAS\nc\nd\nUPSTREAM\n"


def test_merge_text_reports_conflict() -> None:
    _merged, clean = forks.merge_text("x\nATLAS\n", "x\nbase\n", "x\nUPSTREAM\n")
    assert not clean


def test_merge_text_keeps_windows_line_endings() -> None:
    merged, clean = forks.merge_text("a\r\nATLAS\r\nc\r\nd\r\n", "a\nb\nc\nd\n", "a\nb\nc\nUP\n")
    assert clean
    assert merged == "a\r\nATLAS\r\nc\r\nUP\r\n"


# ---------------------------------------------------------------------------
# 验证判定
# ---------------------------------------------------------------------------

def test_regressions_compare_against_baseline() -> None:
    base = {"import_ok": True, "pip_conflicts": ["x 1 has y"], "failures": ["t::a"], "ran": True}
    same = {"import_ok": True, "pip_conflicts": ["x 1 has y"], "failures": ["t::a"], "ran": True}
    assert staging.regressions("python", base, same) == []
    worse = {"import_ok": True, "pip_conflicts": ["x 1 has y", "z 2 has w"],
             "failures": ["t::a", "t::b"], "ran": True}
    problems = staging.regressions("python", base, worse)
    assert any("依赖冲突" in p for p in problems)
    assert any("t::b" in p for p in problems)
    assert staging.regressions("frontend", {"build_ok": True, "failures": [], "ran": True},
                               {"build_ok": False, "build_error": "TS2322", "failures": []})


def test_same_major_splits_risky_updates() -> None:
    assert staging.same_major({"kind": "npm", "current": "1.1.20", "latest": "1.1.21"})
    assert not staging.same_major({"kind": "npm", "current": "18.3.1", "latest": "19.3.0"})
    assert not staging.same_major({"kind": "pip", "current": "0.13.10", "latest": "0.14.0"})
    assert staging.same_major({"kind": "npm", "current": "0.0.45", "latest": "0.0.83"})
    assert not staging.same_major({"kind": "fork", "current": "a", "latest": "a"})


def test_relink_junctions_points_into_destination(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "pkg").mkdir(parents=True)
    (src / "node_modules" / "@atlas").mkdir(parents=True)
    (dst / "pkg").mkdir(parents=True)
    (dst / "node_modules" / "@atlas").mkdir(parents=True)
    link = src / "node_modules" / "@atlas" / "pkg"
    try:
        link.symlink_to(src / "pkg", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted here")
    staging.relink_junctions(src, dst, "node_modules")
    created = dst / "node_modules" / "@atlas" / "pkg"
    assert staging.is_link(created)
    assert created.resolve() == (dst / "pkg").resolve()


def test_mirror_never_deletes_through_workspace_links(tmp_path: Path) -> None:
    repo, snap = tmp_path / "repo", tmp_path / "snap"
    (repo / "frontend").mkdir(parents=True)
    (repo / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (repo / "node_modules" / "@atlas").mkdir(parents=True)
    (snap / "@atlas").mkdir(parents=True)  # snapshot taken with links skipped
    (snap / "left-pad").mkdir()
    link = repo / "node_modules" / "@atlas" / "frontend"
    if staging.IS_WIN:
        staging.sources.run(["cmd", "/c", "mklink", "/J", str(link), str(repo / "frontend")],
                            timeout=30)
    else:
        link.symlink_to(repo / "frontend", target_is_directory=True)
    # The link must exist before mirror() can be shown not to follow it; a
    # machine where mklink silently failed would otherwise make this test pass
    # while proving nothing.
    assert staging.is_link(link)
    staging.mirror(snap, repo / "node_modules")
    assert (repo / "frontend" / "package.json").exists()
    assert (repo / "node_modules" / "left-pad").is_dir()


def test_group_plan_orders_dependencies_before_their_transitives() -> None:
    components = [
        {"id": "npm:react", "kind": "npm"}, {"id": "pip-transitive:t", "kind": "pip-transitive"},
        {"id": "pip:x", "kind": "pip"}, {"id": "npm-transitive:r", "kind": "npm-transitive"},
    ]
    groups = staging.group_plan(
        components, ["npm:react", "pip-transitive:t", "pip:x", "npm-transitive:r"],
    )
    # A transitive pin is only meaningful once its direct dependency is settled,
    # so each transitive group must follow the group it derives from. `GROUPS`
    # order is the contract; anything else silently upgrades a package before
    # the thing that requires it.
    assert [group.key for group in groups] == [
        "pip", "pip-transitive", "npm", "npm-transitive",
    ]


# ---------------------------------------------------------------------------
# 设置、锁定、失败记忆
# ---------------------------------------------------------------------------

def _status(root: Path, components: list[Component]) -> None:
    (root / "status.json").write_text(json.dumps(
        {"checked_at": "2026-10-10T00:00:00+00:00",
         "components": [item.to_dict() for item in components]}), encoding="utf-8")


def test_holds_and_failures_shape_the_plan(tmp_path: Path) -> None:
    _status(tmp_path, [
        Component(id="pip:a", name="a", category="backend", kind="pip", current="1",
                  latest="2", status=OUTDATED),
        Component(id="pip:b", name="b", category="backend", kind="pip", current="1",
                  latest="2", status=OUTDATED),
        Component(id="pip:c", name="c", category="backend", kind="pip", current="1",
                  latest="2", status=OUTDATED),
        Component(id="pip:d", name="d", category="backend", kind="pip", current="1",
                  latest="1", status=LATEST),
    ])
    check.save_settings({"holds": {"pip:b": "等 React 19 适配"}}, tmp_path)
    check.record_failure("pip:c", "2", "tests failed", tmp_path)
    view = check.view(tmp_path)
    by_id = {item["id"]: item for item in view["components"]}
    assert by_id["pip:b"]["status"] == HELD and not by_id["pip:b"]["actionable"]
    assert by_id["pip:c"]["failed_latest"]
    assert check.auto_plan(tmp_path) == ["pip:a"]
    backend = next(c for c in view["summary"]["categories"] if c["id"] == "backend")
    assert backend["outdated"] == 2 and backend["actionable"] == 2
    check.clear_failure("pip:c", tmp_path)
    assert check.auto_plan(tmp_path) == ["pip:a", "pip:c"]


def test_settings_validation(tmp_path: Path) -> None:
    assert check.load_settings(tmp_path)["mode"] == "auto"
    with pytest.raises(ValueError):
        check.save_settings({"mode": "always"}, tmp_path)
    assert check.save_settings({"mode": "check", "interval_hours": 0}, tmp_path)[
        "interval_hours"] == 1


def test_check_due(tmp_path: Path) -> None:
    assert check.check_due(tmp_path)
    _status(tmp_path, [])
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    from datetime import UTC, datetime

    status["checked_at"] = datetime.now(UTC).isoformat()
    (tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")
    assert not check.check_due(tmp_path)
    check.save_settings({"mode": "off"}, tmp_path)
    assert not check.check_due(tmp_path)


# ---------------------------------------------------------------------------
# 扫描器（不联网）
# ---------------------------------------------------------------------------

def test_scan_mcp_merges_npm_dependency_and_reads_live_config(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "atlas.example.toml").write_text(
        '[tools.servers.playwright]\ncommand = "npx"\nargs = ["--yes", "@playwright/mcp@0.0.45"]\n'
        '[tools.servers.serena]\ncommand = "serena"\nargs = []\n', encoding="utf-8")
    live = tmp_path / "live.toml"
    live.write_text('[tools.servers.fs]\ncommand = "npx"\n'
                    'args = ["-y", "@modelcontextprotocol/server-filesystem", "~"]\n',
                    encoding="utf-8")
    npm_item = Component(id="npm:@playwright/mcp", name="@playwright/mcp", category="automation",
                         kind="npm")
    ctx = inventory.Context(repo=tmp_path, python="python", atlas_dir=tmp_path,
                            config_path=live, fetch=False)
    items = {item.id: item for item in inventory.scan_mcp(ctx, {npm_item.id: npm_item})}
    assert npm_item.detail["mcp_refs"][0]["version"] == "0.0.45"
    assert items["mcp:serena"].strategy == "manual"
    fs = items["mcp:@modelcontextprotocol/server-filesystem"]
    assert fs.status == LATEST and "未锁版本" in fs.note


def test_scan_git_pins_offline(tmp_path: Path) -> None:
    core = tmp_path / "core"
    core.mkdir()
    sha = "343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c"
    (core / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=[]\n[project.optional-dependencies]\n'
        f'learning = ["skillopt @ git+https://github.com/microsoft/SkillOpt@{sha}"]\n',
        encoding="utf-8")
    ctx = inventory.Context(repo=tmp_path, python="python", atlas_dir=tmp_path, fetch=False)
    [item] = inventory.scan_git_pins(ctx)
    assert item.id == "git:skillopt" and item.category == "learning"
    assert item.detail == {"repo": "microsoft/SkillOpt", "sha": sha}


def test_scan_all_turns_scanner_errors_into_rows(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_ctx: inventory.Context) -> list[Component]:
        raise RuntimeError("网络断了")

    for name in ("scan_pip", "scan_git_pins", "scan_npm", "scan_runtime",
                 "scan_borrowed"):
        monkeypatch.setattr(inventory, name, boom)
    ctx = inventory.Context(repo=tmp_path, python="python", atlas_dir=tmp_path, fetch=False)
    items = inventory.scan_all(ctx)
    assert {item.status for item in items} == {"error"}
    # Five scanners run independently — pip, git, npm, runtime, borrowed — and each
    # converts its own failure into a row. mcp does not: it runs last against the
    # npm results, so with npm failed it receives an empty mapping and returns
    # cleanly. A scanner that raises without recording would be a silent hole in
    # the inventory, so the count is asserted exactly rather than as "> 0".
    assert len(ctx.errors) == 5


# ---------------------------------------------------------------------------
# 合并后的本机收尾
# ---------------------------------------------------------------------------

def test_post_merge_syncs_live_mcp_versions(tmp_path: Path) -> None:
    example = tmp_path / "example.toml"
    example.write_text('args = ["--yes", "@playwright/mcp@0.0.83"]\n'
                       'args = ["--yes", "chrome-devtools-mcp@1.10.1", "--headless"]\n',
                       encoding="utf-8")
    live = tmp_path / "atlas.toml"
    live.write_text('args = ["--yes", "@playwright/mcp@0.0.45"]\n'
                    'args = ["--yes", "chrome-devtools-mcp@1.9.0", "--headless"]\n'
                    'args = ["-y", "other-mcp@3.0.0"]\n', encoding="utf-8")
    changed = postmerge.sync_mcp_versions(example, live)
    assert len(changed) == 2
    text = live.read_text(encoding="utf-8")
    assert "@playwright/mcp@0.0.83" in text and "chrome-devtools-mcp@1.10.1" in text
    assert "other-mcp@3.0.0" in text
    assert (tmp_path / "atlas.toml.bak-upstream").exists()


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api.upstream_router import upstream_router

    root = tmp_path / "upstream"
    root.mkdir()
    monkeypatch.setattr(check, "upstream_root", lambda: root)
    app = FastAPI()
    app.include_router(upstream_router)
    return TestClient(app)


def test_upstream_api_view_settings_and_holds(client) -> None:  # noqa: ANN001
    view = client.get("/api/upstream").json()
    assert {"components", "summary", "settings", "run", "checking", "supported"} <= set(view)
    response = client.put("/api/upstream/settings", json={"mode": "check"})
    assert response.status_code == 200 and response.json()["mode"] == "check"
    assert client.put("/api/upstream/settings", json={"mode": "bad"}).status_code == 400
    held = client.post("/api/upstream/holds", json={"id": "npm:react", "reason": "等适配"}).json()
    assert held["holds"] == {"npm:react": "等适配"}
    released = client.delete("/api/upstream/holds/npm:react").json()
    assert released["holds"] == {}
    nothing = client.post("/api/upstream/apply", json={"ids": ["npm:none"]}).json()
    assert nothing["started"] is False


# ---------------------------------------------------------------------------
# 任务锁
# ---------------------------------------------------------------------------

def test_run_skips_when_lock_held_and_keeps_the_lock(tmp_path: Path) -> None:
    """别的任务正持锁时要跳过，且不能把对方的锁删掉（否则并发两次会同时开跑）。"""
    import os

    (tmp_path / "job.lock").write_text(str(os.getpid()), encoding="utf-8")
    (tmp_path / "run.json").write_text('{"state": "running", "id": "other"}', encoding="utf-8")
    result = staging.run([], data_root=tmp_path, repo=tmp_path)
    assert result["state"] == "skipped"
    assert (tmp_path / "job.lock").exists()
    # 正在跑的那个任务的进度不能被这次跳过覆盖
    assert json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))["id"] == "other"


def test_stale_lock_with_recycled_pid_does_not_block(tmp_path: Path) -> None:
    """进程已死、PID 被系统复用的陈旧锁，不能永久挡住后续追新。"""
    import os
    import time

    lock = tmp_path / "job.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    old = time.time() - staging.JOB_LOCK_MAX_AGE_SECONDS - 60
    os.utime(lock, (old, old))
    result = staging.run([], data_root=tmp_path, repo=tmp_path)
    assert result["state"] != "skipped"
