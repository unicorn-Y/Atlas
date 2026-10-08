"""Run F1-B's real ModelRouter language smoke without persisting observations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


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


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _token_count(usage: Any, *names: str) -> int | None:
    for name in names:
        value = _field(usage, name)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


def _cost_report(raw: Any) -> tuple[dict[str, Any] | None, float | None]:
    usage = _field(raw, "usage")
    for container, prefix in ((usage, "usage"), (raw, "response")):
        for name in ("total_cost_usd", "cost_usd", "cost"):
            value = _field(container, name)
            if isinstance(value, (int, float)) and value >= 0:
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


async def _run(limit: int) -> dict[str, Any]:
    # Construct the product ModelManager first so it reads the configured model and
    # credentials from Atlas' existing user settings. It is only read after this point.
    from atlas.config import get_config
    from atlas.models import ModelManager

    model_manager = ModelManager()
    config = get_config()

    isolation_root = Path(tempfile.mkdtemp(prefix="atlas-f1-language-"))
    os.environ["ATLAS_DATA_DIR"] = str(isolation_root / "atlas")
    os.environ["MEMORYOS_DATA_ROOT"] = str(isolation_root / "memoryos")
    os.environ["MEMORYOS_DB_PATH"] = str(isolation_root / "memoryos" / "memory.sqlite3")

    from atlas.memory.observer import MemoryObserver, _dominant_language

    observer = MemoryObserver(
        model_manager,
        {
            "memory.v1.observer_daily_token_budget": 1_000_000,
            "memory.unified.event_class": "TEST",
        },
    )
    model_id = observer._select_model_id()
    router = model_manager.model_router

    provider_calls: list[dict[str, Any]] = []
    original_complete_for = router.complete_for

    async def traced_complete_for(model_id_arg, purpose, messages, **kwargs):
        response = await original_complete_for(model_id_arg, purpose, messages, **kwargs)
        usage = getattr(response, "usage", None)
        raw = getattr(response, "raw", None)
        cost, cost_usd = _cost_report(raw)
        provider_calls.append({
            "model_id": model_id_arg,
            "purpose": purpose,
            "input_tokens": _token_count(usage, "input_tokens", "prompt_tokens"),
            "output_tokens": _token_count(usage, "output_tokens", "completion_tokens"),
            "provider_reported_cost": cost,
            "provider_reported_cost_usd": cost_usd,
        })
        return response

    router.complete_for = traced_complete_for

    results: list[dict[str, Any]] = []
    observation_texts: list[str] = []
    for segment_index, dialogue in enumerate(_DIALOGUES[:limit], start=1):
        for repetition in range(1, 4):
            queue = _make_queue(MemoryObserver, dialogue, repetition)
            batch = await observer._start_batch(
                f"f1-language:{uuid.uuid4().hex}", queue, {"purpose": "F1-B language smoke"},
            )
            if batch is None:
                raise RuntimeError("Observer deferred the isolated smoke batch")
            observations = (batch.payload or {}).get("observations", [])
            texts = [
                str(item.get("content", {}).get("text") or "")
                for item in observations
            ]
            observation_texts.extend(texts)
            results.append({
                "segment": segment_index,
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
                "input_tokens": batch.input_tokens,
                "output_tokens": batch.output_tokens,
                "observation_texts": texts,
                "raw_output": batch.raw_output,
            })

    chinese_count = sum(_dominant_language(text) == "zh" for text in observation_texts)
    provider_input = [call["input_tokens"] for call in provider_calls]
    provider_output = [call["output_tokens"] for call in provider_calls]
    reported_usd = [call["provider_reported_cost_usd"] for call in provider_calls]
    return {
        "status": "complete" if observation_texts else "no_observation_texts",
        "model_id": model_id,
        "model_manager_gateway_source": model_manager.gateway_source,
        "model_manager_gateway_host": _safe_route_host(model_manager.gateway_base_url),
        "isolated_roots": {
            "ATLAS_DATA_DIR": os.environ["ATLAS_DATA_DIR"],
            "MEMORYOS_DATA_ROOT": os.environ["MEMORYOS_DATA_ROOT"],
            "MEMORYOS_DB_PATH": os.environ["MEMORYOS_DB_PATH"],
        },
        "segments": limit,
        "repetitions_per_segment": 3,
        "model_router_calls": len(provider_calls),
        "observation_rows": len(observation_texts),
        "chinese_text_rows": chinese_count,
        "chinese_text_ratio": chinese_count / len(observation_texts) if observation_texts else None,
        "language_mismatch_rows": observer.language_mismatch_count,
        "usage": {
            "provider_reported_input_tokens": sum(item for item in provider_input if item is not None),
            "provider_reported_output_tokens": sum(item for item in provider_output if item is not None),
            "requests_without_complete_provider_token_usage": sum(
                item is None for item in provider_input
            ) + sum(item is None for item in provider_output),
            "batch_accounted_input_tokens": sum(item["input_tokens"] for item in results),
            "batch_accounted_output_tokens": sum(item["output_tokens"] for item in results),
            "provider_reported_cost_usd": sum(reported_usd) if all(
                item is not None for item in reported_usd
            ) and reported_usd else None,
            "requests_without_provider_cost_usd": sum(item is None for item in reported_usd),
            "provider_cost_fields": [call["provider_reported_cost"] for call in provider_calls],
        },
        "results": results,
        "model_calls": provider_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=10, choices=range(1, 11),
        help="number of the ten natural dialogue segments to run (each runs three times)",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args.limit))
    except Exception as exc:
        print(json.dumps({
            "status": "blocked",
            "error_type": type(exc).__name__,
            "detail": "ModelRouter call failed; exception details are omitted to avoid exposing credentials.",
        }, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    ratio = result["chinese_text_ratio"]
    return 0 if ratio is not None and ratio >= 0.98 else 1


if __name__ == "__main__":
    raise SystemExit(main())
