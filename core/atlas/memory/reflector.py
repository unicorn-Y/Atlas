"""Model-backed reflection and consolidation of durable memories.

Vendored and adapted from mastra-ai/mastra at
commit 9c2e4c7cde40a4321112e24affd1750e9be827f9 (Apache-2.0).
Source files:
  - packages/memory/src/processors/observational-memory/reflector-agent.ts
    (blob bcf92d0c4b2f52aaf34daf5e4f7feed66af059db)
  - packages/memory/src/processors/observational-memory/thresholds.ts
    (blob b46e0d2e8142fc812a8c1ccff66d3a7f12cd3d0d)

Adapted for Atlas Memory V1 §S4:
  - Outputs structured operations list (MERGE, SUPERSEDE, ROLLUP_DAY,
    ROLLUP_WEEK, PROFILE_UPDATE, IMPORTANCE) rather than raw text rewrites.
  - Profile compression validation: <= 600 tokens and strict traceability
    where every sentence must be grounded in source refs.
  - Local static validation of proposed operations prior to MemoryOS
    consolidation:apply persistence.
  - Pre-check token saver: skips model invocation if memories under threshold.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import structlog

from atlas.models.tokens import estimate_tokens
from atlas.time_context import (
    now_local,
    resolve_source_event_test_clock,
    test_clock_context,
    timezone_name,
)

log = structlog.get_logger()

# ----------------------------------------------------------------------
# Thresholds and configuration defaults (from thresholds.ts & S4 task book)
# ----------------------------------------------------------------------

DEFAULT_RECORD_COUNT_THRESHOLD = 5
DEFAULT_TOKEN_THRESHOLD = 2000
MAX_PROFILE_TOKENS = 600
MAX_RETRIES = 5
INITIAL_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0

ALLOWED_CONSOLIDATION_OPS = frozenset({
    "MERGE",
    "SUPERSEDE",
    "ROLLUP_DAY",
    "ROLLUP_WEEK",
    "PROFILE_UPDATE",
    "IMPORTANCE",
})

FORBIDDEN_CONSOLIDATION_OPS = frozenset({
    "DELETE",
    "REMOVE",
    "DROP",
    "ERASE",
    "HARD_ERASE",
})

# ----------------------------------------------------------------------
# Hierarchical compression guidance (from Mastra COMPRESSION_GUIDANCE)
# ----------------------------------------------------------------------

COMPRESSION_GUIDANCE: dict[int, str] = {
    0: "",
    1: (
        "\n## COMPRESSION REQUIRED (LEVEL 1: GENTLE)\n"
        "Your previous reflection was too long or uncompressed.\n"
        "Please re-process with slightly more compression:\n"
        "- Condense older observations into higher-level reflections\n"
        "- Retain more fine details for recent context\n"
        "- Combine related items more aggressively, preserving names, places, dates, and people\n"
        "- Keep the user profile concise (must be <= 600 tokens)\n"
        "- Aim for 8/10 detail level.\n"
    ),
    2: (
        "\n## AGGRESSIVE COMPRESSION REQUIRED (LEVEL 2)\n"
        "Your previous reflection was still too large.\n"
        "Please re-process with much more aggressive compression:\n"
        "- Heavily condense older items into high-level summaries\n"
        "- Remove redundant observations and merge overlapping items\n"
        "- Keep user profile strictly <= 600 tokens and grounded\n"
        "- Aim for 6/10 detail level.\n"
    ),
    3: (
        "\n## CRITICAL COMPRESSION REQUIRED (LEVEL 3)\n"
        "Failed to compress sufficiently after multiple attempts.\n"
        "Please re-process with maximum compression:\n"
        "- Summarize oldest observations into brief high-level summaries\n"
        "- Ruthlessly merge related observations on the same topic\n"
        "- Drop trivial procedural details; preserve names, dates, key facts, decisions\n"
        "- Aim for 4/10 detail level.\n"
    ),
    4: (
        "\n## EXTREME COMPRESSION REQUIRED (LEVEL 4)\n"
        "Multiple compression attempts have failed.\n"
        "- Drastically reduce the number of operations\n"
        "- Merge all same-day items into a single daily rollup\n"
        "- Combine all related facts into high-level core facts\n"
        "- Preserve only user preferences, key decisions, and critical unresolved items\n"
        "- Aim for 2/10 detail level.\n"
    ),
}

MAX_COMPRESSION_LEVEL = 4


def get_max_threshold(threshold: int | dict[str, int]) -> int:
    """Get the maximum value from a threshold (from Mastra thresholds.ts)."""
    if isinstance(threshold, (int, float)):
        return int(threshold)
    if isinstance(threshold, dict) and "max" in threshold:
        return int(threshold["max"])
    return DEFAULT_TOKEN_THRESHOLD


def calculate_dynamic_threshold(
    threshold: int | dict[str, int], current_tokens: int
) -> int:
    """Calculate dynamic threshold based on space (from Mastra thresholds.ts)."""
    if isinstance(threshold, (int, float)):
        return int(threshold)
    if isinstance(threshold, dict) and "max" in threshold and "min" in threshold:
        total_budget = int(threshold["max"])
        base_threshold = int(threshold["min"])
        return max(base_threshold, total_budget - current_tokens)
    return DEFAULT_TOKEN_THRESHOLD


# ----------------------------------------------------------------------
# Prompts
# ----------------------------------------------------------------------

_BASE_SYSTEM_INSTRUCTIONS = """You are the memory reflection consciousness of an AI assistant (Reflector).
Your reason for existing is to reflect on candidate memories, re-organize and streamline them, eliminate redundancies, establish supersede links, generate daily/weekly rollups, update the condensed user profile, and calibrate importance.

