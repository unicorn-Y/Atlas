"""Capability health probes: what Atlas can *do right now*, not what it started.

``/api/health`` reports startup completion only. A component can finish starting
and still be useless — a skill corpus with one malformed ``name:`` makes the
whole source unloadable, an FTS index can lag behind the pages on disk, and an
MCP server can be configured yet never connected. Those are exactly the states
that used to look healthy.

Every probe here is:

* **cheap** — file stats, one read-only SQLite handle, one ``git rev-parse``.
  Only :func:`_check_chat_model` touches the network, and it is bounded;
* **read-only** — nothing calls ``ensure()``, ``sync()``, ``rebuild()``,
  ``scan_skills_sync()`` or ``git`` write commands;
* **isolated** — a probe that raises or times out yields ``degraded`` /
  ``unavailable`` for itself and never stops the report from rendering.

The report shape is fixed by :func:`capabilities_report`; the HTTP surface is
``atlas.api.capability_probes_router`` and the ``/api/health`` summary reuses
:func:`cached_capability_summary` so the default health path stays flat.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"

#: Default per-probe wall clock budget. A probe that misses it is reported as
#: ``degraded`` instead of holding the endpoint open.
DEFAULT_PROBE_TIMEOUT = 2.0
#: The chat probe is the one probe that speaks to a provider, so its first byte
#: can exceed a couple of seconds; still bounded, just with more room.
CHAT_PROBE_TIMEOUT = 15.0
#: How long a computed report stays servable. ``/api/capabilities`` is the only
#: caller that computes; ``/api/health`` only reads what it finds here.
REPORT_TTL_SECONDS = 60.0

#: The chat probe is the only one that spends tokens, so its verdict outlives the
#: report: a report refresh re-runs the cheap local probes and reuses this answer.
#: 10 minutes is long enough that pressing refresh a few times is free, and short
#: enough that a provider outage is still noticed without restarting Atlas.
CHAT_CACHE_TTL_SECONDS = 600.0

#: A failure is remembered only briefly, so a recovered provider is picked up
#: quickly instead of staying hidden behind the successful-answer window.
CHAT_FAILURE_TTL_SECONDS = 30.0
#: Upper bound on SKILL.md files parsed per scan, so a huge user skill directory
#: cannot turn one probe into a walk of the whole home folder.
SKILL_SCAN_LIMIT = 600


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """What a single probe found."""

    status: str
    detail: str


@dataclass(slots=True)
class ProbeContext:
    """Services a probe may consult.

    Resolution mirrors ``health_router._service``: the per-app container first,
    then the ``atlas.server`` module globals that tests patch. The module is only
    read from ``sys.modules`` — importing ``atlas.server`` just to find ``None``
    costs over a second and is a side effect a read-only probe must not have.
    Whoever patches those globals has already imported the module.
    """

    services: Any
    #: True when the caller explicitly asked to retest the model. Only the
    #: token-spending chat probe consults it; every other probe is always fresh.
    recheck_model: bool = False

    def resolve(self, name: str) -> Any:
        value = getattr(self.services, name, None)
        if value is not None:
            return value
        server = sys.modules.get("atlas.server")
        return getattr(server, name, None) if server is not None else None


@dataclass(frozen=True, slots=True)
class Probe:
    """One capability check.

    ``check`` returns :class:`ProbeOutcome`; a plain function is run in a worker
    thread (blocking file/DB/git IO), a coroutine function is awaited directly.
    """

    id: str
    title: str
    check: Callable[[ProbeContext], ProbeOutcome | Any]
    remediation: str
    timeout: float = DEFAULT_PROBE_TIMEOUT


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ChatVerdict:
    """A remembered chat answer, keyed by the model it was measured against."""

    model_id: str
    at: float
    outcome: ProbeOutcome


#: Long-lived on purpose. This is the only probe that spends real tokens and
#: blocks on the network, so re-asking on every ``?refresh=true`` would bill the
#: user for pressing a button. Keyed by model id: switching models invalidates
#: it by construction, and a *failing* verdict is remembered for the shorter
#: :data:`CHAT_FAILURE_TTL_SECONDS` so a recovered provider is noticed quickly.
_CHAT_VERDICT: _ChatVerdict | None = None


def _chat_cache_ttl(outcome: ProbeOutcome) -> float:
    """Successes are trusted longer than failures.

    A provider that just answered is very unlikely to be down a minute later,
    while a provider that just failed may have been a transient blip. Caching
    the failure for the full success window would hide the recovery.
    """
    return CHAT_CACHE_TTL_SECONDS if outcome.status == STATUS_OK else CHAT_FAILURE_TTL_SECONDS


def invalidate_chat_verdict() -> None:
    """Drop the remembered chat answer (model switch, settings change, tests)."""
    global _CHAT_VERDICT
    _CHAT_VERDICT = None


def _remembered_chat(model_id: str) -> ProbeOutcome | None:
    entry = _CHAT_VERDICT
    if entry is None or entry.model_id != model_id:
        return None
    if time.monotonic() - entry.at > _chat_cache_ttl(entry.outcome):
        return None
    return entry.outcome


async def _check_chat_model(ctx: ProbeContext) -> ProbeOutcome:
    """Can the selected model actually answer?

    The answer is cached per model id so repeated refreshes do not spend tokens;
    ``ctx.recheck_model`` skips the cache after an explicit user action.
    """
    manager = ctx.resolve("model_mgr")
    if manager is None:
        return ProbeOutcome(STATUS_UNAVAILABLE, "模型管理器未初始化")

    model_id = str(getattr(manager, "current_model", "") or "").strip()
    if not model_id:
        return ProbeOutcome(STATUS_UNAVAILABLE, "没有选中任何模型")

    global _CHAT_VERDICT
    if not ctx.recheck_model:
        cached = _remembered_chat(model_id)
        if cached is not None:
            return cached

    outcome = await _probe_chat_model(manager, model_id)
    # Only cache verdicts worth trusting for a while; a missing router or an
    # unconfigured manager is cheap to re-check and should not be sticky.
    if outcome.status in (STATUS_OK, STATUS_DEGRADED, STATUS_UNAVAILABLE):
        _CHAT_VERDICT = _ChatVerdict(model_id=model_id, at=time.monotonic(), outcome=outcome)
    return outcome


async def _probe_chat_model(manager: Any, model_id: str) -> ProbeOutcome:
    try:
        availability = manager.model_availability(model_id)
    except Exception as error:  # noqa: BLE001 - a broken catalog is a finding, not a crash
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{model_id}: 无法确定可用性 ({error})")
    if not availability.get("available"):
        reason = availability.get("reason") or "unknown"
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{model_id}: {availability.get('message') or reason}")

    router = getattr(manager, "model_router", None)
    if router is None:
        return ProbeOutcome(STATUS_UNAVAILABLE, "模型路由器未初始化")

    try:
        route = await router.resolve(model_id, "model_test")
        result = await router.complete(
            route,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=2,
        )
    except Exception as error:  # noqa: BLE001 - unreachable provider is the point
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{model_id}: 调用失败 ({type(error).__name__}: {error})")

    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return ProbeOutcome(STATUS_DEGRADED, f"{model_id}: 返回空响应")
    return ProbeOutcome(STATUS_OK, f"{model_id} 已应答「{text[:20]}」")


def _sha1(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _memory_rel_paths(root: Path) -> list[str]:
    """Page paths the index is expected to cover, without touching the library."""
    from atlas.memory.library.store import MemoryStore

    store = MemoryStore(root, vcs=False)
    try:
        return list(store.pages()) + list(store.diary_pages())
    except OSError:
        return []


def _check_memory_index(ctx: ProbeContext) -> ProbeOutcome:
    """Is the memory index readable, FTS-queryable, and in step with the pages?"""
    from atlas.memory.library.health import memory_enabled, memory_root, readonly_connection

    if not memory_enabled():
        return ProbeOutcome(STATUS_UNAVAILABLE, "记忆库已在配置中关闭")

    root = memory_root()
    index_path = Path(root) / ".index.sqlite"
    if not index_path.is_file():
        return ProbeOutcome(STATUS_UNAVAILABLE, f"缺少索引文件 {index_path}")

    try:
        db = readonly_connection(index_path)
    except Exception as error:  # noqa: BLE001 - locked or corrupt is a finding
        return ProbeOutcome(STATUS_UNAVAILABLE, f"索引无法打开 ({error})")

    try:
        try:
            item_rows = db.execute("SELECT count(*) FROM items").fetchone()[0]
            fts_rows = db.execute("SELECT count(*) FROM items_fts").fetchone()[0]
        except Exception as error:  # noqa: BLE001 - missing FTS5 table is the failure
            return ProbeOutcome(STATUS_UNAVAILABLE, f"FTS5 索引不可用 ({error})")
        try:
            indexed = {row["path"]: row["sha"] for row in db.execute("SELECT path, sha FROM files")}
        except Exception as error:  # noqa: BLE001
            return ProbeOutcome(STATUS_UNAVAILABLE, f"索引清单不可读 ({error})")
    finally:
        db.close()

    present = _memory_rel_paths(Path(root))
    if not present:
        return ProbeOutcome(STATUS_DEGRADED, "记忆库目录里没有任何页面")

    missing = [rel for rel in present if rel not in indexed]
    stale = [rel for rel in present if rel in indexed and _sha1(Path(root) / rel) != indexed[rel]]
    dropped = [rel for rel in indexed if rel not in set(present)]

    problems: list[str] = []
    if missing:
        problems.append(f"{len(missing)} 个页面未入库")
    if stale:
        problems.append(f"{len(stale)} 个页面索引过期")
    if dropped:
        problems.append(f"{len(dropped)} 条记录已无对应文件")
    if problems:
        sample = sorted(missing + stale + dropped)[:4]
        return ProbeOutcome(
            STATUS_DEGRADED,
            f"{'、'.join(problems)}（如 {'、'.join(sample)}）；FTS5 可用，{item_rows} 条片段",
        )
    return ProbeOutcome(
        STATUS_OK,
        f"{len(present)} 个页面全部已索引，FTS5 可用（{item_rows} 条片段 / {fts_rows} 行）",
    )


def _check_skill_corpus(ctx: ProbeContext) -> ProbeOutcome:
    """Does every registered skill source parse, or does one bad file drop it?"""
    # Private helpers on purpose: the probe must apply the loader's *exact* rules,
    # and a copy of the validation logic here would drift from them.
    from atlas.skills import _LAYOUT_PARTS, _frontmatter_to_skill_info, _parse_skill_md

    manager = ctx.resolve("skill_mgr")
    sources = dict(getattr(manager, "_sources", {}) or {}) if manager is not None else {}
    if not sources:
        return ProbeOutcome(STATUS_UNAVAILABLE, "技能管理器未注册任何技能来源")

    invalid: list[str] = []
    examined = 0
    valid = 0
    truncated = False

    ordered = sorted(sources.values(), key=lambda item: (item.priority, item.name, str(item.root)))
    for source in ordered:
        root = Path(source.root)
        if not root.is_dir():
            continue
        expected_parts = _LAYOUT_PARTS.get(source.layout, 2)
        try:
            files = sorted(
                (path for path in root.rglob("SKILL.md") if len(path.relative_to(root).parts) == expected_parts),
                key=lambda path: path.relative_to(root).as_posix().casefold(),
            )
        except OSError:
            invalid.append(f"{source.name}: 目录无法读取")
            continue
        for skill_md in files:
            if examined >= SKILL_SCAN_LIMIT:
                truncated = True
                break
            examined += 1
            label = f"{source.name}/{skill_md.relative_to(root).as_posix()}"
            parsed = _parse_skill_md(skill_md)
            if parsed is None:
                invalid.append(f"{label}: frontmatter 无法解析")
                continue
            info = _frontmatter_to_skill_info(
                parsed[0],
                skill_md,
                skills_dir=root if source.layout == "category" else None,
            )
            if info is None:
                invalid.append(f"{label}: 必填字段无效")
                continue
            valid += 1
        if truncated:
            break

    if valid == 0:
        detail = f"扫描 {examined} 个 SKILL.md，没有可加载的技能"
        if invalid:
            detail += f"（首个问题：{invalid[0]}）"
        return ProbeOutcome(STATUS_UNAVAILABLE, detail)
    if invalid:
        preview = "；".join(invalid[:4])
        remainder = f"（另有 {len(invalid) - 4} 个）" if len(invalid) > 4 else ""
        return ProbeOutcome(
            STATUS_DEGRADED,
            f"{valid} 个可加载，{len(invalid)} 个无效 {preview}{remainder}",
        )
    detail = f"{valid} 个技能全部可加载（{len(ordered)} 个来源）"
    if truncated:
        detail += f"，扫描上限 {SKILL_SCAN_LIMIT} 个文件"
    return ProbeOutcome(STATUS_OK, detail)


def _check_mcp_servers(ctx: ProbeContext) -> ProbeOutcome:
    """Is at least one configured MCP server connected with tools?"""
    client = ctx.resolve("mcp_client")
    if client is None:
        return ProbeOutcome(STATUS_UNAVAILABLE, "MCP 客户端未初始化")

    try:
        status = client.get_runtime_status()
    except Exception as error:  # noqa: BLE001
        return ProbeOutcome(STATUS_UNAVAILABLE, f"无法读取 MCP 运行状态 ({error})")

    if not status.get("available"):
        reason = str(status.get("blocking_reason") or "").strip() or "运行时不可用"
        return ProbeOutcome(STATUS_UNAVAILABLE, reason)

    servers = [item for item in (status.get("servers") or []) if isinstance(item, dict)]
    enabled = [item for item in servers if item.get("configured") and item.get("enabled")]
    if not enabled:
        return ProbeOutcome(STATUS_UNAVAILABLE, "没有已配置并启用的 MCP 服务器")

    connected = [item for item in enabled if item.get("connected") or item.get("state") == "connected"]
    if not connected:
        reason = str(status.get("blocking_reason") or "").strip()
        detail = f"0/{len(enabled)} 个服务器已连接"
        return ProbeOutcome(STATUS_DEGRADED, f"{detail}（{reason}）" if reason else detail)

    tools = 0
    for item in connected:
        try:
            tools += int(item.get("tool_count") or 0)
        except (TypeError, ValueError):
            continue
    if tools == 0:
        return ProbeOutcome(
            STATUS_DEGRADED,
            f"{len(connected)}/{len(enabled)} 个服务器已连接，但未发现任何工具",
        )
    return ProbeOutcome(STATUS_OK, f"{len(connected)}/{len(enabled)} 个服务器已连接，共 {tools} 个工具")


def _spec_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _check_computer_use(ctx: ProbeContext) -> ProbeOutcome:
    """Can the desktop (computer-use) runtime serve a tool call?"""
    runtime = ctx.resolve("computer_use")
    if runtime is None:
        return ProbeOutcome(STATUS_UNAVAILABLE, "电脑操作运行时未初始化")

    try:
        tools = list(runtime.get_tools_for_llm() or [])
    except Exception as error:  # noqa: BLE001
        return ProbeOutcome(STATUS_UNAVAILABLE, f"无法列出电脑操作工具 ({error})")
    if not tools:
        return ProbeOutcome(STATUS_UNAVAILABLE, "电脑操作运行时没有注册任何工具")

    drivers = [name for name in ("cua_driver", "pywinauto") if _spec_available(name)]
    if not drivers:
        return ProbeOutcome(
            STATUS_DEGRADED,
            f"{len(tools)} 个工具已注册，但缺少 cua_driver / pywinauto 驱动",
        )
    return ProbeOutcome(STATUS_OK, f"{len(tools)} 个工具可用，驱动 {', '.join(drivers)}")


def _check_browser_runtime(ctx: ProbeContext) -> ProbeOutcome:
    """Is the browser adapter importable and credentialed (without launching one)?"""
    adapter = ctx.resolve("browser_use")
    if adapter is None:
        return ProbeOutcome(STATUS_UNAVAILABLE, "浏览器适配器未初始化")
    if not _spec_available("browser_use"):
        return ProbeOutcome(STATUS_UNAVAILABLE, "未安装 browser_use 依赖")

    from atlas.config import get_config

    try:
        key = str(get_config().gateway_api_key or "").strip()
    except Exception as error:  # noqa: BLE001
        return ProbeOutcome(STATUS_DEGRADED, f"适配器已导入，但配置不可读 ({error})")
    if not key:
        return ProbeOutcome(
            STATUS_DEGRADED,
            "适配器已导入，但缺少模型网关密钥，浏览器任务会在启动时失败",
        )
    last_error = str(getattr(adapter, "last_error", "") or "").strip()
    detail = "适配器就绪（本次未启动浏览器）"
    if last_error:
        detail += f"，上次错误：{last_error}"
    return ProbeOutcome(STATUS_OK, detail)


def _check_scheduler_store(ctx: ProbeContext) -> ProbeOutcome:
    """Is the scheduled-task store readable, and did every task survive loading?"""
    from atlas.scheduler import TaskStatus, _default_schedules_path, _load_tasks_from_toml

    path = Path(_default_schedules_path())
    if not path.is_file():
        return ProbeOutcome(STATUS_OK, f"尚无 {path.name}，没有定时任务")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{path} 无法读取 ({error})")

    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        parsed_document = tomllib.loads(raw)
    except Exception as error:  # noqa: BLE001 - malformed TOML is a finding
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{path.name} 解析失败 ({error})")

    declared = parsed_document.get("tasks") or {}
    if not isinstance(declared, dict):
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{path.name} 的 tasks 段不是映射")

    try:
        tasks = _load_tasks_from_toml(path)
    except Exception as error:  # noqa: BLE001
        return ProbeOutcome(STATUS_UNAVAILABLE, f"定时任务加载失败 ({type(error).__name__}: {error})")

    if len(tasks) != len(declared):
        ignored = sorted(set(declared) - set(tasks))
        preview = "、".join(ignored[:4])
        return ProbeOutcome(
            STATUS_DEGRADED,
            f"{len(declared) - len(tasks)} 个任务无法加载（如 {preview}）",
        )
    if not tasks:
        return ProbeOutcome(STATUS_OK, f"{path.name} 可读，暂无定时任务")
    active = sum(1 for task in tasks.values() if task.status == TaskStatus.ACTIVE)
    detail = f"{path.name} 可读，{len(tasks)} 个任务（{active} 个启用）"
    if active == 0:
        return ProbeOutcome(STATUS_DEGRADED, f"{detail}，全部已暂停")
    return ProbeOutcome(STATUS_OK, detail)


def _check_git_worktree(ctx: ProbeContext) -> ProbeOutcome:
    """Can the git / worktree tooling see the checkout it is supposed to manage?"""
    from atlas.agent.subagent_worktree import _run_git, resolve_repo_root
    from atlas.config import PROJECT_ROOT

    root = resolve_repo_root(str(PROJECT_ROOT))
    if not root:
        return ProbeOutcome(STATUS_UNAVAILABLE, f"{PROJECT_ROOT} 不在 git 仓库中")

    listing = _run_git(["worktree", "list", "--porcelain"], cwd=root)
    if listing.returncode != 0:
        message = (listing.stderr or "").strip().splitlines()
        reason = message[-1] if message else f"退出码 {listing.returncode}"
        return ProbeOutcome(STATUS_DEGRADED, f"{root} 可读，但 worktree 列表失败（{reason}）")

    worktrees = sum(1 for line in (listing.stdout or "").splitlines() if line.startswith("worktree "))
    head = _run_git(["rev-parse", "--short", "HEAD"], cwd=root)
    commit = (head.stdout or "").strip() if head.returncode == 0 else "无提交"
    return ProbeOutcome(STATUS_OK, f"{Path(root).name}@{commit} 可读，{worktrees} 个工作树")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROBES: tuple[Probe, ...] = (
    Probe(
        id="chat_model",
        title="对话模型可应答",
        check=_check_chat_model,
        remediation="在 设置 → 模型 中确认已选模型及其密钥，然后重试连接。",
        timeout=CHAT_PROBE_TIMEOUT,
    ),
    Probe(
        id="memory_index",
        title="记忆索引可搜索",
        check=_check_memory_index,
        remediation="打开 记忆库 页面触发一次同步（检索索引会重建缺失或过期的条目）。",
    ),
    Probe(
        id="skill_corpus",
        title="技能语料可加载",
        check=_check_skill_corpus,
        remediation="按提示修好对应 SKILL.md 的 frontmatter（name 需为小写连字符、description 必填）。",
    ),
    Probe(
        id="mcp_servers",
        title="MCP 服务器已连接",
        check=_check_mcp_servers,
        remediation="在 设置 → MCP 中检查该服务器的命令/传输方式，并查看其启动日志。",
    ),
    Probe(
        id="computer_use",
        title="电脑操作运行时可用",
        check=_check_computer_use,
        remediation="安装 cua_driver 或 pywinauto，并确认桌面会话未被远程/无头模式取代。",
    ),
    Probe(
        id="browser_runtime",
        title="浏览器运行时可用",
        check=_check_browser_runtime,
        remediation="安装 browser_use 并在 设置 → 模型 配置模型网关密钥。",
    ),
    Probe(
        id="scheduler_store",
        title="定时任务存储可读",
        check=_check_scheduler_store,
        remediation="检查 data/schedules.toml 的 TOML 语法与任务字段（trigger_type/status 必须合法）。",
    ),
    Probe(
        id="git_worktree",
        title="Git / 工作树工具可用",
        check=_check_git_worktree,
        remediation="确认 git 在 PATH 中，且 D:\\Atlas 是完整克隆（.git 未损坏）。",
    ),
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def _run_probe(probe: Probe, ctx: ProbeContext) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if inspect.iscoroutinefunction(probe.check):
            outcome = await asyncio.wait_for(probe.check(ctx), probe.timeout)
        else:
            outcome = await asyncio.wait_for(asyncio.to_thread(probe.check, ctx), probe.timeout)
        status, detail = outcome.status, outcome.detail
    except (asyncio.TimeoutError, TimeoutError):
        status, detail = STATUS_DEGRADED, f"检查超时（>{probe.timeout:g}s）"
    except Exception as error:  # noqa: BLE001 - one broken probe must not blank the report
        log.warning("capabilities.probe_error", probe=probe.id, error=str(error))
        status, detail = STATUS_UNAVAILABLE, f"检查失败 ({type(error).__name__}: {error})"
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "id": probe.id,
        "title": probe.title,
        "status": status,
        "detail": detail,
        "latency_ms": latency_ms,
    }


def _verdict(entries: list[dict[str, Any]]) -> str:
    statuses = {entry["status"] for entry in entries}
    if STATUS_UNAVAILABLE in statuses:
        return STATUS_UNAVAILABLE
    if STATUS_DEGRADED in statuses:
        return STATUS_DEGRADED
    return STATUS_OK


def _build_report(entries: list[dict[str, Any]], duration_ms: int) -> dict[str, Any]:
    failing = [
        {
            "id": entry["id"],
            "title": entry["title"],
            "status": entry["status"],
            "detail": entry["detail"],
            "remediation": next((probe.remediation for probe in PROBES if probe.id == entry["id"]), ""),
        }
        for entry in entries
        if entry["status"] != STATUS_OK
    ]
    counts = {status: sum(1 for entry in entries if entry["status"] == status) for status in
              (STATUS_OK, STATUS_DEGRADED, STATUS_UNAVAILABLE)}
    return {
        "status": _verdict(entries),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_ms": duration_ms,
        "summary": {"total": len(entries), **counts},
        "probes": entries,
        "failing": failing,
    }


@dataclass(slots=True)
class _CachedReport:
    #: Strong reference on purpose: it keeps ``id(services)`` from being reused by
    #: another AppServices while this entry is cached.
    services: Any
    computed_at: float
    report: dict[str, Any]


_CACHE: dict[int, _CachedReport] = {}
_REFRESH_LOCK: asyncio.Lock | None = None


def _refresh_lock() -> asyncio.Lock:
    global _REFRESH_LOCK
    if _REFRESH_LOCK is None:
        _REFRESH_LOCK = asyncio.Lock()
    return _REFRESH_LOCK


def _fresh_entry(services: Any) -> _CachedReport | None:
    entry = _CACHE.get(id(services))
    if entry is None or entry.services is not services:
        return None
    if time.monotonic() - entry.computed_at > REPORT_TTL_SECONDS:
        _CACHE.pop(id(services), None)
        return None
    return entry


async def _run_all(services: Any, *, recheck_model: bool) -> dict[str, Any]:
    ctx = ProbeContext(services=services, recheck_model=recheck_model)
    started = time.perf_counter()
    entries = list(await asyncio.gather(*(_run_probe(probe, ctx) for probe in PROBES)))
    report = _build_report(entries, int((time.perf_counter() - started) * 1000))
    log.info(
        "capabilities.report",
        status=report["status"],
        duration_ms=report["duration_ms"],
        failing=[entry["id"] for entry in report["failing"]],
    )
    return report


async def capabilities_report(
    services: Any, *, refresh: bool = False, recheck_model: bool = False
) -> dict[str, Any]:
    """Full capability report, served from a short-lived cache unless refreshed.

    ``refresh`` re-runs the cheap local probes; it deliberately does **not** retest
    the chat model, because that spends tokens and a user pressing refresh should
    not be billed for it. ``recheck_model`` is the explicit "test my model again"
    action (a settings save or a visible button) and is the only way to retest.
    The chat verdict also expires on its own after :data:`CHAT_CACHE_TTL_SECONDS`.
    """
    async with _refresh_lock():
        if not refresh:
            cached = _fresh_entry(services)
            if cached is not None:
                return {**cached.report, "cached": True}
        if recheck_model:
            invalidate_chat_verdict()
        report = await _run_all(services, recheck_model=recheck_model)
        _CACHE[id(services)] = _CachedReport(services=services, computed_at=time.monotonic(), report=report)
        _prune_cache()
        return {**report, "cached": False}


def _prune_cache() -> None:
    cutoff = time.monotonic() - REPORT_TTL_SECONDS
    for key in [key for key, entry in _CACHE.items() if entry.computed_at <= cutoff]:
        _CACHE.pop(key, None)


def cached_capability_summary(services: Any) -> dict[str, Any] | None:
    """At-a-glance verdict for an already-computed report, or ``None``.

    Deliberately synchronous and allocation-light: ``/api/health`` calls this on
    every poll and must not run a probe, open a database, or wait on a lock.
    """
    entry = _fresh_entry(services)
    if entry is None:
        return None
    report = entry.report
    return {
        "status": report["status"],
        "counts": report["summary"],
        "failing": [
            {"id": item["id"], "title": item["title"], "status": item["status"], "remediation": item["remediation"]}
            for item in report["failing"]
        ],
        "checked_at": report["checked_at"],
        "age_seconds": int(time.monotonic() - entry.computed_at),
    }


def reset_cache() -> None:
    """Drop every cached report (tests, and after a config change)."""
    _CACHE.clear()
    invalidate_chat_verdict()
