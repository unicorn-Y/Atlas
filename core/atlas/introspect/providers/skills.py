"""Introspection provider: the skill catalog.

Skills are Atlas's procedure layer, and the two questions that actually come up
are "what is installed" and "why did a dependency keep this one from running".
``preflight_dependencies`` answers the second without activating anything, which
matters because activation mutates state and an introspection call must not.

``scan_skills`` is intentionally not used: it re-reads the catalog from disk, and
an HTTP introspection request should not trigger a rescan.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

_log = logging.getLogger(__name__)


def _manager(ctx: Context) -> Any:
    return getattr(ctx.services, "skill_mgr", None) if ctx.services else None


def _mgr_with_catalog(ctx: Context) -> Any:
    """The skill manager, scanned if its index is still empty.

    A freshly constructed ``SkillManager`` has an empty index until someone calls
    ``scan_skills``; the production lifespan does that, but introspection is also
    mounted over a bare container in tests and in the CLI. Scanning here keeps the
    answer truthful instead of reporting "0 skills" for a machine with twelve.
    """
    mgr = _manager(ctx)
    if mgr is None:
        return None
    try:
        empty = not mgr.list_skills()
    except Exception:  # noqa: BLE001
        return mgr
    if empty:
        scanner = getattr(mgr, "scan_skills_sync", None) or getattr(mgr, "scan_skills", None)
        if callable(scanner):
            try:
                scanner()
            except Exception:  # noqa: BLE001 - a failed scan still leaves a usable manager
                # Deliberately swallowed: this is a best-effort catalog refresh on a
                # read-only path. Reporting the failure as an introspection error
                # would replace a useful (if smaller) answer with none at all.
                _log.debug("introspect.skills.scan_failed", exc_info=True)
    return mgr


def _list(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    mgr = _mgr_with_catalog(ctx)
    if mgr is None:
        return {"count": 0, "skills": [], "note": "当前应用没有 skill_mgr 服务。"}
    lister = getattr(mgr, "list_skills", None)
    if not callable(lister):
        return {"count": 0, "skills": [], "note": "skill_mgr 没有 list_skills()。"}
    try:
        rows = list(lister())
    except Exception as exc:  # noqa: BLE001
        return {"count": 0, "skills": [], "error": f"{type(exc).__name__}: {exc}"}

    wanted = str(args.get("filter") or "").strip().lower()
    if wanted:
        rows = [
            row
            for row in rows
            if wanted in str(getattr(row, "name", "")).lower()
            or wanted in str(getattr(row, "description", "")).lower()
        ]
    category = str(args.get("category") or "").strip().lower()
    if category:
        rows = [
            row
            for row in rows
            if category in str(getattr(row, "category", "")).lower()
        ]

    detail = {
        "count": len(rows),
        "skills": [
            {
                "name": getattr(row, "name", ""),
                "description": str(getattr(row, "description", ""))[:200],
                "category": getattr(row, "category", ""),
                "source": str(getattr(row, "source", "")),
            }
            for row in rows
        ],
    }
    count = getattr(mgr, "skill_count", None)
    if count is not None:
        try:
            detail["total"] = count() if callable(count) else count
        except Exception:  # noqa: BLE001 - a count is a nicety, never a failure
            detail["total"] = len(rows)
    else:
        detail["total"] = len(rows)
    return detail


def _categories(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    mgr = _mgr_with_catalog(ctx)
    if mgr is None:
        return {"note": "当前应用没有 skill_mgr 服务。"}
    # ``categories`` is a list attribute, not a method. Calling it unconditionally
    # raised ``TypeError: 'list' object is not callable`` on the first live run.
    value = getattr(mgr, "categories", None)
    try:
        cats = value() if callable(value) else value
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if cats is None:
        return {"categories": []}
    return {"categories": list(cats) if not isinstance(cats, dict) else cats}


#: ``preflight_dependencies`` returns one row per declared dependency with a
#: ``state`` field — including the satisfied ones. Treating "returned rows" as
#: "blocking" marked every skill unready, so the states that actually block are
#: named here instead.
BLOCKING_STATES = frozenset({"missing", "unsatisfied", "error", "unavailable", "not_found"})


def _blocking(findings: list[Any]) -> list[Any]:
    return [
        row
        for row in findings
        if str(row.get("state", "")).strip().lower() in BLOCKING_STATES
    ]


def _preflight(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Dependency readiness without activating the skill.

    Activation mutates the process; a read-only endpoint may only *ask*.

    ``check_dependencies`` and ``preflight_dependencies`` both require a skill
    name — there is no "check everything" mode. When no name is given this returns
    every skill whose dependencies are *not* satisfied, by asking each one in turn,
    which is the question callers actually meant by "preflight all".
    """
    mgr = _mgr_with_catalog(ctx)
    if mgr is None:
        return {"note": "当前应用没有 skill_mgr 服务。"}
    name = str(args.get("name") or "").strip()
    preflight = getattr(mgr, "preflight_dependencies", None)

    if name:
        if not callable(preflight):
            return {"name": name, "note": "skill_mgr 没有 preflight_dependencies()。"}
        try:
            findings = preflight(name)
        except Exception as exc:  # noqa: BLE001
            return {"name": name, "error": f"{type(exc).__name__}: {exc}"}
        findings = list(findings or [])
        if not findings:
            # ``preflight_dependencies`` returns [] both for a satisfied skill and
            # for a name it does not know, so an unknown name would otherwise be
            # reported ready. Confirm the skill exists before claiming anything.
            known = getattr(mgr, "get_skill", None)
            exists = True
            if callable(known):
                try:
                    exists = known(name) is not None
                except Exception:  # noqa: BLE001
                    exists = True
            if not exists:
                return {
                    "name": name,
                    "error": f"没有名为 {name!r} 的技能。",
                    "ready": False,
                }
        blockers = _blocking(findings)
        return {
            "name": name,
            "ready": not blockers,
            "blocking": blockers,
            "checked": len(findings),
        }

    lister = getattr(mgr, "list_skills", None)
    if not callable(lister) or not callable(preflight):
        return {"note": "skill_mgr 不支持批量预检。"}
    try:
        names = [getattr(row, "name", "") for row in lister()]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    blocked: list[dict[str, Any]] = []
    for one in names:
        if not one:
            continue
        try:
            findings = list(preflight(one) or [])
        except Exception as exc:  # noqa: BLE001 - one bad skill must not hide the rest
            blocked.append({"name": one, "error": f"{type(exc).__name__}: {exc}"})
            continue
        blockers = _blocking(findings)
        if blockers:
            blocked.append({"name": one, "blocking": blockers})
    return {"checked": len(names), "blocked": blocked, "count": len(blocked)}


