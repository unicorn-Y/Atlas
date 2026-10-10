# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/workflow/definition.ts (Apache-2.0)
# Validation shape follows zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/contracts/src/workflow/index.ts (Apache-2.0)
"""Built-in Expert Workflow definition and its validated phase mapping."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping, TypedDict


BUILT_IN_EXPERT_WORKFLOW_KIND = "expert"
BUILT_IN_EXPERT_WORKFLOW_DEFINITION_ID = "expert"
BUILT_IN_EXPERT_WORKFLOW_DEFINITION_VERSION = "2"


class WorkflowStrategy(TypedDict):
    """Strategy limits mirrored from ZCode's workflow contract."""

    clarify: dict[str, float | int]
    executor: dict[str, float | int]
    finalCritic: dict[str, int]
    reactLoop: dict[str, int]


class WorkflowPhaseDefinition(TypedDict, total=False):
    """One ordered phase and its optional artifact-driven graph behavior."""

    artifactPath: str
    behavior: str
    description: str
    nodePromptsFromArtifact: dict[str, str]
    phase: str
    seedGraphFromArtifact: dict[str, str]
    title: str


class WorkflowDefinition(TypedDict):
    """Serializable definition consumed by a workflow runtime."""

    definitionId: str
    definitionVersion: str
    description: str
    kind: str
    phaseOrder: list[str]
    phases: list[WorkflowPhaseDefinition]
    strategy: WorkflowStrategy
    title: str


DEFAULT_EXPERT_WORKFLOW_STRATEGY: WorkflowStrategy = {
    "clarify": {
        "confidenceThreshold": 0.8,
        "maxRounds": 3,
        "minRounds": 1,
    },
    "executor": {
        "drainingChangeHours": 1,
        "frontierTarget": 3,
        "maxConcurrentLoops": 2,
        "maxConsecutiveErrors": 3,
        "maxPlannerRuns": 10,
    },
    "finalCritic": {
        "maxIterations": 3,
    },
    "reactLoop": {
        "maxRounds": 30,
    },
}


def create_expert_workflow_definition() -> WorkflowDefinition:
    """Create the validated eight-phase Expert Workflow definition."""
    definition: WorkflowDefinition = {
        "definitionId": BUILT_IN_EXPERT_WORKFLOW_DEFINITION_ID,
        "definitionVersion": BUILT_IN_EXPERT_WORKFLOW_DEFINITION_VERSION,
        "description": "Durable long-task workflow for large NL->Code work. Child agent sessions perform each phase.",
        "kind": BUILT_IN_EXPERT_WORKFLOW_KIND,
        "phaseOrder": [
            "clarify",
            "task_analysis",
            "arch_decompose",
            "env_setup",
            "meta_prompt",
            "exec",
            "final_critic",
            "complete",
        ],
        "phases": [
            {
                "artifactPath": "artifacts/01-clarify.md",
                "behavior": "agent",
                "description": "Refine the user goal, assumptions, acceptance criteria, and unresolved questions. Ask only if blocking.",
                "phase": "clarify",
                "title": "Clarify",
            },
            {
                "artifactPath": "artifacts/02-task-analysis.md",
                "behavior": "agent",
                "description": "Map the task to repo context, constraints, risks, likely files, validation, and failure paths.",
                "phase": "task_analysis",
                "title": "Task Analysis",
            },
            {
                "artifactPath": "artifacts/03-architecture-decompose.md",
                "behavior": "agent",
                "description": "Decompose the work into a dependency graph of implementation and verification nodes.",
                "phase": "arch_decompose",
                "seedGraphFromArtifact": {
                    "gateAfterPhase": "meta_prompt",
                    "targetPhase": "exec",
                },
                "title": "Architecture Decompose",
            },
            {
                "artifactPath": "artifacts/04-env-setup.md",
                "behavior": "agent",
                "description": "Check whether environment setup, dependencies, credentials, or local services are required.",
                "phase": "env_setup",
                "title": "Environment Setup",
            },
            {
                "artifactPath": "artifacts/05-meta-prompt.md",
                "behavior": "agent",
                "description": "Create the execution instructions, constraints, and node prompts needed for downstream work.",
                "nodePromptsFromArtifact": {
                    "targetPhase": "exec",
                },
                "phase": "meta_prompt",
                "title": "Meta Prompt",
            },
            {
                "artifactPath": "artifacts/06-exec.md",
                "behavior": "scheduled_graph",
                "description": "Execute the planned work through the normal agent runtime. Preserve small steps and validation.",
                "phase": "exec",
                "title": "Execute",
            },
            {
                "artifactPath": "artifacts/07-final-critic.md",
                "behavior": "critic",
                "description": "Review results against acceptance criteria, identify regressions, missing tests, and residual risk.",
                "phase": "final_critic",
                "title": "Final Critic",
            },
            {
                "behavior": "complete",
                "description": "Write final report and mark the run completed.",
                "phase": "complete",
                "title": "Complete",
            },
        ],
        "strategy": deepcopy(DEFAULT_EXPERT_WORKFLOW_STRATEGY),
        "title": "Expert Workflow",
    }
    return _validate_definition(definition)


