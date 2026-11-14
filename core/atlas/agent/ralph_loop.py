"""Model-facing foreground Ralph loop over the existing delegation seam.

Port of the DSH ``tool-ralph`` capability (experimental/tool-ralph) onto Atlas's
own primitives: every round spawns one *fresh* child through
:class:`atlas.agent.enrichment.DelegationService` (no parent conversation), the
child's final message must satisfy a fixed structured report schema (validated
by ``atlas.agent.delegation_output_schema``), and only a bounded handoff crosses
rounds. The shared workspace is the long-term memory; the loop itself carries
only the immutable objective and the previous report.

No new engine primitive is introduced here: the loop is plain tool logic over
the existing subagent spawn + structured-output seams, exactly like the DSH
upstream, which ships Ralph as a tool package and not an engine change.
"""

from __future__ import annotations

import json
from typing import Any

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["continue", "complete", "blocked"]},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "nextSteps": {"type": "array", "items": {"type": "string"}},
        "blocker": {"type": "string"},
    },
    "required": ["status", "summary", "evidence", "nextSteps", "blocker"],
    "additionalProperties": False,
}

#: DSH defaults: 256 rounds ceiling, 16 KiB handoff, 16 KiB parent-facing result.
DEFAULT_MAX_ROUNDS = 256
MAX_HANDOFF_CHARS = 16_384
MAX_RESULT_CHARS = 16_384

_TRUNCATION_NOTICE = "\n… [truncated]"

ROUND_PROMPT_TEMPLATE = (
    "You are one fresh worker in a foreground Ralph loop. You receive no parent "
    "conversation and no prior child session. Do not call the ralph tool: this "
    "round already is its worker.\n"
    "Immutable objective:\n{objective}\n"
    "Ralph round: {round} of {max_rounds}.\n"
    "The shared workspace and its current working tree are the long-term memory "
    "and source of truth. Inspect them before acting, preserve existing work, "
    "perform concrete in-scope work, and verify what you change. Treat the "
    "previous report only as a bounded handoff; confirm it against the workspace.\n"
    "Previous structured handoff:\n{prior}\n"
    "Return one report with exact normalized strings. Use status continue with at "
    "least one nextSteps entry while useful work remains; complete only with "
    "concrete evidence and no nextSteps; blocked only when no meaningful progress "
    "is possible without human input or an external-state change. blocker must be "
    "empty unless blocked."
)


def resolve_max_rounds(requested: int | None, ceiling: int = DEFAULT_MAX_ROUNDS) -> int:
    """Resolve one model-selected round cap against the deployment ceiling."""
    value = DEFAULT_MAX_ROUNDS if requested is None else requested
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("Ralph maxRounds must be a positive integer")
    if value > ceiling:
        raise ValueError(f"Ralph maxRounds {value} exceeds the deployment ceiling {ceiling}")
    return value