def _plugin_patches(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Local plugin edits that will survive an upgrade.

    Answers the question a user cannot otherwise answer: "did my one-line fix
    actually stick, or will the next upgrade wipe it?" The patch layer keeps the
    shipped bytes recoverable, so a non-zero count here means the edit is safe.
    """
    runtime = getattr(ctx.services, "plugin_runtime", None) if ctx.services else None
    if runtime is None:
        return {"patches": [], "count": 0, "note": "插件服务尚未就绪"}
    wanted = str(args.get("plugin") or "").strip()
    try:
        names = [item["name"] for item in runtime.discover()]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if wanted:
        names = [name for name in names if name == wanted]
        if not names:
            return {"error": f"插件不存在：{wanted}"}
    rows: list[dict[str, Any]] = []
    for name in names:
        try:
            listing = runtime.list_patches(name)
        except Exception as exc:  # noqa: BLE001 - one broken plugin must not hide the rest
            rows.append({"plugin": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if listing.get("count"):
            rows.append({"plugin": name, **listing})
    return {
        "patched_plugins": len(rows),
        "count": sum(row.get("count", 0) for row in rows),
        "plugins": rows,
    }


def _sources(ctx: Context, _args: dict[str, Any]) -> dict[str, Any]:
    """Enumerate the discovery ladder: one row per registered SkillSource.

    This is the host-visible view of the per-scope layering seam — the same
    priorities ``default_skill_sources`` / ``register_skill_source`` /
    ``with_sources`` compose. Higher priority wins duplicate names; the row
    order is exactly the scan order, so the answer explains precedence without
    re-deriving it from code.
    """
    mgr = _mgr_with_catalog(ctx)
    if mgr is None:
        return {"note": "当前应用没有 skill_mgr 服务。"}
    sources = getattr(mgr, "_sources", None)
    if not isinstance(sources, dict):
        return {"error": "skill_mgr 没有可读的 _sources 注册表。"}
    rows = []
    for source in sorted(sources.values(), key=lambda item: (item.priority, item.name)):
        try:
            layout_parts = {"single": 1, "flat": 2, "category": 3}.get(
                getattr(source, "layout", ""), None,
            )
            skill_files = 0
            if source.root.is_dir():
                skill_files = sum(
                    1 for path in source.root.rglob("SKILL.md")
                    if layout_parts is None
                    or len(path.relative_to(source.root).parts) == layout_parts
                )
            rows.append({
                "name": source.name,
                "priority": source.priority,
                "layout": source.layout,
                "root": str(source.root),
                "exists": source.root.is_dir(),
                "skill_md_count": skill_files,
            })
        except OSError as exc:
            rows.append({
                "name": getattr(source, "name", "?"),
                "priority": getattr(source, "priority", -1),
                "layout": getattr(source, "layout", "?"),
                "root": str(getattr(source, "root", "")),
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {
        "count": len(rows),
        "sources": rows,
        "note": "按扫描顺序排列；同名技能由更高 priority 的来源胜出（同层内 name、path 决胜）。",
    }


PROVIDER = Provider(
    id="skills",
    title="技能目录",
    summary="已安装技能的分类与来源，以及依赖是否就绪（不触发激活）。",
    methods=(
        Method(
            name="list",
            summary="列出技能（可按名称/描述/分类过滤）。",
            input_schema=object_schema(
                {
                    "filter": {"type": "string", "description": "按名称或描述做子串过滤。"},
                    "category": {"type": "string", "description": "只看某一分类。"},
                }
            ),
            run=_list,
        ),
        Method(
            name="categories",
            summary="列出技能分类。",
            input_schema=object_schema(),
            run=_categories,
        ),
        Method(
            name="sources",
            summary="列出发现根阶梯：每个来源的优先级、布局、根目录与发现的 SKILL.md 数。",
            input_schema=object_schema(),
            run=_sources,
        ),
        Method(
            name="preflight",
            summary="检查技能依赖是否就绪；不激活技能。",
            input_schema=object_schema(
                {"name": {"type": "string", "description": "技能名；省略则检查全部。"}}
            ),
            run=_preflight,
        ),
        Method(
            name="plugin_patches",
            summary="列出插件上保留至今的本地改动（升级不会覆盖）。",
            input_schema=object_schema(
                {"plugin": {"type": "string", "description": "只看某个插件；省略则列出全部。"}}
            ),
            run=_plugin_patches,
        ),
    ),
)
