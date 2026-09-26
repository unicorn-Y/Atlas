"""Structured task plans used to guide and resume multi-step agent runs."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanSubtask:
    id: str
    title: str
    verification: str
    status: str = "pending"
    evidence: str = ""


@dataclass
class TaskPlan:
    goal: str
    subtasks: list[PlanSubtask] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TaskPlan:
        goal = value.get("goal")
        subtasks = value.get("subtasks")
        if not isinstance(goal, str) or not goal.strip() or not isinstance(subtasks, list):
            raise ValueError("A plan requires a goal and a subtasks list")
        parsed: list[PlanSubtask] = []
        seen: set[str] = set()
        for item in subtasks:
            if not isinstance(item, dict):
                raise ValueError("Each plan subtask must be an object")
            task_id, title, verification = (
                item.get("id"), item.get("title"), item.get("verification")
            )
            if not all(
                isinstance(part, str) and part.strip()
                for part in (task_id, title, verification)
            ):
                raise ValueError("Each subtask requires id, title, and verification")
            if task_id in seen:
                raise ValueError(f"Duplicate plan subtask id: {task_id}")
            seen.add(task_id)
            status = item.get("status", "pending")
            if status not in ("pending", "completed"):
                raise ValueError(f"Invalid status for subtask {task_id}")
            parsed.append(PlanSubtask(
                id=task_id, title=title, verification=verification,
                status=status, evidence=str(item.get("evidence", "")),
            ))
        if not parsed:
            raise ValueError("A plan must contain at least one subtask")
        return cls(goal=goal, subtasks=parsed)

    def apply_verification(self, results: list[dict[str, Any]]) -> None:
        by_id = {item.id: item for item in self.subtasks}
        for result in results:
            if not isinstance(result, dict):
                continue
            item = by_id.get(result.get("id"))
            evidence = result.get("evidence")
            if (
                item
                and result.get("completed") is True
                and isinstance(evidence, str)
                and evidence.strip()
            ):
                item.status = "completed"
                item.evidence = evidence.strip()


_MULTI_STEP = re.compile(
    r"(?:\bthen\b|\bafter that\b|\bfirst\b.{0,160}\bthen\b|"
    r"\b1[.)]\s|\b2[.)]\s|\n\s*[-*]\s|"
    r"先.{0,160}(?:再|然后|接着)|第[一二1].{0,160}第[二三23])",
    re.IGNORECASE,
)


def requires_plan(message: str) -> bool:
    """Use planning for explicit sequences and numbered/bulleted task lists."""
    return bool(_MULTI_STEP.search(message))
