"""Live glue between the library store and Atlas' skills, tools and models.

Three cost levers live here:

1. Skill index by retrieval — the prompt carries the top hits for this message
   plus a one-line category summary, never the whole library.
2. On-demand skill fetch — catalog skills (collected, not installed) are
   downloaded the first time ``use_skill`` asks for them.
3. Deferred tools — rarely used / MCP tool schemas are collapsed to a name list;
   ``tool_search`` loads the ones a task needs into the session.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import structlog

from atlas.library.search import Bm25Index
from atlas.library.store import LibraryStore, slugify
from atlas.library.taxonomy import OTHER_ID

log = structlog.get_logger(__name__)

_STORE: LibraryStore | None = None
_DISCOVERY_REGISTRY: Any | None = None
_DISCOVERY_REGISTRY_PATH: str | None = None


def get_store() -> LibraryStore:
    global _STORE
    if _STORE is None:
        from atlas.config import DATA_ROOT

        _STORE = LibraryStore(DATA_ROOT / "data" / "library")
    return _STORE


def library_skills_dir() -> Path:
    return get_store().skills_dir


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def _function(schema: dict[str, Any]) -> dict[str, Any]:
    return schema.get("function", schema) if isinstance(schema, dict) else {}


def tool_kind(name: str) -> str:
    if "__" in name:
        return "mcp"
    return "builtin"


def _with_category(store: LibraryStore, item: dict[str, Any]) -> dict[str, Any]:
    row = store.assignment(item["key"])
    category = store.category(row["category"]) if row else None
    item["category"] = category["id"] if category else None
    item["category_name"] = category["name"] if category else ""
    item["assigned_by"] = row.get("by") if row else None
    # Category keywords bridge languages in retrieval: "查论文" finds an English arXiv skill.
    item["category_keywords"] = list((category or {}).get("keywords") or [])[:16]
    return item


def skill_items(skill_mgr: Any, store: LibraryStore | None = None) -> list[dict[str, Any]]:
    store = store or get_store()
    catalog = store.catalog()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for info in (skill_mgr.list_skills() if skill_mgr is not None else []):
        entry = catalog.get(f"skill:{info.name}", {})
        seen.add(info.name)
        items.append({
            "key": f"skill:{info.name}", "type": "skill", "name": info.name,
            "title": entry.get("title_zh", ""), "description": info.description,
            "when_to_use": entry.get("when_to_use_zh", ""), "tags": list(info.tags or []),
            "declared_category": info.category or entry.get("category", ""),
            "category_suggestion": entry.get("category_suggestion_zh", ""),
            "status": "installed", "source": info.source, "version": info.version,
            "homepage": entry.get("homepage", ""),
        })
    for key, entry in catalog.items():
        if entry.get("type") != "skill" or entry["name"] in seen:
            continue
        items.append({
            "key": key, "type": "skill", "name": entry["name"], "title": entry.get("title_zh", ""),
            "description": entry["description"], "when_to_use": entry.get("when_to_use_zh", ""),
            "tags": list(entry.get("tags") or []), "declared_category": entry.get("category", ""),
            "category_suggestion": entry.get("category_suggestion_zh", ""), "status": "available",
            "source": entry.get("source") or entry.get("repo", ""), "homepage": entry.get("homepage", ""),
            "stars": entry.get("stars"), "last_updated": entry.get("last_updated"),
            "official": bool(entry.get("official")),
        })
    return [_with_category(store, item) for item in items]


def tool_items(tool_schemas: Iterable[dict[str, Any]], mcp_servers: Iterable[str] = (),
               store: LibraryStore | None = None) -> list[dict[str, Any]]:
    store = store or get_store()
    configured = {str(name).lower() for name in mcp_servers}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for schema in tool_schemas:
        fn = _function(schema)
        name = str(fn.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        server = name.split("__", 1)[0] if "__" in name else ""
        items.append({
            "key": f"tool:{name}", "type": "tool", "kind": tool_kind(name), "name": name,
            "server": server, "description": str(fn.get("description") or "").strip(),
            "tags": [server] if server else [], "declared_category": "", "status": "installed",
        })
    for key, entry in store.catalog().items():
        if entry.get("type") != "tool":
            continue
        installed = entry["name"].lower() in configured
        items.append({
            "key": key, "type": "tool", "kind": entry.get("kind", "mcp"), "name": entry["name"],
            "title": entry.get("title_zh", ""), "description": entry["description"],
            "when_to_use": entry.get("when_to_use_zh", ""), "tags": list(entry.get("tags") or []),
            "declared_category": entry.get("category", ""),
            "category_suggestion": entry.get("category_suggestion_zh", ""),
            "status": "installed" if installed else "available", "catalog": True,
            "install": entry.get("install"), "remote_url": entry.get("remote_url", ""),
            "env_required": entry.get("env_required") or [], "homepage": entry.get("homepage", ""),
            "stars": entry.get("stars"), "last_updated": entry.get("last_updated"),
            "official": bool(entry.get("official")), "windows": entry.get("windows"),
            "pricing": entry.get("pricing"), "tool_names": entry.get("tool_names") or [],
        })
    return [_with_category(store, item) for item in items]


def all_tool_schemas(agent: Any) -> list[dict[str, Any]]:
    """Every tool the main agent could be offered (before deferral)."""
    from atlas.engine.kernel.tools import kernel_tool_schemas

    tools = list(agent._model_facing_tools()) if agent is not None else []
    names = {_function(t).get("name") for t in tools}
    tools.extend(t for t in kernel_tool_schemas(include_workflow=True) if _function(t).get("name") not in names)
    return tools


# ---------------------------------------------------------------------------
# Model classifier for 一键整理
# ---------------------------------------------------------------------------

def _pick_model(model_mgr: Any) -> str | None:
    from atlas.config import load_user_settings

    try:
        settings = load_user_settings() or {}
    except Exception:  # noqa: BLE001
        settings = {}
    models = model_mgr.list_models() if model_mgr is not None else []
    ids = {str(m.get("id") or "") for m in models} | {str(m.get("litellm_model") or "") for m in models}
    for candidate in (settings.get("library_model"), settings.get("memory_model"),
                      settings.get("compression_model"), getattr(model_mgr, "current_model", None)):
        chosen = str(candidate or "").strip()
        if chosen and (chosen in ids or candidate == getattr(model_mgr, "current_model", None)):
            return chosen
    return None


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON")
    value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return value


def make_classifier(model_mgr: Any):
    router = getattr(model_mgr, "model_router", None)
    model_id = _pick_model(model_mgr) if router is not None else None
    if router is None or not model_id:
        return None

    async def classify(items: list[dict[str, Any]], categories: list[dict[str, Any]]) -> dict[str, Any]:
        cats = "\n".join(f"{c['id']}｜{c['name']}｜{c.get('description', '')}" for c in categories)
        rows = "\n".join(
            f"{item['key']}｜{(item.get('title') or '')}｜{str(item.get('description', ''))[:160]}"
            f"｜{','.join((item.get('tags') or [])[:5])}" for item in items
        )
        prompt = (
            "把下面每个技能/工具放进最合适的分类。\n"
            "规则：优先用已有分类；确实放不进任何已有分类、而且有几条同类时，才新建分类，"
            "在 new_categories 里给出 id（英文短横线）、name（中文 2~6 字）、description，"
            "新分类要能装下一类东西，不要为单个条目新建；实在不好归的放 other。\n"
            "只输出 JSON：{\"assign\": {\"条目key\": \"分类id\"}, \"new_categories\": "
            "[{\"id\": \"...\", \"name\": \"...\", \"description\": \"...\"}]}\n\n"
            f"已有分类（id｜名称｜说明）：\n{cats}\n\n条目（key｜标题｜描述｜标签）：\n{rows}"
        )
        result = await router.complete_for(
            model_id, "library_organize",
            [{"role": "system", "content": "你是严谨的分类器，只输出 JSON。"},
             {"role": "user", "content": prompt}],
            max_tokens=min(4000, 200 + 30 * len(items)), temperature=0,
        )
        return _parse_json_object(str(getattr(result, "text", "") or ""))

    return classify


async def organize_library(skill_mgr: Any, agent: Any, mcp_client: Any, model_mgr: Any,
                           *, full: bool = False, use_model: bool = True) -> dict[str, Any]:
    store = get_store()
    items = skill_items(skill_mgr, store) + tool_items(
        all_tool_schemas(agent), _configured_servers(mcp_client), store,
    )
    classifier = make_classifier(model_mgr) if use_model else None
    report = await store.organize(items, classifier=classifier, full=full)
    report["model"] = "on" if classifier else "off"
    return report


def _configured_servers(mcp_client: Any) -> list[str]:
    try:
        return list(mcp_client.get_configured_server_names()) if mcp_client is not None else []
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Skill index (prompt) + skill_search + on-demand fetch
# ---------------------------------------------------------------------------

_SKILL_INDEX_CACHE: dict[str, Any] = {}


def _skill_usage_counts() -> dict[str, int]:
    """Load ``skill name → use_count`` from the usage telemetry table, best effort.

    Read once per index build (the index itself is cached), so this adds one
    small query when the skill set changes and nothing on a normal turn. A
    missing table or unreadable DB simply means every skill ranks as unused.
    """
    try:
        from atlas.skills.agent_collections import _registry_path

        path = _registry_path()
        if path is None or not path.exists():
            return {}
        import sqlite3

        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            rows = db.execute(
                "SELECT skill_name, SUM(use_count) FROM skill_usage GROUP BY skill_name"
            ).fetchall()
        return {str(name): int(count or 0) for name, count in rows}
    except Exception:  # noqa: BLE001 - ranking falls back to retrieval order
        return {}


def _skill_index(skill_mgr: Any) -> tuple[Bm25Index, list[dict[str, Any]]]:
    store = get_store()
    infos = skill_mgr.list_skills() if skill_mgr is not None else []
    live_skills: list[tuple[str, str, str]] = []
    for info in infos:
        if getattr(info, "disable_model_invocation", False):
            continue
        try:
            digest = hashlib.sha256(Path(info.path).read_bytes()).hexdigest()
        except (OSError, AttributeError):
            digest = "unavailable"
        live_skills.append((str(info.name), str(getattr(info, "version", "")), digest))
    live_skills.sort()
    _sync_discovery_catalog(skill_mgr, infos)
    fingerprint = json.dumps(live_skills, separators=(",", ":"), ensure_ascii=False)
    catalog_revision = hashlib.sha256(fingerprint.encode()).hexdigest()
    signature = f"{store.version}:{catalog_revision}:{len(store.catalog())}"
    if _SKILL_INDEX_CACHE.get("sig") != signature:
        items = skill_items(skill_mgr, store)
        model_disabled = {str(info.name) for info in infos
                          if getattr(info, "disable_model_invocation", False)}
        items = [item for item in items if str(item.get("name") or "") not in model_disabled]
        usage = _skill_usage_counts()
        for item in items:
            item["use_count"] = usage.get(str(item.get("name") or ""), 0)
        _SKILL_INDEX_CACHE.update(
            sig=signature, items=items, index=Bm25Index(items),
            catalog_revision=catalog_revision,
        )
    return _SKILL_INDEX_CACHE["index"], _SKILL_INDEX_CACHE["items"]


def _sync_discovery_catalog(skill_mgr: Any, infos: list[Any]) -> dict[str, list[str]]:
    """Keep a durable digest/retirement projection beside the skill registry."""
    global _DISCOVERY_REGISTRY, _DISCOVERY_REGISTRY_PATH
    if skill_mgr is None:
        return {"added": [], "updated": [], "retired": [], "unchanged": []}
    try:
        from atlas.skills.agent_collections import _registry_path
        from atlas.skills.registry import SkillRegistry

        path = _registry_path()
        if path is None:
            return {"added": [], "updated": [], "retired": [], "unchanged": []}
        key = str(path.resolve())
        if _DISCOVERY_REGISTRY is None or _DISCOVERY_REGISTRY_PATH != key:
            _DISCOVERY_REGISTRY = SkillRegistry(path)
            _DISCOVERY_REGISTRY_PATH = key
        return _DISCOVERY_REGISTRY.reconcile_discovery_catalog(infos)
    except Exception as exc:  # noqa: BLE001 - prompt retrieval can use live scan on DB failure
        log.warning("library.skill_catalog_sync_failed", error_type=type(exc).__name__)
        return {"added": [], "updated": [], "retired": [], "unchanged": []}


def _usage_bonus(item: dict[str, Any]) -> float:
    """Tie-break score from real load counts, in BM25 units.

    ``log1p`` keeps a heavily used skill from permanently outranking a much more
    relevant one: 1 use → ~0.07, 10 → ~0.24, 100 → ~0.46. Relevance scores are
    typically several points, so this only reorders near-ties.
    """
    try:
        return 0.1 * math.log1p(max(0, int(item.get("use_count") or 0)))
    except (TypeError, ValueError):
        return 0.0


def _skill_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {"name": item["name"], "description": str(item.get("title") or item["description"])[:110]}
    if item.get("category_name"):
        row["category"] = item["category_name"]
    if item["status"] != "installed":
        row["fetch_on_use"] = True
    return row


def skill_index_message(skill_mgr: Any, query: str, *, top_k: int = 30,
                        list_all_below: int = 30) -> str | None:
    """System-message text for this turn's skill index, or None when there are no skills."""
    if skill_mgr is None:
        return None
    index, items = _skill_index(skill_mgr)
    if not items:
        return None
    if len(items) <= list_all_below:
        chosen = items
        header = ""
    else:
        # Retrieve a slightly wider candidate set, then let real usage reorder it:
        # a skill that has actually been loaded before is more likely to be the
        # right one than a fresh keyword tie. The bonus is capped well below the
        # BM25 range so relevance still decides, and usage only breaks ties.
        hits = index.search(query, limit=max(top_k * 2, top_k))
        ranked = sorted(
            ((_score + _usage_bonus(item), item) for _score, item in hits),
            key=lambda pair: -pair[0],
        )
        chosen = [item for _score, item in ranked[:top_k]]
        counts: dict[str, int] = {}
        for item in items:
            counts[item.get("category_name") or "未整理"] = counts.get(item.get("category_name") or "未整理", 0) + 1
        summary = "、".join(f"{name} {n}" for name, n in sorted(counts.items(), key=lambda kv: -kv[1])[:24])
        header = (f" The library holds {len(items)} skills ({summary}); only the ones most relevant to "
                  "this message are listed. Call skill_search(query, category) to look for others before "
                  "concluding no skill fits.")
        if not chosen:
            return ("Atlas Skill index (call use_skill(name) to load full instructions when one matches "
                    f"this task):{header}\n[]")
    return ("Atlas Skill index (call use_skill(name) to load full instructions when one matches "
            f"this task):{header}\n<available_skills revision=\"{_SKILL_INDEX_CACHE.get('catalog_revision', '')}\">\n"
            + json.dumps([_skill_row(i) for i in chosen], ensure_ascii=False)
            + "\n</available_skills>")


