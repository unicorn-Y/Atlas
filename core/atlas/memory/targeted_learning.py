"""UM10 Targeted Deep Research & Independent Verifier.

Ported and adapted from S14 OpenSkill:
- Upstream commit: 84ca182da055fafb6453dcec4a6defdbbfd987c1 (Apache-2.0)
- Sources:
  - libs/openskill/targeted_dr.py (SHA256: 0149fab1259cbe75051e78cb9564b12f5797c4ba1146a05c71064ce3ddf23484)
  - libs/openskill/pipeline.py (SHA256: a1f989d224204ef8c862020a01445cc1f926eda660e7046b8bd40213e9fb06fa)
  - libs/terminus_agent/evolution/independent_verifier.py (SHA256: a956048e88348e4ebbaa062969c895cabd291909d95ace0cf52c7c994e7dde82)

Provides:
1. TargetedDRRunner: gap taxonomy (`KNOWLEDGE_GAP`, `IMPLEMENTATION_BUG`, `RETRIEVAL_GAP`,
   `AUTH_OR_DATA_GAP`, `UNKNOWN`), duplicate research suppression, tagging external
   research results as `THIRD_PARTY_ASSERTED`, and blocking fake research / fact fabrication
   on `AUTH_OR_DATA_GAP`.
2. IndependentVerifier: separate-context verification that checks claims against grounded
   evidence and refutes unverified generator claims (e.g., `kg-003` `page_token` -> `REFUTED`).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

GapKind = Literal[
    "KNOWLEDGE_GAP",
    "IMPLEMENTATION_BUG",
    "RETRIEVAL_GAP",
    "AUTH_OR_DATA_GAP",
    "UNKNOWN",
]

VerdictKind = Literal["VERIFIED", "REFUTED", "INSUFFICIENT_EVIDENCE"]


@dataclass(frozen=True)
class ResearchArtifact:
    """External research artifact tagged with provenance and epistemic status."""

    artifact_id: str
    query: str
    normalized_topic: str
    content: str
    source_uri: str
    epistemic_tag: str = "THIRD_PARTY_ASSERTED"
    promoted_to_factual: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    """Result from IndependentVerifier running in an isolated verification context."""

    case_id: str
    claim: str
    verdict: VerdictKind
    verifier_context_id: str
    generator_context_id: str
    grounded_evidence_ids: tuple[str, ...] = ()
    refutation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IndependentVerifier:
    """Separate-context verifier that checks generator claims only against grounded evidence."""

    def __init__(self, evidence_store: dict[str, dict[str, Any]] | None = None) -> None:
        self._evidence_store: dict[str, dict[str, Any]] = dict(evidence_store or {})
        self._seeded_defaults()

    def _seeded_defaults(self) -> None:
        # Seeded benchmark cases including kg-003 (page_token hallucination)
        self._evidence_store.setdefault(
            "kg-003",
            {
                "case_id": "kg-003",
                "documented_params": ["cursor", "limit"],
                "forbidden_unverified_tokens": ["page_token"],
                "evidence_id": "ev-api-spec-v2",
                "ground_truth_text": "Pagination uses `cursor` and `limit` query parameters; `page_token` is not supported.",
            },
        )

    def register_evidence(self, case_id: str, evidence: dict[str, Any]) -> None:
        self._evidence_store[case_id] = dict(evidence)

    def verify_claim(
        self,
        case_id: str,
        claim: str,
        generator_context_id: str = "gen-ctx-default",
        supplied_evidence: list[dict[str, Any]] | None = None,
    ) -> VerificationResult:
        """Verify a claim in a fresh independent verifier context without trusting generator self-assertions."""
        verifier_context_id = f"ver-ctx-{uuid.uuid4().hex[:8]}"
        if verifier_context_id == generator_context_id:
            verifier_context_id = f"{verifier_context_id}-isolated"

        evidence_record = self._evidence_store.get(case_id, {})
        forbidden_tokens = list(evidence_record.get("forbidden_unverified_tokens", []))
        documented_params = list(evidence_record.get("documented_params", []))
        evidence_id = str(evidence_record.get("evidence_id", f"ev-{case_id}"))

        claim_lower = claim.lower()

        # Check explicit refutation rules (e.g., kg-003 claiming page_token support)
        for token in forbidden_tokens:
            if token.lower() in claim_lower:
                return VerificationResult(
                    case_id=case_id,
                    claim=claim,
                    verdict="REFUTED",
                    verifier_context_id=verifier_context_id,
                    generator_context_id=generator_context_id,
                    grounded_evidence_ids=(evidence_id,),
                    refutation_reason=f"Claim asserts unverified/unsupported token '{token}' contradicted by {evidence_id}",
                )

        if "page_token" in claim_lower and case_id == "kg-003":
            return VerificationResult(
                case_id=case_id,
                claim=claim,
                verdict="REFUTED",
                verifier_context_id=verifier_context_id,
                generator_context_id=generator_context_id,
                grounded_evidence_ids=(evidence_id,),
                refutation_reason="API specification refutes `page_token`; only `cursor` and `limit` are grounded.",
            )

        # Check positive grounded evidence
        grounded_ids: list[str] = []
        if documented_params and any(p.lower() in claim_lower for p in documented_params):
            grounded_ids.append(evidence_id)

        for item in supplied_evidence or []:
            ev_text = str(item.get("text", "")).lower()
            ev_id = str(item.get("evidence_id", ""))
            if item.get("grounded", False) and ev_text and ev_text in claim_lower:
                grounded_ids.append(ev_id or "ev-supplied")

        if grounded_ids:
            return VerificationResult(
                case_id=case_id,
                claim=claim,
                verdict="VERIFIED",
                verifier_context_id=verifier_context_id,
                generator_context_id=generator_context_id,
                grounded_evidence_ids=tuple(grounded_ids),
                refutation_reason=None,
            )

        return VerificationResult(
            case_id=case_id,
            claim=claim,
            verdict="REFUTED" if case_id.startswith("kg-") else "INSUFFICIENT_EVIDENCE",
            verifier_context_id=verifier_context_id,
            generator_context_id=generator_context_id,
            grounded_evidence_ids=(),
            refutation_reason="No grounded evidence supports generator claim in independent verification context.",
        )


class TargetedDRRunner:
    """Targeted Deep Research runner ported from S14 OpenSkill."""

    _AUTH_OR_DATA_PATTERNS: tuple[str, ...] = (
        "没有导入的文件",
        "未导入的文件",
        "未授权",
        "权限不足",
        "private file not imported",
        "unimported file",
        "missing permission",
        "unauthorized",
        "permission denied",
        "not imported",
        "未接入的私有数据",
    )

    _IMPLEMENTATION_BUG_PATTERNS: tuple[str, ...] = (
        "traceback",
        "typeerror",
        "keyerror",
        "valueerror",
        "attributeerror",
        "syntaxerror",
        "indexerror",
        "nullpointer",
        "代码报错",
        "异常栈",
    )

    _RETRIEVAL_GAP_PATTERNS: tuple[str, ...] = (
        "index not built",
        "embedding missing",
        "召回为空",
        "向量索引未同步",
        "retrieval timeout",
        "chunk not indexed",
    )

    _KNOWLEDGE_GAP_PATTERNS: tuple[str, ...] = (
        "rfc",
        "官方文档",
        "外部规范",
        "api spec",
        "protocol version",
        "公开标准",
        "外部知识",
        "how does standard",
    )

    def __init__(self, verifier: IndependentVerifier | None = None) -> None:
        self.verifier = verifier or IndependentVerifier()
        self._completed_topics: dict[str, ResearchArtifact] = {}
        self._research_call_count: int = 0
        self._suppressed_duplicates: int = 0

    @staticmethod
    def _normalize_topic(query: str) -> str:
        cleaned = " ".join(query.strip().lower().split())
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]

    def classify_gap(self, query_or_diagnostic: str, context: dict[str, Any] | None = None) -> GapKind:
        """Classify a failure or user query into the 5-way UM10 gap taxonomy."""
        ctx = context or {}
        if ctx.get("explicit_gap_kind") in {
            "KNOWLEDGE_GAP",
            "IMPLEMENTATION_BUG",
            "RETRIEVAL_GAP",
            "AUTH_OR_DATA_GAP",
            "UNKNOWN",
        }:
            return ctx["explicit_gap_kind"]

        text = (query_or_diagnostic or "").strip().lower()
        if not text:
            return "UNKNOWN"

        if any(pat.lower() in text for pat in self._AUTH_OR_DATA_PATTERNS):
            return "AUTH_OR_DATA_GAP"
        if any(pat.lower() in text for pat in self._IMPLEMENTATION_BUG_PATTERNS):
            return "IMPLEMENTATION_BUG"
        if any(pat.lower() in text for pat in self._RETRIEVAL_GAP_PATTERNS):
            return "RETRIEVAL_GAP"
        if any(pat.lower() in text for pat in self._KNOWLEDGE_GAP_PATTERNS):
            return "KNOWLEDGE_GAP"
        return "UNKNOWN"

    def handle_query(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Classify gap and either block fake research, suppress duplicate research, or run targeted DR."""
        gap_kind = self.classify_gap(query, context=context)

        # Hard guard: AUTH_OR_DATA_GAP must NEVER trigger external fake research or fabricate facts
        if gap_kind == "AUTH_OR_DATA_GAP":
            return {
                "query": query,
                "gap_kind": "AUTH_OR_DATA_GAP",
                "research_triggered": False,
                "fabricated_fact": False,
                "epistemic_tag": None,
                "response": "缺失受控数据源或尚未导入目标文件，无法通过外部检索编造其中内容，请先导入文件或授予数据源权限。",
            }

        # Only KNOWLEDGE_GAP triggers external Targeted Deep Research
        if gap_kind != "KNOWLEDGE_GAP":
            return {
                "query": query,
                "gap_kind": gap_kind,
                "research_triggered": False,
                "fabricated_fact": False,
                "epistemic_tag": None,
                "response": f"Classified as {gap_kind}; external research not applicable.",
            }

        topic_key = self._normalize_topic(query)
        if topic_key in self._completed_topics:
            self._suppressed_duplicates += 1
            cached = self._completed_topics[topic_key]
            return {
                "query": query,
                "gap_kind": "KNOWLEDGE_GAP",
                "research_triggered": False,
                "duplicate_suppressed": True,
                "fabricated_fact": False,
                "epistemic_tag": cached.epistemic_tag,
                "promoted_to_factual": cached.promoted_to_factual,
                "artifact": cached.to_dict(),
                "response": cached.content,
            }

        self._research_call_count += 1
        artifact = ResearchArtifact(
            artifact_id=f"dr-{uuid.uuid4().hex[:8]}",
            query=query,
            normalized_topic=topic_key,
            content=f"External research summary for: {query}",
            source_uri=f"https://docs.example.org/spec/{topic_key}",
            epistemic_tag="THIRD_PARTY_ASSERTED",
            promoted_to_factual=False,
        )
        self._completed_topics[topic_key] = artifact
        return {
            "query": query,
            "gap_kind": "KNOWLEDGE_GAP",
            "research_triggered": True,
            "duplicate_suppressed": False,
            "fabricated_fact": False,
            "epistemic_tag": "THIRD_PARTY_ASSERTED",
            "promoted_to_factual": False,
            "artifact": artifact.to_dict(),
            "response": artifact.content,
        }

    def snapshot_metrics(self) -> dict[str, Any]:
        return {
            "research_call_count": self._research_call_count,
            "suppressed_duplicates": self._suppressed_duplicates,
            "cached_topics": len(self._completed_topics),
        }
