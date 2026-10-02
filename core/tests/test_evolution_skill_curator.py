"""E6 技能自学/整理桥测试（无网络、无模型调用）。

覆盖：三类候选来源（重复成功运行 / 用户保存 / X2 录制包）、同名去重合并、
approve → 技能包、拒绝后不可直接批准且文件保留（curator 从不删除）、
维护操作（去重合并 / 按版本出处标过期 / 按闲置标 stale / 置顶跳过）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atlas.evolution.skill_curator import (
    DEFAULT_MIN_RUNS,
    SkillCurator,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=45)


@pytest.fixture()
def curator(tmp_path: Path) -> SkillCurator:
    return SkillCurator(directory=tmp_path / "candidates")


class TestCandidateCreation:
    def test_repeated_runs_gate_and_creation(self, curator: SkillCurator) -> None:
        runs = [{"run_id": f"r{i}", "success": True} for i in range(1, 3)]
        assert curator.create_candidate_from_runs(
            name="deploy", description="部署检查", run_results=runs) is None, \
            f"成功运行少于 {DEFAULT_MIN_RUNS} 次不得生成候选"
        runs.append({"run_id": "r3", "success": True})
        record = curator.create_candidate_from_runs(
            name="deploy", description="部署检查", run_results=runs,
            references=["tasks/results/r3.result.md"])
        assert record["origin"] == "repeated_runs"
        assert record["use_count"] == 3
        assert record["source_runs"] == ["r1", "r2", "r3"]
        assert record["status"] == "candidate"
        assert (curator.directory / "deploy.json").exists()

    def test_user_request_candidate(self, curator: SkillCurator) -> None:
        record = curator.create_candidate(
            name="weekly-report", description="周报模板", origin="user_request",
            parameters={"steps": ["汇总 commits", "写小结"]})
        assert record["id"] == "weekly-report"
        assert record["provenance"]["history"][0]["action"] == "created"

    def test_recording_bundle_candidate(self, curator: SkillCurator) -> None:
        record = curator.create_candidate_from_recording({
            "name": "login-flow", "description": "登录流程",
            "steps": ["打开页面", "填表单", "提交"],
            "assets": ["screenshots/step1.png"],
            "references": ["recordings/login.jsonl"],
            "recording_version": "1.0.0",
        })
        assert record["origin"] == "recording_bundle"
        assert record["parameters"]["steps"] == ["打开页面", "填表单", "提交"]
        assert record["assets"] == ["screenshots/step1.png"]
        assert record["provenance"]["source_version"] == "1.0.0"

    def test_invalid_origin_rejected(self, curator: SkillCurator) -> None:
        with pytest.raises(ValueError, match="origin"):
            curator.create_candidate(name="x", description="", origin="vibes")

    def test_same_name_merges(self, curator: SkillCurator) -> None:
        first = curator.create_candidate(
            name="Deploy", description="部署", origin="user_request",
            references=["a.md"], source_runs=["r1"], run_count=1)
        second = curator.create_candidate(
            name="deploy", description="部署（重复触发）", origin="repeated_runs",
            references=["b.md"], assets=["shot.png"],
            parameters={"region": "cn"}, source_runs=["r2"], run_count=1)
        assert second["id"] == first["id"] == "deploy"
        assert second.pop("_merged") is True
        assert sorted(second["references"]) == ["a.md", "b.md"]
        assert second["assets"] == ["shot.png"]
        assert second["parameters"] == {"region": "cn"}
        assert second["source_runs"] == ["r1", "r2"]
        assert second["use_count"] == 2
        actions = [h["action"] for h in second["provenance"]["history"]]
        assert "merged" in actions
        files = list(curator.directory.glob("*.json"))
        assert len(files) == 1, "同名候选只保留一个文件"


class TestApprove:
    def test_approve_returns_skill_bundle(self, curator: SkillCurator) -> None:
        curator.create_candidate(
            name="login-flow", description="登录流程", origin="recording_bundle",
            references=["recordings/login.jsonl"],
            parameters={"steps": ["打开页面", "填表单"]}, source_version="1.0.0")
        bundle = curator.approve("login-flow")
        assert bundle["name"] == "login-flow"
        assert "# login-flow" in bundle["instructions"]
        assert "1. 打开页面" in bundle["instructions"]
        assert "recordings/login.jsonl" in bundle["instructions"]
        assert bundle["references"] == ["recordings/login.jsonl"]
        assert bundle["parameters"]["steps"] == ["打开页面", "填表单"]
        assert bundle["metadata"] == {
            "origin": "recording_bundle", "source_runs": [], "use_count": 0,
            "version": "1.0.0", "approved_at": bundle["metadata"]["approved_at"],
            "curator": "atlas-evolution",
        }
        assert curator.get("login-flow")["status"] == "approved"

    def test_approve_missing_and_rejected(self, curator: SkillCurator) -> None:
        with pytest.raises(ValueError, match="未找到"):
            curator.approve("ghost")
        curator.create_candidate(name="x", description="", origin="user_request")
        curator.reject("x", reason="质量不佳")
        with pytest.raises(ValueError, match="拒绝"):
            curator.approve("x")
        # 从不删除：文件还在，状态 rejected。
        data = json.loads((curator.directory / "x.json").read_text(encoding="utf-8"))
        assert data["status"] == "rejected"
        assert data["provenance"]["history"][-1]["reason"] == "质量不佳"


class TestMaintain:
    def test_flag_stale_and_reactivate(self, curator: SkillCurator) -> None:
        curator.create_candidate(name="old", description="", origin="user_request", now=OLD)
        counts = curator.maintain(now=NOW)
        assert counts["flagged_stale"] == 1
        assert curator.get("old")["status"] == "stale"
        # 再次出现 → 复活（curator reactivated 概念）。
        revived = curator.create_candidate(
            name="old", description="", origin="repeated_runs", source_runs=["r9"], now=NOW)
        assert revived["status"] == "candidate"
        actions = [h["action"] for h in revived["provenance"]["history"]]
        assert "reactivated" in actions

    def test_flag_outdated_by_version_provenance(self, curator: SkillCurator) -> None:
        curator.create_candidate(
            name="recorder", description="", origin="recording_bundle",
            source_version="1.0.0", now=NOW)
        counts = curator.maintain(known_versions={"recorder": "1.2.0"}, now=NOW)
        assert counts["flagged_outdated"] == 1
        assert curator.get("recorder")["outdated"] is True
        # 已是最新版本不标。
        counts = curator.maintain(known_versions={"recorder": "1.0.0"}, now=NOW)
        assert counts["flagged_outdated"] == 0

    def test_pinned_never_auto_transitions(self, curator: SkillCurator) -> None:
        record = curator.create_candidate(name="pinned", description="", origin="user_request",
                                          now=OLD)
        record["pinned"] = True
        curator._save(record)
        counts = curator.maintain(now=NOW)
        assert counts["flagged_stale"] == 0
        assert curator.get("pinned")["status"] == "candidate"

    def test_dedupe_merges_duplicates_keeps_both_files(self, curator: SkillCurator) -> None:
        primary = curator.create_candidate(
            name="dup", description="第一个", origin="user_request",
            references=["p.md"], run_count=1, now=OLD)
        twin = {**json.loads((curator.directory / "dup.json").read_text(encoding="utf-8")),
                "id": "dup-2", "references": ["t.md"], "use_count": 5}
        (curator.directory / "dup-2.json").write_text(
            json.dumps(twin, ensure_ascii=False), encoding="utf-8")
        counts = curator.maintain(now=NOW)
        assert counts["merged"] == 1
        merged = curator.get("dup")
        assert sorted(merged["references"]) == ["p.md", "t.md"]
        assert merged["use_count"] == 6, "重复候选的运行数并入主记录"
        absorbed = curator.get("dup-2")
        assert absorbed["status"] == "merged" and absorbed["merged_into"] == primary["id"]
        assert (curator.directory / "dup-2.json").exists(), "curator 从不删除文件"

    def test_mark_used_reactivates_and_counts(self, curator: SkillCurator) -> None:
        curator.create_candidate(name="used", description="", origin="user_request", now=OLD)
        curator.maintain(now=NOW)
        assert curator.get("used")["status"] == "stale"
        record = curator.mark_used("used", now=NOW)
        assert record["use_count"] == 1
        assert record["last_used_at"] is not None
        assert record["status"] == "candidate"


def test_candidates_dir_follows_evolution_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("atlas.evolution.watcher.evolution_root",
                        lambda: tmp_path / "evo")
    from atlas.evolution.skill_curator import candidates_dir

    assert candidates_dir() == tmp_path / "evo" / "candidates"


# ---------------------------------------------------------------------------
# 路由接线：approve → 用户技能目录（市场同款布局）+ 唯一注册表 local_evolved
# ---------------------------------------------------------------------------
def _market_env(tmp_path: Path) -> dict:
    from atlas.skills import SkillManager, default_skill_sources
    from atlas.skills.market import SkillMarket
    from atlas.skills.registry import SkillRegistry

    user_skills = tmp_path / "skills"
    registry = SkillRegistry(tmp_path / "skill-registry.db")
    manager = SkillManager(skills_dir=user_skills)
    for source in default_skill_sources(workspace=tmp_path / "ws", atlas_home=tmp_path):
        manager.register_skill_source(source)
    manager.scan_skills_sync()
    market = SkillMarket(registry, data_dir=tmp_path, user_skills_dir=user_skills,
                         skill_manager=manager, adapters=[])
    return {"registry": registry, "manager": manager, "market": market,
            "user_skills": user_skills}


def test_approve_endpoint_registers_local_evolved(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api import skills_market_router
    from atlas.api.evolution_router import evolution_router

    monkeypatch.setattr("atlas.evolution.watcher.evolution_root",
                        lambda: tmp_path / "evo")
    env = _market_env(tmp_path)
    skills_market_router.set_market_supplier(lambda: env["market"])
    app = FastAPI()
    app.include_router(evolution_router)
    client = TestClient(app)
    curator = SkillCurator()  # 目录经 evolution_root 惰性解析到 tmp
    curator.create_candidate(
        name="login-flow", description="登录流程", origin="recording_bundle",
        references=["recordings/login.jsonl"],
        parameters={"steps": ["打开页面", "填表单"]}, source_version="1.0.0")
    try:
        first = client.post("/api/evolution/candidates/login-flow/approve")
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["ok"] is True and result["saved"] is True
        assert result["skill"] == "login-flow"
        assert result["origin_kind"] == "local_evolved"
        assert result["version"] == "1.0.0"  # source_version 成为初始版本
        skill_dir = env["user_skills"] / "community" / "login-flow"
        assert result["path"] == str(skill_dir)
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "version: 1.0.0" in text and "打开页面" in text
        provenance = env["market"].provenance("login-flow")
        assert provenance["origin_kind"] == "local_evolved"
        assert env["manager"].get_skill("login-flow") is not None  # 发现索引已重扫
        assert curator.get("login-flow")["status"] == "approved"

        # 幂等重批准：原地更新、版本号递增、不产生重复记录。
        curator.create_candidate(
            name="login-flow", description="登录流程（更新）", origin="recording_bundle",
            parameters={"steps": ["打开页面", "填表单", "提交"]})
        second = client.post("/api/evolution/candidates/login-flow/approve").json()
        assert second["ok"] is True and second["saved"] is True
        assert second["version"] == "1.0.1"
        active = [row for row in env["registry"].list(status="active")
                  if row["name"] == "login-flow"]
        assert len(active) == 1 and active[0]["version"] == "1.0.1"
        assert env["registry"].get("login-flow", "1.0.0") is None
        updated = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "version: 1.0.1" in updated and "提交" in updated
    finally:
        skills_market_router.set_market_supplier(None)


def test_approve_endpoint_degrades_when_market_unavailable(tmp_path, monkeypatch) -> None:
    """技能库不可用（无注册表）时：批准生效，saved=false + 中文原因，绝不阻塞。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from atlas.api import skills_market_router
    from atlas.api.evolution_router import evolution_router

    def unavailable() -> None:
        raise RuntimeError("skill registry unavailable")

    monkeypatch.setattr(skills_market_router, "_market_supplier", unavailable)
    monkeypatch.setattr("atlas.evolution.watcher.evolution_root",
                        lambda: tmp_path / "evo")
    curator = SkillCurator()
    curator.create_candidate(name="solo", description="仅批准", origin="user_request")
    app = FastAPI()
    app.include_router(evolution_router)
    result = TestClient(app).post("/api/evolution/candidates/solo/approve").json()
    assert result["ok"] is True and result["saved"] is False
    assert "技能库" in result["note"]
    assert curator.get("solo")["status"] == "approved"