def search_skills(skill_mgr: Any, query: str, *, category: str = "", limit: int = 10) -> list[dict[str, Any]]:
    index, items = _skill_index(skill_mgr)
    wanted = category.strip()

    def where(item: dict[str, Any]) -> bool:
        return not wanted or wanted in {item.get("category"), item.get("category_name")}

    if query.strip():
        hits = [item for _score, item in index.search(query, limit=limit, where=where)]
    else:
        hits = [item for item in items if where(item)][:limit]
    return [_skill_row(item) | {"description": str(item.get("description", ""))[:240]} for item in hits]


async def ensure_skill(skill_mgr: Any, name: str) -> bool:
    """Make sure a skill is installed, fetching a catalog skill on first use."""
    if skill_mgr is None:
        return False
    if skill_mgr.get_skill(name) is not None:
        return True
    store = get_store()
    entry = store.catalog_entry(f"skill:{name}")
    if entry is None:
        return False
    row = store.assignment(f"skill:{name}")
    category = (row or {}).get("category") or slugify(str(entry.get("category") or OTHER_ID))
    if category.startswith("new-"):
        category = category[4:] or OTHER_ID
    target = store.skills_dir / category / name
    await fetch_skill(entry, target)
    await asyncio.to_thread(skill_mgr.scan_skills_sync)
    return skill_mgr.get_skill(name) is not None


