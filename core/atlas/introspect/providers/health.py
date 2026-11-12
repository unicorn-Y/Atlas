"""Introspection provider: live health and startup state.

Atlas starts a lot of things asynchronously — DBOS, MCP clients, skills, plugins,
engine registrations, channels, automation, the scheduler, Telegram, extensions,
and session migration. Each can fail independently, and the failure is recorded in
``StartupComponents`` rather than raised, because a dead Telegram bot must not stop
the desktop app from opening.

That design is right and it makes health invisible: the app is "up" while half its
components are ``failed``. This provider surfaces those states, plus the capability
probes that answer "can this actually answer a message right now".

The capability report is cached for 60 seconds inside
:mod:`atlas.capabilities.probes`; passing ``refresh=true`` forces a re-run, which
spends a real model request on the ``chat_model`` probe. That is why it is opt-in
and off by default.
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _server() -> Any:
    """Late-bound ``atlas.server``: it is the module whose globals hold the
    startup tracker, and late binding keeps the import out of module load."""
    import atlas.server

    return atlas.server


def _startup(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """The startup tracker, from services first and the server module second.

    Same fallback ``health_router`` uses: only ``runtime_mgr`` is pre-filled in
    ``AppServices``, and the rest are attached during lifespan. Reading both means
    this provider answers correctly whether or not lifespan has finished yet.
    """
    services = ctx.services
    tracker = getattr(services, "startup", None) if services is not None else None
    if tracker is None:
        tracker = getattr(_server(), "startup", None)
    if tracker is None:
        return {"available": False, "note": "启动追踪器还没挂上（lifespan 未完成或未启用）。"}

    snapshot = tracker.snapshot() if hasattr(tracker, "snapshot") else {}
    errors = tracker.error_snapshot() if hasattr(tracker, "error_snapshot") else {}
    try:
        core_ready = bool(tracker.core_ready)
    except Exception:  # noqa: BLE001 - core_ready is a threading.Event in some builds
        core_ready = bool(getattr(tracker, "core_ready", False))
    failed = sorted(name for name, state in snapshot.items() if state == "failed")
    pending = sorted(name for name, state in snapshot.items() if state == "starting")
    return {
        "available": True,
        "core_ready": core_ready,
        "components": snapshot,
        "failed": failed,
        "pending": pending,
        "errors": errors,
    }


async def _capabilities(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.capabilities.probes import capabilities_report

    services = ctx.services
    refresh = args.get("refresh") is True
    recheck_model = args.get("recheck_model") is True
    report = await capabilities_report(
        services, refresh=refresh, recheck_model=recheck_model
    )
    return {"refreshed": refresh, **report}


def _capability_catalog(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    from atlas.capabilities.probes import DEFAULT_PROBE_TIMEOUT, PROBES

    return {
        "count": len(PROBES),
        "default_timeout_seconds": DEFAULT_PROBE_TIMEOUT,
        "probes": [
            {
                "id": probe.id,
                "title": probe.title,
                "timeout_seconds": probe.timeout,
                "remediation": probe.remediation,
            }
            for probe in PROBES
        ],
    }


def _runs(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """In-flight runs, by status. Read from the manager's in-memory map.

    Deliberately not a SQL query: the interesting question is what this process is
    doing now, and the persisted table holds historical rows that would drown it.
    """
    services = ctx.services
    manager = getattr(services, "runtime_mgr", None) if services is not None else None
    if manager is None:
        return {"available": False, "note": "RuntimeManager 未挂载。"}

    runs = list(getattr(manager, "runs", {}).values())
    counts: dict[str, int] = {}
    for run in runs:
        status = getattr(run, "status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    limit = int(args.get("limit") or 50)
    return {
        "available": True,
        "connections": len(getattr(manager, "connections", {}) or {}),
        "runs": len(runs),
        "by_status": counts,
        "detail": [
            {
                "run_id": run.run_id,
                "conversation_id": run.conversation_id,
                "status": run.status,
                "model": run.model,
                "workspace": getattr(run, "workspace", None),
                "started_at": getattr(run, "started_at", None),
                "sequence": getattr(run, "sequence", 0),
                "waiting_for": getattr(run, "waiting_for", None),
            }
            for run in runs[:limit]
        ],
    }


def _ports(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Who owns the backend port, and does it look like us?

    Two Atlas backends once shared port 8765 (PIDs 40820 and 45104). Every symptom
    of that — settings landing on the wrong process, a window attached to an older
    backend, requests answered by a build you did not launch — presented as a
    *client* bug. This method exists so the question can be asked of the running
    backend instead of guessed from the outside: the answer names the PID.
    """
    from atlas.config import get_config
    from atlas.port_guard import describe, probe

    cfg = get_config()
    pairs: list[tuple[str, int]] = [(cfg.server_host, int(cfg.server_port))]
    for host, port in args.get("ports") or []:
        try:
            pairs.append((str(host), int(port)))
        except (TypeError, ValueError):
            continue
    results = []
    for host, port in pairs:
        found = probe(host, port)
        results.append({**dict(found), "sentence": describe(found)})
    return {
        "configured_host": cfg.server_host,
        "configured_port": int(cfg.server_port),
        "probes": results,
        # The visible flag matters: a non-loopback bind is a real exposure, and
        # security_audit already calls it out. Repeating it here puts the fact next
        # to the port number that makes it true.
        "non_loopback": cfg.server_host not in {"127.0.0.1", "localhost", "::1"},
    }


