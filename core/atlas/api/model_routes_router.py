"""Model routing inspection: which model actually serves which purpose.

Read-only. Resolves routes without sending a single provider request, so the
panel costs nothing and never bills the account.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()

# Every purpose that Atlas actually routes. Keeping the list here (rather than
# deriving it at runtime) is deliberate: a purpose only shows up once some code
# path really calls ``complete_for`` with it, so this list doubles as a census.
PURPOSES: tuple[tuple[str, str], ...] = (
    ("conversation", "主对话"),
    ("planning", "规划"),
    ("compression", "上下文压缩"),
    ("memory_library", "记忆整理"),
    ("deep_research", "深度研究"),
    ("whatsnew", "更新说明"),
    ("suggestions", "输入建议"),
    ("vision", "看图"),
)

_SAFE_FIELDS = (
    "purpose",
    "provider",
    "api_mode",
    "model",
    "wire_model",
    "base_url",
    "fallback_reason",
)


def _route_row(spec: Any) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for name in _SAFE_FIELDS:
        value = getattr(spec, name, None)
        # base_url is the only network address we expose; it is already visible
        # in settings. The key, credential pool and proxy are never read here.
        row[name] = value if value is None or isinstance(value, str) else str(value)
    return row


@router.get("/api/maintenance/model-routes")
async def get_model_routes(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Report the route each purpose resolves to for the current model."""
    manager = services.model_mgr
    current = str(getattr(manager, "current_model", "") or "")
    model_router = getattr(manager, "model_router", None)

    routes: list[dict[str, Any]] = []
    if model_router is not None and current:
        for purpose, label in PURPOSES:
            try:
                spec = await model_router.resolve(current, purpose)
                row = _route_row(spec)
                row["label"] = label
                row["resolved"] = True
            except Exception as exc:  # noqa: BLE001 - a broken purpose must not hide the others
                row = {
                    "purpose": purpose,
                    "label": label,
                    "resolved": False,
                    "fallback_reason": f"{type(exc).__name__}: {exc}",
                }
            routes.append(row)

    models = []
    for item in getattr(manager, "list_models", lambda: [])() or []:
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        models.append({
            "id": model_id,
            "provider": str(item.get("provider") or ""),
            "current": model_id == current,
        })

    return {
        "current_model": current,
        "routes": routes,
        "models": models,
        "note": "只解析路由，不发起任何模型请求，因此不会产生费用。",
    }