def workflow_definition_phase_map(
    definition: WorkflowDefinition,
) -> dict[str, WorkflowPhaseDefinition]:
    """Map each phase id to its definition, preserving source order semantics."""
    return {phase["phase"]: phase for phase in definition["phases"]}


def _validate_definition(definition: WorkflowDefinition) -> WorkflowDefinition:
    """Mirror the source WorkflowDefinitionSchema checks and normalized output."""
    for key in ("definitionId", "definitionVersion", "kind", "title"):
        _require_nonempty_string(definition.get(key), key)
    if "description" in definition and not isinstance(definition["description"], str):
        raise ValueError("description must be a string")

    order = definition.get("phaseOrder")
    phases = definition.get("phases")
    if not isinstance(order, list) or not order:
        raise ValueError("phaseOrder must contain at least one phase")
    if not isinstance(phases, list) or not phases:
        raise ValueError("phases must contain at least one phase")

    normalized_phases: list[WorkflowPhaseDefinition] = []
    for index, phase in enumerate(phases):
        if not isinstance(phase, Mapping):
            raise ValueError(f"phases[{index}] must be an object")
        _require_nonempty_string(phase.get("phase"), f"phases[{index}].phase")
        _require_nonempty_string(phase.get("description"), f"phases[{index}].description")
        _require_nonempty_string(phase.get("title"), f"phases[{index}].title")
        behavior = phase.get("behavior", "agent")
        if behavior not in {"agent", "scheduled_graph", "critic", "complete"}:
            raise ValueError(f"phases[{index}].behavior has unsupported value {behavior!r}")
        cleaned: WorkflowPhaseDefinition = {
            "behavior": behavior,
            "description": phase["description"],
            "phase": phase["phase"],
            "title": phase["title"],
        }
        if "artifactPath" in phase:
            if not isinstance(phase["artifactPath"], str):
                raise ValueError(f"phases[{index}].artifactPath must be a string")
            cleaned["artifactPath"] = phase["artifactPath"]
        if "nodePromptsFromArtifact" in phase:
            target = phase["nodePromptsFromArtifact"]
            if not isinstance(target, Mapping):
                raise ValueError(f"phases[{index}].nodePromptsFromArtifact must be an object")
            _require_nonempty_string(target.get("targetPhase"), f"phases[{index}].nodePromptsFromArtifact.targetPhase")
            cleaned["nodePromptsFromArtifact"] = {"targetPhase": target["targetPhase"]}
        if "seedGraphFromArtifact" in phase:
            seed = phase["seedGraphFromArtifact"]
            if not isinstance(seed, Mapping):
                raise ValueError(f"phases[{index}].seedGraphFromArtifact must be an object")
            _require_nonempty_string(seed.get("targetPhase"), f"phases[{index}].seedGraphFromArtifact.targetPhase")
            seed_graph = {"targetPhase": seed["targetPhase"]}
            if "gateAfterPhase" in seed:
                _require_nonempty_string(seed["gateAfterPhase"], f"phases[{index}].seedGraphFromArtifact.gateAfterPhase")
                seed_graph["gateAfterPhase"] = seed["gateAfterPhase"]
            cleaned["seedGraphFromArtifact"] = seed_graph
        normalized_phases.append(cleaned)

    seen_phases: set[str] = set()
    for phase in normalized_phases:
        phase_id = phase["phase"]
        if phase_id in seen_phases:
            raise ValueError(f"Duplicate workflow phase definition: {phase_id}")
        seen_phases.add(phase_id)

    seen_order: set[str] = set()
    for phase_id in order:
        _require_nonempty_string(phase_id, "phaseOrder entry")
        if phase_id in seen_order:
            raise ValueError(f"Duplicate workflow phase order entry: {phase_id}")
        seen_order.add(phase_id)
        if phase_id not in seen_phases:
            raise ValueError(f"Workflow phaseOrder references unknown phase: {phase_id}")
    for phase_id in seen_phases:
        if phase_id not in seen_order:
            raise ValueError(f"Workflow phase definition is missing from phaseOrder: {phase_id}")

    strategy = _validate_strategy(definition.get("strategy"))
    return {
        "definitionId": definition["definitionId"],
        "definitionVersion": definition["definitionVersion"],
        "kind": definition["kind"],
        "phaseOrder": list(order),
        "phases": normalized_phases,
        "strategy": strategy,
        "title": definition["title"],
        **({"description": definition["description"]} if "description" in definition else {}),
    }


