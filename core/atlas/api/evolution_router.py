"""X5「自动追新」路由（``/api/evolution``）。

挂载：``app.include_router(evolution_router)``（由 server 集成方完成；与 models 路由一样
继承服务端的 OriginGuard 中间件）。所有数据目录经 :func:`atlas.evolution.watcher.evolution_root`
等惰性解析，conftest 的 ATLAS_DATA_DIR 隔离直接生效。监视按需执行（POST /check），
**绝不阻塞启动**；上游离线时返回中文错误并继续服务缓存数据。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
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


def _auto_maintain_candidates() -> dict[str, Any] | None:
    settings = curator_mod.curator_settings()
    if settings["auto_maintenance_paused"]:
        return None
    counts = _curator().maintain()
    curator_mod.save_curator_settings(last_maintenance_at=datetime.now(UTC).isoformat(timespec="seconds"))
    return counts


def _installed_skill_audit() -> list[dict[str, Any]]:
    from datetime import timedelta

    from atlas.api.skills_market_router import get_market

    rows = get_market().registry.list(status="active")
    now = datetime.now(UTC)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if (row.get("provenance") or {}).get("installed_path"):
            grouped.setdefault(str(row.get("name") or ""), []).append(row)
    suggestions: list[dict[str, Any]] = []
    for name, versions in sorted(grouped.items()):
        ordered = sorted(versions, key=lambda row: curator_mod._version_key(str(row.get("version") or "0")), reverse=True)
        if len(ordered) > 1:
            suggestions.append({"kind": "duplicate_versions", "name": name, "severity": "review",
                                "versions": [row.get("version") for row in ordered],
                                "reason": "同一已安装技能存在多个 active 版本；请检查来源并决定保留版本。",
                                "action": "手工审阅版本和来源；Curator 不会自动卸载或修改技能。"})
            for row in ordered[1:]:
                suggestions.append({"kind": "older_version", "name": name, "version": row.get("version"),
                                    "severity": "review", "reason": f"同名技能存在较新版本 {ordered[0].get('version')}。",
                                    "action": "检查依赖后手工移除或固定版本。"})
        for row in ordered:
            raw_at = row.get("updated_at") or (row.get("provenance") or {}).get("installed_at")
            try:
                updated_at = datetime.fromisoformat(str(raw_at).replace("Z", "+00:00"))
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue
            if updated_at < now - timedelta(days=365):
                suggestions.append({"kind": "possibly_stale", "name": name, "version": row.get("version"),
                                    "severity": "review", "reason": f"该版本已超过 365 天未更新（{raw_at}）。",
                                    "action": "检查维护状态和用途；不会自动归档或删除。"})
    return suggestions


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
    automatic = _auto_maintain_candidates()
    return {"ok": True, "candidate": record,
            "automatic_maintenance": automatic,
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
    automatic = _auto_maintain_candidates()
    return {"created": True, "candidate": record, "automatic_maintenance": automatic,
            "merged": bool(record.pop("_merged", False))}


class RecordingBundle(BaseModel):
    bundle: dict[str, Any]


@evolution_router.post("/candidates/from-recording")
async def create_candidate_from_recording(body: RecordingBundle) -> dict[str, Any]:
    record = _curator().create_candidate_from_recording(body.bundle)
    automatic = _auto_maintain_candidates()
    return {"created": True, "candidate": record, "automatic_maintenance": automatic,
            "merged": bool(record.pop("_merged", False))}


class ConversationCandidateCreate(BaseModel):
    conversation_id: str
    run_id: str | None = None
    name: str | None = None


@evolution_router.post("/candidates/from-conversation")
async def create_candidate_from_conversation(body: ConversationCandidateCreate) -> dict[str, Any]:
    """提炼当前对话最近一次成功运行，生成待审核技能候选。"""
    from atlas import server
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import read_session_messages
    from atlas.evolution.run_learning import transcript_excerpt

    memory = getattr(server, "memory", None)
    conversation = await memory.get_conversation(body.conversation_id) if memory else None
    if conversation is None:
        raise HTTPException(status_code=404, detail="找不到这个对话。")
    runtime = getattr(server, "runtime_mgr", None)
    requested_run = str(body.run_id or "").strip()
    if requested_run:
        run = runtime.runs.get(requested_run) if runtime else None
        if run is None or run.conversation_id != body.conversation_id:
            raise HTTPException(status_code=404, detail="找不到这个对话中的运行记录。")
        if run.status != "completed":
            raise HTTPException(status_code=409, detail="只有成功完成的运行可以提炼为技能。")
        run_id = run.run_id
        project_id = getattr(run, "project_id", None)
        agent_id = getattr(run, "agent_id", None)
        fallback_user = str(getattr(run, "user_input", "") or "")
    else:
        candidates = [run for run in getattr(runtime, "runs", {}).values()
                      if run.conversation_id == body.conversation_id and run.status == "completed"]
        run = max(candidates, key=lambda item: str(item.updated_at), default=None)
        if run is None:
            raise HTTPException(status_code=409, detail="这个对话还没有成功完成的运行。")
        run_id = run.run_id
        project_id = getattr(run, "project_id", None)
        agent_id = getattr(run, "agent_id", None)
        fallback_user = str(getattr(run, "user_input", "") or "")
    messages = await asyncio.to_thread(
        read_session_messages, DATA_ROOT / "engine", body.conversation_id, limit=1000,
    )
    user_text, assistant_text = transcript_excerpt(messages, run_id)
    user_text = user_text or fallback_user
    if not assistant_text:
        assistant_text = next((str(env.get("data", {}).get("content") or "").strip()
                               for env in reversed(run.events)
                               if env.get("event") == "message.completed"
                               and str(env.get("data", {}).get("content") or "").strip()), "")
    try:
        record = _curator().create_candidate_from_conversation(
            conversation_id=body.conversation_id, run_id=run_id,
            user_text=user_text, assistant_text=assistant_text, name=body.name,
            project_id=project_id, agent_id=agent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    automatic = _auto_maintain_candidates()
    return {"created": True, "candidate": record, "automatic_maintenance": automatic}


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


@evolution_router.post("/candidates/{candidate_id}/rollback")
async def rollback_candidate(candidate_id: str) -> dict[str, Any]:
    """Uninstall the evolved skill registered by this approved candidate."""
    curator = _curator()
    record = curator.get(candidate_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到候选技能：{candidate_id}")
    if record.get("status") != "approved":
        raise HTTPException(status_code=409, detail="只有已批准的候选技能可以回滚")
    name = str(record.get("name") or "")
    if any(item.get("id") != candidate_id and item.get("status") == "approved"
           and item.get("name") == name for item in curator.list()):
        raise HTTPException(status_code=409, detail="这个技能还关联其它已批准候选；先处理同名候选")
    try:
        from atlas.api.skills_market_router import get_market

        market = get_market()
        registry_rows = [row for row in market.registry.list() if row.get("name") == name]
        evolved = [row for row in registry_rows
                   if (row.get("provenance") or {}).get("origin_kind") == "local_evolved"]
        if not evolved:
            raise HTTPException(status_code=409, detail="统一技能库中没有找到该候选对应的演化技能")
        from atlas.skills.lifecycle import remove_skill

        latest = max(evolved, key=lambda row: str(row.get("updated_at") or ""))
        result = remove_skill(
            market.registry, market.user_skills_dir, name, latest["version"],
            approval_event_id=f"evolution-rollback:{candidate_id}",
            reason=f"回滚来源运行：{', '.join(record.get('source_runs') or [])}",
        )
        market._rescan()
        updated = curator.mark_rolled_back(candidate_id)
    except HTTPException:
        raise
    except Exception as exc:  # Installed-skill diagnostics must not disable the curator controls.
        raise HTTPException(status_code=500, detail=f"回滚演化技能失败：{exc}") from exc
    return {"ok": True, "candidate": updated, "removed": result}


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


class CandidatePinBody(BaseModel):
    pinned: bool


class CuratorSettingsBody(BaseModel):
    auto_maintenance_paused: bool


@evolution_router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(candidate_id: str, body: RejectBody) -> dict[str, Any]:
    try:
        record = _curator().reject(candidate_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "candidate": record}


@evolution_router.post("/candidates/{candidate_id}/pin")
async def pin_candidate(candidate_id: str, body: CandidatePinBody) -> dict[str, Any]:
    try:
        record = _curator().pin(candidate_id, body.pinned)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "candidate": record}


@evolution_router.get("/curator/status")
async def curator_status() -> dict[str, Any]:
    candidates = _curator().list()
    settings = curator_mod.curator_settings()
    counts: dict[str, int] = {}
    for candidate in candidates:
        status = str(candidate.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    try:
        installed_suggestions = _installed_skill_audit()
        audit_error = None
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        installed_suggestions = []
        audit_error = f"已安装技能分析暂不可用：{type(exc).__name__}"
    return {"status": "paused" if settings["auto_maintenance_paused"] else "active",
            **settings, "counts": counts, "candidate_count": len(candidates),
            "installed_suggestions": installed_suggestions, "installed_audit_error": audit_error,
            "automatic_changes": "候选新建时执行安全的去重/过期标记；已安装技能仅产生建议。"}


@evolution_router.patch("/curator/settings")
async def update_curator_settings(body: CuratorSettingsBody) -> dict[str, Any]:
    settings = curator_mod.save_curator_settings(paused=body.auto_maintenance_paused)
    return {"ok": True, **settings}


@evolution_router.post("/curator/maintain")
async def run_curator_maintenance() -> dict[str, Any]:
    counts = _curator().maintain()
    settings = curator_mod.save_curator_settings(last_maintenance_at=datetime.now(UTC).isoformat(timespec="seconds"))
    try:
        installed_suggestions = _installed_skill_audit()
        audit_error = None
    except Exception as exc:  # The local candidate maintenance remains useful if marketplace state is unavailable.
        installed_suggestions = []
        audit_error = f"已安装技能分析暂不可用：{type(exc).__name__}"
    return {"ok": True, "counts": counts, **settings,
            "installed_suggestions": installed_suggestions, "installed_audit_error": audit_error,
            "note": "仅整理候选；已安装技能没有被自动修改。"}


@evolution_router.post("/candidates/maintain")
async def maintain_candidates() -> dict[str, Any]:
    """整理员维护：去重合并、按版本出处标过期、按闲置标 stale（从不删除）。"""
    return await run_curator_maintenance()