def _logs(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Which log files are large enough to be compressed on the next run."""
    from atlas.config import PROJECT_ROOT

    directory = PROJECT_ROOT / "data" / "logs"
    threshold = args.get("max_mb") or 32
    limit = int(threshold) * 1024 * 1024

    files: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    if directory.is_dir():
        for item in sorted(directory.glob("*.log")):
            try:
                size = item.stat().st_size
            except OSError:
                continue
            files.append(
                {
                    "name": item.name,
                    "bytes": size,
                    "over_limit": size > limit,
                }
            )
        for item in sorted(directory.glob("*.zst")):
            try:
                archives.append({"name": item.name, "bytes": item.stat().st_size})
            except OSError:
                continue

    return {
        "directory": str(directory),
        "max_mb": limit // (1024 * 1024),
        "files": files,
        "total_bytes": sum(f["bytes"] for f in files),
        "over_limit": [f["name"] for f in files if f["over_limit"]],
        "archives": archives,
        "archive_bytes": sum(a["bytes"] for a in archives),
    }


def _telemetry(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Whether OTLP export is live, and what would enable it."""
    from atlas import telemetry

    state = telemetry.status()
    state["hint"] = (
        "已启用"
        if state["enabled"]
        else "未启用：设置 OTEL_EXPORTER_OTLP_TRACES_ENDPOINT 或 "
        "OTEL_EXPORTER_OTLP_ENDPOINT 后重启后端"
    )
    return state


def _office(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Whether PDF export, recalculation, and rendering can actually run here.

    Three capabilities are commonly assumed to exist because the libraries that
    create the files do: ``python-docx`` writes a .docx, so the next question —
    "turn it into a PDF" — sounds like it should follow. It does not; that needs an
    office suite on the PATH. Asking the backend is cheaper than discovering it
    through a failed export, and the hint says which package would fix it.
    """
    from atlas import libreoffice

    state = libreoffice.status()
    state["sentence"] = libreoffice.describe()
    state["exportable"] = sorted(libreoffice._EXPORTABLE)
    state["renderable"] = sorted(libreoffice._RENDERABLE)
    return state


def _tts(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Local text-to-speech: installed or not, and what downloading would cost.

    Cloud TTS is billed per character and needs the network; a local Kokoro model
    is a one-time download and then free. This method reports which is ready so the
    agent can pick a provider instead of failing on the cloud path with no key.
    """
    from atlas.tts_local import get_local_tts

    manager = get_local_tts()
    state = manager.status()
    # ``ready`` is true when *any* offline engine exists, which on Windows is
    # usually SAPI before the Kokoro model is ever downloaded. Say which one,
    # because the two differ in quality and in what ``speaker``/``speed`` mean.
    engines = state.get("engines") or []
    if state.get("model"):
        state["engine"] = "sherpa-onnx"
        state["sentence"] = (
            f"本地语音可用（{state['model']}，含 {state.get('speakers', 0)} 个音色）。"
        )
    elif engines:
        state["engine"] = engines[0]
        state["sentence"] = (
            f"本地语音可用（{engines[0]} 系统语音）。想要更好的音质可下载 "
            f"{state.get('model_url') or 'Kokoro 模型'}。"
        )
    else:
        state["engine"] = None
        state["sentence"] = (
            "本地语音不可用：既没有系统语音，也没有 Kokoro 模型。"
            "调用 tts_download 工具拉取模型。"
        )
    return state


def _spill(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """How much spilled tool output is sitting on disk, and what pruning would free.

    Oversized tool results are written to a content-addressed file so the model
    can be handed a path instead of 190 MB of text. Nothing ever enumerated those
    files afterwards, so the only way to learn the cost was to go look on disk.
    This defaults to ``dry_run``: reporting the cost is safe, deleting evidence a
    live session might still reference is not.
    """
    from atlas import spill_store

    state = spill_store.inventory()
    state["sentence"] = spill_store.describe()
    if bool(args.get("dry_run", True)):
        plan = spill_store.prune(
            keep_days=int(args.get("keep_days", spill_store.DEFAULT_KEEP_DAYS)),
            dry_run=True,
        )
        state["prunable_count"] = plan["removed_count"]
        state["prunable_bytes"] = plan["freed_bytes"]
    return state


def _projections(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Hit rate of the derived-read cache behind the session list.

    ``list_sessions_rich`` projects every compression chain and reads ``unread``
    per row, which costs ~180 ms on the live database; the sidebar pays it on
    every refresh. This reports whether the cache is actually earning that back,
    because a cache that is always cold looks identical to a working one from the
    outside.
    """
    from atlas.engine.state.projections import _SHARED, shared_for

    from atlas.config import DATA_ROOT

    path = DATA_ROOT / "engine" / "state.db"
    caches = list(_SHARED.values())
    stats = [cache.stats() for cache in caches]
    hits = sum(item["hits"] for item in stats)
    misses = sum(item["misses"] for item in stats)
    entries = sum(item["entries"] for item in stats)
    hit_rate = (hits / (hits + misses)) if (hits + misses) else None
    return {
        "db_path": str(path),
        "caches": len(caches),
        "entries": entries,
        "capacity": shared_for(path).stats()["capacity"],
        "hits": hits,
        "misses": misses,
        "hit_rate": hit_rate,
        "invalidations": sum(item["invalidations"] for item in stats),
        "sentence": (
            f"投影缓存命中 {hits} 次、未命中 {misses} 次"
            + (f"（命中率 {hit_rate:.0%}）" if hit_rate is not None else "（还没有读取）")
            + f"，当前缓存 {entries} 条。"
        ),
    }


def _run_logs(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """How many session archives exist, and how much rotation would reclaim.

    ``maintain_logs`` only ever globbed ``*.log``, so ``runs/<date>/<run_id>.jsonl``
    was never rotated: one uncompressed file per run, forever. This reports that
    backlog without touching it — archiving is a separate, explicit call because
    compression is irreversible from the reader's point of view.
    """
    from datetime import datetime, timezone
    from pathlib import Path

    from atlas.logs import LOG_DIR

    runs = Path(LOG_DIR) / "runs"
    hours = int(args.get("older_than_hours", 48))
    cutoff = datetime.now(timezone.utc).timestamp() - max(0, hours) * 3600

    plain: list[Path] = []
    archives: list[Path] = []
    if runs.is_dir():
        plain = sorted(runs.glob("*/*.jsonl"))
        archives = sorted(runs.glob("*/*.jsonl.zst"))

    total = sum(p.stat().st_size for p in plain)
    due = [p for p in plain if p.stat().st_mtime < cutoff]
    due_bytes = sum(p.stat().st_size for p in due)
    archived_bytes = sum(p.stat().st_size for p in archives)
    return {
        "directory": str(runs),
        "jsonl_files": len(plain),
        "bytes": total,
        "mb": round(total / 1024 / 1024, 2),
        "archived_files": len(archives),
        "archived_bytes": archived_bytes,
        "older_than_hours": hours,
        "rotatable_files": len(due),
        "rotatable_bytes": due_bytes,
        "rotatable_mb": round(due_bytes / 1024 / 1024, 2),
        "sentence": (
            f"会话日志 {len(plain)} 个、{total / 1024 / 1024:.1f} MB，"
            f"其中 {len(due)} 个超过 {hours} 小时可以压缩；"
            f"已归档 {len(archives)} 个（{archived_bytes / 1024 / 1024:.1f} MB）。"
        ),
    }


PROVIDER = Provider(
    id="health",
    title="健康",
    summary="启动组件是否就绪、能力探针结论、以及当前进程里在跑什么。",
    methods=(
        Method(
            name="startup",
            summary="启动组件的状态快照与失败原因。",
            input_schema=object_schema(),
            run=_startup,
        ),
        Method(
            name="capabilities",
            summary="跑（或读缓存）能力探针，回答“现在能不能正常应答”。",
            input_schema=object_schema(
                {
                    "refresh": {"type": "boolean", "description": "忽略缓存重跑，默认 false。"},
                    "recheck_model": {
                        "type": "boolean",
                        "description": "连对话模型也重新探（会消耗一次真实请求）。",
                    },
                }
            ),
            run=_capabilities,
        ),
        Method(
            name="capability_catalog",
            summary="探针清单与各自的补救建议。",
            input_schema=object_schema(),
            run=_capability_catalog,
        ),
        Method(
            name="runs",
            summary="当前进程内的连接数与运行中的任务。",
            input_schema=object_schema(
                {"limit": {"type": "integer", "description": "最多返回多少个任务，默认 50。"}}
            ),
            run=_runs,
        ),
        Method(
            name="ports",
            summary="后端端口被谁占着（PID）、监听是否正常、以及是否绑在非回环地址。",
            input_schema=object_schema(
                {
                    "ports": {
                        "type": "array",
                        "description": "额外要探的 [host, port] 对，可选；默认只探配置里的那一个。",
                        "items": {"type": "array", "items": {"type": "string"}},
                    }
                }
            ),
            run=_ports,
        ),
        Method(
            name="logs",
            summary="日志目录现状：多大的文件会在下次维护时被压缩轮转。",
            input_schema=object_schema(
                {
                    "max_mb": {
                        "type": "integer",
                        "description": "轮转阈值（MB），默认 32，与 CLI 保持一致。",
                    }
                }
            ),
            run=_logs,
        ),
        Method(
            name="telemetry",
            summary="OTLP 遥测是否已配置：没配端点就完全惰性，不建 provider 不起线程。",
            input_schema=object_schema(),
            run=_telemetry,
        ),
        Method(
            name="office",
            summary="PDF 导出、公式重算、文档渲染这三件事在这台机器上能不能做。",
            input_schema=object_schema(),
            run=_office,
        ),
        Method(
            name="tts",
            summary="本地语音合成是否可用，以及走云端之外的离线选项。",
            input_schema=object_schema(),
            run=_tts,
        ),
        Method(
            name="spill",
            summary="溢出的工具输出在磁盘上占了多少、按保留策略能清掉多少。",
            input_schema=object_schema(
                {
                    "dry_run": {
                        "type": "boolean",
                        "description": "只算不删，默认 true；设为 false 才会真的删文件。",
                    },
                    "keep_days": {"type": "integer", "description": "保留天数，默认 14。"},
                }
            ),
            run=_spill,
        ),
        Method(
            name="run_logs",
            summary="会话日志（runs/*.jsonl）的积压与已归档量：压缩轮转一直没有覆盖到它们。",
            input_schema=object_schema(
                {
                    "older_than_hours": {
                        "type": "integer",
                        "description": "超过这个小时数才算“可压缩”，默认 48。",
                    }
                }
            ),
            run=_run_logs,
        ),
        Method(
            name="projections",
            summary="会话列表背后的投影缓存：命中率和失效次数。",
            input_schema=object_schema(),
            run=_projections,
        ),
    ),
)
