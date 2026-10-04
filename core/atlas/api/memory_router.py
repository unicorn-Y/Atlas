"""Memory, fact and knowledge surface (``/api/facts, /api/memory, /api/knowledge``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()


class FactCreateRequest(BaseModel):
    key: str
    value: str
    category: str = "general"


@router.get("/api/facts")
async def list_facts(
    services: Annotated[AppServices, Depends(get_app_services)],
    category: str | None = Query(None),
) -> list[dict[str, Any]]:
    """List all facts, optionally filtered by category."""
    memory = services.memory
    assert memory is not None
    return await memory.list_facts(category=category)


@router.post("/api/facts")
async def create_or_update_fact(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: FactCreateRequest,
) -> dict[str, str]:
    """Create or update a fact (upsert by key)."""
    memory = services.memory
    assert memory is not None
    await memory.set_fact(req.key, req.value, req.category)
    return {"status": "ok", "key": req.key}


@router.delete("/api/facts/{key}")
async def delete_fact(
    services: Annotated[AppServices, Depends(get_app_services)],
    key: str,
) -> dict[str, str]:
    """Delete a fact by key."""
    memory = services.memory
    assert memory is not None
    ok = await memory.delete_fact(key)
    if not ok:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "ok", "key": key}


@router.get("/api/memory/candidates")
async def list_memory_candidates(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
) -> list[dict[str, Any]]:
    """List extracted memory candidates for user review."""
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid candidate status")
    return await memory.list_memory_candidates(status=status)


@router.post("/api/memory/optimization-reports")
async def create_memory_optimization_report(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Generate and preserve a ranked, advisory memory optimization report."""
    memory = services.memory
    assert memory is not None
    return await memory.create_memory_optimization_report()


