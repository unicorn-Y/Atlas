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
