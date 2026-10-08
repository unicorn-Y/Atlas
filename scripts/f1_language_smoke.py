"""Run F1-B's real ModelRouter language smoke without persisting observations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_CORE_ROOT = _REPO_ROOT / "core"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from memory_v1.gemini_runtime import (  # noqa: E402
    MODEL_ID,
    PROVIDER_ID,
    bootstrap_model_manager,
    clear_gateway_fallback_config,
    clear_inherited_gateway_credentials,
    read_isolated_model_settings,
    write_isolated_user_settings,
)


_DIALOGUES = (
    ("我对花生过敏，点餐时需要避开。", "明白，点餐建议会留意这个忌口。"),
    ("我每周二、周四下班后会去游泳。", "收到，你通常每周游泳两次。"),
    ("我早上习惯喝无糖豆浆。", "好的，早餐建议会考虑这个习惯。"),
    ("我现在住在成都，之前住在杭州。", "明白，你目前住在成都。"),
    ("我做项目时更喜欢用 TypeScript。", "好的，我会在代码示例中优先考虑 TypeScript。"),
    ("我最近开始每天步行三十分钟。", "不错，我会记住你最近开始的步行习惯。"),
    ("我正在准备一个关于数据库迁移的分享。", "明白，你正在准备数据库迁移主题的分享。"),
    ("周末我会陪父母去看展览。", "祝你们看展愉快。"),
    ("我不喜欢太吵的咖啡馆，更喜欢靠窗的位置。", "收到，之后推荐咖啡馆时会优先考虑安静和靠窗座位。"),
    ("我把个人笔记从旧电脑迁到了新电脑。", "明白，你已经完成个人笔记的迁移。"),
)

_SAFE_CALL_FIELDS = {
    "model_id",
    "purpose",
    "status",
    "input_tokens",
    "output_tokens",
    "provider_reported_cost",
    "provider_reported_cost_usd",
    "error_type",
}
_SAFE_RESULT_FIELDS = {
    "sample_number",
    "segment",
    "repetition",
    "source_events",
    "language_status",
    "language_mismatch_count",
    "observer_accounted_input_tokens",
    "observer_accounted_output_tokens",
    "observation_texts",
    "raw_output",
}


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _token_count(usage: Any, *names: str) -> int | None:
    for name in names:
        value = _field(usage, name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            return int(value)
    return None


def _cost_report(raw: Any) -> tuple[dict[str, Any] | None, float | None]:
    usage = _field(raw, "usage")
    for container, prefix in ((usage, "usage"), (raw, "response")):
        for name in ("total_cost_usd", "cost_usd", "cost"):
            value = _field(container, name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                entry = {"field": f"{prefix}.{name}", "value": float(value)}
                usd = float(value) if name.endswith("_usd") else None
                return entry, usd
    return None, None


def _safe_route_host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if not parsed.hostname:
        return None
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def _make_queue(observer_type, dialogue: tuple[str, str], repetition: int):
    from atlas.memory.observer import _SessionQueue

    queue = _SessionQueue()
    for speaker, text in (("USER", dialogue[0]), ("ATLAS", dialogue[1])):
        source = {
            "source_event_id": f"f1-language:{uuid.uuid4().hex}",
            "text": text,
            "speaker_role": speaker,
            "epistemic_kind": "ASSERTED" if speaker == "USER" else "INFERRED",
            "source_kind": "CHAT",
            "source_object_id": uuid.uuid4().hex,
            "source_revision": str(repetition),
        }
        queue.entries.append(observer_type._queue_entry(source, text))
    return queue


def _input_digest(limit: int) -> str:
    payload = json.dumps(_DIALOGUES[:limit], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _valid_sample_number(value: Any, limit: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= limit * 3:
        raise ValueError("resume evidence contains an invalid sample number")
    return value


def _pending_samples(limit: int, successful_samples: set[int]) -> list[int]:
    return [sample_number for sample_number in range(1, limit * 3 + 1)
            if sample_number not in successful_samples]


def _copy_safe_model_call(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("resume evidence contains a malformed ModelRouter call")
    model_id = item.get("model_id")
    purpose = item.get("purpose")
    status = item.get("status")
    if model_id != MODEL_ID or purpose != "memory_observe" or status not in {"started", "succeeded", "failed"}:
        raise ValueError("resume evidence does not match the fixed Gemini memory_observe route")
    cleaned = {key: item[key] for key in _SAFE_CALL_FIELDS if key in item}
    for name in ("input_tokens", "output_tokens", "provider_reported_cost_usd"):
        value = cleaned.get(name)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        ):
            cleaned[name] = None
    if isinstance(cleaned.get("provider_reported_cost"), dict):
        raw_cost = cleaned["provider_reported_cost"]
        cleaned["provider_reported_cost"] = {
            "field": str(raw_cost.get("field", ""))[:80],
            "value": raw_cost.get("value")
            if isinstance(raw_cost.get("value"), (int, float))
            and not isinstance(raw_cost.get("value"), bool)
            else None,
        }
    elif cleaned.get("provider_reported_cost") is not None:
        cleaned["provider_reported_cost"] = None
    if cleaned.get("error_type") is not None:
        cleaned["error_type"] = str(cleaned["error_type"])[:80]
    return cleaned


def _copy_safe_result(item: Any, limit: int) -> dict[str, Any]:
    if not isinstance(item, dict) or item.get("status") != "succeeded":
        raise ValueError("resume evidence contains a non-success result row")
    sample_number = _valid_sample_number(item.get("sample_number"), limit)
    expected_segment = (sample_number - 1) // 3 + 1
    expected_repetition = (sample_number - 1) % 3 + 1
    if item.get("segment") != expected_segment or item.get("repetition") != expected_repetition:
        raise ValueError("resume evidence sample numbering does not match the fixed dialogue order")
    cleaned = {key: item[key] for key in _SAFE_RESULT_FIELDS if key in item}
    cleaned["status"] = "succeeded"
    cleaned["sample_number"] = sample_number
    events = cleaned.get("source_events")
    if not isinstance(events, list) or not events:
        raise ValueError("resume evidence is missing the sample's source events")
    cleaned["source_events"] = [
        {
            "source_event_id": str(event.get("source_event_id") or ""),
            "speaker_role": str(event.get("speaker_role") or ""),
            "text": str(event.get("text") or ""),
        }
        for event in events
        if isinstance(event, dict)
    ]
    texts = cleaned.get("observation_texts")
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise ValueError("resume evidence contains malformed Observation text")
    if not isinstance(cleaned.get("raw_output"), str):
        raise ValueError("resume evidence is missing the raw Observation output")
    return cleaned


def _load_resume(path: Path, limit: int) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("resume file is not an F1-B language smoke artifact")
    if data.get("input_sha256") != _input_digest(limit) or data.get("limit") != limit:
        raise ValueError("resume evidence was produced from a different dialogue set or sample limit")
    route = data.get("route")
    if not isinstance(route, dict) or (
        route.get("model_id") != MODEL_ID
        or route.get("observer_model_id") != MODEL_ID
        or route.get("provider_id") != PROVIDER_ID
    ):
        raise ValueError("resume evidence does not match the fixed Gemini memory_observe route")

    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in data.get("results", []):
        cleaned = _copy_safe_result(row, limit)
        sample_number = cleaned["sample_number"]
        if sample_number in seen:
            raise ValueError("resume evidence repeats a successful sample")
        seen.add(sample_number)
        results.append(cleaned)

    attempts: list[dict[str, Any]] = []
    for row in data.get("attempt_history", []):
        if not isinstance(row, dict):
            raise ValueError("resume evidence contains malformed attempt history")
        sample_number = _valid_sample_number(row.get("sample_number"), limit)
        status = row.get("status")
        if status not in {"succeeded", "failed"}:
            raise ValueError("resume evidence contains an unknown attempt status")
        attempt = {"sample_number": sample_number, "status": status}
        if row.get("error_type") is not None:
            attempt["error_type"] = str(row["error_type"])[:80]
        attempts.append(attempt)
    for row in results:
        if not any(
            item["sample_number"] == row["sample_number"] and item["status"] == "succeeded"
            for item in attempts
        ):
            attempts.append({"sample_number": row["sample_number"], "status": "succeeded"})

    model_calls = [
        _copy_safe_model_call(row)
        for row in data.get("model_calls", [])
    ]
    return {
        "results": results,
        "attempt_history": attempts,
        "model_calls": model_calls,
        "route": {
            key: route[key]
            for key in (
                "model_id",
                "observer_model_id",
                "provider_id",
                "provider_endpoint_host",
                "credential_present",
                "credential_source",
                "credential_value_recorded",
            )
            if key in route
        },
    }


def _source_validation(result: dict[str, Any]) -> dict[str, Any]:
    source_ids = {
        str(item.get("source_event_id") or "")
        for item in result.get("source_events", [])
        if isinstance(item, dict) and item.get("source_event_id")
    }
    try:
        parsed = json.loads(result.get("raw_output") or "")
    except (TypeError, json.JSONDecodeError):
        return {"parseable": False, "evidence_items": 0, "matching_source_items": 0}

    observations = parsed.get("observations") if isinstance(parsed, dict) else None
    if not isinstance(observations, list):
        return {"parseable": False, "evidence_items": 0, "matching_source_items": 0}
    evidence_items = [
        source_id
        for observation in observations
        if isinstance(observation, dict)
        for source_id in (observation.get("evidence") or [])
        if isinstance(source_id, str)
    ]
    matching = sum(source_id in source_ids for source_id in evidence_items)
    return {
        "parseable": True,
        "evidence_items": len(evidence_items),
        "matching_source_items": matching,
    }


def _summarize(
    *,
    limit: int,
    input_sha256: str,
    results: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    model_calls: list[dict[str, Any]],
    route: dict[str, Any],
    isolated_roots: dict[str, str],
) -> dict[str, Any]:
    from atlas.memory.observer import _dominant_language

    ordered = sorted(results, key=lambda item: item["sample_number"])
    texts = [text for item in ordered for text in item.get("observation_texts", [])]
    chinese = sum(_dominant_language(text) == "zh" for text in texts)
    source_checks = [_source_validation(item) for item in ordered]
    evidence_total = sum(item["evidence_items"] for item in source_checks)
    evidence_matching = sum(item["matching_source_items"] for item in source_checks)
    parse_errors = sum(not item["parseable"] for item in source_checks)
    failed_attempts = [item for item in attempts if item["status"] == "failed"]
    input_tokens = [
        item["input_tokens"]
        for item in model_calls
        if isinstance(item.get("input_tokens"), (int, float))
    ]
    output_tokens = [
        item["output_tokens"]
        for item in model_calls
        if isinstance(item.get("output_tokens"), (int, float))
    ]
    missing_usage = sum(
        item.get("input_tokens") is None or item.get("output_tokens") is None
        for item in model_calls
    )
    accounted_input = sum(
        int(item.get("observer_accounted_input_tokens") or 0)
        for item in ordered
    )
    accounted_output = sum(
        int(item.get("observer_accounted_output_tokens") or 0)
        for item in ordered
    )
    ratio = chinese / len(texts) if texts else None
    complete = len(ordered) == limit * 3
    evidence_passed = evidence_total > 0 and evidence_total == evidence_matching and parse_errors == 0
    passed = bool(
        complete
        and ratio is not None
        and ratio >= 0.98
        and sum(int(item.get("language_mismatch_count") or 0) for item in ordered) == 0
        and evidence_passed
    )
    status = (
        "complete_with_documented_transient_failure"
        if complete and failed_attempts
        else "complete"
        if complete
        else "incomplete"
    )
    return {
        "schema_version": 1,
        "status": status,
        "run_ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": input_sha256,
        "limit": limit,
        "route": route,
        "fake_provider": False,
        "isolated_roots": isolated_roots,
        "acceptance": {
            "dialogues": limit,
            "repetitions_per_dialogue": 3,
            "completed_sample_batches": len(ordered),
            "required_sample_batches": limit * 3,
            "observation_text_rows": len(texts),
            "chinese_text_rows": chinese,
            "chinese_text_ratio": ratio,
            "required_ratio": 0.98,
            "language_mismatch_rows": sum(
                int(item.get("language_mismatch_count") or 0) for item in ordered
            ),
            "passed": passed,
        },
        "source_validation": {
            "verified_observation_evidence_items": evidence_total,
            "matching_same_batch_source_items": evidence_matching,
            "unparseable_batch_outputs": parse_errors,
            "each_output_evidence_cites_same_batch_source_ids": evidence_passed,
            "observation_expectations_injected": False,
            "language_metric": "Atlas observer._dominant_language over each raw observation text",
        },
        "tokens": {
            "provider_reported_input_tokens": sum(input_tokens),
            "provider_reported_output_tokens": sum(output_tokens),
            "model_router_calls_without_complete_provider_usage": missing_usage,
            "observer_accounted_input_tokens": accounted_input,
            "observer_accounted_output_tokens": accounted_output,
            "provider_reported_cost_usd": (
                sum(float(item["provider_reported_cost_usd"]) for item in model_calls)
                if model_calls
                and all(item.get("provider_reported_cost_usd") is not None for item in model_calls)
                else None
            ),
        },
        "model_router_calls": len(model_calls),
        "attempt_history": attempts,
        "failed_attempts": failed_attempts,
        "results": ordered,
        "model_calls": model_calls,
    }


async def _run(
    *,
    limit: int,
    isolation_root: Path,
    settings_source: Path,
    resume: dict[str, Any] | None,
) -> dict[str, Any]:
    logging.disable(logging.CRITICAL)
    isolation_root = isolation_root.resolve()
    atlas_data_root = isolation_root / "atlas-data"
    memory_root = isolation_root / "memoryos-data"
    db_path = memory_root / "db" / "memoryos.sqlite3"
    for path in (atlas_data_root, memory_root, db_path.parent):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["ATLAS_DATA_DIR"] = str(atlas_data_root)
    os.environ["MEMORYOS_DATA_ROOT"] = str(memory_root)
    os.environ["MEMORYOS_DB_PATH"] = str(db_path)
    clear_inherited_gateway_credentials()
    if str(_CORE_ROOT) not in sys.path:
        sys.path.insert(0, str(_CORE_ROOT))

    settings = read_isolated_model_settings(settings_source)
    settings_path = write_isolated_user_settings(atlas_data_root, settings)

    from atlas.config import get_config
    from atlas.memory.observer import MemoryObserver, _dominant_language

    config = get_config()
    clear_gateway_fallback_config(config.raw)
    model_manager, route_metadata = bootstrap_model_manager(config, settings, settings_path)
    observer = MemoryObserver(
        model_manager,
        {
            "memory.v1.observer_daily_token_budget": 1_000_000,
            "memory.unified.event_class": "TEST",
        },
    )
    model_id = observer._select_model_id()
    if model_id != MODEL_ID:
        raise RuntimeError("Observer did not select the fixed Gemini memory model")

    router = model_manager.model_router
    route = await router.resolve(model_id, purpose="memory_observe")
    if (
        route.provider != PROVIDER_ID
        or _safe_route_host(route.base_url) != route_metadata["provider_endpoint_host"]
        or not route.key
    ):
        raise RuntimeError("ModelRouter did not resolve the fixed Gemini credential route")

    provider_calls: list[dict[str, Any]] = []
    original_complete_for = router.complete_for

    async def traced_complete_for(model_id_arg, purpose, messages, **kwargs):
        call = {
            "model_id": model_id_arg,
            "purpose": purpose,
            "status": "started",
            "input_tokens": None,
            "output_tokens": None,
            "provider_reported_cost": None,
            "provider_reported_cost_usd": None,
        }
        provider_calls.append(call)
        try:
            response = await original_complete_for(model_id_arg, purpose, messages, **kwargs)
        except Exception as exc:
            call["status"] = "failed"
            call["error_type"] = type(exc).__name__
            raise
        usage = getattr(response, "usage", None)
        raw = getattr(response, "raw", None)
        cost, cost_usd = _cost_report(raw)
        call.update({
            "status": "succeeded",
            "input_tokens": _token_count(usage, "input_tokens", "prompt_tokens"),
            "output_tokens": _token_count(usage, "output_tokens", "completion_tokens"),
            "provider_reported_cost": cost,
            "provider_reported_cost_usd": cost_usd,
        })
        return response

    router.complete_for = traced_complete_for

    results = list(resume["results"]) if resume else []
    attempts = list(resume["attempt_history"]) if resume else []
    model_calls = list(resume["model_calls"]) if resume else []
    model_calls.extend(provider_calls)
    successful_samples = {item["sample_number"] for item in results}
    for sample_number in _pending_samples(limit, successful_samples):
        segment = (sample_number - 1) // 3 + 1
        repetition = (sample_number - 1) % 3 + 1
        queue = _make_queue(MemoryObserver, _DIALOGUES[segment - 1], repetition)
        try:
            batch = await observer._start_batch(
                f"f1-language:{uuid.uuid4().hex}",
                queue,
                {"purpose": "F1-B language smoke"},
            )
            if batch is None:
                raise RuntimeError("Observer deferred the isolated smoke batch")
            observations = (batch.payload or {}).get("observations", [])
            texts = [
                str(item.get("content", {}).get("text") or "")
                for item in observations
            ]
            row = {
                "status": "succeeded",
                "sample_number": sample_number,
                "segment": segment,
                "repetition": repetition,
                "source_events": [
                    {
                        "source_event_id": entry["source_event_id"],
                        "speaker_role": entry["speaker_role"],
                        "text": entry["text"],
                    }
                    for entry in queue.entries
                ],
                "language_status": batch.language_status,
                "language_mismatch_count": batch.language_mismatch_count,
                "observer_accounted_input_tokens": batch.input_tokens,
                "observer_accounted_output_tokens": batch.output_tokens,
                "observation_texts": texts,
                "raw_output": str(batch.raw_output or ""),
            }
            results.append(row)
            successful_samples.add(sample_number)
            attempts.append({"sample_number": sample_number, "status": "succeeded"})
        except Exception as exc:
            attempts.append({
                "sample_number": sample_number,
                "status": "failed",
                "error_type": type(exc).__name__,
            })
            break
    model_calls.extend(provider_calls)

    return _summarize(
        limit=limit,
        input_sha256=_input_digest(limit),
        results=results,
        attempts=attempts,
        model_calls=model_calls,
        route=route_metadata,
        isolated_roots={
            "ATLAS_DATA_DIR": str(atlas_data_root),
            "MEMORYOS_DATA_ROOT": str(memory_root),
            "MEMORYOS_DB_PATH": str(db_path),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        choices=range(1, 11),
        help="number of natural Chinese dialogue segments to run, three batches each",
    )
    parser.add_argument("--isolation-root", type=Path, required=True)
    parser.add_argument(
        "--settings-source",
        type=Path,
        default=_REPO_ROOT / "data" / "user-settings.json",
        help="read-only source for the approved Gemini/custom-provider metadata",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="resume from a prior F1-B artifact; successful sample numbers are never repeated",
    )
    args = parser.parse_args()
    resume = None
    try:
        if args.resume_from:
            resume = _load_resume(args.resume_from, args.limit)
        result = asyncio.run(_run(
            limit=args.limit,
            isolation_root=args.isolation_root,
            settings_source=args.settings_source,
            resume=resume,
        ))
    except Exception as exc:
        result = {
            "schema_version": 1,
            "status": "blocked",
            "error_type": type(exc).__name__,
            "detail": "ModelRouter setup or smoke execution failed; secret-bearing exception text is omitted.",
            "input_sha256": _input_digest(args.limit),
            "limit": args.limit,
            "results": resume["results"] if resume else [],
            "attempt_history": resume["attempt_history"] if resume else [],
            "failed_attempts": (
                [item for item in resume["attempt_history"] if item["status"] == "failed"]
                if resume
                else []
            ),
            "model_calls": resume["model_calls"] if resume else [],
            "route": resume["route"] if resume else {},
            "fake_provider": False,
        }
        exit_code = 2
    else:
        exit_code = 0 if result["acceptance"]["passed"] else 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status"),
        "model_id": result.get("route", {}).get("model_id"),
        "provider_id": result.get("route", {}).get("provider_id"),
        "completed_sample_batches": result.get("acceptance", {}).get("completed_sample_batches"),
        "observation_text_rows": result.get("acceptance", {}).get("observation_text_rows"),
        "chinese_text_ratio": result.get("acceptance", {}).get("chinese_text_ratio"),
        "failed_attempts": len(result.get("failed_attempts", [])),
        "secret_recorded": False,
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
