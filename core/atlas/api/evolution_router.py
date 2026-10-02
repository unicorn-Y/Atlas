"""X5「自动追新」路由（``/api/evolution``）。

挂载：``app.include_router(evolution_router)``（由 server 集成方完成；与 models 路由一样
继承服务端的 OriginGuard 中间件）。所有数据目录经 :func:`atlas.evolution.watcher.evolution_root`
等惰性解析，conftest 的 ATLAS_DATA_DIR 隔离直接生效。监视按需执行（POST /check），
**绝不阻塞启动**；上游离线时返回中文错误并继续服务缓存数据。
"""

from __future__ import annotations

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
    """批准候选 → 返回交给统一 SkillManager 的技能包（本路由不做技能库落盘）。"""
    try:
        bundle = _curator().approve(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "bundle": bundle,
            "note": "技能包由技能集成方写入统一 SkillManager"}


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
