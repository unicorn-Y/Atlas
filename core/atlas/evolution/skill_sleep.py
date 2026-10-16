"""Nightly evidence-based skill candidate generation and gated promotion."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import structlog

from atlas.config import DATA_ROOT

log = structlog.get_logger(__name__)

STATE_DB = DATA_ROOT / "engine" / "state.db"  # compatibility only; never read by this adapter
WORK_DIR = DATA_ROOT / "data" / "skill-sleep"


def harvest_atlas(state_db: Path | None = None, *, since_iso: str | None = None,
                  limit: int = 0) -> list[Any]:
    """Map recent M3 Markdown episodes to SkillOpt SessionDigest rows.

    ``state_db`` remains an ignored compatibility parameter. SessionDB is not
    queried and transcript content is not copied into SkillOpt inputs.
    """
    from skillopt_sleep.types import SessionDigest
    from atlas.evolution.skill_candidate import read_experiences
    from atlas.memory.library import get_library

    library = get_library()
    if library is None:
        return []
    since = None
    if since_iso:
        from datetime import datetime
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    experiences = read_experiences(library.store, limit=max(limit, 120) if limit else 120)
    digests = []
    for item in experiences:
        if since and item.recorded_at:
            from datetime import datetime
            try:
                recorded = datetime.fromisoformat(item.recorded_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if recorded < since:
                continue
        digests.append(SessionDigest(
            session_id=item.experience_id,
            project=item.task or "Atlas memory experience",
            git_branch="",
            started_at=item.recorded_at,
            ended_at=item.recorded_at,
            user_prompts=[item.task, item.summary],
            assistant_finals=[item.outcome, *item.steps],
            tools_used=list(item.commands),
            feedback_signals=[*item.errors, *item.open_items],
            n_user_turns=1,
            n_assistant_turns=1,
            raw_path="",
        ))
        if limit and len(digests) >= limit:
            break
    return digests


def _model_env() -> dict[str, str]:
    """SkillOpt's OpenAI-compatible backend settings from Atlas' configured gateway."""
    from atlas.config import get_config, load_user_settings

    cfg, settings = get_config(), load_user_settings() or {}
    endpoint = str(settings.get("gateway_base_url") or cfg.gateway_base_url).removesuffix("/")
    chosen = str(settings.get("memory_model") or settings.get("selected_model")
                 or cfg.default_model)
    model = next((str(m.get("litellm_model") or chosen) for m in cfg.get("models.custom", []) or []
                  if isinstance(m, dict) and m.get("id") == chosen), chosen)
    return {
        "AZURE_OPENAI_AUTH_MODE": "openai_compatible",
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_KEY": str(settings.get("api_key") or cfg.gateway_api_key or "none"),
        "model": model.split("/", 1)[1] if model.startswith("openai/") else model,
    }


def run(*, dry_run: bool = False) -> dict[str, Any]:
    """Generate from M3 Markdown, replay with SkillOpt, and promote only on a strict gain."""
    from skillopt_sleep import cycle
    from skillopt_sleep.config import load_config
    from atlas.evolution.skill_candidate import (
        build_candidate, heldout_composition, is_counterexample,
        read_experiences, score_candidate,
    )
    from atlas.evolution.skill_staging import (
        promote_candidate, record_validation, stage_candidate,
    )
    from atlas.memory.library import get_library
    from atlas.models import ModelManager
    from atlas.skills import SKILLS_DIR

    env = _model_env()
    model = env.pop("model")
    os.environ.update(env)
    library = get_library()
    if library is None:
        raise RuntimeError("memory library is disabled")
    experiences = read_experiences(library.store)
    verified = [item for item in experiences if item.verified and item.outcome.strip()]
    if len({item.experience_id for item in verified}) < 2:
        return {"sessions": len(experiences), "tasks": 0, "accepted": False,
                "adopted": False, "reason": "insufficient_verified_experiences"}

    manager = ModelManager()
    model_id = str(manager.current_model)
    existing_skills = []
    for path in sorted((SKILLS_DIR / "learned").glob("*/SKILL.md")):
        try:
            import yaml
            text = path.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]
            parsed = yaml.safe_load(frontmatter)
            if isinstance(parsed, dict):
                existing_skills.append({"name": str(parsed.get("name") or path.parent.name),
                                        "description": str(parsed.get("description") or "")[:240],
                                        "content": text.split("---", 2)[2].strip()[:1800]})
        except (OSError, ValueError, IndexError, yaml.YAMLError):
            continue
    try:
        candidate = asyncio.run(build_candidate(manager.model_router, model_id, experiences,
                                                 existing_skills=existing_skills))
    except (ValueError, TypeError) as exc:
        from atlas.evolution.skill_staging import record_candidate_rejection
        rejected = record_candidate_rejection(library.store.root, experiences, str(exc))
        log.warning("skill_sleep.candidate_rejected", reason=str(exc), path=str(rejected))
        return {"sessions": len(experiences), "tasks": 0, "accepted": False,
                "adopted": False, "reason": str(exc), "rejected_path": str(rejected)}
    if dry_run:
        return {"sessions": len(experiences), "tasks": 0, "accepted": False,
                "adopted": False, "candidate": candidate.name, "dry_run": True}
    candidate_path = stage_candidate(library.store.root, candidate, status="staging")

    candidate_state = candidate_path.parent / ".skillopt-state"
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config(
        backend="azure_openai", model=model,
        invoked_project=str(WORK_DIR), projects="invoked", state_dir=str(candidate_state),
        target_skill_path=str(candidate_path), managed_skill_name=candidate.name,
        evolve_memory=False,
        auto_adopt=True,  # SkillOpt may update only the Markdown staging file here.
        gate_mode="on", gate_no_regression=True,
        lookback_hours=24 * 14, max_tasks_per_night=12,
    )
    original = cycle.harvest_for_config
    original_mine = cycle.mine
    mined_tasks: list[Any] = []

    def mine_with_evidence(*args: Any, **kwargs: Any) -> list[Any]:
        tasks = original_mine(*args, **kwargs)
        mined_tasks[:] = [{"task_id": task.id, "split": task.split,
                           "origin": task.origin,
                           "experience_ids": list(task.source_sessions or [])}
                          for task in tasks]
        return tasks

    cycle.harvest_for_config = lambda _cfg, since_iso=None, limit=0: harvest_atlas(
        since_iso=since_iso, limit=limit,
    )
    cycle.mine = mine_with_evidence
    try:
        outcome = cycle.run_sleep_cycle(cfg)
    finally:
        cycle.harvest_for_config = original
        cycle.mine = original_mine
    report = outcome.report
    gate = score_candidate(report, gate_mode="on")
    success_cases = {item.experience_id for item in experiences
                     if item.verified and item.outcome.strip() and not is_counterexample(item)}
    counterexample_cases = {item.experience_id for item in experiences
                            if is_counterexample(item)}
    gate_heldout_ids = {experience_id for task in mined_tasks if task["split"] == "val"
                        for experience_id in task["experience_ids"]}
    heldout = heldout_composition(
        type("GateEvidence", (), {"heldout_ids": sorted(gate_heldout_ids)})(),
        success_cases, counterexample_cases,
    )
    if not heldout["passed"]:
        gate["passed"] = False
        gate["reason"] = heldout["reason"]
    record_validation(candidate_path, validation=gate, benchmark={
        "experience_ids": [item.experience_id for item in experiences],
        "success_case_ids": sorted(success_cases),
        "counterexample_case_ids": sorted(counterexample_cases),
        "heldout": heldout,
        "mined_tasks": mined_tasks,
        "model": model_id,
        "tools": sorted({command for item in experiences for command in item.commands}),
        "success_criteria": "heldout aggregate strictly above baseline; zero safety/correctness blockers",
        "n_sessions": report.n_sessions,
        "n_tasks": report.n_tasks,
    }, candidate=candidate)
    promotion = promote_candidate(candidate_path, report=report, gate_mode="on")
    summary = {
        "sessions": report.n_sessions, "tasks": report.n_tasks,
        "accepted": bool(gate["passed"]), "adopted": bool(promotion.get("promoted")),
        "baseline": report.baseline_score, "candidate": report.candidate_score,
        "staging": outcome.staging_dir, "candidate_path": str(candidate_path),
        "promotion": {**promotion, "gate_passed": bool(gate["passed"])},
    }
    log.info("skill_sleep.done", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="generate candidate without replay")
    args = parser.parse_args(argv)
    print(json.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