def _validate_strategy(value: Any) -> WorkflowStrategy:
    if not isinstance(value, Mapping):
        raise ValueError("strategy must be an object")
    clarify = value.get("clarify")
    executor = value.get("executor")
    final_critic = value.get("finalCritic")
    react_loop = value.get("reactLoop")
    if not all(isinstance(section, Mapping) for section in (clarify, executor, final_critic, react_loop)):
        raise ValueError("strategy must define clarify, executor, finalCritic, and reactLoop")
    _require_number(clarify.get("confidenceThreshold"), "strategy.clarify.confidenceThreshold")
    _require_integer(clarify.get("maxRounds"), "strategy.clarify.maxRounds", positive=True)
    _require_integer(clarify.get("minRounds"), "strategy.clarify.minRounds", positive=False)
    _require_number(executor.get("drainingChangeHours"), "strategy.executor.drainingChangeHours", positive=True)
    for key in ("frontierTarget", "maxConcurrentLoops", "maxConsecutiveErrors", "maxPlannerRuns"):
        _require_integer(executor.get(key), f"strategy.executor.{key}", positive=True)
    _require_integer(final_critic.get("maxIterations"), "strategy.finalCritic.maxIterations", positive=True)
    _require_integer(react_loop.get("maxRounds"), "strategy.reactLoop.maxRounds", positive=True)
    return {
        "clarify": {
            "confidenceThreshold": clarify["confidenceThreshold"],
            "maxRounds": clarify["maxRounds"],
            "minRounds": clarify["minRounds"],
        },
        "executor": {
            "drainingChangeHours": executor["drainingChangeHours"],
            "frontierTarget": executor["frontierTarget"],
            "maxConcurrentLoops": executor["maxConcurrentLoops"],
            "maxConsecutiveErrors": executor["maxConsecutiveErrors"],
            "maxPlannerRuns": executor["maxPlannerRuns"],
        },
        "finalCritic": {"maxIterations": final_critic["maxIterations"]},
        "reactLoop": {"maxRounds": react_loop["maxRounds"]},
    }


def _require_nonempty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a nonempty string")


def _require_number(value: Any, path: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{path} must be positive")


def _require_integer(value: Any, path: str, *, positive: bool) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"{path} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{path} must be nonnegative")