def _fix_frontmatter(text: str, name: str, description: str) -> str:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        safe = description.replace("\n", " ").replace('"', "'")
        return f"---\nname: {name}\ndescription: \"{safe}\"\n---\n\n{text}"
    head = match.group(1)
    if re.search(r"^name\s*:", head, re.MULTILINE):
        head = re.sub(r"^name\s*:.*$", f"name: {name}", head, count=1, flags=re.MULTILINE)
    else:
        head = f"name: {name}\n{head}"
    # Many community skills use free-form versions; drop ones Atlas would reject.
    head = re.sub(r"^version\s*:\s*(?![\"']?\d+\.\d+\.\d+[\"']?\s*$).*$\n?", "", head, flags=re.MULTILINE)
    return f"---\n{head}\n---\n" + text[match.end():]


async def fetch_skill(entry: dict[str, Any], target: Path) -> None:
    import httpx

    headers = {"User-Agent": "Atlas-Library"}
    files: dict[str, bytes] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        repo, path = str(entry.get("repo") or ""), str(entry.get("skill_path") or "").strip("/")
        if "has-files" in (entry.get("tags") or []) and repo and path:
            try:
                files = await _github_dir(client, repo, path, str(entry.get("commit") or ""))
            except Exception as exc:  # noqa: BLE001 — fall back to SKILL.md only
                log.info("library.skill_dir_fetch_failed", repo=repo, error=str(exc))
                files = {}
        if "SKILL.md" not in files:
            for attempt in range(3):
                try:
                    response = await client.get(str(entry["raw_url"]))
                    response.raise_for_status()
                    files["SKILL.md"] = response.content
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", 0)
                    if attempt == 2 or 400 <= status < 500:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
    text = files["SKILL.md"].decode("utf-8", errors="replace")
    files["SKILL.md"] = _fix_frontmatter(text, entry["name"], entry["description"]).encode("utf-8")
    for rel, data in files.items():
        dest = (target / rel).resolve()
        if target.resolve() not in dest.parents:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    log.info("library.skill_fetched", name=entry["name"], files=len(files), path=str(target))


