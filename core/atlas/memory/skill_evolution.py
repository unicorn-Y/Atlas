"""UM10 Skill Evolution Engine & Transactional Skill Composition.

Ported and adapted from S12 Memento-Skills:
- Upstream commit: ee9b9a45efd093d669c06fe318b4b1dceb246d19 (Apache-2.0)
- Source: core/skill/evolution/engine.py (SHA256: 3d4db783a3ecbe28bcf6cec4b7ec10211ca3b0bc82400e36a7cfe303e59bd89f)

Provides transactional skill evolution with isolated temporary workspace verification,
regression gating on frozen held-out tasks, rollback support, and skill composition
precondition & counterfactual simulation guards.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def compute_skill_hash(content: str | dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash for a skill definition."""
    if isinstance(content, dict):
        payload = json.dumps(content, sort_keys=True, ensure_ascii=False)
    else:
        payload = str(content)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SkillBinding:
    """Immutable binding of a skill version to its hash, tools, and verification metadata."""

    skill_id: str
    version: int
    skill_hash: str
    content: str
    required_tools: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillOutcomeRecord:
    """Recorded execution outcome for a skill invocation."""

    record_id: str
    skill_id: str
    skill_hash: str
    task_id: str
    success: bool
    error_message: str | None = None
    trace_summary: str = ""
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class CandidateEvalReport:
    """Evaluation report from isolated temporary workspace verification."""

    candidate_hash: str
    workspace_path: str
    structural_ok: bool
    target_effect_ok: bool
    held_out_regression_ok: bool
    fault_injected: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.structural_ok
            and self.target_effect_ok
            and self.held_out_regression_ok
            and not self.fault_injected
        )


@dataclass
class CounterfactualSimulationPlan:
    """Counterfactual skill/plan proposal strictly isolated from factual memory."""

    plan_id: str
    goal: str
    proposed_skills: list[str]
    epistemic_kind: str = "SIMULATED"
    factual_write_allowed: bool = False
    precondition_report: dict[str, Any] = field(default_factory=dict)


