"""Dry-run a prompt: what tier it lands in, which tools get offered, what it costs.

Nothing here calls a model. The whole point is to answer "if I send this, what
will Atlas actually load?" before spending a single token.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.engine.kernel import tool_pruning

router = APIRouter()

# Rough chars-per-token for mixed Chinese/English schema text. Atlas's own
# measurements sit between 3.5 and 4.2; 4.0 keeps the estimate slightly optimistic
# so a dry run never talks the user out of a run that would have fit.
_CHARS_PER_TOKEN = 4.0


class SimulateBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    workspace: str = ""
    budget: int = Field(default=24, ge=1, le=200)
    max_per_family: int = Field(default=4, ge=1, le=50)


def _schema_bytes(schemas: list[dict[str, Any]]) -> int:
    import json

    return len(json.dumps(schemas, ensure_ascii=False, default=str))


@router.post("/api/maintenance/plan-simulate")
async def simulate_plan(
    body: SimulateBody,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Report the tier and tool selection a prompt would produce, without running it."""
    manager = services.model_mgr
    schemas: list[dict[str, Any]] = []
    source = "unavailable"
    # The live tool pool lives on the orchestrator (the same object the kernel
    # uses), never on the model manager. Falling back to nothing is correct:
    # an empty pool must not be reported as "you have no tools".
    for candidate in (getattr(services, "orchestrator", None),
                      getattr(manager, "agent", None)):
        if candidate is not None and hasattr(candidate, "_model_facing_tools"):
            try:
                schemas = list(candidate._model_facing_tools() or [])
                source = type(candidate).__name__
                break
            except Exception:  # noqa: BLE001 - a dry run must degrade, not fail
                schemas = []

    tier = tool_pruning.tier_key(body.prompt, body.workspace)
    selection: dict[str, Any] = {}
    if schemas:
        try:
            selection = tool_pruning.explain_selection(
                schemas,
                message=body.prompt,
                workspace=body.workspace,
                budget=body.budget,
                max_per_family=body.max_per_family,
            )
        except Exception as exc:  # noqa: BLE001
            selection = {"error": f"{type(exc).__name__}: {exc}"}

    # ``explain_selection`` returns names in ``selected``, the surviving schemas in
    # ``schemas``, and the byte total in ``selected_bytes``. Read those directly
    # instead of re-deriving them, so the numbers can never drift from the kernel.
    offered_names = [str(name) for name in (selection.get("selected") or [])]
    offered_schemas = selection.get("schemas") or []

    before_bytes = _schema_bytes(schemas)
    after_bytes = int(selection.get("selected_bytes") or 0) or _schema_bytes(offered_schemas)

    return {
        "tier": tier,
        "bucket": tool_pruning.bucket_of(tier),
        "tool_source": source,
        "tool_count_total": len(schemas),
        "tool_count_offered": len(offered_names),
        "offered": offered_names,
        "schema_chars_before": before_bytes,
        "schema_chars_after": after_bytes,
        "schema_saved_ratio": (round(1 - after_bytes / before_bytes, 4) if before_bytes and after_bytes else None),
        "estimate": {
            "schema_tokens_before": int(before_bytes / _CHARS_PER_TOKEN),
            "schema_tokens_after": int(after_bytes / _CHARS_PER_TOKEN),
            "prompt_tokens": int(len(body.prompt) / _CHARS_PER_TOKEN),
            "chars_per_token": _CHARS_PER_TOKEN,
        },
        "selection": selection,
        "note": "只做本地推导，不调用模型，不写任何状态。",
    }
