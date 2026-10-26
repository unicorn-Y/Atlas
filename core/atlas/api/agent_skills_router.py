"""REST surface for the W7 Skill Workshop + per-agent collections.

Endpoints (r8 lane contract):

- ``GET  /api/agents/{agent_id}/skills``           — relation rows + effective view
- ``PUT  /api/agents/{agent_id}/skills``           — batch set relations
- ``GET  /api/skill-proposals``                    — list (filter: status, skill_name)
- ``GET  /api/skill-proposals/{id}``               — one proposal + its event ledger
- ``POST /api/skill-proposals``                    — draft a proposal (agent_learned)
- ``POST /api/skill-proposals/{id}/approve``       — apply (409 on stale/conflict)
- ``POST /api/skill-proposals/{id}/reject``        — reject with reason
- ``POST /api/skill-proposals/{id}/rollback``      — restore the apply snapshot
- ``GET  /api/skills/{name}/usage``                — usage telemetry for one skill

All state lives in the ONE Registry SQLite (``atlas.skills.proposals`` /
``atlas.skills.agent_collections``); this module is HTTP wiring only, following
the ``skills_market_router`` injectable-singleton pattern.

Integration note for the owner of ``atlas/server.py``::

    app.include_router(agent_skills_router)
    # Mount before any single-segment /api/skills/{name} route is irrelevant:
    # every path here has >= 2 segments after /api/skills or lives under
    # /api/agents/{id}/skills, which W1's agent_router does not occupy.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from atlas.origin_guard import TOKEN_HEADER, is_trusted
from atlas.skills.agent_collections import AgentSkillCollections, CollectionError
from atlas.skills.market import MarketError
from atlas.skills.proposals import ProposalError, SkillProposalStore

router = APIRouter(tags=["agent-skills"])

# Injectable singletons (tests install tmp_path-isolated instances; production
# lazily builds over skills_market_router.get_market()'s registry/market).
_collections: AgentSkillCollections | None = None
_proposals: SkillProposalStore | None = None


def set_collections(collections: AgentSkillCollections | None) -> None:
    """Override the collections singleton (``None`` restores the lazy default)."""
    global _collections
    _collections = collections


def set_proposals(proposals: SkillProposalStore | None) -> None:
    """Override the proposal-store singleton (``None`` restores the lazy default)."""
    global _proposals
    _proposals = proposals


def get_collections() -> AgentSkillCollections:
    if _collections is not None:
        return _collections
    return AgentSkillCollections(_market().registry)


def get_proposals() -> SkillProposalStore:
    if _proposals is not None:
        return _proposals
    market = _market()
    collections = _collections or AgentSkillCollections(market.registry)
    return SkillProposalStore(market.registry, market=market, collections=collections)


def _market() -> Any:
    from atlas.api.skills_market_router import get_market

    return get_market()


def _require_trusted_origin(request: Request) -> None:
    """Mirror of the app-level OriginGuard rule for standalone mounts."""
    trusted = is_trusted(
        request.headers.get("origin"),
        request.headers.get(TOKEN_HEADER),
        fetch_site=request.headers.get("sec-fetch-site"),
    )
    if not trusted:
        raise HTTPException(status_code=403, detail="Requests from this origin are not allowed")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProposalError):
        return HTTPException(status_code=exc.status_code, detail={
            "message": exc.message, "code": exc.code,
            **({"details": exc.details} if exc.details else {}),
        })
    if isinstance(exc, MarketError):
        return HTTPException(status_code=503, detail={
            "message": exc.message, "code": exc.code,
        })
    if isinstance(exc, (CollectionError, ValueError)):
        return HTTPException(status_code=422, detail={"message": str(exc), "code": "invalid"})
    return HTTPException(status_code=500, detail={"message": str(exc), "code": "internal"})


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class AgentSkillSetting(BaseModel):
    skill_name: str
    enabled: bool = True
    relation: str = "adopted"
    note: str | None = None


class AgentSkillsBatch(BaseModel):
    skills: list[AgentSkillSetting] = Field(min_length=1)


class ProposalCreate(BaseModel):
    skill_name: str
    files: dict[str, str] | None = None
    writes: dict[str, str] | None = None
    deletes: list[str] | None = None
    kind: str | None = None
    base_revision: str | None = None
    origin: dict[str, Any] | None = None
    goal: str = ""
    evidence: str = ""
    created_by: str = "agent"


class ProposalDecision(BaseModel):
    expected_revision: str | None = None
    reviewer_note: str = ""
    reason: str = ""
    actor: str = "user"


# ---------------------------------------------------------------------------
# Per-agent collections
# ---------------------------------------------------------------------------

@router.get(
    "/api/agents/{agent_id}/skills",
    dependencies=[Depends(_require_trusted_origin)],
)
async def list_agent_skills(agent_id: str) -> dict[str, Any]:
    """Relation rows plus the effective projection (module docstring semantics)."""
    try:
        collections = get_collections()
        return {
            "agent_id": agent_id,
            "count": len(collections.list_agent_skills(agent_id)),
            "skills": collections.effective_skills(agent_id),
            "relations": collections.list_agent_skills(agent_id),
        }
    except (ProposalError, CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


@router.delete("/api/agents/{agent_id}/skills/{skill_name}", dependencies=[Depends(_require_trusted_origin)])
async def remove_agent_skill(agent_id: str, skill_name: str) -> dict[str, Any]:
    try:
        return {"removed": get_collections().remove_agent_skill(agent_id, skill_name),
                "agent_id": agent_id, "skill_name": skill_name}
    except (CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


@router.put(
    "/api/agents/{agent_id}/skills",
    dependencies=[Depends(_require_trusted_origin)],
)
async def set_agent_skills(
    agent_id: str, payload: AgentSkillsBatch,
) -> dict[str, Any]:
    """Batch upsert relation rows; the skill entities stay single-copy in the Registry."""
    try:
        collections = get_collections()
        rows = [
            collections.set_agent_skill(
                agent_id, item.skill_name, enabled=item.enabled,
                relation=item.relation, note=item.note,
            )
            for item in payload.skills
        ]
        return {"agent_id": agent_id, "updated": len(rows), "relations": rows}
    except (ProposalError, CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


# ---------------------------------------------------------------------------
# Skill proposals
# ---------------------------------------------------------------------------

@router.get(
    "/api/skill-proposals",
    dependencies=[Depends(_require_trusted_origin)],
)
async def list_proposals(
    status: str | None = Query(default=None),
    skill_name: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        rows = get_proposals().list(status=status, skill_name=skill_name)
        return {"count": len(rows), "proposals": rows}
    except (ProposalError, CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


@router.get(
    "/api/skill-proposals/{proposal_id}",
    dependencies=[Depends(_require_trusted_origin)],
)
async def inspect_proposal(proposal_id: str) -> dict[str, Any]:
    try:
        store = get_proposals()
        record = store.get(proposal_id)
        if record is None:
            raise HTTPException(status_code=404, detail={
                "message": f"未找到技能提案：{proposal_id}", "code": "proposal_not_found"})
        return {**record, "events": store.events(proposal_id)}
    except ProposalError as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skill-proposals",
    dependencies=[Depends(_require_trusted_origin)],
    status_code=201,
)
async def create_proposal(payload: ProposalCreate) -> dict[str, Any]:
    try:
        record = get_proposals().create_proposal(
            payload.skill_name, files=payload.files, writes=payload.writes,
            deletes=payload.deletes, kind=payload.kind,
            base_revision=payload.base_revision, origin=payload.origin,
            goal=payload.goal, evidence=payload.evidence, created_by=payload.created_by,
        )
        return record
    except (ProposalError, CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skill-proposals/{proposal_id}/approve",
    dependencies=[Depends(_require_trusted_origin)],
)
async def approve_proposal(
    proposal_id: str, payload: ProposalDecision | None = None,
) -> dict[str, Any]:
    body = payload or ProposalDecision()
    try:
        return get_proposals().approve(
            proposal_id, expected_revision=body.expected_revision,
            reviewer_note=body.reviewer_note, actor=body.actor,
        )
    except (ProposalError, MarketError, ValueError) as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skill-proposals/{proposal_id}/reject",
    dependencies=[Depends(_require_trusted_origin)],
)
async def reject_proposal(
    proposal_id: str, payload: ProposalDecision | None = None,
) -> dict[str, Any]:
    body = payload or ProposalDecision()
    try:
        return get_proposals().reject(
            proposal_id, reason=body.reason or body.reviewer_note,
            actor=body.actor, expected_revision=body.expected_revision,
        )
    except (ProposalError, ValueError) as exc:
        raise _http_error(exc) from None


@router.post(
    "/api/skill-proposals/{proposal_id}/rollback",
    dependencies=[Depends(_require_trusted_origin)],
)
async def rollback_proposal(
    proposal_id: str, payload: ProposalDecision | None = None,
) -> dict[str, Any]:
    try:
        return get_proposals().rollback(
            proposal_id, actor=(payload.actor if payload else "user"))
    except (ProposalError, MarketError, ValueError) as exc:
        raise _http_error(exc) from None


# ---------------------------------------------------------------------------
# Usage telemetry
# ---------------------------------------------------------------------------

@router.get(
    "/api/skills/{skill_name}/usage",
    dependencies=[Depends(_require_trusted_origin)],
)
async def skill_usage(skill_name: str) -> dict[str, Any]:
    try:
        return get_collections().usage_stats(skill_name)
    except (CollectionError, ValueError) as exc:
        raise _http_error(exc) from None


@router.get("/api/skills/usage-overview", dependencies=[Depends(_require_trusted_origin)])
async def skill_usage_overview() -> dict[str, Any]:
    """Usage and prompt cost estimate for installed skills, including unused ones."""
    from pathlib import Path
    from atlas.skills import SkillManager

    manager = SkillManager()
    await manager.scan_skills()
    collections = get_collections()
    items: list[dict[str, Any]] = []
    for skill in manager.list_skills():
        try:
            text = Path(skill.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        usage = collections.usage_stats(skill.name)
        items.append({**usage, "description": skill.description, "source": skill.source,
                      "estimated_chars": len(text), "estimated_tokens": (len(text) + 3) // 4})
    return {"skills": items, "estimated_token_method": "SKILL.md characters / 4; approximate"}


__all__ = [
    "router", "set_collections", "set_proposals",
    "get_collections", "get_proposals",
]