def _normalized_text(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0 and value == value.strip()


def _normalized_list(value: Any) -> bool:
    return isinstance(value, list) and all(_normalized_text(item) for item in value)


def validate_report(report: Any, max_handoff_chars: int = MAX_HANDOFF_CHARS) -> dict[str, Any]:
    """Defensively re-validate one round report across the delegation boundary.

    ``delegate_task`` already checked the JSON Schema; this enforces the
    status-specific rules DSH's fixed script checks and the handoff bound.
    """
    if not isinstance(report, dict) or set(report) != {
        "status", "summary", "evidence", "nextSteps", "blocker",
    }:
        raise ValueError("Ralph child returned a malformed round report")
    if not _normalized_text(report["summary"]):
        raise ValueError("Ralph round report summary must be non-empty and normalized")
    if not _normalized_list(report["evidence"]) or not _normalized_list(report["nextSteps"]):
        raise ValueError(
            "Ralph round report evidence and nextSteps must contain only non-empty normalized strings")
    if not isinstance(report["blocker"], str) or report["blocker"] != report["blocker"].strip():
        raise ValueError("Ralph round report blocker must be a normalized string")
    status = report["status"]
    if status == "continue" and (not report["nextSteps"] or report["blocker"] != ""):
        raise ValueError("a continuing Ralph report needs nextSteps and an empty blocker")
    if status == "complete" and (
        not report["evidence"] or report["nextSteps"] or report["blocker"] != ""
    ):
        raise ValueError("a complete Ralph report needs evidence, no nextSteps, and an empty blocker")
    if status == "blocked" and not _normalized_text(report["blocker"]):
        raise ValueError("a blocked Ralph report needs a concrete blocker")
    serialized = json.dumps(report, ensure_ascii=False)
    if len(serialized) > max_handoff_chars:
        raise ValueError(
            f"Ralph round report exceeds maxHandoffChars ({len(serialized)} > {max_handoff_chars})")
    return report


def bound_result(text: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Bound complete parent-facing text, including the truncation marker."""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(_TRUNCATION_NOTICE):
        return _TRUNCATION_NOTICE[:max_chars]
    return f"{text[:max_chars - len(_TRUNCATION_NOTICE)]}{_TRUNCATION_NOTICE}"


def render_terminal(result: dict[str, Any], max_chars: int = MAX_RESULT_CHARS) -> str:
    """Render the fixed terminal envelope without presenting self-report as certification."""
    rounds = result["roundsStarted"]
    rounds_text = f"{rounds} round{'' if rounds == 1 else 's'}"
    report_text = json.dumps(result.get("report"), ensure_ascii=False, indent=2)
    if result["status"] == "complete":
        text = f"Ralph worker reported completion after {rounds_text}.\nFinal report:\n{report_text}"
    elif result["status"] == "blocked":
        text = f"Ralph worker reported a blocker after {rounds_text}.\nFinal report:\n{report_text}"
    elif result["status"] == "budget-limited":
        text = (
            f"Ralph reached its {rounds_text} limit; the worker reported work remaining.\n"
            f"Final report:\n{report_text}")
    else:
        header = f"Ralph round {rounds} child failed before producing a structured report."
        last = result.get("lastReport")
        text = header if last is None else f"{header}\nLast successful handoff:\n{json.dumps(last, ensure_ascii=False, indent=2)}"
    return bound_result(text, max_chars)


def round_prompt(objective: str, round_no: int, max_rounds: int, previous: dict[str, Any] | None) -> str:
    prior = "(none — this is the first round)" if previous is None else json.dumps(
        previous, ensure_ascii=False)
    return ROUND_PROMPT_TEMPLATE.format(
        objective=objective, round=round_no, max_rounds=max_rounds, prior=prior,
    )


async def run_ralph_loop(
    delegation: Any,
    *,
    objective: str,
    max_rounds: int,
    child_options: dict[str, Any],
    cwd: str | None = None,
    max_handoff_chars: int = MAX_HANDOFF_CHARS,
    max_result_chars: int = MAX_RESULT_CHARS,
) -> dict[str, Any]:
    """Run the fixed serial fresh-agent loop toward one immutable objective.

    Returns the DSH terminal envelope:
    ``{status, roundsStarted, report | lastReport}`` where status is one of
    ``complete`` / ``blocked`` / ``budget-limited`` / ``round-failed``.
    """
    objective = str(objective or "").strip()
    if not objective:
        raise ValueError("Ralph objective must be a non-empty string")
    previous: dict[str, Any] | None = None
    for round_no in range(1, max_rounds + 1):
        child = await delegation.delegate_task(
            round_prompt(objective, round_no, max_rounds, previous),
            None,
            None,
            executor="atlas",
            background=False,
            output_schema=REPORT_SCHEMA,
            event_metadata={"agent": "general", "role": "leaf", "background": False,
                            "round": round_no, "kind": "ralph"},
            atlas_options=child_options,
            cwd=cwd,
        )
        if not child.get("schema_valid"):
            return {"status": "round-failed", "roundsStarted": round_no,
                    "lastReport": previous}
        from atlas.agent.delegation_output_schema import extract_json_candidate

        try:
            report = validate_report(
                json.loads(extract_json_candidate(str(child.get("result") or ""))),
                max_handoff_chars,
            )
        except (ValueError, json.JSONDecodeError):
            return {"status": "round-failed", "roundsStarted": round_no,
                    "lastReport": previous}
        if report["status"] == "complete":
            return {"status": "complete", "roundsStarted": round_no, "report": report}
        if report["status"] == "blocked":
            return {"status": "blocked", "roundsStarted": round_no, "report": report}
        previous = report
    return {"status": "budget-limited", "roundsStarted": max_rounds, "report": previous}
