"""UM10 T10.1 — Transactional Skill Evolution & Rollback Tests.

Verifies S12 Memento-Skills port in `atlas.memory.skill_evolution`:
- Candidate evaluation in isolated temporary workspace (never touching production dirs)
- Structural + target effect + frozen held-out regression checks
- Fault injection `skill_candidate_test_failure` preserves `active_skill_hash == baseline_hash`
- Atomic swap on passing candidate and `rollback_last()` restoring previous binding
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from atlas.memory.skill_evolution import (
    SkillBinding,
    SkillEvolutionEngine,
    compute_skill_hash,
)


class _ResponseStub:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class SkillEvolutionHarness:
    """Self-contained harness providing `seed`, `fault`, `tool`, and `api` for T10.1."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.engine = SkillEvolutionEngine(storage_root=tmp_path / "skills_store")

    def seed(self, kind: str) -> dict[str, Any]:
        if kind == "skill":
            baseline_code = (
                "def execute_skill(ctx):\n"
                "    return {'status': 'baseline_v1', 'ok': True}\n"
            )
            binding = self.engine.register_baseline_skill(
                skill_id="skill_alpha",
                content=baseline_code,
                required_tools=("read_file",),
                preconditions=("workspace_ready",),
                postconditions=("artifact_parsed",),
            )
            candidate_code = (
                "def execute_skill(ctx):\n"
                "    return {'status': 'candidate_v2', 'ok': True}\n"
            )
            return {
                "skill_id": binding.skill_id,
                "baseline_hash": binding.skill_hash,
                "evolution_request": {
                    "skill_id": binding.skill_id,
                    "candidate_content": candidate_code,
                    "target_expectation": "candidate_v2",
                },
            }
        raise ValueError(f"Unsupported seed kind: {kind}")

    def fault(self, fault_name: str, enabled: bool = True) -> None:
        self.engine.set_fault(fault_name, enabled)

    def tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "evolve_skill":
            return self.engine.evolve_skill(payload)
        if tool_name == "rollback_skill":
            return self.engine.rollback_last(str(payload.get("skill_id", "skill_alpha")))
        raise ValueError(f"Unsupported tool: {tool_name}")

    def api(self, method: str, path: str) -> _ResponseStub:
        if method.upper() == "GET" and path == "/v1/unified/learning":
            return _ResponseStub(self.engine.snapshot_state())
        raise ValueError(f"Unsupported API call: {method} {path}")


@pytest.fixture
def h(tmp_path: Path) -> SkillEvolutionHarness:
    return SkillEvolutionHarness(tmp_path)


@pytest.mark.integration
def test_failed_evolution_preserves_active_skill(h: SkillEvolutionHarness) -> None:
    """Acceptance test (T10.1): failed candidate test must preserve active_skill_hash."""
    d = h.seed("skill")
    h.fault("skill_candidate_test_failure", True)
    h.tool("evolve_skill", d["evolution_request"])
    assert h.api("GET", "/v1/unified/learning").json()["active_skill_hash"] == d["baseline_hash"]


@pytest.mark.unit
def test_syntax_or_regression_failure_blocks_promotion(h: SkillEvolutionHarness) -> None:
    """Broken syntax or held-out regression failure must not overwrite baseline skill."""
    d = h.seed("skill")

    # 1. Syntax error in candidate
    bad_syntax_res = h.tool(
        "evolve_skill",
        {
            "skill_id": d["skill_id"],
            "candidate_content": "def execute_skill(ctx):\n    return {\n",
        },
    )
    assert bad_syntax_res["promoted"] is False
    assert h.api("GET", "/v1/unified/learning").json()["active_skill_hash"] == d["baseline_hash"]

    # 2. Frozen held-out regression break
    regression_res = h.tool(
        "evolve_skill",
        {
            "skill_id": d["skill_id"],
            "candidate_content": "def execute_skill(ctx):\n    # REGRESSION_BREAK\n    return None\n",
        },
    )
    assert regression_res["promoted"] is False
    assert "held_out_regression_failed" in regression_res["reasons"]
    assert h.api("GET", "/v1/unified/learning").json()["active_skill_hash"] == d["baseline_hash"]


@pytest.mark.unit
def test_successful_evolution_and_atomic_rollback(h: SkillEvolutionHarness) -> None:
    """Passing candidate promotes new skill_hash and rollback_last restores baseline_hash."""
    d = h.seed("skill")
    res = h.tool("evolve_skill", d["evolution_request"])
    assert res["promoted"] is True
    promoted_hash = h.api("GET", "/v1/unified/learning").json()["active_skill_hash"]
    assert promoted_hash != d["baseline_hash"]
    assert promoted_hash == compute_skill_hash(d["evolution_request"]["candidate_content"])

    rb = h.tool("rollback_skill", {"skill_id": d["skill_id"]})
    assert rb["rolled_back"] is True
    assert h.api("GET", "/v1/unified/learning").json()["active_skill_hash"] == d["baseline_hash"]


@pytest.mark.unit
def test_evolve_failure_records_outcome_and_cleans_temp_workspace(
    h: SkillEvolutionHarness,
) -> None:
    """evolve_failure records failure outcome and evaluates in an auto-cleaned temp directory."""
    d = h.seed("skill")
    patched = "def execute_skill(ctx):\n    return {'status': 'patched_ok'}\n"
    result = h.engine.evolve_failure(
        skill_id=d["skill_id"],
        failure_trace="KeyError: missing_field",
        patched_content=patched,
        target_expectation="patched_ok",
    )
    assert result["promoted"] is True
    state = h.engine.snapshot_state()
    assert state["outcomes_recorded"] == 1
    assert state["candidate_evaluations"] == 1
    # Verify temporary workspace was cleaned up after evaluation
    eval_report = h.engine._candidate_reports[-1]
    assert not Path(eval_report.workspace_path).exists()
    assert isinstance(h.engine.get_active_binding(d["skill_id"]), SkillBinding)