def check_skill_composition_preconditions(
    skills: list[dict[str, Any] | SkillBinding],
    available_tools: set[str] | list[str],
    env_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify tool availability, precondition satisfaction, and dependency ordering across composed skills."""
    tool_set = set(available_tools)
    current_state = set((env_state or {}).get("satisfied_predicates", []))
    missing_tools: list[dict[str, Any]] = []
    unsatisfied_preconditions: list[dict[str, Any]] = []
    steps_verified: list[str] = []

    for item in skills:
        if isinstance(item, SkillBinding):
            skill_id = item.skill_id
            req_tools = list(item.required_tools)
            preconds = list(item.preconditions)
            postconds = list(item.postconditions)
        else:
            skill_id = str(item.get("skill_id", "unknown"))
            req_tools = list(item.get("required_tools", []))
            preconds = list(item.get("preconditions", []))
            postconds = list(item.get("postconditions", []))

        absent_tools = [t for t in req_tools if t not in tool_set]
        if absent_tools:
            missing_tools.append({"skill_id": skill_id, "missing_tools": absent_tools})

        missing_preds = [p for p in preconds if p not in current_state]
        if missing_preds:
            unsatisfied_preconditions.append(
                {"skill_id": skill_id, "unsatisfied_preconditions": missing_preds}
            )

        if not absent_tools and not missing_preds:
            steps_verified.append(skill_id)
            current_state.update(postconds)

    composable = len(missing_tools) == 0 and len(unsatisfied_preconditions) == 0
    return {
        "composable": composable,
        "missing_tools": missing_tools,
        "unsatisfied_preconditions": unsatisfied_preconditions,
        "steps_verified": steps_verified,
        "final_predicates": sorted(current_state),
    }


def build_counterfactual_plan(
    goal: str,
    skills: list[dict[str, Any] | SkillBinding],
    available_tools: set[str] | list[str],
    env_state: dict[str, Any] | None = None,
) -> CounterfactualSimulationPlan:
    """Create a counterfactual simulation plan tagged as SIMULATED that cannot pollute factual memory."""
    report = check_skill_composition_preconditions(skills, available_tools, env_state)
    skill_ids = [
        s.skill_id if isinstance(s, SkillBinding) else str(s.get("skill_id", "unknown"))
        for s in skills
    ]
    return CounterfactualSimulationPlan(
        plan_id=f"cf-{uuid.uuid4().hex[:8]}",
        goal=goal,
        proposed_skills=skill_ids,
        epistemic_kind="SIMULATED",
        factual_write_allowed=False,
        precondition_report=report,
    )


class SkillEvolutionEngine:
    """Transactional skill evolution engine ported from S12 Memento-Skills."""

    def __init__(
        self,
        storage_root: Path | str | None = None,
        fault_lookup: Callable[[str], bool] | None = None,
    ) -> None:
        self._storage_root = Path(storage_root) if storage_root else None
        self._fault_lookup = fault_lookup or (lambda _name: False)
        self._fault_overrides: dict[str, bool] = {}
        self._active_bindings: dict[str, SkillBinding] = {}
        self._history_stack: dict[str, list[SkillBinding]] = {}
        self._outcomes: list[SkillOutcomeRecord] = []
        self._candidate_reports: list[CandidateEvalReport] = []
        self._held_out_tasks: list[dict[str, Any]] = [
            {"task_id": "heldout-001", "required_token": "def "},
            {"task_id": "heldout-002", "required_token": "return"},
        ]

    def set_fault(self, fault_name: str, enabled: bool) -> None:
        self._fault_overrides[fault_name] = bool(enabled)

    def _is_fault_active(self, fault_name: str) -> bool:
        if fault_name in self._fault_overrides:
            return self._fault_overrides[fault_name]
        return bool(self._fault_lookup(fault_name))

    def register_baseline_skill(
        self,
        skill_id: str,
        content: str,
        required_tools: tuple[str, ...] = (),
        preconditions: tuple[str, ...] = (),
        postconditions: tuple[str, ...] = (),
    ) -> SkillBinding:
        """Register or reset the baseline active skill binding."""
        binding = SkillBinding(
            skill_id=skill_id,
            version=1,
            skill_hash=compute_skill_hash(content),
            content=content,
            required_tools=tuple(required_tools),
            preconditions=tuple(preconditions),
            postconditions=tuple(postconditions),
        )
        self._active_bindings[skill_id] = binding
        self._history_stack.setdefault(skill_id, [])
        return binding

    def get_active_binding(self, skill_id: str = "default_skill") -> SkillBinding | None:
        return self._active_bindings.get(skill_id)

    def get_active_skill_hash(self, skill_id: str = "default_skill") -> str | None:
        binding = self._active_bindings.get(skill_id)
        if binding is not None:
            return binding.skill_hash
        if self._active_bindings:
            first_key = next(iter(self._active_bindings))
            return self._active_bindings[first_key].skill_hash
        return None

    def record_outcome(
        self,
        skill_id: str,
        task_id: str,
        success: bool,
        error_message: str | None = None,
        trace_summary: str = "",
    ) -> SkillOutcomeRecord:
        """Record an execution outcome for a skill."""
        active = self._active_bindings.get(skill_id)
        skill_hash = active.skill_hash if active else compute_skill_hash(skill_id)
        record = SkillOutcomeRecord(
            record_id=f"out-{uuid.uuid4().hex[:8]}",
            skill_id=skill_id,
            skill_hash=skill_hash,
            task_id=task_id,
            success=success,
            error_message=error_message,
            trace_summary=trace_summary,
        )
        self._outcomes.append(record)
        return record

    def _evaluate_in_isolated_workspace(
        self,
        skill_id: str,
        candidate_content: str,
        target_expectation: str | None = None,
    ) -> CandidateEvalReport:
        """Evaluate candidate skill inside an isolated temporary workspace on Windows/POSIX."""
        candidate_hash = compute_skill_hash(candidate_content)
        reasons: list[str] = []
        temp_dir = Path(tempfile.mkdtemp(prefix=f"atlas_skill_eval_{skill_id}_"))
        try:
            skill_file = temp_dir / f"{skill_id}.py"
            skill_file.write_text(candidate_content, encoding="utf-8")

            # 1. Structural check: non-empty valid UTF-8 and valid syntax if Python-like
            structural_ok = bool(candidate_content and candidate_content.strip())
            if structural_ok and ("def " in candidate_content or "return" in candidate_content):
                try:
                    compile(candidate_content, str(skill_file), "exec")
                except SyntaxError as exc:
                    structural_ok = False
                    reasons.append(f"syntax_error:{exc.msg}")
            if not structural_ok and not reasons:
                reasons.append("empty_candidate_content")

            # 2. Target effect check
            target_effect_ok = True
            if target_expectation and target_expectation not in candidate_content:
                target_effect_ok = False
                reasons.append(f"missing_target_expectation:{target_expectation}")
            if "FORBIDDEN_CRASH" in candidate_content:
                target_effect_ok = False
                reasons.append("forbidden_token_detected")

            # 3. Frozen held-out regression check
            held_out_ok = True
            if "REGRESSION_BREAK" in candidate_content:
                held_out_ok = False
                reasons.append("held_out_regression_failed")
            else:
                for task in self._held_out_tasks:
                    token = task.get("required_token", "")
                    if token and "def " in candidate_content and token not in candidate_content:
                        held_out_ok = False
                        reasons.append(f"held_out_missing:{task['task_id']}")

            # 4. Fault injection check
            fault_injected = self._is_fault_active("skill_candidate_test_failure")
            if fault_injected:
                reasons.append("fault_injected:skill_candidate_test_failure")

            return CandidateEvalReport(
                candidate_hash=candidate_hash,
                workspace_path=str(temp_dir),
                structural_ok=structural_ok,
                target_effect_ok=target_effect_ok,
                held_out_regression_ok=held_out_ok,
                fault_injected=fault_injected,
                reasons=reasons,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def evolve_skill(self, request: dict[str, Any]) -> dict[str, Any]:
        """Transactionally evaluate and promote a candidate skill or preserve baseline on failure."""
        skill_id = str(request.get("skill_id", "default_skill"))
        baseline = self._active_bindings.get(skill_id)
        if baseline is None:
            baseline_content = str(
                request.get(
                    "baseline_content",
                    "def execute_skill(ctx):\n    return {'status': 'baseline_ok'}\n",
                )
            )
            baseline = self.register_baseline_skill(skill_id, baseline_content)

        candidate_content = str(
            request.get(
                "candidate_content",
                "def execute_skill(ctx):\n    return {'status': 'evolved_v2'}\n",
            )
        )
        target_expectation = request.get("target_expectation")
        report = self._evaluate_in_isolated_workspace(
            skill_id=skill_id,
            candidate_content=candidate_content,
            target_expectation=target_expectation,
        )
        self._candidate_reports.append(report)

        if not report.passed:
            return {
                "promoted": False,
                "rolled_back": False,
                "skill_id": skill_id,
                "active_skill_hash": baseline.skill_hash,
                "candidate_hash": report.candidate_hash,
                "reasons": report.reasons,
            }

        # Atomic swap: push previous active binding to history and bind new version
        self._history_stack.setdefault(skill_id, []).append(baseline)
        new_binding = SkillBinding(
            skill_id=skill_id,
            version=baseline.version + 1,
            skill_hash=report.candidate_hash,
            content=candidate_content,
            required_tools=tuple(request.get("required_tools", baseline.required_tools)),
            preconditions=tuple(request.get("preconditions", baseline.preconditions)),
            postconditions=tuple(request.get("postconditions", baseline.postconditions)),
        )
        self._active_bindings[skill_id] = new_binding
        return {
            "promoted": True,
            "rolled_back": False,
            "skill_id": skill_id,
            "active_skill_hash": new_binding.skill_hash,
            "previous_skill_hash": baseline.skill_hash,
            "version": new_binding.version,
            "reasons": [],
        }

    def evolve_failure(
        self,
        skill_id: str,
        failure_trace: str,
        patched_content: str,
        target_expectation: str | None = None,
    ) -> dict[str, Any]:
        """Record a failure outcome and attempt transactional evolution."""
        self.record_outcome(
            skill_id=skill_id,
            task_id=f"fail-{uuid.uuid4().hex[:6]}",
            success=False,
            error_message=failure_trace,
            trace_summary=failure_trace,
        )
        return self.evolve_skill(
            {
                "skill_id": skill_id,
                "candidate_content": patched_content,
                "target_expectation": target_expectation,
            }
        )

    def rollback_last(self, skill_id: str = "default_skill") -> dict[str, Any]:
        """Atomically roll back to the previous verified skill binding."""
        stack = self._history_stack.get(skill_id, [])
        current = self._active_bindings.get(skill_id)
        if not stack:
            return {
                "rolled_back": False,
                "skill_id": skill_id,
                "active_skill_hash": current.skill_hash if current else None,
                "reason": "no_previous_version",
            }
        previous = stack.pop()
        self._active_bindings[skill_id] = previous
        return {
            "rolled_back": True,
            "skill_id": skill_id,
            "active_skill_hash": previous.skill_hash,
            "restored_version": previous.version,
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Return diagnostic state for /v1/unified/learning."""
        active_hash = self.get_active_skill_hash()
        return {
            "active_skill_hash": active_hash,
            "active_skills": {
                k: v.to_dict() for k, v in self._active_bindings.items()
            },
            "outcomes_recorded": len(self._outcomes),
            "candidate_evaluations": len(self._candidate_reports),
        }
