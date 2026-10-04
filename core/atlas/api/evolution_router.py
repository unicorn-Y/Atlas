"""X5「自动追新」路由（``/api/evolution``）。

挂载：``app.include_router(evolution_router)``（由 server 集成方完成；与 models 路由一样
继承服务端的 OriginGuard 中间件）。所有数据目录经 :func:`atlas.evolution.watcher.evolution_root`
等惰性解析，conftest 的 ATLAS_DATA_DIR 隔离直接生效。监视按需执行（POST /check），
**绝不阻塞启动**；上游离线时返回中文错误并继续服务缓存数据。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.evolution import branch_flow, capability_diff, parity_mapper, taskbook_draft, watcher
from atlas.evolution import skill_curator as curator_mod

log = structlog.get_logger()

evolution_router = APIRouter(prefix="/api/evolution")


def _store() -> watcher.EvolutionStore:
    return watcher.EvolutionStore()


# ---------------------------------------------------------------------------
# 来源管理
# ---------------------------------------------------------------------------


@evolution_router.get("/sources")
async def list_sources() -> dict[str, Any]:
    """监视来源清单（含状态与缓存条数）。"""
    return {"sources": watcher.list_sources(_store())}


class SourceCreate(BaseModel):
    repo: str = Field(description="owner/name")
    kind: str = "commit"
    id: str | None = None
    mirror_path: str | None = None
    remote: str = "origin"
    ref: str = "main"


@evolution_router.post("/sources")
async def add_source(body: SourceCreate) -> dict[str, Any]:
    try:
        record = _store().add_source(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "source": record}


@evolution_router.delete("/sources/{source_id}")
async def remove_source(source_id: str) -> dict[str, Any]:
    if not _store().remove_source(source_id):
        raise HTTPException(status_code=404, detail=f"未找到来源：{source_id}")
    return {"ok": True, "removed": source_id}


# ---------------------------------------------------------------------------
# 监视 / 差异 / 建议
# ---------------------------------------------------------------------------


@evolution_router.post("/check")
async def check_now() -> dict[str, Any]:
    """立即跑一轮上游监视（按需执行；单来源失败不影响其它来源，离线返回缓存）。"""
    return watcher.run_check(_store())


@evolution_router.get("/diffs")
async def list_diffs(include_irrelevant: bool = False) -> dict[str, Any]:
    """对缓存的上游条目做能力差异分类（离线可用）。"""
    entries = _store().all_entries()
    diffs = capability_diff.diff_entries(entries)
    if not include_irrelevant:
        diffs = [d for d in diffs if d["cls"] != "IRRELEVANT"]
    return {
        "diffs": diffs,
        "counts": capability_diff.summarize_classes(diffs),
        "total_entries": len(entries),
    }


@evolution_router.get("/parity")
async def parity() -> dict[str, Any]:
    """CORE-PARITY 更新建议行 + 补丁提案文本（提案只返回字符串，不写 docs/plan）。"""
    diffs = [d for d in capability_diff.diff_entries(_store().all_entries())
             if d["cls"] != "IRRELEVANT"]
    rows = parity_mapper.build_parity_rows(diffs=diffs)
    return {
        "rows": rows,
        "patch_proposal": parity_mapper.render_parity_patch(rows),
        "note": "提案文本不会写入 docs/plan，修改需人工完成",
    }


# ---------------------------------------------------------------------------
# 草稿与分支
# ---------------------------------------------------------------------------


@evolution_router.get("/drafts")
async def drafts() -> dict[str, Any]:
    return {"drafts": taskbook_draft.list_drafts()}


@evolution_router.post("/drafts/generate")
async def generate_drafts() -> dict[str, Any]:
    """按当前建议生成任务书草稿（UPGRADE/REPLACE 各一份，仅草稿）。"""
    created = taskbook_draft.generate_drafts(entries=_store().all_entries())
    return {"ok": True, "created": created}


class DraftApprove(BaseModel):
    base: str | None = None


@evolution_router.post("/drafts/{draft_id}/approve")
async def approve_draft(draft_id: str, body: DraftApprove | None = None) -> dict[str, Any]:
    """批准草稿 → 隔离分支 + worktree + 合并提案文本。**永不自动合并 main**。"""
    if taskbook_draft.get_draft(draft_id) is None:
        raise HTTPException(status_code=404, detail=f"未找到草稿：{draft_id}")
    result = branch_flow.approve_draft(draft_id, base=body.base if body else None)
    return result  # ok=False 时附中文 reason（已批准/非 git 仓库/git 不可用等）


@evolution_router.get("/branches")
async def branches() -> dict[str, Any]:
    return {"branches": branch_flow.list_branches(),
            "note": "合并永远需要人工执行 MERGE-PROPOSAL.md 中的命令"}


# ---------------------------------------------------------------------------
# 技能候选（curator 桥）
# ---------------------------------------------------------------------------


def _curator() -> curator_mod.SkillCurator:
    return curator_mod.SkillCurator()


@evolution_router.get("/candidates")
async def list_candidates() -> dict[str, Any]:
    return {"candidates": _curator().list()}


class CandidateCreate(BaseModel):
    name: str
    description: str = ""
    origin: str = "user_request"
    references: list[str] = []
    assets: list[str] = []
    parameters: dict[str, Any] = {}
    source_runs: list[str] = []
    source_version: str | None = None


@evolution_router.post("/candidates")
async def create_candidate(body: CandidateCreate) -> dict[str, Any]:
    try:
        record = _curator().create_candidate(
            name=body.name, description=body.description, origin=body.origin,
            references=body.references, assets=body.assets, parameters=body.parameters,
            source_runs=body.source_runs, source_version=body.source_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "candidate": record,
            "merged": bool(record.pop("_merged", False))}


class RunsCandidateCreate(BaseModel):
    name: str
    description: str
    run_results: list[dict[str, Any]]
    references: list[str] = []
    min_runs: int = curator_mod.DEFAULT_MIN_RUNS


@evolution_router.post("/candidates/from-runs")
async def create_candidate_from_runs(body: RunsCandidateCreate) -> dict[str, Any]:
    record = _curator().create_candidate_from_runs(
        name=body.name, description=body.description, run_results=body.run_results,
        references=body.references, min_runs=body.min_runs,
    )
    if record is None:
        return {"created": False,
                "reason": f"成功运行不足 {body.min_runs} 次，未生成候选技能"}
    return {"created": True, "candidate": record, "merged": bool(record.pop("_merged", False))}


class RecordingBundle(BaseModel):
    bundle: dict[str, Any]


@evolution_router.post("/candidates/from-recording")
async def create_candidate_from_recording(body: RecordingBundle) -> dict[str, Any]:
    record = _curator().create_candidate_from_recording(body.bundle)
    return {"created": True, "candidate": record, "merged": bool(record.pop("_merged", False))}


@evolution_router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(candidate_id: str) -> dict[str, Any]:
    """批准候选 → 写入用户技能目录并登记到唯一技能注册表（origin_kind=local_evolved）。

    落盘走技能市场的同款布局（``<user skills>/community/<name>``）与
    ``SkillMarket.register_local``，不建第二注册表。幂等：重复批准原地更新，
    版本号递增，不产生重复记录。技能库暂不可用时批准仍然生效，返回
    ``saved=false`` 加中文原因（不阻塞整理流程）。
    """
    try:
        bundle = _curator().approve(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        saved = _persist_evolved_bundle(bundle)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        log.warning("evolution.candidate.persist_failed",
                    candidate=candidate_id, error=str(exc))
        return {"ok": True, "bundle": bundle, "saved": False,
                "note": f"候选已批准，但写入统一技能库未成功：{exc}"}
    return {"ok": True, "bundle": bundle, "saved": True, "skill": saved["skill"],
            "version": saved["version"], "path": saved["path"],
            "origin_kind": "local_evolved",
            "note": "技能包已写入用户技能目录，并登记到统一技能注册表"
                    "（origin_kind=local_evolved）"}


def _bump_patch(version: str) -> str:
    major, minor, patch = (int(part) for part in str(version).split("."))
    return f"{major}.{minor}.{patch + 1}"


def _persist_evolved_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """把整理员技能包写入用户技能目录（市场安装同款布局）并 register_local。"""
    import yaml

    from atlas.api.skills_market_router import get_market, save_local_skill_bundle
    from atlas.skills.acquisition import VERSION_RE

    name = str(bundle.get("name") or "").strip()
    metadata = bundle.get("metadata") or {}
    version = str(metadata.get("version") or "").strip()
    if not VERSION_RE.fullmatch(version):
        version = "1.0.0"
    market = get_market()
    prior = [
        row for row in market.registry.list()
        if row["name"] == name
        and (row.get("provenance") or {}).get("origin_kind") == "local_evolved"
    ]
    if prior:
        # 幂等重批准：原地更新，版本号递增而不是重复登记。
        version = _bump_patch(max(
            (row["version"] for row in prior), key=curator_mod._version_key))
    description = str(bundle.get("description") or "").strip() or "由 X5 整理员批准的演化技能"
    frontmatter = {"name": name, "version": version, "description": description}
    skill_md = (
        "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
        + "---\n\n" + str(bundle.get("instructions") or "").strip() + "\n")
    return save_local_skill_bundle(
        name, {"SKILL.md": skill_md}, origin_kind="local_evolved",
        reason="X5 候选技能批准（atlas-evolution 整理员）", market=market)


class RejectBody(BaseModel):
    reason: str = ""


@evolution_router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(candidate_id: str, body: RejectBody) -> dict[str, Any]:
    try:
        record = _curator().reject(candidate_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "candidate": record}


@evolution_router.post("/candidates/maintain")
async def maintain_candidates() -> dict[str, Any]:
    """整理员维护：去重合并、按版本出处标过期、按闲置标 stale（从不删除）。"""
    counts = _curator().maintain()
    return {"ok": True, "counts": counts}
