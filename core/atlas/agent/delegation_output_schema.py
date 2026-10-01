# Ported from NousResearch/hermes-agent@330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3:
# tools/delegation_output_schema.py (MIT, (c) Nous Research).
# Changes: Atlas module path and Chinese validation/retry text.
"""JSON Schema validation helpers for delegated Agent output."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def coerce_output_schema(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Return a validated schema or a user-facing validation error."""
    if raw is None:
        return None, None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None, "output_schema 必须是 JSON Schema 对象，不能是无效 JSON 字符串。"
    if not isinstance(raw, dict):
        return None, f"output_schema 必须是 JSON Schema 对象，收到 {type(raw).__name__}。"
    try:
        from jsonschema.validators import validator_for

        validator_for(raw).check_schema(raw)
    except Exception as exc:
        return None, f"output_schema 不是有效的 JSON Schema：{exc}"
    return raw, None


def append_output_contract(context: str | None, schema: dict[str, Any]) -> str:
    """Append the required machine-readable response contract to the child task."""
    schema_text = json.dumps(schema, indent=2, ensure_ascii=False)
    block = (
        "结构化输出要求：最终回复只能包含符合以下 JSON Schema 的 JSON 值，"
        "不得添加前后说明或代码围栏。\n"
        f"{schema_text}"
    )
    base = (context or "").rstrip()
    return f"{base}\n\n{block}" if base else block


def extract_json_candidate(text: str) -> str:
    """Strip a code fence or surrounding prose around the outermost JSON value."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json\n"):
            raw = raw.split("\n", 1)[1]
    spans: list[tuple[int, str]] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start >= 0 and end > start:
            spans.append((start, raw[start : end + 1]))
    for _start, candidate in sorted(spans):
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            continue
    return spans[0][1] if spans else raw


def validate_output(text: str, schema: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return validity and up to ten JSON Schema diagnostics."""
    candidate = extract_json_candidate(text or "")
    if not candidate.strip():
        return False, ["回复为空，预期收到符合 Schema 的 JSON。"]
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError) as exc:
        return False, [f"回复不是有效 JSON：{exc}"]
    from jsonschema.validators import validator_for

    validator = validator_for(schema)(schema)
    errors = sorted(validator.iter_errors(parsed), key=lambda e: list(e.absolute_path))
    rendered = [
        "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}"
                      for part in error.absolute_path) + f": {error.message}"
        for error in errors[:10]
    ]
    return not rendered, rendered


def build_retry_message(errors: list[str]) -> str:
    """Build the one allowed correction turn without repeating the schema."""
    error_block = "\n".join(f"- {error}" for error in errors)
    return (
        "上一次最终回复未通过结构化输出校验。校验错误：\n"
        f"{error_block}\n\n"
        "请仅回复修正后的 JSON 值，并遵守任务上下文中的 OUTPUT CONTRACT。"
    )
