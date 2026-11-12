"""Isolated LoCoMo-Refined retrieval and LLM-judged evaluation."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from atlas.memory.aml_adapter import MemoryAMLAdapter
from atlas.memory.library import MemoryLibrary

JUDGE_MODEL = "deepseek-v4.1-flash"
CATEGORIES = {
    1: "1_single_hop", 2: "2_temporal", 3: "3_multi_hop", 4: "4_open_domain",
}
_MODEL_MANAGER: Any = None


def _model_judge(question: str, gold: list[str], evidence: str) -> str:
    global _MODEL_MANAGER
    from atlas.models import ModelManager

    if _MODEL_MANAGER is None:
        _MODEL_MANAGER = ModelManager()
    result = asyncio.run(_MODEL_MANAGER.model_router.complete_for(
        JUDGE_MODEL, "memory_library", [
            {"role": "system", "content": (
                "Judge a proposed memory-retrieval answer using only the evidence. "
                "Return exactly JSON: {\"correct\": true|false, \"reason\": \"...\"}. "
                "Mark correct only when all required facts in a gold answer are included, "
                "the evidence does not contradict it, and temporal precision matches "
                "the question (do not accept a less precise date/time when precision is asked)."
            )},
            {"role": "user", "content": json.dumps({
                "question": question, "gold_answers": gold, "evidence": evidence,
            }, ensure_ascii=False)},
        ], max_tokens=300, temperature=0,
    ))
    return str(getattr(result, "text", "") or "")


def _decode_judgment(raw: Any) -> bool:
    if isinstance(raw, dict):
        value = raw.get("correct")
        if isinstance(value, bool):
            return value
        raise ValueError("judge JSON requires boolean 'correct'")
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        result = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("judge returned no JSON object")
        result = json.loads(match.group(0))
    if not isinstance(result, dict) or not isinstance(result.get("correct"), bool):
        raise ValueError("judge JSON requires boolean 'correct'")
    return result["correct"]


def _date_for(conversation: dict[str, Any], session_key: str) -> str:
    suffix = session_key.removeprefix("session_")
    return str(conversation.get(f"session_{suffix}_date_time") or "")


def _ordered_turns(conversation: dict[str, Any]):
    sessions = sorted(
        (key for key, value in conversation.items()
         if re.fullmatch(r"session_\d+", key) and isinstance(value, list)),
        key=lambda key: int(key.split("_")[1]),
    )
    for session in sessions:
        turns = conversation[session]
        def dia_order(turn: dict[str, Any]) -> tuple[int, str]:
            dia = str(turn.get("dia_id") or "")
            match = re.search(r":(\d+)$", dia)
            return (int(match.group(1)) if match else 0, dia)
        for turn in sorted(turns, key=dia_order):
            yield session, turn


def run_locomo(
    dataset_path: str | Path, *, data_dir: str | Path | None = None,
    judge: Callable[..., Any] | None = None,
    limit_conversations: int | None = None,
    limit_questions: int | None = None, k: int = 10,
    include_questions: bool = False,
) -> dict[str, Any]:
    """Ingest selected conversations into a disposable memory root and score QA."""
    started = time.monotonic()
    path = Path(dataset_path)
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("LoCoMo dataset must be a top-level list")
    conversations = dataset[:max(0, int(limit_conversations))] if limit_conversations is not None else dataset
    owns_dir = data_dir is None
    temporary = tempfile.TemporaryDirectory(prefix="atlas-locomo-memory-") if owns_dir else None
    root = Path(temporary.name) if temporary else Path(data_dir)  # type: ignore[arg-type]
    records: list[dict[str, Any]] = []
    try:
        library = MemoryLibrary(root, vcs=False)
        library.index._schedule_embeddings = lambda: None  # type: ignore[method-assign]
        library.index._vector_search = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
        # vcs=False: the evaluator's disposable root must never git-init or commit.
        library.ready()
        adapter = MemoryAMLAdapter(library)
        judge_fn = judge or _model_judge
        category_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        per_conversation: list[dict[str, Any]] = []
        total_questions = skipped = evaluated = errors = 0
        remaining = None if limit_questions is None else max(0, int(limit_questions))

        for conv in conversations:
            if not isinstance(conv, dict) or not isinstance(conv.get("conversation"), dict):
                raise ValueError("each dataset item must contain a conversation object")
            conversation = conv["conversation"]
            ingest_count = 0
            for session, turn in _ordered_turns(conversation):
                speaker, text = str(turn.get("speaker") or ""), str(turn.get("text") or "")
                dia_id = str(turn.get("dia_id") or "")
                at = _date_for(conversation, session)
                adapter.add(f"[{at}] {speaker}: {text}", meta={
                    "session": session, "dia_id": dia_id, "at": at,
                })
                ingest_count += 1

            conv_total = conv_skipped = conv_evaluated = conv_errors = conv_correct = 0
            for qa in conv.get("qa", []):
                if remaining == 0:
                    break
                total_questions += 1
                conv_total += 1
                if qa.get("is_multi_modality") is True:
                    skipped += 1
                    conv_skipped += 1
                    continue
                if remaining is not None:
                    remaining -= 1
                question = str(qa.get("question") or "")
                hits = adapter.search(question, k=max(0, int(k)))
                evidence = "\n".join(text for text, _score in hits)
                gold = qa.get("answer")
                gold_answers = [str(item) for item in gold] if isinstance(gold, list) else [str(gold or "")]
                correct = False
                last_exc: Exception | None = None
                for attempt in range(3):
                    try:
                        raw = judge_fn(question, gold_answers, evidence)
                        if asyncio.iscoroutine(raw):
                            raw = asyncio.run(raw)
                        correct = _decode_judgment(raw)
                        last_exc = None
                        break
                    except Exception as exc:
                        # 判分调用偶发超时/连接失败（实测 87 次挂 1 次）。把它当"答错"
                        # 会让基础设施抖动直接污染分数，所以重试；三次都失败才记 error。
                        last_exc = exc
                        if attempt < 2:
                            time.sleep(1.5 * (attempt + 1))
                if last_exc is not None:
                    errors += 1
                    conv_errors += 1
                    correct = False
                evaluated += 1
                conv_evaluated += 1
                conv_correct += int(correct)
                category = CATEGORIES.get(qa.get("category"), f"{qa.get('category')}_unknown")
                category_counts[category][1] += 1
                category_counts[category][0] += int(correct)
                if include_questions:
                    # 逐题明细：没有它只能看汇总，出了问题无法定位是检索还是判定。
                    records.append({
                        "sample_id": conv.get("sample_id"), "category": category,
                        "question": question, "gold": gold_answers[:2],
                        "correct": bool(correct),
                        "evidence_ids": [str(e) for e in (qa.get("evidence") or [])],
                        "top_hits": [str(t)[:160] for t, _s in hits[:3]],
                    })
            per_conversation.append({
                "sample_id": conv.get("sample_id"), "ingest_count": ingest_count,
                "questions_total": conv_total, "questions_skipped_multimodal": conv_skipped,
                "questions_evaluated": conv_evaluated, "judge_errors": conv_errors,
                "correct": conv_correct,
                "accuracy": conv_correct / conv_evaluated if conv_evaluated else 0.0,
            })
            if remaining == 0:
                break

        by_category = {
            key: {"correct": counts[0], "evaluated": counts[1],
                  "accuracy": counts[0] / counts[1] if counts[1] else 0.0}
            for key, counts in sorted(category_counts.items())
        }
        return {
            "dataset": str(path), "judge_model": JUDGE_MODEL if judge is None else "custom",
            "judge_is_official": False, "conversations": len(per_conversation),
            "questions_total": total_questions, "questions_skipped_multimodal": skipped,
            "questions_evaluated": evaluated, "judge_errors": errors,
            "accuracy_overall": sum(item["correct"] for item in per_conversation) / evaluated if evaluated else 0.0,
            "by_category": by_category, "per_conversation": per_conversation,
            "per_question": records,
            "elapsed_seconds": time.monotonic() - started,
        }
    finally:
        db = getattr(getattr(locals().get("library"), "index", None), "_db", None)
        if db is not None:
            db.close()
            library.index._db = None
        if temporary is not None:
            temporary.cleanup()
