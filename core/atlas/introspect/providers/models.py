"""Introspection provider: the model roster and its readiness.

The recurring failure this answers is "why did the run fail before it started":
a model that is listed but has no credential, or a current model that is not in
the roster at all. Both are configuration facts, and both are invisible from the
UI until a request fails.

**No credential ever leaves this module.** ``api_key_configured`` is a boolean and
that is the only thing reported; key material stays in
:mod:`atlas.secrets_store`.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _manager(ctx: Context) -> Any:
    return getattr(ctx.services, "model_mgr", None) if ctx.services else None


def _models(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    mgr = _manager(ctx)
    if mgr is None:
        return {"count": 0, "models": [], "note": "当前应用没有 model_mgr 服务。"}
    lister = getattr(mgr, "list_models", None)
    if not callable(lister):
        return {"count": 0, "models": [], "note": "model_mgr 没有 list_models()。"}
    try:
        rows = list(lister())
    except Exception as exc:  # noqa: BLE001
        return {"count": 0, "models": [], "error": f"{type(exc).__name__}: {exc}"}

    wanted = str(args.get("filter") or "").strip().lower()
    if wanted:
        rows = [
            row
            for row in rows
            if wanted in str(row.get("id", "")).lower()
            or wanted in str(row.get("name", "")).lower()
            or wanted in str(row.get("provider", "")).lower()
        ]
    return {"count": len(rows), "models": rows}


def _current(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    mgr = _manager(ctx)
    if mgr is None:
        return {"note": "当前应用没有 model_mgr 服务。"}

    def read(attr: str) -> Any:
        """Read a member that may be a plain attribute or a bound method.

        ``ModelManager`` exposes ``current_model`` as a property and
        ``context_window_for_model`` as a method; calling the former would raise
        and indexing the latter would lie. Ask, do not assume.
        """
        try:
            value = getattr(mgr, attr, None)
        except Exception as exc:  # noqa: BLE001 - a property may raise
            return f"<{type(exc).__name__}>"
        if callable(value):
            try:
                return value()
            except TypeError:
                return value
            except Exception as exc:  # noqa: BLE001
                return f"<{type(exc).__name__}>"
        return value

    out: dict[str, Any] = {}
    for attr in ("current_model", "current_litellm_model", "gateway_source"):
        out[attr] = read(attr)
    model = out.get("current_model")

    def limit(fn_name: str) -> Any:
        fn = getattr(mgr, fn_name, None)
        if not callable(fn):
            return None
        try:
            return fn(model)
        except Exception as exc:  # noqa: BLE001
            return f"<{type(exc).__name__}: {exc}>"

    out["context_window"] = limit("context_window_for_model")
    out["output_tokens"] = limit("output_tokens_for_model")
    return out


def _readiness(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """Which listed models cannot actually run, and why.

    This is the "run failed before the model was called" answer: a model whose
    credential is absent. Reported as names only — never the key itself.
    """
    mgr = _manager(ctx)
    if mgr is None:
        return {"note": "当前应用没有 model_mgr 服务。"}
    probe = getattr(mgr, "missing_model_credentials", None)
    if probe is None:
        return {"missing_credentials": [], "count": 0, "note": "model_mgr 没有 this probe。"}
    try:
        missing = probe() if callable(probe) else probe
        missing = list(missing or [])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "missing_credentials": missing,
        "count": len(missing),
        "note": "这些模型已列出但缺少凭据，调用会在请求前失败。",
    }


PROVIDER = Provider(
    id="models",
    title="模型与就绪度",
    summary="模型清单、当前选择、上下文与输出上限，以及缺凭据而无法运行的模型。",
    methods=(
        Method(
            name="list",
            summary="列出模型清单（可过滤）。",
            input_schema=object_schema(
                {"filter": {"type": "string", "description": "按 id/名称/provider 做子串过滤。"}}
            ),
            run=_models,
        ),
        Method(
            name="current",
            summary="当前选中的模型及其上下文窗口与输出上限。",
            input_schema=object_schema(),
            run=_current,
        ),
        Method(
            name="readiness",
            summary="列出缺少凭据、因而无法运行的模型。",
            input_schema=object_schema(),
            run=_readiness,
        ),
    ),
)
