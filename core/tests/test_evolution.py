"""X5 自动追新测试（无网络）。

- 用本地临时 git 仓库充当假上游（commit + tag），本地镜像走 clone；
- 需要网络的取数一律注入 fake fetcher 或 monkeypatch，绝不真实访问 GitHub；
- E2 分类五类、E3 建议形状、E4 草稿、E5 批准→worktree 分支（git 不可用则跳过）、
  以及离线行为（中文错误 + 缓存继续服务）与路由契约。
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from atlas.evolution import branch_flow, capability_diff, parity_mapper, taskbook_draft
from atlas.evolution.watcher import (
    EvolutionStore,
    UpstreamUnavailable,
    run_check,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 假上游 / 假 Atlas 仓库
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc.stdout.strip()


def _commit(repo: Path, message: str, file_name: str = "a.txt") -> str:
    (repo / file_name).write_text(message, encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", message, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture()
def upstream(tmp_path: Path) -> Path:
    """带两个提交和一个注释标签的假上游。"""
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "tester", cwd=repo)
    _commit(repo, "feat(tool_search): lazy tool catalog")
    _git("tag", "-a", "v1.0.0", "-m", "release v1.0.0", cwd=repo)
    _commit(repo, "feat(context): better compaction")
    return repo


@pytest.fixture()
def mirror(tmp_path: Path, upstream: Path) -> Path:
    clone = tmp_path / "mirror"
    _git("clone", "--quiet", str(upstream), str(clone), cwd=tmp_path)
    _git("remote", "add", "upstream", str(upstream), cwd=clone)
    _git("config", "user.email", "t@example.com", cwd=clone)
    _git("config", "user.name", "tester", cwd=clone)
    return clone


@pytest.fixture()
def evo_root(tmp_path: Path, monkeypatch) -> Path:
    """把 evolution 数据根指到 tmp（conftest 已隔离 ATLAS_DATA_DIR，这里再收紧一层）。"""
    root = tmp_path / "evolution-data"
    monkeypatch.setattr("atlas.evolution.watcher.evolution_root", lambda: root)
    return root


def _store(evo_root: Path, **source_extra: str) -> EvolutionStore:
    store = EvolutionStore(root=evo_root)
    store.add_source({
        "id": "fake-up", "repo": "fake/upstream", "kind": "commit",
        "mirror_path": str(Path(source_extra.pop("mirror_path"))),
        "remote": source_extra.pop("remote", "upstream"), "ref": "main", **source_extra,
    })
    return store


# ---------------------------------------------------------------------------
# E1 watcher
# ---------------------------------------------------------------------------


class TestWatcher:
    def test_local_git_commits_incremental(self, evo_root, upstream, mirror) -> None:
        store = _store(evo_root, mirror_path=mirror)
        first = run_check(store, now=NOW)
        assert first["ok"] is True
        assert first["results"][0]["new_entries"] == 2
        newest = _git("rev-parse", "HEAD", cwd=upstream)
        assert store.get_state("fake-up")["last_id"] == newest
        entries = store.cached_entries("fake-up")
        assert entries[0]["id"] == newest  # 最新在前
        assert entries[0]["files"], "本地 git 应带出变更文件"

        # 上游前进一格 → 只出 1 条新条目；再跑一轮无新增。
        _commit(upstream, "fix(repetition): guard loops")
        second = run_check(store, now=NOW)
        assert second["results"][0]["new_entries"] == 1
        third = run_check(store, now=NOW)
        assert third["results"][0]["new_entries"] == 0

    def test_local_tags(self, evo_root, upstream, mirror) -> None:
        store = _store(evo_root, mirror_path=mirror, kind="tag")
        first = run_check(store, now=NOW)
        assert first["results"][0]["new_entries"] == 1
        assert store.cached_entries("fake-up")[0]["id"] == "v1.0.0"
        _git("tag", "-a", "v2.0.0", "-m", "release v2", cwd=upstream)
        second = run_check(store, now=NOW)
        assert second["results"][0]["new_entries"] == 1

    def test_offline_keeps_cache_and_reports_chinese(self, evo_root, mirror) -> None:
        store = _store(evo_root, mirror_path=mirror)
        run_check(store, now=NOW)  # 先成功一轮，留缓存
        cached = store.cached_entries("fake-up")
        assert cached

        def offline(source, last_id):  # noqa: ANN001
            raise UpstreamUnavailable(
                "上游 fake/upstream 暂不可达（离线或网络超时），本次使用缓存数据")

        summary = run_check(store, fetcher=offline, now=NOW)
        assert summary["ok"] is False
        assert "暂不可达" in summary["errors"][0]
        assert store.cached_entries("fake-up") == cached, "离线时缓存不得被动"

    def test_sources_crud_and_defaults(self, evo_root) -> None:
        store = EvolutionStore(root=evo_root)
        store.ensure_defaults()
        ids = {s["id"] for s in store.list_sources()}
        assert {"hermes-agent", "codex", "claude-code", "opencode", "pi-mono",
                "browser-use", "stagehand"} <= ids
        claude = store.get_source("claude-code")
        assert claude["kind"] == "release", "claude-code 只看 releases"
        with pytest.raises(ValueError, match="owner/name"):
            store.add_source({"repo": "no-slash"})
        with pytest.raises(ValueError, match="kind"):
            store.add_source({"repo": "a/b", "kind": "rss"})
        assert store.add_source({"repo": "x/y", "id": "extra"})["id"] == "extra"
        assert store.remove_source("extra") is True
        assert store.get_source("extra") is None

    def test_missing_mirror_is_graceful(self, evo_root, tmp_path) -> None:
        store = _store(evo_root, mirror_path=tmp_path / "nope")
        summary = run_check(store, now=NOW)
        assert summary["ok"] is False
        assert "本地镜像不存在" in summary["errors"][0]


# ---------------------------------------------------------------------------
# E2 capability diff
# ---------------------------------------------------------------------------


def _entry(**kw: object) -> dict:
    base = {"id": "e1", "kind": "commit", "repo": "fake/up", "ref": "main",
            "title": "", "subject": "", "body": "", "files": [], "source": "fake-up"}
    base.update(kw)
    return base


class TestCapabilityDiff:
    def test_new_when_missing(self) -> None:
        diff = capability_diff.classify_entry(
            _entry(subject="feat(mcp-ui): render mcp apps inside chat"))
        assert diff["cls"] == "NEW"
        assert diff["capabilities"][0]["id"] == "F1"

    def test_better_when_partial(self) -> None:
        diff = capability_diff.classify_entry(
            _entry(subject="mcp: oauth discovery and health checks"))
        assert diff["cls"] == "BETTER_THAN_ATLAS"
        assert diff["capabilities"][0]["id"] == "E1"

    def test_already_have(self) -> None:
        diff = capability_diff.classify_entry(
            _entry(subject="worktree: speed up worktree add"))
        assert diff["cls"] == "ALREADY_HAVE"
        assert diff["capabilities"][0]["id"] == "P3"

    def test_regression_removed_never_advises_removal(self) -> None:
        diff = capability_diff.classify_entry(_entry(
            subject="remove tool_search module from tools",
            files=["tools/tool_search.py"]))
        assert diff["cls"] == "REGRESSION_REMOVED"
        assert diff["advisory"] is False
        assert "不建议" in diff["reason"]

    def test_irrelevant(self) -> None:
        diff = capability_diff.classify_entry(_entry(subject="chore: bump version"))
        assert diff["cls"] == "IRRELEVANT"
        assert diff["advisory"] is False

    def test_path_only_match(self) -> None:
        diff = capability_diff.classify_entry(_entry(
            subject="refactor internals", files=["agent/context_compressor.py"]))
        assert diff["cls"] in ("ALREADY_HAVE", "BETTER_THAN_ATLAS")
        assert diff["capabilities"][0]["id"] == "X1"
        assert diff["matched_files"] == ["agent/context_compressor.py"]

    def test_removal_by_upstream_does_not_delete_from_map(self) -> None:
        """上游删除能力后，映射表与建议仍完整（只记录，不自动改表）。"""
        before = len(capability_diff.CAPABILITY_MAP)
        capability_diff.classify_entry(_entry(
            subject="delete repetition guard entirely", files=["agent/repetition_guard.py"]))
        assert len(capability_diff.CAPABILITY_MAP) == before


# ---------------------------------------------------------------------------
# E3 parity mapper
# ---------------------------------------------------------------------------


class TestParity:
    def _diffs(self) -> list[dict]:
        return [
            capability_diff.classify_entry(_entry(
                subject="feat(mcp-ui): mcp apps renderer", id="a1")),
            capability_diff.classify_entry(_entry(
                subject="mcp: health sampling improvements", id="a2")),
            capability_diff.classify_entry(_entry(
                subject="worktree: polish worktree add", id="a3")),
            capability_diff.classify_entry(_entry(
                subject="remove tool_search module", files=["tools/tool_search.py"], id="a4")),
            capability_diff.classify_entry(_entry(subject="chore: bump", id="a5")),
        ]

    def test_row_shape_and_suggestions(self) -> None:
        rows = parity_mapper.build_parity_rows(diffs=self._diffs())
        by_class = {row["entry_id"]: row["suggestion"] for row in rows}
        assert by_class["a1"] == "REPLACE"   # NEW → 引入上游实现
        assert by_class["a2"] == "UPGRADE"   # BETTER
        assert by_class["a3"] == "KEEP"      # ALREADY_HAVE
        assert by_class["a4"] == "KEEP"
        regression = next(row for row in rows if row["entry_id"] == "a4")
        assert regression["advisory"] is False
        assert "a5" not in by_class, "IRRELEVANT 不产生建议行"
        row = rows[0]
        for key in ("capability_id", "capability", "source", "repo", "repo_file",
                    "why_stronger", "atlas_implementation", "suggestion"):
            assert key in row

    def test_patch_proposal_is_text_only(self, tmp_path) -> None:
        rows = parity_mapper.build_parity_rows(diffs=self._diffs())
        patch = parity_mapper.render_parity_patch(rows, generated_on=NOW.date())
        assert isinstance(patch, str)
        assert "*** Begin Patch" in patch and "*** End Patch" in patch
        assert "未写入 docs/plan" in patch
        # docs/plan 对本模块只读：没有任何写盘路径参数。
        import inspect

        for func in (parity_mapper.build_parity_rows, parity_mapper.render_parity_patch):
            params = inspect.signature(func).parameters
            assert all("docs" not in p for p in params)


# ---------------------------------------------------------------------------
# E4 taskbook drafts
# ---------------------------------------------------------------------------


class TestDrafts:
    def test_generate_and_index(self, evo_root, tmp_path, monkeypatch) -> None:
        drafts_dir = tmp_path / "taskbooks"
        monkeypatch.setattr("atlas.evolution.taskbook_draft.drafts_root", lambda: drafts_dir)
        created = taskbook_draft.generate_drafts(entries=[
            _entry(subject="feat(mcp-ui): mcp apps renderer", id="a1", published_at="2026-10-01"),
            _entry(subject="chore: bump", id="a2"),
        ], generated_on=NOW.date())
        assert len(created) == 1
        record = created[0]
        assert record["id"] == f"ATLAS-AUTO-20261003-{record['id'].split('-', 3)[3]}"
        path = Path(record["file"])
        assert path.exists() and path.name.endswith(".draft.md")
        text = path.read_text(encoding="utf-8")
        for section in ("## 来源", "## Atlas 集成点", "## 可能改动文件", "## 聚焦验收标准"):
            assert section in text
        assert "fake/up" in text and "草稿" in text
        index = taskbook_draft.load_index()
        assert index["drafts"][record["id"]]["status"] == "draft"
        listed = taskbook_draft.list_drafts()
        assert listed[0]["exists"] is True

    def test_regenerate_keeps_approved(self, evo_root, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("atlas.evolution.taskbook_draft.drafts_root",
                            lambda: tmp_path / "tb")
        taskbook_draft.generate_drafts(entries=[
            _entry(subject="feat(mcp-ui): mcp apps renderer", id="a1")],
            generated_on=NOW.date())
        draft_id = taskbook_draft.list_drafts()[0]["id"]
        taskbook_draft.set_draft_status(draft_id, "approved", branch="atlas-auto/x")
        again = taskbook_draft.generate_drafts(entries=[
            _entry(subject="feat(mcp-ui): mcp apps renderer", id="a1")],
            generated_on=NOW.date())
        assert again[0]["status"] == "approved"
        assert again[0]["branch"] == "atlas-auto/x"


# ---------------------------------------------------------------------------
# E5 branch flow
# ---------------------------------------------------------------------------


GIT_AVAILABLE = shutil.which("git") is not None


def _make_atlas_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "atlas-repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "tester", cwd=repo)
    _commit(repo, "init atlas")
    return repo


def _seed_draft(draft_id: str) -> None:
    index = {"drafts": {draft_id: {
        "id": draft_id, "capability_id": "X1", "capability": "自动上下文压缩",
        "source": "fake-up", "repo": "fake/upstream", "repo_file": "agent/context_compressor.py",
        "ref": "abc123", "suggestion": "UPGRADE", "status": "draft",
        "file": f"/nonexistent/{draft_id}.draft.md", "created_at": "2026-10-03T00:00:00+00:00",
        "branch": None,
    }}}
    taskbook_draft.save_index(index)


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git 不可用")
class TestBranchFlow:
    def test_approve_creates_isolated_worktree(self, evo_root, tmp_path) -> None:
        repo = _make_atlas_repo(tmp_path)
        draft_id = "ATLAS-AUTO-20261003-x1-fake-up"
        _seed_draft(draft_id)
        main_before = _git("rev-parse", "main", cwd=repo)
        head_before = _git("rev-parse", "HEAD", cwd=repo)

        result = branch_flow.approve_draft(draft_id, repo=repo)

        assert result["ok"] is True
        assert result["branch"] == "atlas-auto/20261003-x1-fake-up"
        worktree = Path(result["worktree"])
        assert worktree.is_dir()
        proposal = Path(result["merge_proposal"]).read_text(encoding="utf-8")
        assert "不会自动合并" in proposal and "merge --no-ff" in proposal
        assert (worktree / ".git").exists()
        # main 与主工作区完全未动。
        assert _git("rev-parse", "main", cwd=repo) == main_before
        assert _git("rev-parse", "HEAD", cwd=repo) == head_before
        assert _git("symbolic-ref", "--short", "HEAD", cwd=repo) == "main"
        # 记录与草稿状态。
        record = branch_flow.get_branch("20261003-x1-fake-up")
        assert record and record["status"] == "proposal" and record["base"] == "main"
        draft = taskbook_draft.get_draft(draft_id)
        assert draft["status"] == "approved" and draft["branch"] == result["branch"]
        assert (evo_root / "branches.json").exists()

        again = branch_flow.approve_draft(draft_id, repo=repo)
        assert again["ok"] is False and "已批准" in again["reason"]

    def test_missing_draft_and_non_git_repo(self, evo_root, tmp_path) -> None:
        missing = branch_flow.approve_draft("ATLAS-AUTO-20261003-none", repo=tmp_path)
        assert missing["ok"] is False and "未找到草稿" in missing["reason"]

        plain = tmp_path / "plain"
        plain.mkdir()
        draft_id = "ATLAS-AUTO-20261003-x2-notgit"
        _seed_draft(draft_id)
        result = branch_flow.approve_draft(draft_id, repo=plain)
        assert result["ok"] is False and "不是 git 仓库" in result["reason"]
        assert taskbook_draft.get_draft(draft_id)["status"] == "draft"


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(evo_root, tmp_path, monkeypatch):
    from fastapi import FastAPI

    from atlas.api.evolution_router import evolution_router

    monkeypatch.setattr("atlas.evolution.taskbook_draft.drafts_root",
                        lambda: tmp_path / "taskbooks")
    monkeypatch.setattr("atlas.evolution.branch_flow._default_repo",
                        lambda: _atlas_repo_holder["repo"])
    _atlas_repo_holder["repo"] = None
    app = FastAPI()
    app.include_router(evolution_router)
    return TestClient(app)


_atlas_repo_holder: dict = {"repo": None}


class TestRouter:
    def test_sources_endpoints(self, client: TestClient) -> None:
        payload = client.get("/api/evolution/sources").json()
        ids = {s["id"] for s in payload["sources"]}
        assert "hermes-agent" in ids and "codex" in ids
        resp = client.post("/api/evolution/sources", json={"repo": "bad"})
        assert resp.status_code == 400 and "owner/name" in resp.json()["detail"]
        resp = client.post("/api/evolution/sources", json={"repo": "a/b", "id": "x"})
        assert resp.status_code == 200 and resp.json()["source"]["id"] == "x"
        assert client.delete("/api/evolution/sources/x").json()["ok"] is True
        assert client.delete("/api/evolution/sources/x").status_code == 404

    def test_check_offline_serves_cached_diffs(self, client: TestClient, evo_root,
                                               monkeypatch) -> None:
        def offline(source, last_id):  # noqa: ANN001
            raise UpstreamUnavailable(
                "上游 openai/codex 暂不可达（离线或网络超时），本次使用缓存数据")

        monkeypatch.setattr("atlas.evolution.watcher.default_fetcher", offline)
        summary = client.post("/api/evolution/check").json()
        assert summary["ok"] is False
        assert all("暂不可达" in err for err in summary["errors"])

        # 预置缓存条目后，/diffs 与 /parity 照常服务（离线可用）。
        store = EvolutionStore(root=evo_root)
        store.append_entries("codex", [_entry(
            subject="feat(mcp-ui): mcp apps renderer", id="abc", repo="openai/codex",
            source="codex")])
        store.save()

        diffs = client.get("/api/evolution/diffs").json()
        assert diffs["total_entries"] == 1
        assert diffs["counts"]["NEW"] == 1
        assert all(d["cls"] != "IRRELEVANT" for d in diffs["diffs"])

        parity = client.get("/api/evolution/parity").json()
        assert parity["rows"] and parity["rows"][0]["suggestion"] == "REPLACE"
        assert "patch_proposal" in parity

    def test_draft_generate_list_approve_flow(self, client: TestClient, evo_root,
                                              tmp_path, monkeypatch) -> None:
        if not GIT_AVAILABLE:
            pytest.skip("git 不可用")
        store = EvolutionStore(root=evo_root)
        store.data["sources"].append({"id": "codex", "repo": "openai/codex",
                                      "kind": "commit", "remote": "origin", "ref": "main"})
        store.append_entries("codex", [_entry(
            subject="feat(mcp-ui): mcp apps renderer", id="abc", repo="openai/codex",
            source="codex")])
        store.save()
        created = client.post("/api/evolution/drafts/generate").json()
        assert created["ok"] is True and len(created["created"]) == 1
        drafts = client.get("/api/evolution/drafts").json()["drafts"]
        assert drafts and drafts[0]["status"] == "draft"

        repo = _make_atlas_repo(tmp_path)
        _atlas_repo_holder["repo"] = repo
        main_before = _git("rev-parse", "main", cwd=repo)
        draft_id = drafts[0]["id"]
        result = client.post(f"/api/evolution/drafts/{draft_id}/approve", json={"base": None})
        assert result.status_code == 200 and result.json()["ok"] is True
        assert result.json()["branch"].startswith("atlas-auto/")
        assert _git("rev-parse", "main", cwd=repo) == main_before, "main 绝不被触碰"

        branches = client.get("/api/evolution/branches").json()["branches"]
        assert branches and branches[0]["draft_id"] == draft_id
        # 重复批准 → 中文提示，不出新分支。
        dup = client.post(f"/api/evolution/drafts/{draft_id}/approve", json={}).json()
        assert dup["ok"] is False and "已批准" in dup["reason"]
        assert client.post("/api/evolution/drafts/ATLAS-AUTO-nope/approve",
                           json={}).status_code == 404

    def test_candidates_endpoints(self, client: TestClient) -> None:
        resp = client.post("/api/evolution/candidates/from-runs", json={
            "name": "deploy-check", "description": "部署前检查", "min_runs": 3,
            "run_results": [{"run_id": "r1", "success": True},
                            {"run_id": "r2", "success": True}],
        }).json()
        assert resp["created"] is False and "不足" in resp["reason"]

        resp = client.post("/api/evolution/candidates/from-recording", json={
            "bundle": {"name": "login-flow", "description": "登录流程",
                       "steps": ["打开页面", "填表单"], "assets": ["shot.png"]},
        }).json()
        assert resp["created"] is True
        candidate_id = resp["candidate"]["id"]

        approve = client.post(f"/api/evolution/candidates/{candidate_id}/approve").json()
        assert approve["ok"] is True
        bundle = approve["bundle"]
        assert bundle["name"] == "login-flow"
        assert "打开页面" in bundle["instructions"]
        assert bundle["metadata"]["curator"] == "atlas-evolution"
        listed = client.get("/api/evolution/candidates").json()["candidates"]
        assert listed[0]["status"] == "approved"
