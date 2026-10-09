"""Real-model F2-A observer smoke against isolated Atlas and MemoryOS roots.

Runs the ten question-heavy Chinese conversations three times each through the
production ModelRouter and posts each valid derived batch to a private MemoryOS
test instance. No model/provider stub is used in this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sqlite3
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CORE_ROOT))

MODEL_ID = "gemini-3.8-flash"
PROXY_BASE_URL = "http://127.0.0.1:8045/v1"
PRODUCTION_SETTINGS = REPO_ROOT / "data" / "user-settings.json"
MEMORYOS_ROOT = Path(r"D:\MemoryOS")
MEMORYOS_SERVICE_PYTHON = MEMORYOS_ROOT / "service" / ".venv" / "Scripts" / "python.exe"
PROXY_TOKEN_DB = Path(os.environ.get("USERPROFILE", r"C:\Users\25011")) / ".antigravity_tools" / "token_stats.db"


CONVERSATIONS: list[dict[str, Any]] = [
    {
        "id": "daughter_age_school",
        "expected_facts": ["用户有一个6岁的女儿"],
        "turns": [
            "我女儿今年6岁。她明年通常该读几年级？上海小学一般几岁入学？要不要先学拼音？如果生日在十月会影响入学吗？",
            "如果我想帮她准备入学，先培养阅读习惯有用吗？每天读多久比较合适？需要报数学班吗？你会怎么安排？",
        ],
    },
    {
        "id": "hangzhou_home",
        "expected_facts": ["用户住在杭州"],
        "turns": [
            "我住在杭州。下周杭州会下雨吗？去西湖几点人少？带伞还是穿雨衣？哪条地铁线最方便？",
            "我周末想找个安静的咖啡馆，滨江有什么推荐？哪家有插座？通常几点关门？开车停车方便吗？",
        ],
    },
    {
        "id": "tea_preference",
        "expected_facts": ["用户喜欢无糖绿茶"],
        "turns": [
            "我平时喜欢喝无糖绿茶。晚上喝茶会影响睡眠吗？乌龙茶和绿茶哪个咖啡因更多？有什么低咖啡因饮品？下午几点后不建议喝？",
            "如果我想买一只保温杯，选多大容量合适？玻璃内胆会不会容易碎？泡茶用多少度的水？哪些品牌比较耐用？",
        ],
    },
    {
        "id": "meeting_time_change",
        "expected_facts": ["周报评审会从周二改到周四下午两点"],
        "turns": [
            "周报评审会原定周二上午十点，现在改到周四下午两点。周四下雨会影响到场吗？要不要通知全组？会议室A有投影吗？提前几分钟到好？",
            "如果有人临时缺席，改成线上合适吗？会议要留多少时间？需要提前发材料吗？周四午饭后大家通常有空吗？",
        ],
    },
    {
        "id": "atlas_work_role",
        "expected_facts": ["用户在Atlas项目负责模型调用验收"],
        "turns": [
            "我在Atlas项目负责模型调用验收。ModelRouter的路由规则在哪里看？如果换成OpenAI，缓存还能用吗？超时一般设多少？哪些日志最有用？",
            "验收表应该包含哪些列？需要覆盖重试吗？要测试并发吗？一次跑多少用例比较合理？",
        ],
    },
    {
        "id": "running_habit",
        "expected_facts": ["用户每周三晚上跑步五公里"],
        "turns": [
            "我每周三晚上固定跑步五公里。跑前热身多久比较合适？雨天要改在室内吗？晚上跑步会影响睡眠吗？什么配速适合初学者？",
            "如果我想准备十公里比赛，训练计划怎么排？每周跑几次好？跑鞋多久该换？跑后应该做哪些拉伸？",
        ],
    },
    {
        "id": "colleague_chenlin",
        "expected_facts": ["用户的同事陈琳来自成都并负责后端数据平台"],
        "turns": [
            "我的同事陈琳来自成都，她在后端组负责数据平台。成都最近气温怎么样？她喜欢什么编程语言？你觉得她适合做组长吗？春节去成都哪里好玩？",
            "如果团队要做季度复盘，应该看哪些指标？文档用表格还是幻灯片？会前要不要匿名收集意见？怎样控制会议时间？",
        ],
    },
    {
        "id": "python_react_preference",
        "expected_facts": ["用户喜欢用Python写数据脚本，前端项目使用React"],
        "turns": [
            "数据处理脚本我喜欢用Python，前端项目我用React。Python最新版本有哪些变化？现在升级有兼容问题吗？React用哪种状态管理更合适？我需要学Svelte吗？",
            "如果团队统一格式化工具，选哪一个好？代码评审要检查哪些点？monorepo适合我们吗？你会怎么拆目录？",
        ],
    },
    {
        "id": "budget_report_commitment",
        "expected_facts": ["用户答应在本月28日前提交预算报告"],
        "turns": [
            "我答应在本月28日前提交预算报告。预算应该按季度还是年度拆分？需要做敏感性分析吗？谁会评审？周末加班赶得上吗？",
            "报告需要附哪些凭证？用人民币还是也列美元？要不要放现金流预测？提交前找谁校对比较好？",
        ],
    },
    {
        "id": "hypothetical_travel_questions",
        "expected_facts": [],
        "turns": [
            "如果我以后搬去东京住，三月通常冷吗？需要准备什么衣服？工作签证容易申请吗？我需要带哪些证件？",
            "假如我去台北旅行，哪里夜市最值得逛？住在哪个区域方便？要不要租车？一天安排几个景点合适？",
        ],
    },
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 2)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _safe_roots(run_root: Path) -> dict[str, Path]:
    atlas_root = run_root / "atlas_data"
    memory_root = run_root / "memoryos_data"
    memory_db = memory_root / "db" / "memoryos.sqlite3"
    hermes_root = run_root / "hermes_home"
    for path in (atlas_root, memory_root, memory_db.parent, hermes_root):
        path.mkdir(parents=True, exist_ok=True)

    roots = {
        "ATLAS_DATA_DIR": atlas_root.resolve(),
        "MEMORYOS_DATA_ROOT": memory_root.resolve(),
        "MEMORYOS_DB_PATH": memory_db.resolve(),
        "HERMES_HOME": hermes_root.resolve(),
    }
    protected = [
        (REPO_ROOT / "data").resolve(),
        Path(r"D:\MemoryOSData").resolve(),
        Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local") + r"\hermes").resolve(),
    ]
    for name, path in roots.items():
        if any(path == target or target in path.parents for target in protected):
            raise RuntimeError(f"refusing non-isolated {name} path")
        os.environ[name] = str(path)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["ATLAS_UNIFIED_EVENT_CLASS"] = "TEST"
    os.environ["MEMORYOS_FORMATION_WORKER"] = "0"
    return roots


def _usage_fields(usage: Any) -> dict[str, int | None]:
    def read(*keys: str) -> int | None:
        for key in keys:
            value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return None

    return {
        "input_tokens": read("input_tokens", "prompt_tokens"),
        "output_tokens": read("output_tokens", "completion_tokens"),
    }


def _response_model(raw: Any) -> str | None:
    value = raw.get("model") if isinstance(raw, dict) else getattr(raw, "model", None)
    return str(value) if value else None


def _stored_observation_text(record: Any) -> str:
    """Read the full RAW_EVIDENCE observation text returned by GET /records."""
    content = record.get("content") if isinstance(record, dict) else None
    observation = content.get("text") if isinstance(content, dict) else None
    text = observation.get("text") if isinstance(observation, dict) else None
    if not isinstance(text, str) or not text:
        raise RuntimeError("MemoryOS GET record did not expose stored observation text")
    return text


def _matching_evidence_snippet(evidence: Any, source_event_id: str) -> dict[str, Any]:
    """Select the provenance snippet without parsing its intentionally truncated text."""
    snippets = evidence.get("snippets", []) if isinstance(evidence, dict) else []
    matches = [
        snippet for snippet in snippets
        if isinstance(snippet, dict)
        and str(snippet.get("source_event_id") or "") == source_event_id
    ]
    if len(matches) != 1:
        raise RuntimeError("MemoryOS evidence GET did not return the submitted derived observation")
    if not isinstance(matches[0].get("text"), str):
        raise RuntimeError("MemoryOS evidence GET did not expose an evidence snippet")
    return matches[0]


class _UsageTrackingRouter:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    async def complete_for(self, model_id: str, purpose: str, messages: list[dict[str, Any]], **kwargs: Any):
        started = time.perf_counter()
        result = await self.inner.complete_for(model_id, purpose, messages, **kwargs)
        usage = _usage_fields(getattr(result, "usage", None))
        self.calls.append({
            "requested_model": model_id,
            "purpose": purpose,
            "response_model": _response_model(getattr(result, "raw", None)),
            **usage,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        return result


def _case_sources(case: dict[str, Any], trial: int, run_id: str) -> list[dict[str, Any]]:
    from atlas.memory.capture import build_observation

    sources: list[dict[str, Any]] = []
    messages: list[tuple[str, str]] = []
    for user_text in case["turns"]:
        messages.append(("USER", user_text))
        messages.append(("ATLAS", "好的，我可以帮你一起梳理。"))

    for index, (role, text) in enumerate(messages, start=1):
        source_kind = "ATLAS_USER_MESSAGE" if role == "USER" else "ATLAS_ASSISTANT_MESSAGE"
        epistemic = "USER_ASSERTED" if role == "USER" else "INFERRED"
        object_id = f"f2a-{run_id}-t{trial}-{case['id']}-m{index}"
        source = build_observation(
            source_kind=source_kind,
            source_object_id=object_id,
            source_revision="1",
            content={"text": text},
            speaker_role=role,
            epistemic_kind=epistemic,
            occurred_at=(datetime.now(UTC) - timedelta(minutes=index)).isoformat(timespec="seconds"),
            source_timezone="UTC",
            locator={"kind": "MESSAGE", "value": f"{run_id}/{trial}/{case['id']}/{index}"},
        )
        source["text"] = text
        sources.append(source)
    return sources


def _receipt_sources(ack: Any) -> list[str]:
    receipts = ack.get("receipts") if isinstance(ack, dict) else None
    return [
        str(row.get("source_event_id") or "")
        for row in receipts or [] if isinstance(row, dict)
    ]


def _gateway_usage_since(started_epoch: float, ended_epoch: float) -> dict[str, Any]:
    if not PROXY_TOKEN_DB.is_file():
        return {"available": False, "reason": "proxy token statistics database unavailable"}
    try:
        uri = f"file:{PROXY_TOKEN_DB.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as conn:
            rows = conn.execute(
                "SELECT timestamp,model,input_tokens,output_tokens,cached_tokens,total_tokens "
                "FROM token_usage WHERE timestamp BETWEEN ? AND ? AND model LIKE ?",
                (started_epoch - 2, ended_epoch + 2, "gemini-3.8-flash%"),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": type(exc).__name__}
    by_model: dict[str, dict[str, int]] = {}
    for _timestamp, model, input_tokens, output_tokens, cached_tokens, total_tokens in rows:
        item = by_model.setdefault(str(model), {"requests": 0, "input_tokens": 0,
                                                  "output_tokens": 0, "cached_tokens": 0,
                                                  "total_tokens": 0})
        item["requests"] += 1
        item["input_tokens"] += int(input_tokens or 0)
        item["output_tokens"] += int(output_tokens or 0)
        item["cached_tokens"] += int(cached_tokens or 0)
        item["total_tokens"] += int(total_tokens or 0)
    return {"available": True, "requests": len(rows), "by_model": by_model}


async def _run_smoke(run_root: Path, output_path: Path) -> dict[str, Any]:
    roots = _safe_roots(run_root)
    run_id = uuid.uuid4().hex[:8]
    subject_id = f"atlas-f2a-{run_id}"
    from scripts.memory_v1.real_memory import RealMemoryService
    from scripts.memory_v1 import gemini_runtime

    atlas_config_path = REPO_ROOT / "config" / "atlas.toml"
    if not atlas_config_path.is_file() or not PRODUCTION_SETTINGS.is_file():
        raise FileNotFoundError("Atlas config or backed-up production model settings unavailable")

    safe_settings = gemini_runtime.read_isolated_model_settings(PRODUCTION_SETTINGS)
    settings_path = gemini_runtime.write_isolated_user_settings(
        roots["ATLAS_DATA_DIR"], safe_settings,
    )

    import tomllib
    from atlas.config import AtlasConfig
    from atlas.memory.observer import MemoryObserver
    from atlas.memory.unified_facade import UnifiedMemoryFacade

    raw_config = tomllib.loads(atlas_config_path.read_text(encoding="utf-8"))
    # The real production TOML has a gateway fallback, but this isolated run
    # must prove it resolves through the registered custom Gemini provider.
    # Clear only the in-memory fallback fields; never rewrite production config.
    gemini_runtime.clear_gateway_fallback_config(raw_config)
    raw_config.setdefault("memory", {}).setdefault("unified", {}).update({
        "enabled": True,
        "subject_binding": subject_id,
        "event_class": "TEST",
    })
    raw_config["memory"].setdefault("v1", {})["observer_daily_token_budget"] = 1_000_000
    model_config = AtlasConfig(raw_config)
    manager, safe_route_evidence = gemini_runtime.bootstrap_model_manager(
        model_config, safe_settings, settings_path,
    )
    router = manager.model_router
    tracked_router = _UsageTrackingRouter(router)
    route = await router.resolve(MODEL_ID, "memory_observe")
    route_evidence = {
        **safe_route_evidence,
        "router_purpose": route.purpose,
        "resolved_provider": route.provider,
        "api_mode": route.api_mode,
        "resolved_model": route.model,
        "wire_model": route.wire_model,
        "provider_endpoint_host": urlsplit(str(route.base_url or "")).netloc,
        "fallback_reason": route.fallback_reason,
        "api_key_recorded": False,
    }
    if route.provider != "custom" or route.wire_model != MODEL_ID or route_evidence["provider_endpoint_host"] != "127.0.0.1:8045":
        raise RuntimeError("real smoke route did not resolve to the authorized Gemini base model on port 8045")

    memory_service = RealMemoryService(
        roots["MEMORYOS_DATA_ROOT"],
        subject_id=subject_id,
        service_python=MEMORYOS_SERVICE_PYTHON,
    )
    facade = None
    try:
        memory_service.start()
        facade = memory_service.facade()
        actual_service_db_path = (memory_service.data_root / "db" / "memoryos.sqlite3").resolve()
        if actual_service_db_path != roots["MEMORYOS_DB_PATH"] or not actual_service_db_path.is_file():
            raise RuntimeError("isolated MemoryOS database path does not match MEMORYOS_DB_PATH")
        observer_config = AtlasConfig(raw_config)

        class _ObserverManager:
            current_model = manager.current_model
            model_router = tracked_router

            @staticmethod
            def list_models():
                return manager.list_models()

        observer = MemoryObserver(_ObserverManager(), observer_config)
    except BaseException:
        if facade is not None:
            await facade.aclose()
        await memory_service.aclose()
        memory_service.stop()
        raise

    model_window_started = time.time()
    model_started_iso = _now_iso()
    batches: list[dict[str, Any]] = []
    durations_ms: list[float] = []
    total_posted = 0
    total_http_accepted = 0
    total_http_posts = 0
    total_source_accepted = 0
    rejected_by_reason: Counter[str] = Counter()
    mixed_rejection_batches = 0
    mixed_rejection_batches_posted = 0
    checkpoint_path = output_path.with_name(output_path.stem + ".partial.json")

    def write_checkpoint(status: str = "running") -> None:
        _atomic_json(checkpoint_path, {
            "schema": "F2-A-real-observer-smoke-v1",
            "status": status,
            "run_id": run_id,
            "started_at": model_started_iso,
            "updated_at": _now_iso(),
            "isolation": {name: str(path) for name, path in roots.items()},
            "actual_service_db_path": str(actual_service_db_path),
            "route": route_evidence,
            "completed_or_current_batch_count": len(batches),
            "aggregate_so_far": {
                "extraction_p50_ms": _percentile(durations_ms, 0.50),
                "extraction_p95_ms": _percentile(durations_ms, 0.95),
                "source_items_http_accepted": total_source_accepted,
                "derived_items_submitted": total_posted,
                "derived_items_http_accepted": total_http_accepted,
                "derived_http_posts": total_http_posts,
                "item_rejected_by_reason": dict(rejected_by_reason),
                "mixed_rejection_batches": mixed_rejection_batches,
                "mixed_rejection_batches_http_accepted": mixed_rejection_batches_posted,
                "model_api_call_count_including_retries": len(tracked_router.calls),
            },
            "batches": batches,
        })

    write_checkpoint()

    try:
        for trial in range(1, 4):
            for case in CONVERSATIONS:
                session_id = f"f2a-{run_id}-t{trial}-{case['id']}"
                context = memory_service.context(session_id=session_id)
                sources = _case_sources(case, trial, run_id)

                source_ack = await facade.observe_batch({
                    "contract_version": "UM-WIN-1.0",
                    "event_class": "TEST",
                    "context": context,
                    "observations": [{key: value for key, value in source.items() if key != "text"}
                                     for source in sources],
                })
                expected_source_ids = [str(source["source_event_id"]) for source in sources]
                actual_source_ids = _receipt_sources(source_ack)
                if (
                    not isinstance(source_ack, dict)
                    or int(source_ack.get("accepted", -1)) != len(sources)
                    or Counter(actual_source_ids) != Counter(expected_source_ids)
                ):
                    raise RuntimeError(f"isolated MemoryOS did not acknowledge all source messages for {session_id}")
                total_source_accepted += int(source_ack["accepted"])

                before_rejected = Counter(observer.item_rejected_counts)
                api_call_start = len(tracked_router.calls)
                started = time.perf_counter()
                batch = await observer.add_messages(
                    session_id, sources, session_ended=True, context=context,
                )
                extraction_ms = round((time.perf_counter() - started) * 1000, 2)
                if batch is None:
                    raise RuntimeError(f"observer produced no batch for flushed session {session_id}")
                durations_ms.append(extraction_ms)
                rejected_delta = Counter(observer.item_rejected_counts) - before_rejected
                rejected_by_reason.update(rejected_delta)
                items = list((batch.payload or {}).get("observations") or [])
                item_texts = [str(item.get("content", {}).get("text") or "") for item in items]
                post_started = time.perf_counter()
                ack: dict[str, Any] | None = None
                stored: list[dict[str, Any]] = []
                checkpoint_entry = {
                    "trial": trial,
                    "case_id": case["id"],
                    "expected_facts_for_human_review": case["expected_facts"],
                    "expected_no_fact": not case["expected_facts"],
                    "session_id": session_id,
                    "source_messages": [
                        {"source_event_id": source["source_event_id"],
                         "speaker_role": source["speaker_role"],
                         "text": source["text"]}
                        for source in sources
                    ],
                    "source_http_ack": {
                        "accepted": source_ack.get("accepted"),
                        "receipt_count": len(actual_source_ids),
                    },
                    "model_id": batch.model_id,
                    "extraction_ms": extraction_ms,
                    "input_tokens": batch.input_tokens,
                    "output_tokens": batch.output_tokens,
                    "language_status": batch.language_status,
                    "item_rejected": dict(rejected_delta),
                    "raw_model_output": batch.raw_output,
                    "derived_items": [
                        {
                            "text": item_texts[index],
                            "facet": items[index].get("facet"),
                            "speaker_role": items[index].get("speaker_role"),
                            "source_event_id": items[index].get("source_event_id"),
                            "evidence": items[index].get("derived_from", []),
                        }
                        for index in range(len(items))
                    ],
                    "http_post": {
                        "attempted": bool(items),
                        "state": "pending" if items else "not_needed_empty_extraction",
                        "accepted": None if items else 0,
                        "receipt_count": None if items else 0,
                    },
                    "stored_records": stored,
                    "observer_acknowledged": False,
                    "api_calls": tracked_router.calls[api_call_start:],
                }
                batches.append(checkpoint_entry)
                write_checkpoint()
                if items:
                    ack = await facade.observe_batch(batch.payload)
                    total_http_posts += 1
                    expected_ids = [str(item.get("source_event_id") or "") for item in items]
                    receipt_ids = _receipt_sources(ack)
                    if (
                        int(ack.get("accepted", -1)) != len(items)
                        or len(receipt_ids) != len(items)
                        or Counter(receipt_ids) != Counter(expected_ids)
                    ):
                        raise RuntimeError(f"derived MemoryOS POST did not acknowledge each accepted item for {session_id}")
                    total_posted += len(items)
                    total_http_accepted += int(ack["accepted"])
                    receipt_rows = []
                    for receipt in ack["receipts"]:
                        if not isinstance(receipt, dict):
                            raise RuntimeError("MemoryOS observe receipt was not an object")
                        record_ref = receipt.get("record_ref") or (
                            f"episode:{receipt['event_id']}" if receipt.get("event_id") else None
                        )
                        if not record_ref:
                            raise RuntimeError("MemoryOS observe receipt did not include a readable event reference")
                        receipt_rows.append({
                            "source_event_id": str(receipt.get("source_event_id") or ""),
                            "record_ref": str(record_ref),
                        })
                    checkpoint_entry["http_post"] = {
                        "attempted": True,
                        "state": "accepted",
                        "accepted": int(ack["accepted"]),
                        "receipt_count": len(receipt_rows),
                        "receipts": receipt_rows,
                    }
                    write_checkpoint()
                    for receipt, receipt_row in zip(ack["receipts"], receipt_rows):
                        record_ref = receipt_row["record_ref"]
                        record = await facade.get_record(str(record_ref))
                        content = record.get("content") if isinstance(record, dict) else None
                        evidence = await facade.client().evidence(str(record_ref))
                        source_event_id = receipt_row["source_event_id"]
                        snippet = _matching_evidence_snippet(evidence, source_event_id)
                        stored_text = _stored_observation_text(record)
                        stored.append({
                            "record_ref": str(record_ref),
                            "stored_text": stored_text,
                            "facet": record.get("facet"),
                            "record_content": content,
                            "source_refs": record.get("source_refs", []),
                            "evidence_source_event_id": source_event_id,
                            "evidence_snippet_truncated": bool(snippet.get("truncated")),
                            "evidence_snippet_chars": len(snippet["text"]),
                        })
                        checkpoint_entry["stored_records"] = stored
                        write_checkpoint()
                    if [row["stored_text"] for row in stored] != item_texts:
                        raise RuntimeError(f"stored MemoryOS text differed from the accepted observer payload for {session_id}")

                post_ms = round((time.perf_counter() - post_started) * 1000, 2)
                if rejected_delta and items:
                    mixed_rejection_batches += 1
                    if ack is not None and int(ack.get("accepted", -1)) == len(items):
                        mixed_rejection_batches_posted += 1
                checkpoint_entry["memoryos_post_ms"] = post_ms
                checkpoint_entry["http_post"] = {
                    "attempted": bool(items),
                    "state": "accepted" if ack is not None else "not_needed_empty_extraction",
                    "accepted": ack.get("accepted") if ack else 0,
                    "receipt_count": len(ack.get("receipts") or []) if ack else 0,
                }
                checkpoint_entry["stored_records"] = stored
                write_checkpoint()
                next_batch = await observer.ack_batch(batch.batch_id)
                checkpoint_entry["observer_acknowledged"] = True
                if next_batch is not None:
                    checkpoint_entry["next_batch_pending"] = next_batch.batch_id
                    write_checkpoint()
                    raise RuntimeError(f"observer unexpectedly split session {session_id} into additional batches")
                write_checkpoint()

        model_window_ended = time.time()
        gateway_usage = _gateway_usage_since(model_window_started, model_window_ended)
        all_api_calls = list(tracked_router.calls)
        exact_usage_calls = sum(
            call["input_tokens"] is not None and call["output_tokens"] is not None
            for call in all_api_calls
        )
        return {
            "schema": "F2-A-real-observer-smoke-v1",
            "status": "completed",
            "run_id": run_id,
            "started_at": model_started_iso,
            "ended_at": _now_iso(),
            "requirements": {
                "conversation_count": len(CONVERSATIONS),
                "trials_per_conversation": 3,
                "batch_count": len(batches),
                "questions_per_conversation": "multiple natural Chinese questions per case",
                "real_model_provider_used": True,
                "fake_provider_used": False,
            },
            "isolation": {name: str(path) for name, path in roots.items()},
            "route": route_evidence,
            "proxy": {
                "version": "Antigravity Tools 4.8.5-beta.10",
                "request_reasoning_effort": "low for Gemini bare model memory purposes",
                "routing_source": "https://github.com/lbjlaq/Antigravity-Manager/blob/main/CHANGELOG_EN.md",
                "expected_effective_variant": "gemini-3.8-flash-low",
                "thinking_disabled": False,
                "proxy_usage_records_during_run": gateway_usage,
            },
            "aggregate": {
                "extraction_p50_ms": _percentile(durations_ms, 0.50),
                "extraction_p95_ms": _percentile(durations_ms, 0.95),
                "total_http_source_items_accepted": total_source_accepted,
                "derived_items_submitted": total_posted,
                "derived_items_http_accepted": total_http_accepted,
                "derived_http_posts": total_http_posts,
                "item_rejected_by_reason": dict(rejected_by_reason),
                "mixed_rejection_batches": mixed_rejection_batches,
                "mixed_rejection_batches_http_accepted": mixed_rejection_batches_posted,
                "model_api_call_count_including_retries": len(all_api_calls),
                "api_calls_with_exact_provider_usage": exact_usage_calls,
                "api_usage_by_call": all_api_calls,
            },
            "manual_fact_review": {
                "status": "PENDING",
                "criteria": "Read every stored_records[].stored_text against its source_messages; question/request-only content is not a fact.",
                "question_as_fact_count": None,
                "bad_item_caused_valid_batch_loss_count": None,
                "reviewer_note": "Populate after inspecting all stored record text and the item_rejected/HTTP receipt evidence.",
            },
            "batches": batches,
        }
    finally:
        if facade is not None:
            await facade.aclose()
        await memory_service.aclose()
        memory_service.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "plan" / "MEMORY-V1" / "eval" / (
            "F2-A-real-smoke-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
        ),
    )
    parser.add_argument("--run-root", type=Path, default=None)
    args = parser.parse_args()
    checkpoint_path = args.output.with_name(args.output.stem + ".partial.json")
    if args.output.exists() or checkpoint_path.exists():
        parser.error("--output or its partial checkpoint already exists; choose a new path")
    run_root = (args.run_root or Path(os.environ.get("LOCALAPPDATA", r"C:\Users\25011\AppData\Local"))
                / "Temp" / f"atlas_f2a_{uuid.uuid4().hex[:8]}").resolve()
    if run_root.exists() and any(run_root.iterdir()):
        parser.error("--run-root must be new or empty")
    run_root.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = asyncio.run(_run_smoke(run_root, args.output))
    except Exception as exc:  # noqa: BLE001 - record a sanitized failure artifact without provider payloads
        if checkpoint_path.is_file():
            try:
                partial = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                partial = {"schema": "F2-A-real-observer-smoke-v1"}
            partial["status"] = "failed"
            partial["error_type"] = type(exc).__name__
            partial["error_details"] = "omitted to avoid recording provider credentials or request data"
            _atomic_json(checkpoint_path, partial)
        failure = {
            "schema": "F2-A-real-observer-smoke-v1",
            "status": "failed",
            "run_root": str(run_root),
            "partial_checkpoint": str(checkpoint_path.resolve()) if checkpoint_path.exists() else None,
            "error_type": type(exc).__name__,
            "error_details": "omitted to avoid recording provider credentials or request data",
        }
        _atomic_json(args.output, failure)
        print(json.dumps({"status": "failed", "output": str(args.output.resolve()),
                          "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1
    _atomic_json(args.output, result)
    checkpoint_path.unlink(missing_ok=True)
    print(json.dumps({
        "status": result["status"],
        "output": str(args.output.resolve()),
        "batch_count": result["requirements"]["batch_count"],
        "route_model": result["route"]["wire_model"],
        "proxy_rows": result["proxy"]["proxy_usage_records_during_run"].get("requests"),
        "question_review": result["manual_fact_review"]["status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