@router.get("/api/memory/optimization-reports")
async def list_memory_optimization_reports(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved optimization report snapshots, newest first."""
    memory = services.memory
    assert memory is not None
    return await memory.list_memory_optimization_reports(limit=limit)


@router.post("/api/memory/maturity-reports")
async def create_memory_maturity_report(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Generate and preserve a deterministic, advisory knowledge maturity report."""
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_maturity_report()


@router.get("/api/memory/maturity-reports")
async def list_memory_maturity_reports(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved maturity report snapshots, newest first."""
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_maturity_reports(limit=limit)


@router.post("/api/memory/knowledge-health-reports")
async def create_knowledge_health_report(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_health_report()


@router.get("/api/memory/knowledge-health-reports")
async def list_knowledge_health_reports(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_health_reports(limit=limit)


@router.post("/api/memory/knowledge-health-reports/{report_id}/approve")
async def approve_knowledge_health_report(
    services: Annotated[AppServices, Depends(get_app_services)],
    report_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_health_report(report_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending knowledge health report not found")
    return {"status": "approved", "id": report_id}


@router.post("/api/memory/knowledge-health-reports/{report_id}/reject")
async def reject_knowledge_health_report(
    services: Annotated[AppServices, Depends(get_app_services)],
    report_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_health_report(report_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending knowledge health report not found")
    return {"status": "rejected", "id": report_id}


@router.post("/api/memory/consolidated-insights")
async def create_knowledge_consolidated_insights(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_consolidated_insights()


@router.get("/api/memory/consolidated-insights")
async def list_knowledge_consolidated_insights(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_consolidated_insights(limit=limit)


@router.get("/api/memory/insight-applications")
async def list_knowledge_insight_applications(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_insight_applications(limit=limit)


@router.post("/api/memory/self-steering-reports")
async def create_memory_self_steering_report(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Create auditable suggestions from maturity and approved outcome signals."""
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_self_steering_report()


@router.get("/api/memory/self-steering-reports")
async def list_memory_self_steering_reports(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Return preserved self-steering snapshots, newest first."""
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_self_steering_reports(limit=limit)


@router.post("/api/memory/self-steering-reports/{report_id}/approve")
async def approve_memory_self_steering_report(
    services: Annotated[AppServices, Depends(get_app_services)],
    report_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_self_steering_report(report_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending self-steering report not found")
    return {"status": "approved", "id": report_id}


@router.post("/api/memory/self-steering-reports/{report_id}/reject")
async def reject_memory_self_steering_report(
    services: Annotated[AppServices, Depends(get_app_services)],
    report_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_self_steering_report(report_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending self-steering report not found")
    return {"status": "rejected", "id": report_id}


@router.post("/api/memory/optimization-candidates")
async def create_memory_optimization_candidates(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_optimization_candidates()


@router.get("/api/memory/optimization-candidates")
async def list_memory_optimization_candidates(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None), limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid optimization candidate status")
    return await memory.list_knowledge_optimization_candidates(status=status, limit=limit)


@router.post("/api/memory/optimization-candidates/{candidate_id}/approve")
async def approve_memory_optimization_candidate(
    services: Annotated[AppServices, Depends(get_app_services)],
    candidate_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_optimization_candidate(candidate_id, approved=True):
        raise HTTPException(
            status_code=404, detail="Eligible pending optimization candidate not found"
        )
    return {"status": "approved", "id": candidate_id}


@router.post("/api/memory/optimization-candidates/{candidate_id}/reject")
async def reject_memory_optimization_candidate(
    services: Annotated[AppServices, Depends(get_app_services)],
    candidate_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_optimization_candidate(candidate_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending optimization candidate not found")
    return {"status": "rejected", "id": candidate_id}


@router.post("/api/memory/consolidation-proposals")
async def create_memory_consolidation_proposals(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.create_knowledge_consolidation_proposals()


@router.get("/api/memory/consolidation-proposals")
async def list_memory_consolidation_proposals(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None), limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid consolidation proposal status")
    return await memory.list_knowledge_consolidation_proposals(status=status, limit=limit)


@router.post("/api/memory/consolidation-proposals/{proposal_id}/approve")
async def approve_memory_consolidation_proposal(
    services: Annotated[AppServices, Depends(get_app_services)],
    proposal_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_consolidation_proposal(proposal_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending consolidation proposal not found")
    return {"status": "approved", "id": proposal_id}


@router.post("/api/memory/consolidation-proposals/{proposal_id}/reject")
async def reject_memory_consolidation_proposal(
    services: Annotated[AppServices, Depends(get_app_services)],
    proposal_id: str,
) -> dict[str, str]:
    memory = services.memory
    assert memory is not None
    if not await memory.review_knowledge_consolidation_proposal(proposal_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending consolidation proposal not found")
    return {"status": "rejected", "id": proposal_id}


@router.post("/api/memory/consolidation-proposals/{proposal_id}/activate")
async def activate_memory_consolidation_proposal(
    services: Annotated[AppServices, Depends(get_app_services)],
    proposal_id: str,
) -> dict[str, Any]:
    memory = services.memory
    assert memory is not None
    activation = await memory.activate_knowledge_consolidation_proposal(proposal_id)
    if activation is None:
        raise HTTPException(status_code=404, detail="Approved consolidation proposal not found")
    return activation


@router.get("/api/memory/knowledge-activations")
async def list_memory_knowledge_activations(
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_activations(limit=limit)


@router.post("/api/memory/knowledge-activations/{activation_id}/verify")
async def verify_memory_knowledge_activation_usage(
    services: Annotated[AppServices, Depends(get_app_services)],
    activation_id: str,
    candidate_id: str = Body(...),
    evidence_refs: list[str] = Body(...),
    usage_id: str | None = Body(None),
) -> dict[str, Any]:
    """Verify a claimed advisory use against its activated evidence provenance."""
    memory = services.memory
    assert memory is not None
    verification = await memory.verify_knowledge_activation_usage(
        activation_id,
        candidate_id=candidate_id,
        evidence_refs=evidence_refs,
        usage_id=usage_id,
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Knowledge activation not found")
    return verification


@router.get("/api/memory/knowledge-verifications")
async def list_memory_knowledge_verifications(
    services: Annotated[AppServices, Depends(get_app_services)],
    activation_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """Query immutable advisory knowledge verification snapshots."""
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge_verifications(activation_id=activation_id, limit=limit)


@router.get("/api/memory/goal-outcomes")
async def list_goal_outcomes(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List durable goal results and pending experience-review candidates."""
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal experience status")
    return await memory.list_goal_outcomes(experience_status=status, limit=limit)


@router.post("/api/memory/goal-outcomes/{outcome_id}/approve")
async def approve_goal_experience(
    services: Annotated[AppServices, Depends(get_app_services)],
    outcome_id: str,
) -> dict[str, str]:
    """Approve one pending goal outcome for future advisory context."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_experience(outcome_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal outcome not found")
    return {"status": "approved", "id": outcome_id}


@router.post("/api/memory/goal-outcomes/{outcome_id}/reject")
async def reject_goal_experience(
    services: Annotated[AppServices, Depends(get_app_services)],
    outcome_id: str,
) -> dict[str, str]:
    """Reject one pending goal outcome."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_experience(outcome_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal outcome not found")
    return {"status": "rejected", "id": outcome_id}


@router.get("/api/memory/goal-knowledge/feedback")
async def list_goal_knowledge_feedback(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List helpful or failed usage outcomes with source provenance."""
    memory = services.memory
    assert memory is not None
    return await memory.list_goal_knowledge_feedback(knowledge_id, limit)


@router.post("/api/memory/goal-knowledge/evolution/evaluate")
async def evaluate_goal_knowledge_evolution(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Analyze approved advisory usage and persist review-only recommendations."""
    memory = services.memory
    assert memory is not None
    return await memory.evaluate_goal_knowledge_evolution(knowledge_id)


@router.get("/api/memory/goal-knowledge/evolution/evaluations")
async def list_goal_knowledge_evolution_evaluations(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_goal_knowledge_evolution_evaluations(knowledge_id, limit)


@router.get("/api/memory/goal-knowledge/evolution/recommendations")
async def list_goal_knowledge_evolution_recommendations(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    memory = services.memory
    assert memory is not None
    return await memory.list_goal_knowledge_evolution_recommendations(
        knowledge_id, limit,
    )


@router.get("/api/memory/goal-knowledge/proposals")
async def list_goal_knowledge_proposals(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List improvement proposals separately from active advisory knowledge."""
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal knowledge proposal status")
    return await memory.list_goal_knowledge_proposals(status=status, limit=limit)


@router.post("/api/memory/goal-knowledge/proposals/{proposal_id}/approve")
async def approve_goal_knowledge_proposal(
    services: Annotated[AppServices, Depends(get_app_services)],
    proposal_id: str,
) -> dict[str, str]:
    """Promote a pending advisory improvement after explicit approval."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_knowledge_proposal(proposal_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal knowledge proposal not found")
    return {"status": "approved", "id": proposal_id}


@router.post("/api/memory/goal-knowledge/proposals/{proposal_id}/reject")
async def reject_goal_knowledge_proposal(
    services: Annotated[AppServices, Depends(get_app_services)],
    proposal_id: str,
) -> dict[str, str]:
    """Reject a pending advisory improvement without changing active knowledge."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_knowledge_proposal(proposal_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal knowledge proposal not found")
    return {"status": "rejected", "id": proposal_id}


@router.post("/api/memory/goal-knowledge/refinements/evaluate")
async def evaluate_goal_knowledge_refinements(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Evaluate approved improvement candidates using the deterministic refinement gate."""
    memory = services.memory
    assert memory is not None
    return await memory.evaluate_goal_knowledge_refinements(knowledge_id)


@router.get("/api/memory/goal-knowledge/refinements")
async def list_goal_knowledge_refinements(
    services: Annotated[AppServices, Depends(get_app_services)],
    status: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List refinement candidates separately from advisory knowledge."""
    memory = services.memory
    assert memory is not None
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid goal knowledge refinement status")
    return await memory.list_goal_knowledge_refinements(status=status, limit=limit)


@router.get("/api/memory/goal-knowledge/refinement-evaluations")
async def list_goal_knowledge_refinement_evaluations(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List deterministic refinement decisions and their supporting candidates."""
    memory = services.memory
    assert memory is not None
    return await memory.list_goal_knowledge_refinement_evaluations(
        knowledge_id=knowledge_id, limit=limit,
    )


@router.get("/api/memory/goal-knowledge/governance/evaluate")
async def evaluate_goal_knowledge_governance(
    services: Annotated[AppServices, Depends(get_app_services)],
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Evaluate pending advisory reviews against deterministic provenance gates."""
    memory = services.memory
    assert memory is not None
    try:
        return await memory.evaluate_goal_knowledge_governance(entity_type, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/memory/goal-knowledge/governance/history")
async def list_goal_knowledge_governance_history(
    services: Annotated[AppServices, Depends(get_app_services)],
    knowledge_id: str | None = Query(None),
    limit: int = Query(100, ge=0, le=500),
) -> list[dict[str, Any]]:
    """List append-only review decisions and their provenance."""
    memory = services.memory
    assert memory is not None
    return await memory.list_goal_knowledge_governance_history(knowledge_id, limit)


@router.post("/api/memory/goal-knowledge/refinements/{refinement_id}/approve")
async def approve_goal_knowledge_refinement(
    services: Annotated[AppServices, Depends(get_app_services)],
    refinement_id: str,
) -> dict[str, str]:
    """Apply a reviewed refinement to advisory knowledge."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_knowledge_refinement(refinement_id, approved=True):
        raise HTTPException(status_code=404, detail="Pending goal knowledge refinement not found")
    return {"status": "approved", "id": refinement_id}


@router.post("/api/memory/goal-knowledge/refinements/{refinement_id}/reject")
async def reject_goal_knowledge_refinement(
    services: Annotated[AppServices, Depends(get_app_services)],
    refinement_id: str,
) -> dict[str, str]:
    """Reject a candidate without changing advisory or active knowledge."""
    memory = services.memory
    assert memory is not None
    if not await memory.review_goal_knowledge_refinement(refinement_id, approved=False):
        raise HTTPException(status_code=404, detail="Pending goal knowledge refinement not found")
    return {"status": "rejected", "id": refinement_id}


@router.post("/api/memory/candidates/{candidate_id}/approve")
async def approve_memory_candidate(
    services: Annotated[AppServices, Depends(get_app_services)],
    candidate_id: str,
) -> dict[str, str]:
    """Promote a pending candidate after explicit user approval."""
    memory = services.memory
    assert memory is not None
    if not await memory.promote_memory_candidate(candidate_id):
        raise HTTPException(
            status_code=404, detail="Pending memory candidate not found"
        )
    return {"status": "approved", "id": candidate_id}


@router.post("/api/memory/candidates/{candidate_id}/reject")
async def reject_memory_candidate(
    services: Annotated[AppServices, Depends(get_app_services)],
    candidate_id: str,
) -> dict[str, str]:
    """Reject a pending memory candidate."""
    memory = services.memory
    assert memory is not None
    if not await memory.reject_memory_candidate(candidate_id):
        raise HTTPException(
            status_code=404, detail="Pending memory candidate not found"
        )
    return {"status": "rejected", "id": candidate_id}


class KnowledgeAddRequest(BaseModel):
    content: str
    source: str = ""
    category: str = "general"
    metadata: dict[str, Any] = {}


@router.get("/api/knowledge")
async def list_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List knowledge base entries."""
    memory = services.memory
    assert memory is not None
    return await memory.list_knowledge(category=category, limit=limit)


@router.post("/api/knowledge")
async def add_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: KnowledgeAddRequest,
) -> dict[str, Any]:
    """Add a knowledge entry."""
    memory = services.memory
    assert memory is not None
    entry_id = await memory.add_knowledge(
        content=req.content,
        source=req.source,
        category=req.category,
        metadata=req.metadata,
    )
    return {"id": entry_id, "content": req.content, "source": req.source}


@router.get("/api/knowledge/search")
async def search_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: str = Query(..., min_length=1),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Search the knowledge base."""
    memory = services.memory
    assert memory is not None
    return await memory.search_knowledge(query=q, category=category, limit=limit)


@router.delete("/api/knowledge/{entry_id}")
async def delete_knowledge(
    services: Annotated[AppServices, Depends(get_app_services)],
    entry_id: str,
) -> dict[str, str]:
    """Delete a knowledge entry."""
    memory = services.memory
    assert memory is not None
    ok = await memory.delete_knowledge(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Knowledge entry not found: {entry_id}")
    return {"status": "ok", "id": entry_id}
