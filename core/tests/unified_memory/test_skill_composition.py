"""UM10 T10.2 — Skill Composition Precondition & Counterfactual Guard Tests.

Verifies skill composition checks and counterfactual simulation isolation in
`atlas.memory.skill_evolution`:
- Tool availability checking across composed skills
- Precondition -> postcondition state progression across multi-step composition
- Counterfactual simulation plans tagged `epistemic_kind="SIMULATED"` with
  `factual_write_allowed=False` so simulated plans never pollute factual memory
"""

from __future__ import annotations

import pytest

from atlas.memory.skill_evolution import (
    SkillBinding,
    build_counterfactual_plan,
    check_skill_composition_preconditions,
    compute_skill_hash,
)


def _make_binding(
    skill_id: str,
    tools: tuple[str, ...],
    preconditions: tuple[str, ...],
    postconditions: tuple[str, ...],
) -> SkillBinding:
    content = f"def {skill_id}(ctx):\n    return True\n"
    return SkillBinding(
        skill_id=skill_id,
        version=1,
        skill_hash=compute_skill_hash(content),
        content=content,
        required_tools=tools,
        preconditions=preconditions,
        postconditions=postconditions,
    )


@pytest.mark.integration
def test_valid_skill_composition_chain_satisfies_preconditions() -> None:
    """Step 1 postconditions satisfy Step 2 preconditions when all tools exist."""
    step1 = _make_binding(
        "extract_schema",
        tools=("sql_inspect",),
        preconditions=("db_connected",),
        postconditions=("schema_loaded",),
    )
    step2 = _make_binding(
        "generate_migration",
        tools=("file_write",),
        preconditions=("schema_loaded",),
        postconditions=("migration_ready",),
    )

    report = check_skill_composition_preconditions(
        skills=[step1, step2],
        available_tools={"sql_inspect", "file_write"},
        env_state={"satisfied_predicates": ["db_connected"]},
    )
    assert report["composable"] is True
    assert report["missing_tools"] == []
    assert report["unsatisfied_preconditions"] == []
    assert report["steps_verified"] == ["extract_schema", "generate_migration"]
    assert "migration_ready" in report["final_predicates"]


@pytest.mark.unit
def test_composition_detects_missing_tools_and_unsatisfied_preconditions() -> None:
    """Missing tools or out-of-order preconditions must mark composition as non-composable."""
    step1 = _make_binding(
        "deploy_bundle",
        tools=("k8s_apply", "docker_push"),
        preconditions=("artifact_signed",),
        postconditions=("deployed",),
    )

    report = check_skill_composition_preconditions(
        skills=[step1],
        available_tools={"docker_push"},
        env_state={"satisfied_predicates": ["workspace_clean"]},
    )
    assert report["composable"] is False
    assert report["missing_tools"] == [
        {"skill_id": "deploy_bundle", "missing_tools": ["k8s_apply"]}
    ]
    assert report["unsatisfied_preconditions"] == [
        {"skill_id": "deploy_bundle", "unsatisfied_preconditions": ["artifact_signed"]}
    ]


@pytest.mark.unit
def test_counterfactual_plan_is_tagged_simulated_and_blocks_factual_write() -> None:
    """Counterfactual plans must carry epistemic_kind == 'SIMULATED' and disallow factual writes."""
    skills = [
        {
            "skill_id": "simulate_refactor",
            "required_tools": ["ast_parse"],
            "preconditions": ["repo_indexed"],
            "postconditions": ["refactor_previewed"],
        }
    ]
    plan = build_counterfactual_plan(
        goal="What if we replace the legacy parser with AST transforms?",
        skills=skills,
        available_tools=["ast_parse"],
        env_state={"satisfied_predicates": ["repo_indexed"]},
    )
    assert plan.epistemic_kind == "SIMULATED"
    assert plan.factual_write_allowed is False
    assert plan.proposed_skills == ["simulate_refactor"]
    assert plan.precondition_report["composable"] is True