CRITICAL PRINCIPLES:
1. USER ASSERTIONS TAKE PRECEDENCE: When the user states facts about themselves, that is authoritative.
2. NEVER DELETE: You cannot delete or erase memories. To resolve duplicates or outdated facts, use MERGE or SUPERSEDE.
3. GROUNDED TRACEABILITY: Never invent facts. Every rollup, merge, and profile sentence MUST be strictly traceable to the candidate record refs.
4. PROFILE TOKEN LIMIT: The user profile in PROFILE_UPDATE MUST NOT exceed 600 tokens.
5. STRICT OPERATION LIST: Output ONLY a JSON object with an "operations" list.

LANGUAGE CONSISTENCY (HARD RULE): Keep every natural-language output field (`text`, `into_text`, `reason`, and textual `value`) in the dominant language of the cited source records. Chinese source records must produce Chinese text; do not translate them into English. If a `key` is present, keep it as a concise English dot-separated slug. Preserve facts and structure; this rule changes language only.

VALID OPERATIONS:
1. MERGE: Combine multiple records describing the exact same event or continuing fact.
   {"op": "MERGE", "refs": ["record_ref_1", "record_ref_2"], "into_text": "Consolidated concise text", "keep_ref": "record_ref_1"}
   - refs must contain at least 2 distinct existing record refs.
   - keep_ref is the primary record to keep (must be in refs).

2. SUPERSEDE: Explicit replacement when a new memory invalidates or updates an old memory (e.g. location moved, setting updated).
   {"op": "SUPERSEDE", "old_ref": "old_record_ref", "new_ref": "new_record_ref", "reason": "User moved from city A to city B"}
   - old_ref and new_ref must be distinct existing record refs.

3. ROLLUP_DAY: Daily summary of significant events and facts for a specific day.
   {"op": "ROLLUP_DAY", "date": "YYYY-MM-DD", "refs": ["record_ref_1", ...], "text": "Summary of events on this day"}
   - date must be in YYYY-MM-DD format. Only generate for dates that have relevant records.

4. ROLLUP_WEEK: Weekly summary aggregating milestones and important facts across a week.
   {"op": "ROLLUP_WEEK", "date": "YYYY-MM-DD", "refs": ["record_ref_1", ...], "text": "Summary of week milestones"}

5. PROFILE_UPDATE: Condensed understanding of the user ("我对用户的了解", facet=SUMMARY, scope=PROFILE).
   {"op": "PROFILE_UPDATE", "refs": ["record_ref_1", ...], "text": "Condensed profile statement(s)..."}
   - Must be <= 600 tokens.
   - Every sentence MUST be traceable to the supporting refs.

6. IMPORTANCE: Adjust importance level when a memory represents a core enduring preference or trivial detail.
   {"op": "IMPORTANCE", "ref": "record_ref", "level": "HIGH" | "MEDIUM" | "LOW"}

FORBIDDEN:
- Do NOT output DELETE, REMOVE, DROP, ERASE, or HARD_ERASE.
- Do NOT invent facts or cite refs not present in the input candidates.
- If no consolidation is needed, return {"operations": []}.

CHINESE EXAMPLES (additions; retain the operation rules above):
- MERGE: [r1] 用户周六上午看牙医；[r2] 用户本周六上午会看牙医 → `into_text`: "用户本周六上午看牙医"。
- SUPERSEDE: [r1] 用户常住杭州；[r2] 用户已搬到深圳 → `reason`: "用户从杭州搬到深圳，深圳取代杭州成为现居地"。
- ROLLUP_DAY: 2026-06-15 的记录显示用户完成了 Atlas 发布准备 → `text`: "用户完成 Atlas 发布准备"。
- ROLLUP_WEEK: 本周记录显示用户完成发布准备并安排了下周复核 → `text`: "用户完成发布准备，并安排下周复核"。
- PROFILE_UPDATE: 依据 [r1] 用户常住深圳和 [r2] 用户偏好安静工作环境，输出对应的中文画像句子。
- IMPORTANCE: 将核心偏好设为 `"level": "HIGH"`；枚举值保持协议原样，不翻译。
- USER ASSERTIONS vs QUESTIONS: 将“用户陈述常住深圳”保留为权威事实；“我住哪里？”仍是提问，不会覆盖该事实。
- DATES AND COMPLETIONS: 合并时保留原记录中的日期与 ✅ 完成标记，并用中文写出可追溯的结果。
"""


def build_reflector_system_prompt(
    custom_instructions: str | None = None,
    *,
    current_timezone: str | None = None,
    current_local_time: str | None = None,
) -> str:
    """Build the Reflector's system prompt (adapted from Mastra buildReflectorSystemPrompt)."""
    prompt = _BASE_SYSTEM_INSTRUCTIONS
    if current_timezone and current_local_time:
        prompt += (
            "\n\nUSER LOCAL CLOCK CONTEXT (AUTHORITATIVE FOR ROLLUP DATES):\n"
            f"Timezone: {current_timezone}\n"
            f"Current local date and time: {current_local_time}\n"
            "Use this timezone's local calendar day and week when producing ROLLUP_DAY "
            "and ROLLUP_WEEK dates. The date in each rollup operation is a local date "
            "in this timezone."
        )
    if custom_instructions:
        prompt += f"\n\n=== CUSTOM INSTRUCTIONS ===\n\n{custom_instructions}"
    return prompt


