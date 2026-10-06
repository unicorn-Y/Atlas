"""UM10 T10.3 & T10.4 — Targeted Deep Research & Independent Verifier Tests.

Verifies S14 OpenSkill port in `atlas.memory.targeted_learning`:
- 5-way gap classification (`KNOWLEDGE_GAP`, `IMPLEMENTATION_BUG`, `RETRIEVAL_GAP`,
  `AUTH_OR_DATA_GAP`, `UNKNOWN`)
- `AUTH_OR_DATA_GAP` blocks fake external research and refuses fact fabrication
  (Acceptance test: `"找出那个没有导入的文件里的人名"` -> `AUTH_OR_DATA_GAP`, `fabricated_fact == False`)
- Duplicate research suppression and `THIRD_PARTY_ASSERTED` tagging on external research
- `IndependentVerifier` running in a distinct verification context and refuting
  unverified generator claims (`kg-003` `page_token` -> `REFUTED`)
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.memory.targeted_learning import (
    IndependentVerifier,
    TargetedDRRunner,
)


class TargetedLearningHarness:
    """Self-contained harness providing `seed` and `chat` for T10.3 & T10.4."""

    def __init__(self) -> None:
        self.verifier = IndependentVerifier()
        self.runner = TargetedDRRunner(verifier=self.verifier)
        self.seeded: set[str] = set()

    def seed(self, kind: str) -> dict[str, Any]:
        self.seeded.add(kind)
        return {"seeded": kind}

    def chat(self, prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.runner.handle_query(prompt, context=context)


@pytest.fixture
def h() -> TargetedLearningHarness:
    return TargetedLearningHarness()


@pytest.mark.integration
def test_data_gap_does_not_trigger_fake_research(h: TargetedLearningHarness) -> None:
    """Acceptance test (T10.3): unimported private file query must be AUTH_OR_DATA_GAP without fabrication."""
    h.seed("knowledge_gap")
    result = h.chat("找出那个没有导入的文件里的人名")
    assert result["gap_kind"] == "AUTH_OR_DATA_GAP" and not result["fabricated_fact"]
    assert result["research_triggered"] is False
    assert h.runner.snapshot_metrics()["research_call_count"] == 0


@pytest.mark.unit
def test_five_way_gap_taxonomy_classification(h: TargetedLearningHarness) -> None:
    """All 5 gap kinds in UM10 taxonomy are accurately classified."""
    assert (
        h.runner.classify_gap("请查询 RFC 9110 官方文档里 Retry-After 的外部规范")
        == "KNOWLEDGE_GAP"
    )
    assert (
        h.runner.classify_gap("Traceback (most recent call last): TypeError: NoneType")
        == "IMPLEMENTATION_BUG"
    )
    assert (
        h.runner.classify_gap("Vector index not built and 向量索引未同步 for chunk")
        == "RETRIEVAL_GAP"
    )
    assert (
        h.runner.classify_gap("Permission denied: 访问未授权的私有仓库")
        == "AUTH_OR_DATA_GAP"
    )
    assert h.runner.classify_gap("随便聊聊今天的天气") == "UNKNOWN"


@pytest.mark.unit
def test_duplicate_research_suppression_and_third_party_tagging(
    h: TargetedLearningHarness,
) -> None:
    """External research is tagged THIRD_PARTY_ASSERTED and duplicate queries are suppressed."""
    q1 = "请查询 RFC 9110 官方文档中的状态码规范"
    r1 = h.chat(q1)
    assert r1["gap_kind"] == "KNOWLEDGE_GAP"
    assert r1["research_triggered"] is True
    assert r1["epistemic_tag"] == "THIRD_PARTY_ASSERTED"
    assert r1["promoted_to_factual"] is False

    # Second identical/whitespace-normalized query must be suppressed
    r2 = h.chat("  请查询   RFC 9110 官方文档中的状态码规范 ")
    assert r2["gap_kind"] == "KNOWLEDGE_GAP"
    assert r2["research_triggered"] is False
    assert r2["duplicate_suppressed"] is True
    assert r2["epistemic_tag"] == "THIRD_PARTY_ASSERTED"
    metrics = h.runner.snapshot_metrics()
    assert metrics["research_call_count"] == 1
    assert metrics["suppressed_duplicates"] == 1


@pytest.mark.integration
def test_independent_verifier_refutes_kg003_page_token_claim(
    h: TargetedLearningHarness,
) -> None:
    """T10.4: IndependentVerifier runs in separate context and refutes kg-003 page_token claim."""
    gen_ctx = "gen-ctx-session-42"
    verdict = h.verifier.verify_claim(
        case_id="kg-003",
        claim="The endpoint supports pagination via the `page_token` parameter.",
        generator_context_id=gen_ctx,
    )
    assert verdict.verdict == "REFUTED"
    assert verdict.verifier_context_id != verdict.generator_context_id
    assert "page_token" in (verdict.refutation_reason or "")

    # Grounded claim on kg-003 (`cursor` and `limit`) is VERIFIED
    verified = h.verifier.verify_claim(
        case_id="kg-003",
        claim="Pagination uses `cursor` and `limit` parameters.",
        generator_context_id=gen_ctx,
    )
    assert verified.verdict == "VERIFIED"
    assert verified.verifier_context_id != verified.generator_context_id
    assert "ev-api-spec-v2" in verified.grounded_evidence_ids