async def _github_dir(client: Any, repo: str, path: str, ref: str, *, budget: list[int] | None = None) -> dict[str, bytes]:
    import os

    budget = budget if budget is not None else [80]
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo}/contents/{path}" + (f"?ref={ref}" if ref else "")
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    out: dict[str, bytes] = {}
    for node in response.json():
        if budget[0] <= 0:
            break
        rel = node["path"][len(path):].lstrip("/")
        if node["type"] == "file" and node.get("download_url") and int(node.get("size") or 0) < 2_000_000:
            budget[0] -= 1
            data = await client.get(node["download_url"])
            data.raise_for_status()
            out[rel] = data.content
        elif node["type"] == "dir":
            sub = await _github_dir(client, repo, node["path"], ref, budget=budget)
            out.update({f"{rel}/{k}": v for k, v in sub.items()})
    return out


# ---------------------------------------------------------------------------
# Deferred tools
# ---------------------------------------------------------------------------

# Builtins the model needs rarely; MCP tools (server__tool) are always deferrable.
DEFERRABLE_BUILTINS = frozenset({
    "kanban_create_board", "kanban_list", "kanban_create_task", "kanban_update_task",
    "kanban_create", "kanban_update",
    "create_document", "create_spreadsheet", "create_presentation", "read_office",
    "create_checkpoint", "list_checkpoints", "restore_checkpoint", "git_pr_create", "git_pr_comment",
    "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource", "automation_manage",
    "project_note", "project_sources_search", "clock.curr_time", "clock.sleep",
    "list_available_plugins_to_install", "request_plugin_install", "wait_for_environment",
    "send_message_to_user_async", "request_user_input_async", "get_context_remaining", "new_context",
    "new_context_window", "execute_code", "subtask_status", "subtask_message",
    # Compatibility aliases of local_shell / local_process (Codex and Claude names);
    # offering them next to the real tools only gives the model more ways to misquote.
    "exec_command", "powershell", "write_stdin",
})