def extract_record_text(record: dict[str, Any]) -> str:
    """Extract legible summary/text from a unified record dict."""
    content = record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "summary", "narrative", "title", "value", "topic"):
            val = content.get(key)
            if val and isinstance(val, str):
                return val
        return json.dumps(content, ensure_ascii=False)
    return str(record.get("text") or record.get("summary") or "")


def build_reflector_user_prompt(
    records: list[dict[str, Any]],
    *,
    current_profile: str | None = None,
    existing_rollups: list[str] | None = None,
    compression_level: int = 0,
) -> str:
    """Build the user prompt containing candidate records to reflect on."""
    lines: list[str] = ["## CANDIDATE MEMORIES TO REFLECT ON:\n"]
    for rec in records:
        ref = rec.get("record_ref") or rec.get("id") or "unknown"
        facet = rec.get("facet") or "FACT"
        recorded_at = rec.get("recorded_at") or rec.get("created_at") or "unknown"
        valid_time = rec.get("valid_time")
        when = ""
        if isinstance(valid_time, dict) and valid_time.get("valid_from"):
            when = f" (valid_from: {valid_time['valid_from']})"
        text = extract_record_text(rec)
        lines.append(f"- [{ref}] ({facet}, {recorded_at}{when}): {text}")

    if current_profile:
        lines.append("\n## CURRENT USER PROFILE (for reference / refinement):\n")
        lines.append(current_profile.strip())

    if existing_rollups:
        lines.append("\n## EXISTING ROLLUPS (do not duplicate):\n")
        for rollup in existing_rollups:
            lines.append(f"- {rollup}")

    level = max(0, min(MAX_COMPRESSION_LEVEL, compression_level))
    guidance = COMPRESSION_GUIDANCE.get(level, "")
    if guidance:
        lines.append(guidance)

    lines.append(
        "\nPlease analyze these memories and output a valid JSON object with 'operations'."
    )
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Parser and Validators (adapted from Mastra parseReflectorOutput & validateCompression)
# ----------------------------------------------------------------------


def parse_reflector_output(output_text: str) -> list[dict[str, Any]]:
    """Parse JSON operations from model output (handling code fences or bare JSON)."""
    text = (output_text or "").strip()
    if not text:
        return []

    # Strip markdown code fence
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidate_str = fence_match.group(1).strip() if fence_match else text

    # Try direct parse
    try:
        parsed = json.loads(candidate_str)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            ops = parsed.get("operations")
            if isinstance(ops, list):
                return [item for item in ops if isinstance(item, dict)]
            if "op" in parsed or "action" in parsed:
                return [parsed]
    except Exception as exc:
        log.debug("reflector.parse_reflector_output_failed", error=str(exc), exc_info=True)

    # Fallback regex search for JSON object or array
    json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict):
                ops = parsed.get("operations")
                if isinstance(ops, list):
                    return [item for item in ops if isinstance(item, dict)]
        except Exception as exc:
            log.debug("reflector.parse_reflector_output_failed", error=str(exc), exc_info=True)

    log.warning("memory_reflector.parse_failed", raw_output=text[:200])
    return []


def validate_compression(
    profile_text: str,
    max_tokens: int = MAX_PROFILE_TOKENS,
    token_counter: Callable[[str], int] | None = None,
) -> bool:
    """Validate that the reflected profile stays under the token ceiling."""
    if not profile_text:
        return True
    counter = token_counter or estimate_tokens
    count = counter(profile_text)
    return count <= max_tokens


def _extract_ngrams_and_terms(text: str) -> set[str]:
    text_lower = text.lower()
    terms = set(re.findall(r"[a-zA-Z0-9_]{2,}", text_lower))
    cjk_blocks = re.findall(r"[\u4e00-\u9fff]+", text_lower)
    for block in cjk_blocks:
        if len(block) == 1:
            terms.add(block)
        for i in range(len(block) - 1):
            terms.add(block[i : i + 2])
    return terms


def validate_traceability(
    profile_text: str,
    records_by_ref: dict[str, dict[str, Any]],
    refs: list[str],
) -> tuple[bool, str | None]:
    """Verify that every sentence in profile_text is grounded in referenced records."""
    if not profile_text.strip():
        return True, None
    if not refs:
        return False, "REFS_EMPTY: profile update must cite supporting refs"

    evidence_parts: list[str] = []
    for ref in refs:
        rec = records_by_ref.get(ref)
        if rec is not None:
            evidence_parts.append(extract_record_text(rec))
    evidence_text = " ".join(evidence_parts)
    evidence_terms = _extract_ngrams_and_terms(evidence_text)

    # Split into sentences
    sentences = [
        s.strip()
        for s in re.split(r"[。\n.!?！？；;]+", profile_text)
        if s.strip()
    ]
    if not sentences:
        return True, None

    for sentence in sentences:
        s_terms = _extract_ngrams_and_terms(sentence)
        if not s_terms:
            continue
        overlap = s_terms.intersection(evidence_terms)
        ratio = len(overlap) / len(s_terms)
        # Require at least 30% term overlap with cited evidence
        if ratio < 0.30:
            return (
                False,
                f"UNGROUNDED_SENTENCE: sentence {sentence!r} has insufficient overlap ({ratio:.2f}) with refs {refs}",
            )

    return True, None


