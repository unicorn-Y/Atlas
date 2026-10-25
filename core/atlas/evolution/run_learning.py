"""Durable terminal-run signals and automatic skill-candidate extraction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from atlas.evolution.skill_curator import SkillCurator


def record_terminal_run(
    *, run_id: str, conversation_id: str, status: str, project_id: str | None = None,
    agent_id: str | None = None, user_text: str = "", assistant_text: str = "",
) -> dict[str, Any]:
    """Persist a terminal outcome and create an idempotent candidate on success."""
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError("status must be a terminal run status")
    from atlas.evolution.watcher import evolution_root

    root = evolution_root() / "run-outcomes"
    root.mkdir(parents=True, exist_ok=True)
    outcome = {
        "run_id": str(run_id), "conversation_id": str(conversation_id),
        "status": status, "project_id": str(project_id or ""),
        "agent_id": str(agent_id or ""),
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path = root / f"{_safe_id(run_id)}.json"
    duplicate = False
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prior, dict) and prior.get("status") == status:
                outcome = prior
                duplicate = True
        except (OSError, ValueError):
            pass
    if not duplicate:
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    candidate = None
    if status == "completed" and str(user_text).strip() and str(assistant_text).strip():
        candidate = SkillCurator().create_candidate_from_conversation(
            conversation_id=conversation_id, run_id=run_id, user_text=user_text,
            assistant_text=assistant_text, project_id=project_id, agent_id=agent_id,
        )
    return {"outcome": outcome, "candidate": candidate, "duplicate": duplicate}


def _safe_id(value: str) -> str:
    result = "".join(char for char in str(value) if char.isalnum() or char in "-_")
    return result[:128] or "unknown"


def transcript_excerpt(messages: list[dict[str, Any]], run_id: str) -> tuple[str, str]:
    """Find the user request and final assistant answer for one persisted run."""
    matching = []
    for message in messages:
        metadata = message.get("metadata") or {}
        if isinstance(metadata, dict) and str(metadata.get("run_id") or "") == str(run_id):
            matching.append(message)
    user = next((str(item.get("content") or "").strip() for item in reversed(matching)
                 if item.get("role") == "user" and str(item.get("content") or "").strip()), "")
    assistant = next((str(item.get("content") or "").strip() for item in reversed(matching)
                      if item.get("role") == "assistant"
                      and str(item.get("content") or "").strip()), "")
    return user, assistant
