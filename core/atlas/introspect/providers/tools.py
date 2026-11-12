"""Introspection provider: what the model can actually call.

The tool registry is the model's whole world: if a tool is not registered,
exposed, and passing its ``check_fn``, the model cannot use it no matter how much
code sits behind it. Three questions matter and they are easy to conflate:

* **Registered** — an entry exists (``get_all_entries``).
* **Exposed** — its toolset's ``check_fn`` passes, so it reaches the model.
* **Reachable** — a toolset alias maps to it, so a preset naming the alias finds
  the tools.

A tool that is registered but gated off is the "built but never wired" failure
(P1-14) in its most expensive form: the feature got written, the model never sees
it, and nothing logs a complaint.

Answers come from the live registry singleton, never from a source scan, because
plugins overlay it at startup and scoped tools differ per profile.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

_SNIPPET = 140


def _registry() -> Any:
    from atlas.engine.tools.registry import registry

    return registry


def _is_exposed(entry: Any) -> bool:
    """True when the entry's gate is absent or passes.

    ``check_fn`` is a zero-arg callable that may touch the environment (is a
    binary on PATH? is an API key set?). A gate that raises is treated as closed —
    the exposure filter in ``get_definitions`` would drop the tool anyway, so
    treating it as open here would report a fantasy.
    """
    check = getattr(entry, "check_fn", None)
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:  # noqa: BLE001 - a broken gate closes the tool, never 500s
        return False


def _entry_row(entry: Any, *, exposed: bool | None = None) -> dict[str, Any]:
    description = getattr(entry, "description", "") or ""
    return {
        "name": entry.name,
        "toolset": entry.toolset,
        "description": description[:_SNIPPET],
        "is_async": bool(getattr(entry, "is_async", False)),
        "gated": getattr(entry, "check_fn", None) is not None,
        "exposed": _is_exposed(entry) if exposed is None else exposed,
        "requires_env": sorted(getattr(entry, "requires_env", ()) or ()),
    }


def _summary(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    registry = _registry()
    entries = list(registry.get_all_entries())
    by_toolset: dict[str, dict[str, int]] = {}
    for entry in entries:
        bucket = by_toolset.setdefault(entry.toolset, {"total": 0, "gated": 0, "hidden": 0})
        bucket["total"] += 1
        if getattr(entry, "check_fn", None) is not None:
            bucket["gated"] += 1
            if not _is_exposed(entry):
                bucket["hidden"] += 1

    toolsets = [
        {"toolset": name, **counts} for name, counts in sorted(by_toolset.items())
    ]
    return {
        "tools": len(entries),
        "toolsets": len(toolsets),
        "gated": sum(item["gated"] for item in toolsets),
        "hidden": sum(item["hidden"] for item in toolsets),
        "aliases": registry.get_registered_toolset_aliases(),
        "toolset_breakdown": toolsets,
    }


def _list_tools(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    registry = _registry()
    entries = list(registry.get_all_entries())
    toolset = str(args.get("toolset") or "")
    search = str(args.get("search") or "").lower()
    if toolset:
        entries = [e for e in entries if e.toolset == toolset]
    if search:
        entries = [
            e
            for e in entries
            if search in e.name.lower()
            or search in (getattr(e, "description", "") or "").lower()
        ]
    if args.get("only_hidden") is True:
        entries = [e for e in entries if not _is_exposed(e)]

    limit = int(args.get("limit") or 100)
    rows = [_entry_row(e) for e in entries[:limit]]
    return {"matched": len(entries), "returned": len(rows), "tools": rows}


def _tool_detail(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    registry = _registry()
    name = args["name"]
    entry = registry.get_entry(name)
    if entry is None:
        raise KeyError(f"工具注册表里没有 {name!r}")
    schema = getattr(entry, "schema", None) or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    return {
        **_entry_row(entry),
        "parameters": sorted(props) if isinstance(props, dict) else [],
        "required": list(schema.get("required") or []) if isinstance(schema, dict) else [],
        "has_handler": getattr(entry, "handler", None) is not None,
        "max_result_size_chars": getattr(entry, "max_result_size_chars", None),
        "dynamic_schema_overrides": bool(getattr(entry, "dynamic_schema_overrides", None)),
    }


def _hidden_tools(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Registered, but the model will never see it.

    Sorted by toolset so the report reads as "which subsystem to go fix" rather
    than a flat alphabetical list.
    """
    registry = _registry()
    hidden = [
        _entry_row(entry) for entry in registry.get_all_entries() if not _is_exposed(entry)
    ]
    hidden.sort(key=lambda row: (row["toolset"], row["name"]))
    return {
        "count": len(hidden),
        "note": "这些工具已注册但被 check_fn 挡住，模型看不到；通常意味着依赖没装或环境变量没配。",
        "tools": hidden,
    }


def _aliases(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    registry = _registry()
    aliases = registry.get_registered_toolset_aliases()
    rows = []
    for alias, target in sorted(aliases.items()):
        names = registry.get_tool_names_for_toolset(target)
        rows.append(
            {
                "alias": alias,
                "target": target,
                "tools": len(names),
                "resolves": bool(names),
            }
        )
    return {
        "count": len(rows),
        "broken": [row for row in rows if not row["resolves"]],
        "aliases": rows,
    }


PROVIDER = Provider(
    id="tools",
    title="工具面",
    summary="模型实际能调用什么：注册了哪些工具、哪些被依赖门挡住、别名是否都能解析。",
    methods=(
        Method(
            name="summary",
            summary="工具与工具集总量、被门挡住的分布、别名表。",
            input_schema=object_schema(),
            run=_summary,
        ),
        Method(
            name="list",
            summary="按工具集/关键字筛选工具。",
            input_schema=object_schema(
                {
                    "toolset": {"type": "string", "description": "只看该工具集。"},
                    "search": {"type": "string", "description": "在名称与描述里做子串搜索。"},
                    "only_hidden": {"type": "boolean", "description": "只看被门挡住的工具。"},
                    "limit": {"type": "integer", "description": "最多返回多少条，默认 100。"},
                }
            ),
            run=_list_tools,
        ),
        Method(
            name="detail",
            summary="看单个工具的参数、处理器与结果上限。",
            input_schema=object_schema(
                {"name": {"type": "string", "description": "工具名。"}}, required=("name",)
            ),
            run=_tool_detail,
        ),
        Method(
            name="hidden",
            summary="列出注册了但模型看不到的工具（接线债）。",
            input_schema=object_schema(),
            run=_hidden_tools,
        ),
        Method(
            name="aliases",
            summary="检查工具集别名是否都能解析到真实工具。",
            input_schema=object_schema(),
            run=_aliases,
        ),
    ),
)