def validate_operations_local(
    operations: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
    *,
    token_counter: Callable[[str], int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Statically validate proposed operations before dispatching to MemoryOS.

    Returns:
        (accepted_operations, rejected_operations)
    """
    records_by_ref: dict[str, dict[str, Any]] = {}
    canonical_refs: dict[str, str] = {}
    for rec in candidate_records:
        ref = str(rec.get("record_ref") or rec.get("id") or "").strip()
        if ref:
            records_by_ref[ref] = rec
            canonical_refs[ref] = ref
            if ":" in ref:
                _, ident = ref.split(":", 1)
                if ident and ident not in records_by_ref:
                    records_by_ref[ident] = rec
                    canonical_refs[ident] = ref

    def _to_canon(r: Any) -> str:
        s = str(r or "").strip()
        return canonical_refs.get(s, s)

    valid_ops: list[dict[str, Any]] = []
    rejected_ops: list[dict[str, Any]] = []

    for idx, raw_op in enumerate(operations):
        if not isinstance(raw_op, dict):
            rejected_ops.append({
                "index": idx,
                "op": "UNKNOWN",
                "status": "REJECTED",
                "reason": "INVALID_FORMAT: operation must be a dictionary",
            })
            continue

        op_type = str(raw_op.get("op") or raw_op.get("action") or "").strip().upper()

        if op_type in FORBIDDEN_CONSOLIDATION_OPS:
            rejected_ops.append({
                "index": idx,
                "op": op_type,
                "status": "REJECTED",
                "reason": f"FORBIDDEN_OP: {op_type} is strictly forbidden in Reflector",
            })
            continue

        if op_type not in ALLOWED_CONSOLIDATION_OPS:
            rejected_ops.append({
                "index": idx,
                "op": op_type,
                "status": "REJECTED",
                "reason": f"UNSUPPORTED_OP: operation type {op_type} is not supported",
            })
            continue

        # Op-specific validations
        if op_type == "MERGE":
            refs = raw_op.get("refs") or raw_op.get("record_refs")
            into_text = str(raw_op.get("into_text") or raw_op.get("text") or "").strip()
            keep_ref = raw_op.get("keep_ref")

            if not isinstance(refs, list) or len(refs) < 2:
                rejected_ops.append({
                    "index": idx,
                    "op": "MERGE",
                    "status": "REJECTED",
                    "reason": "INVALID_REFS: MERGE requires at least 2 record refs",
                })
                continue
            if not into_text:
                rejected_ops.append({
                    "index": idx,
                    "op": "MERGE",
                    "status": "REJECTED",
                    "reason": "EMPTY_TEXT: MERGE into_text cannot be empty",
                })
                continue
            missing_ref = next((r for r in refs if str(r) not in records_by_ref), None)
            if missing_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": "MERGE",
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: ref {missing_ref} not in candidate records",
                })
                continue

            canon_refs = [_to_canon(r) for r in refs]
            canon_keep = _to_canon(keep_ref) if keep_ref else canon_refs[0]
            if canon_keep not in canon_refs:
                rejected_ops.append({
                    "index": idx,
                    "op": "MERGE",
                    "status": "REJECTED",
                    "reason": f"INVALID_KEEP_REF: keep_ref {keep_ref} not in refs",
                })
                continue

            valid_ops.append({
                "op": "MERGE",
                "refs": canon_refs,
                "into_text": into_text,
                "keep_ref": canon_keep,
            })

        elif op_type == "SUPERSEDE":
            old_ref_raw = str(raw_op.get("old_ref") or "").strip()
            new_ref_raw = str(raw_op.get("new_ref") or "").strip()
            reason = str(raw_op.get("reason") or "").strip()

            if not old_ref_raw or not new_ref_raw:
                rejected_ops.append({
                    "index": idx,
                    "op": "SUPERSEDE",
                    "status": "REJECTED",
                    "reason": "REF_REQUIRED: old_ref and new_ref are required",
                })
                continue
            if old_ref_raw not in records_by_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": "SUPERSEDE",
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: old_ref {old_ref_raw} not in candidate records",
                })
                continue
            if new_ref_raw not in records_by_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": "SUPERSEDE",
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: new_ref {new_ref_raw} not in candidate records",
                })
                continue

            old_canon = _to_canon(old_ref_raw)
            new_canon = _to_canon(new_ref_raw)
            if old_canon == new_canon:
                rejected_ops.append({
                    "index": idx,
                    "op": "SUPERSEDE",
                    "status": "REJECTED",
                    "reason": "SELF_SUPERSEDE: old_ref and new_ref cannot be the same",
                })
                continue

            valid_ops.append({
                "op": "SUPERSEDE",
                "old_ref": old_canon,
                "new_ref": new_canon,
                "reason": reason or "SUPERSEDED_BY_REFLECTOR",
            })

        elif op_type in ("ROLLUP_DAY", "ROLLUP_WEEK"):
            date_str = str(raw_op.get("date") or "").strip()
            text = str(raw_op.get("text") or "").strip()
            refs = raw_op.get("refs") or []

            if not date_str:
                rejected_ops.append({
                    "index": idx,
                    "op": op_type,
                    "status": "REJECTED",
                    "reason": f"DATE_REQUIRED: {op_type} requires a valid date",
                })
                continue
            if op_type == "ROLLUP_DAY" and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                rejected_ops.append({
                    "index": idx,
                    "op": op_type,
                    "status": "REJECTED",
                    "reason": f"INVALID_DATE: date {date_str} must be YYYY-MM-DD",
                })
                continue
            if not text:
                rejected_ops.append({
                    "index": idx,
                    "op": op_type,
                    "status": "REJECTED",
                    "reason": f"EMPTY_TEXT: {op_type} text cannot be empty",
                })
                continue
            if not isinstance(refs, list) or not refs:
                rejected_ops.append({
                    "index": idx,
                    "op": op_type,
                    "status": "REJECTED",
                    "reason": f"REFS_REQUIRED: {op_type} requires at least one supporting ref",
                })
                continue
            missing_ref = next((r for r in refs if str(r) not in records_by_ref), None)
            if missing_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": op_type,
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: ref {missing_ref} not in candidate records",
                })
                continue

            valid_ops.append({
                "op": op_type,
                "date": date_str,
                "refs": [_to_canon(r) for r in refs],
                "text": text,
            })

        elif op_type == "PROFILE_UPDATE":
            text = str(raw_op.get("text") or "").strip()
            refs = raw_op.get("refs") or []

            if not text:
                rejected_ops.append({
                    "index": idx,
                    "op": "PROFILE_UPDATE",
                    "status": "REJECTED",
                    "reason": "EMPTY_TEXT: PROFILE_UPDATE text cannot be empty",
                })
                continue
            if not isinstance(refs, list) or not refs:
                rejected_ops.append({
                    "index": idx,
                    "op": "PROFILE_UPDATE",
                    "status": "REJECTED",
                    "reason": "REFS_REQUIRED: PROFILE_UPDATE requires at least one supporting ref",
                })
                continue
            missing_ref = next((r for r in refs if str(r) not in records_by_ref), None)
            if missing_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": "PROFILE_UPDATE",
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: ref {missing_ref} not in candidate records",
                })
                continue

            if not validate_compression(text, max_tokens=MAX_PROFILE_TOKENS, token_counter=token_counter):
                rejected_ops.append({
                    "index": idx,
                    "op": "PROFILE_UPDATE",
                    "status": "REJECTED",
                    "reason": f"TOKEN_LIMIT_EXCEEDED: profile update exceeds {MAX_PROFILE_TOKENS} tokens",
                })
                continue

            canon_refs = [_to_canon(r) for r in refs]
            ok, trace_err = validate_traceability(text, records_by_ref, [str(r) for r in refs])
            if not ok:
                rejected_ops.append({
                    "index": idx,
                    "op": "PROFILE_UPDATE",
                    "status": "REJECTED",
                    "reason": trace_err or "UNTRACEABLE_PROFILE_STATEMENT",
                })
                continue

            valid_ops.append({
                "op": "PROFILE_UPDATE",
                "refs": canon_refs,
                "text": text,
            })

        elif op_type == "IMPORTANCE":
            ref_raw = str(raw_op.get("ref") or raw_op.get("record_ref") or "").strip()
            level = str(raw_op.get("level") or "").strip().upper()

            if not ref_raw:
                rejected_ops.append({
                    "index": idx,
                    "op": "IMPORTANCE",
                    "status": "REJECTED",
                    "reason": "REF_REQUIRED: IMPORTANCE requires a record ref",
                })
                continue
            if ref_raw not in records_by_ref:
                rejected_ops.append({
                    "index": idx,
                    "op": "IMPORTANCE",
                    "status": "REJECTED",
                    "reason": f"UNKNOWN_REF: ref {ref_raw} not in candidate records",
                })
                continue
            if level not in {"HIGH", "MEDIUM", "LOW", "1", "2", "3", "4", "5"}:
                rejected_ops.append({
                    "index": idx,
                    "op": "IMPORTANCE",
                    "status": "REJECTED",
                    "reason": f"INVALID_LEVEL: unknown importance level {level}",
                })
                continue

            valid_ops.append({
                "op": "IMPORTANCE",
                "ref": _to_canon(ref_raw),
                "level": level,
            })

    return valid_ops, rejected_ops


def should_reflect(
    records: list[dict[str, Any]],
    *,
    count_threshold: int = DEFAULT_RECORD_COUNT_THRESHOLD,
    token_threshold: int | dict[str, int] = DEFAULT_TOKEN_THRESHOLD,
    token_counter: Callable[[str], int] | None = None,
) -> bool:
    """Check if unorganized new memories meet the threshold to trigger reflection."""
    if not records:
        return False
    if len(records) >= count_threshold:
        return True
    counter = token_counter or estimate_tokens
    total_tokens = sum(counter(extract_record_text(r)) for r in records)
    eff_threshold = (
        calculate_dynamic_threshold(token_threshold, total_tokens)
        if isinstance(token_threshold, dict)
        else get_max_threshold(token_threshold)
    )
    return total_tokens >= eff_threshold


# ----------------------------------------------------------------------
# Result Data Structures
# ----------------------------------------------------------------------


@dataclass
class ReflectionResult:
    subject: str
    reflected: bool
    skip_reason: str | None = None
    proposed_operations: list[dict[str, Any]] = field(default_factory=list)
    locally_accepted: list[dict[str, Any]] = field(default_factory=list)
    locally_rejected: list[dict[str, Any]] = field(default_factory=list)
    remote_results: dict[str, Any] | None = None
    applied_count: int = 0
    rejected_count: int = 0
    token_usage: dict[str, Any] = field(default_factory=dict)
    model_id: str | None = None
    receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
# MemoryReflector Agent
# ----------------------------------------------------------------------


class MemoryReflector:
    """Model-backed memory reflection, streamlining, and consolidation."""

    def __init__(
        self,
        model_manager: Any,
        config: Any = None,
        *,
        client: Any = None,
        token_counter: Callable[[str], int] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._model_manager = model_manager
        self._config = config
        self._client = client
        self._token_counter = token_counter or (lambda text: estimate_tokens(text))
        self._now = lambda: now_local(
            self._config, now=now() if now is not None else None,
        )

    def _select_model_id(self) -> str:
        """Resolve memory model via ModelManager following the standard fallback chain."""
        if self._model_manager is None:
            raise RuntimeError("ModelManager is unavailable for memory reflection")
        from atlas.config import load_user_settings

        try:
            settings = load_user_settings() or {}
        except Exception as exc:
            log.debug("reflector._select_model_id_failed", error=str(exc), exc_info=True)
            settings = {}

        models = self._model_manager.list_models()
        for candidate in (
            settings.get("memory_model"),
            settings.get("compression_model"),
            getattr(self._model_manager, "current_model", None),
        ):
            chosen = str(candidate or "").strip()
            if not chosen:
                continue
            match = next((
                model for model in models
                if chosen in {str(model.get("id") or ""), str(model.get("litellm_model") or "")}
            ), None)
            if match is not None:
                return str(match.get("id") or match.get("litellm_model"))
            if candidate == getattr(self._model_manager, "current_model", None):
                return chosen
        raise RuntimeError("no configured memory/compression/current model is available")

    async def _complete_with_retry(
        self,
        model_id: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4000,
    ) -> Any:
        router = getattr(self._model_manager, "model_router", None)
        if router is None:
            raise RuntimeError("ModelRouter is unavailable for memory reflection")

        delay = INITIAL_RETRY_DELAY_SECONDS
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await router.complete_for(
                    model_id,
                    "memory_reflect",
                    messages,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
            except Exception as exc:
                if attempt >= MAX_RETRIES or not self._retryable(exc):
                    log.error(
                        "memory_reflector.model_call_failed",
                        model_id=model_id,
                        purpose="memory_reflect",
                        attempt=attempt + 1,
                        error_type=type(exc).__name__,
                    )
                    raise
                wait = min(MAX_RETRY_DELAY_SECONDS, delay) * random.uniform(0.8, 1.2)
                log.warning(
                    "memory_reflector.model_call_retry",
                    model_id=model_id,
                    attempt=attempt + 1,
                    wait_seconds=round(wait, 3),
                )
                await asyncio.sleep(wait)
                delay = min(MAX_RETRY_DELAY_SECONDS, delay * 2)
        raise AssertionError("unreachable retry loop")

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        status = status or getattr(response, "status_code", None)
        if status is not None:
            try:
                code = int(status)
                return code in {408, 425, 429} or code >= 500
            except (TypeError, ValueError):
                return False
        try:
            import httpx
            if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
                return True
        except ImportError:
            pass
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    @staticmethod
    def _reported_usage(usage: Any) -> tuple[int | None, int | None]:
        def read(*keys: str) -> int | None:
            if usage is None:
                return None
            for key in keys:
                value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
                if isinstance(value, (int, float)) and value >= 0:
                    return int(value)
            return None

        return read("input_tokens", "prompt_tokens"), read("output_tokens", "completion_tokens")

    async def propose_operations(
        self,
        records: list[dict[str, Any]],
        *,
        current_profile: str | None = None,
        existing_rollups: list[str] | None = None,
        compression_level: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
        """Invoke ModelRouter to propose consolidation operations and validate locally."""
        model_id = self._select_model_id()
        local_now = self._now()
        system_prompt = build_reflector_system_prompt(
            current_timezone=timezone_name(self._config),
            current_local_time=local_now.isoformat(),
        )

        curr_level = compression_level
        last_accepted: list[dict[str, Any]] = []
        last_rejected: list[dict[str, Any]] = []
        token_usage: dict[str, Any] = {}

        while curr_level <= MAX_COMPRESSION_LEVEL:
            user_prompt = build_reflector_user_prompt(
                records,
                current_profile=current_profile,
                existing_rollups=existing_rollups,
                compression_level=curr_level,
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            completion = await self._complete_with_retry(model_id, messages)
            text = completion.text if hasattr(completion, "text") else str(completion)
            usage = getattr(completion, "usage", None)
            inp_tok, out_tok = self._reported_usage(usage)
            token_usage = {
                "prompt_tokens": inp_tok,
                "completion_tokens": out_tok,
            }

            raw_ops = parse_reflector_output(text)
            accepted, rejected = validate_operations_local(
                raw_ops, records, token_counter=self._token_counter
            )

            # Check if rejection was due to compression
            compression_failure = any(
                "TOKEN_LIMIT_EXCEEDED" in r.get("reason", "") for r in rejected
            )
            if compression_failure and curr_level < MAX_COMPRESSION_LEVEL:
                log.info("memory_reflector.compression_retry", level=curr_level + 1)
                curr_level += 1
                continue

            last_accepted = accepted
            last_rejected = rejected
            break

        return last_accepted, last_rejected, token_usage, model_id

    async def apply_operations(
        self,
        subject: str,
        operations: list[dict[str, Any]],
        *,
        client: Any = None,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit accepted operations to MemoryOS consolidation:apply."""
        if not operations:
            return {"total": 0, "accepted_count": 0, "rejected_count": 0, "results": []}

        target_client = client or self._client
        if target_client is None:
            raise RuntimeError("UnifiedMemoryClient is required to apply consolidation operations")

        payload = {
            "context": ctx or {"memory_subject_id": subject, "owner_id": "owner-local"},
            "operations": operations,
            "cue_context": {"current_timezone": timezone_name(self._config)},
        }

        # Handle UnifiedMemoryClient call method
        if hasattr(target_client, "call"):
            res = target_client.call("POST", "/v1/unified/consolidation:apply", json=payload)
            if inspect.isawaitable(res):
                res = await res
            return res if isinstance(res, dict) else {}

        # Handle direct sqlite or synchronous mock client
        if hasattr(target_client, "apply_consolidation"):
            res = target_client.apply_consolidation(subject, operations, ctx=payload["context"])
            if inspect.isawaitable(res):
                res = await res
            return res if isinstance(res, dict) else {}

        raise TypeError(f"Unsupported client type for consolidation apply: {type(target_client)}")

    def _build_and_persist_receipt(
        self, result: ReflectionResult, total_candidates: int
    ) -> dict[str, Any]:
        """Construct receipt dictionary, log it, and optionally persist to disk."""
        receipt_id = f"reflect-{uuid.uuid4().hex[:12]}"
        receipt = {
            "receipt_id": receipt_id,
            "timestamp": self._now().isoformat(),
            "subject": result.subject,
            "reflected": result.reflected,
            "skip_reason": result.skip_reason,
            "total_candidates": total_candidates,
            "model_id": result.model_id,
            "proposed_count": len(result.proposed_operations),
            "applied_count": result.applied_count,
            "rejected_count": result.rejected_count,
            "token_usage": result.token_usage,
            "proposed_operations": result.proposed_operations,
            "remote_results": result.remote_results,
        }

        log.info(
            "memory_reflector.receipt",
            receipt_id=receipt_id,
            subject=result.subject,
            reflected=result.reflected,
            skip_reason=result.skip_reason,
            total_candidates=total_candidates,
            applied_count=result.applied_count,
            rejected_count=result.rejected_count,
        )

        data_dir_env = os.environ.get("ATLAS_DATA_DIR")
        if data_dir_env:
            try:
                receipts_dir = Path(data_dir_env) / "reflection_receipts"
                receipts_dir.mkdir(parents=True, exist_ok=True)
                receipt_file = receipts_dir / f"{receipt_id}.json"
                receipt_file.write_text(
                    json.dumps(receipt, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                log.warning("memory_reflector.receipt_persist_failed", error=str(exc), exc_info=True)

        return receipt

    async def fetch_candidate_records(
        self,
        subject: str = "subject-default",
        *,
        status: str = "ACTIVE",
        facet: str | None = None,
        limit: int = 100,
        client: Any = None,
    ) -> list[dict[str, Any]]:
        """Fetch candidate records from MemoryOS via client/facade."""
        target_client = client or self._client
        if target_client is None:
            return []

        res: Any = None
        if hasattr(target_client, "list_records"):
            try:
                res = target_client.list_records(status=status, facet=facet, limit=limit)
            except TypeError:
                res = target_client.list_records(limit=limit)
            if inspect.isawaitable(res):
                res = await res
        elif hasattr(target_client, "call"):
            params: dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            if facet:
                params["facet"] = facet
            if subject:
                params["memory_subject_id"] = subject
            res = target_client.call("GET", "/v1/unified/records", params=params)
            if inspect.isawaitable(res):
                res = await res

        if isinstance(res, dict):
            items = list(res.get("items") or [])
        elif isinstance(res, list):
            items = list(res)
        else:
            items = []

        if subject:
            items = [
                r for r in items
                if not isinstance(r, dict) or r.get("memory_subject_id") in (None, subject)
            ]
        # Filter for durable memory records (memory:*) when present, as consolidation
        # operates on durable memories rather than transient episode raw event entries.
        memory_items = [r for r in items if str(r.get("record_ref", "")).startswith("memory:")]
        if memory_items:
            return memory_items
        return items

    async def run_reflection_cycle(
        self,
        subject: str = "subject-default",
        *,
        force: bool = False,
        auto_apply: bool = True,
        count_threshold: int = DEFAULT_RECORD_COUNT_THRESHOLD,
        token_threshold: int | dict[str, int] = DEFAULT_TOKEN_THRESHOLD,
        current_profile: str | None = None,
        existing_rollups: list[str] | None = None,
        client: Any = None,
        ctx: dict[str, Any] | None = None,
    ) -> ReflectionResult:
        """Run an end-to-end reflection cycle: GET records -> Model proposes -> POST apply -> log/receipt."""
        records = await self.fetch_candidate_records(subject, client=client)
        result = await self.reflect(
            subject,
            records,
            current_profile=current_profile,
            existing_rollups=existing_rollups,
            auto_apply=auto_apply,
            client=client,
            ctx=ctx,
            force=force,
            count_threshold=count_threshold,
            token_threshold=token_threshold,
        )
        return result

    async def trigger_if_threshold_met(
        self,
        subject: str = "subject-default",
        *,
        auto_apply: bool = True,
        count_threshold: int = DEFAULT_RECORD_COUNT_THRESHOLD,
        token_threshold: int | dict[str, int] = DEFAULT_TOKEN_THRESHOLD,
        client: Any = None,
        ctx: dict[str, Any] | None = None,
    ) -> ReflectionResult | None:
        """Check unorganized records threshold and run reflection if met."""
        records = await self.fetch_candidate_records(subject, client=client)
        if not should_reflect(
            records,
            count_threshold=count_threshold,
            token_threshold=token_threshold,
            token_counter=self._token_counter,
        ):
            return None
        return await self.run_reflection_cycle(
            subject=subject,
            force=True,
            auto_apply=auto_apply,
            count_threshold=count_threshold,
            token_threshold=token_threshold,
            client=client,
            ctx=ctx,
        )

    async def reflect(
        self,
        subject: str,
        records: list[dict[str, Any]],
        *,
        current_profile: str | None = None,
        existing_rollups: list[str] | None = None,
        auto_apply: bool = False,
        client: Any = None,
        ctx: dict[str, Any] | None = None,
        force: bool = False,
        count_threshold: int = DEFAULT_RECORD_COUNT_THRESHOLD,
        token_threshold: int | dict[str, int] = DEFAULT_TOKEN_THRESHOLD,
    ) -> ReflectionResult:
        """Use source-event time for a fully proven TEST reflection batch."""
        event_groups: list[list[dict[str, Any]]] = []
        has_source_provenance = False
        complete_source_provenance = bool(records)
        for record in records:
            metadata = record.get("metadata") if isinstance(record, dict) else None
            if isinstance(metadata, dict) and "source_events" in metadata:
                has_source_provenance = True
            sources = metadata.get("source_events") if isinstance(metadata, dict) else None
            if not isinstance(sources, list) or not sources:
                complete_source_provenance = False
                continue
            event_groups.append(sources)

        source_events = [event for group in event_groups for event in group]
        source_clock = (
            resolve_source_event_test_clock(source_events, self._config)
            if has_source_provenance and complete_source_provenance
            and len(event_groups) == len(records)
            else None
        )
        # Background reflection must not inherit a request clock without its
        # own durable source proof. Missing, mixed, or invalid provenance masks
        # any parent scope and uses the actual wall clock.
        with test_clock_context(
            source_clock.isoformat() if source_clock is not None else None,
            config=self._config,
            event_class="TEST" if source_clock is not None else "PRODUCTION",
        ):
            return await self._reflect_with_records(
                subject,
                records,
                current_profile=current_profile,
                existing_rollups=existing_rollups,
                auto_apply=auto_apply,
                client=client,
                ctx=ctx,
                force=force,
                count_threshold=count_threshold,
                token_threshold=token_threshold,
            )

    async def _reflect_with_records(
        self,
        subject: str,
        records: list[dict[str, Any]],
        *,
        current_profile: str | None = None,
        existing_rollups: list[str] | None = None,
        auto_apply: bool = False,
        client: Any = None,
        ctx: dict[str, Any] | None = None,
        force: bool = False,
        count_threshold: int = DEFAULT_RECORD_COUNT_THRESHOLD,
        token_threshold: int | dict[str, int] = DEFAULT_TOKEN_THRESHOLD,
    ) -> ReflectionResult:
        """Run reflection over candidate records, validating and optionally applying operations."""
        if not force and not should_reflect(
            records,
            count_threshold=count_threshold,
            token_threshold=token_threshold,
            token_counter=self._token_counter,
        ):
            res = ReflectionResult(
                subject=subject,
                reflected=False,
                skip_reason="BELOW_THRESHOLD",
                proposed_operations=[],
            )
            res.receipt = self._build_and_persist_receipt(res, len(records))
            return res

        accepted_ops, rejected_ops, token_usage, model_id = await self.propose_operations(
            records,
            current_profile=current_profile,
            existing_rollups=existing_rollups,
        )

        remote_results: dict[str, Any] | None = None
        applied_count = 0
        remote_rejected = 0

        if auto_apply and accepted_ops:
            remote_results = await self.apply_operations(
                subject, accepted_ops, client=client, ctx=ctx
            )
            applied_count = int(remote_results.get("accepted_count") or 0)
            remote_rejected = int(remote_results.get("rejected_count") or 0)

        res = ReflectionResult(
            subject=subject,
            reflected=True,
            proposed_operations=[*accepted_ops, *rejected_ops],
            locally_accepted=accepted_ops,
            locally_rejected=rejected_ops,
            remote_results=remote_results,
            applied_count=applied_count,
            rejected_count=len(rejected_ops) + remote_rejected,
            token_usage=token_usage,
            model_id=model_id,
        )
        res.receipt = self._build_and_persist_receipt(res, len(records))
        return res


# ----------------------------------------------------------------------
# Background Idle / Daily Trigger & Singletons
# ----------------------------------------------------------------------

_GLOBAL_REFLECTOR: MemoryReflector | None = None


def get_memory_reflector() -> MemoryReflector | None:
    return _GLOBAL_REFLECTOR


def set_memory_reflector(reflector: MemoryReflector | None) -> None:
    global _GLOBAL_REFLECTOR
    _GLOBAL_REFLECTOR = reflector


async def trigger_reflection_if_needed(
    subject: str = "subject-default",
    *,
    reflector: MemoryReflector | None = None,
    client: Any = None,
) -> ReflectionResult | None:
    """Helper to check threshold and trigger reflection if met."""
    target = reflector or _GLOBAL_REFLECTOR
    if target is None:
        return None
    return await target.trigger_if_threshold_met(subject=subject, client=client)


async def reflector_idle_loop(
    reflector: MemoryReflector,
    *,
    check_interval: float = 60.0,
    subject: str = "subject-default",
) -> None:
    """Server lifespan background task running periodic idle reflection checks."""
    log.info("memory_reflector.idle_loop_started", interval=check_interval)
    while True:
        try:
            await asyncio.sleep(check_interval)
            res = await reflector.trigger_if_threshold_met(subject=subject)
            if res and res.reflected:
                log.info(
                    "memory_reflector.idle_cycle_completed",
                    subject=subject,
                    applied_count=res.applied_count,
                )
        except asyncio.CancelledError:
            log.info("memory_reflector.idle_loop_cancelled")
            raise
        except Exception as exc:
            log.warning("memory_reflector.idle_cycle_error", error=str(exc), exc_info=True)