_LOADED: OrderedDict[str, list[str]] = OrderedDict()
_LOADED_CAP = 400


def loaded_tools(session_id: str) -> list[str]:
    return list(_LOADED.get(session_id, []))


def mark_loaded(session_id: str, names: Iterable[str]) -> list[str]:
    current = _LOADED.setdefault(session_id, [])
    _LOADED.move_to_end(session_id)
    added = [name for name in names if name not in current]
    current.extend(added)
    while len(_LOADED) > _LOADED_CAP:
        _LOADED.popitem(last=False)
    return added


# Whole tool families that only matter for specific tasks (mobile dev, Claude-compat task APIs, notebooks).
DEFERRABLE_PREFIXES = ("android_", "ios_", "mobile_", "notebook_", "Task", "TodoWrite", "git_pr_", "kanban_")


def _deferrable(name: str, core: set[str]) -> bool:
    return name not in core and (
        "__" in name or name in DEFERRABLE_BUILTINS or name.startswith(DEFERRABLE_PREFIXES)
    )


def partition_tools(tools: Sequence[dict[str, Any]], *, session_id: str, query: str,
                    config: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Split tools into offered schemas and a deferred-name listing.

    The listing covers every deferrable tool (loaded or not) and is sorted, so
    it stays byte-stable across turns and does not break the prompt cache.
    """
    cfg = dict(config.get("library", {}) or {})
    mode = str(cfg.get("tool_search_mode") or "").strip().lower()
    if mode == "all":
        return list(tools), None
    defer_tools = mode == "on-demand" or cfg.get("defer_tools", True)
    minimum = 0 if mode == "on-demand" else int(cfg.get("defer_min_tools", 30))
    if not defer_tools or len(tools) <= minimum:
        return list(tools), None
    core = {str(name) for name in cfg.get("core_tools", []) or []}
    deferrable = [t for t in tools if _deferrable(str(_function(t).get("name") or ""), core)]
    if len(deferrable) < 5:
        return list(tools), None
    if query.strip():
        items = [{"name": _function(t)["name"], "description": _function(t).get("description", ""),
                  "server": str(_function(t)["name"]).split("__", 1)[0]} for t in deferrable]
        hits = Bm25Index(items).search(query, limit=int(cfg.get("auto_load", 3)),
                                       min_score=float(cfg.get("auto_load_min_score", 5.0)))
        mark_loaded(session_id, [item["name"] for _score, item in hits])
    loaded = set(loaded_tools(session_id))
    deferred_names = {str(_function(t)["name"]) for t in deferrable}
    offered = [t for t in tools if str(_function(t).get("name")) not in deferred_names
               or str(_function(t).get("name")) in loaded]
    return offered, deferred_listing(sorted(deferred_names))


def deferred_listing(names: Sequence[str]) -> str:
    store = get_store()
    groups: dict[str, list[str]] = {}
    for name in names:
        row = store.assignment(f"tool:{name}")
        category = store.category(row["category"]) if row else None
        label = category["name"] if category else (f"{name.split('__', 1)[0]}（MCP）" if "__" in name else "其他")
        groups.setdefault(label, []).append(name)
    lines = [f"- {label}: {', '.join(group)}" for label, group in sorted(groups.items())]
    return (
        "Deferred tools: installed and callable, but their full definitions are collapsed to save "
        "tokens. When a task needs one, call tool_search with query \"select:name1,name2\" (or with "
        "keywords) to load it, then call it normally. Tools you already loaded stay available.\n"
        + "\n".join(lines)
    )


def search_tools(all_tools: Sequence[dict[str, Any]], query: str, *, session_id: str,
                 limit: int = 8) -> dict[str, Any]:
    """tool_search: load matching tools into this session and report them."""
    by_name = {str(_function(t).get("name")): t for t in all_tools if _function(t).get("name")}
    query = query.strip()
    if query.lower().startswith("select:"):
        wanted = [part.strip() for part in query[7:].split(",") if part.strip()]
        matched = [name for name in wanted if name in by_name]
        missing = [name for name in wanted if name not in by_name]
    else:
        items = [{"name": name, "description": _function(t).get("description", ""),
                  "server": name.split("__", 1)[0] if "__" in name else ""} for name, t in by_name.items()]
        matched = [item["name"] for _score, item in Bm25Index(items).search(query, limit=limit)]
        if not matched:
            lowered = query.casefold()
            matched = [name for name, t in by_name.items()
                       if lowered in f"{name} {_function(t).get('description', '')}".casefold()][:limit]
        missing = []
    mark_loaded(session_id, matched)
    tools = []
    for name in matched:
        fn = _function(by_name[name])
        params = (fn.get("parameters") or {}).get("properties") or {}
        tools.append({"name": name, "description": str(fn.get("description") or "")[:300],
                      "parameters": list(params)[:20]})
    result: dict[str, Any] = {"loaded": tools, "note": "已加载，可以直接调用这些工具。" if tools else "没有匹配的已安装工具。"}
    if missing:
        result["unknown"] = missing
    if not query.lower().startswith("select:"):
        catalog = [item for item in tool_items([], [], get_store()) if item["status"] == "available"]
        if catalog:
            hits = Bm25Index(catalog).search(query, limit=3, min_score=4.0)
            if hits:
                result["not_installed"] = [
                    {"name": item["name"], "description": str(item.get("title") or item["description"])[:160],
                     "env_required": item.get("env_required") or []}
                    for _score, item in hits
                ]
                result["note"] += " not_installed 里的工具在「技能与工具库」页面一键安装后才能用，可以建议用户安装。"
    return result
