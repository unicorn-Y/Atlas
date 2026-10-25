"""Isolated retrieval benchmark for Atlas memory search."""
from __future__ import annotations

import json
import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.memory.library import MemoryLibrary
from atlas.memory.library.store import Entry, Page

DATASET_SCHEMA = 1
RETRIEVAL_CONFIG = {
    "engine": "Atlas MemoryIndex hybrid search",
    "keyword": "current MemoryIndex FTS/BM25 path",
    "vectors": "disabled for deterministic, offline benchmark",
    "k": [1, 3, 5],
    "now": "fixed 2026-01-01 UTC",
}


def _load_dataset(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).parent / "benchmarks" / "v1.json"
    try:
        dataset = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read benchmark dataset: {exc}") from exc
    if not isinstance(dataset, dict) or dataset.get("schema_version") != DATASET_SCHEMA:
        raise ValueError(f"dataset schema_version must equal {DATASET_SCHEMA}")
    records, cases = dataset.get("records"), dataset.get("cases")
    if not isinstance(records, list) or not records or not isinstance(cases, list) or not cases:
        raise ValueError("dataset requires non-empty records and cases arrays")
    record_ids = set()
    for row in records:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip() or not str(row.get("text") or "").strip():
            raise ValueError("each record requires non-empty id and text")
        if row["id"] in record_ids:
            raise ValueError(f"duplicate record id: {row['id']}")
        record_ids.add(row["id"])
    for case in cases:
        if (not isinstance(case, dict) or not str(case.get("question") or "").strip()
                or not isinstance(case.get("expected_ids"), list) or not case["expected_ids"]
                or not set(case["expected_ids"]).issubset(record_ids)
                or not isinstance(case.get("answer_terms"), list)):
            raise ValueError("each case requires question, valid expected_ids and answer_terms")
    return dataset


def run_memory_benchmark(
    dataset_path: Path | None = None, *, ks: tuple[int, ...] = (1, 3, 5),
    generate: bool = False, model_id: str | None = None,
) -> dict[str, Any]:
    """Run the shipped retrieval algorithm against a disposable, synthetic corpus."""
    dataset = _load_dataset(dataset_path)
    chosen_ks = tuple(sorted({max(1, int(k)) for k in ks}))
    max_k = max(chosen_ks)
    results: list[dict[str, Any]] = []
    model_mgr = None
    if generate:
        from atlas.models import ModelManager

        model_mgr = ModelManager()
        model_id = model_id or model_mgr.current_model
        if not model_id:
            raise ValueError("--generate requires a configured current model or an explicit --model")
    with tempfile.TemporaryDirectory(prefix="atlas-memory-bench-") as temporary:
        library = MemoryLibrary(Path(temporary) / "memory")
        # Keep this benchmark reproducible and offline: exercise the production
        # keyword ranking and hybrid merger with the vector leg deliberately empty.
        library.index._schedule_embeddings = lambda: None  # type: ignore[method-assign]
        library.index._vector_search = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
        library.ready()
        page = Page(path="事/基准集.md", title="基准集")
        now = datetime(2026, 1, 1, tzinfo=UTC).isoformat(timespec="seconds")
        for row in dataset["records"]:
            page.current.append(Entry(
                id=str(row["id"]), text=str(row["text"]), src=str(row.get("src") or "基准"),
                ref=str(row.get("ref") or ""), at=now,
            ))
        library.store.write(page)
        library.store.commit("隔离记忆召回基准")
        library.index.sync()
        for case in dataset["cases"]:
            hits = library.search(str(case["question"]), limit=max_k, kinds=("fact", "dream"))
            ranked = [str(item.get("id") or "") for item in hits]
            expected = set(map(str, case["expected_ids"]))
            metrics: dict[str, Any] = {}
            for k in chosen_ks:
                top = ranked[:k]
                metrics[f"recall_at_{k}"] = len(expected.intersection(top)) / len(expected)
                metrics[f"citation_precision_at_{k}"] = (
                    len(expected.intersection(top)) / len(top) if top else 0.0
                )
                evidence = "\n".join(str(item.get("text") or "") for item in hits[:k]).casefold()
                terms = [str(term) for term in case["answer_terms"]]
                metrics[f"answer_hit_at_{k}"] = bool(terms) and all(term.casefold() in evidence for term in terms)
            generated = None
            if generate and model_mgr is not None:
                evidence_rows = [{"id": item.get("id"), "text": item.get("text")} for item in hits[:max_k]]
                prompt = [
                    {"role": "system", "content": (
                        "Answer the user's question using only the supplied memory evidence. "
                        "Return JSON with keys answer (string) and citations (array of evidence ids). "
                        "Cite only evidence ids that directly support the answer; do not guess."
                    )},
                    {"role": "user", "content": json.dumps({
                        "question": case["question"], "evidence": evidence_rows,
                    }, ensure_ascii=False)},
                ]
                try:
                    completion = asyncio.run(model_mgr.model_router.complete_for(
                        str(model_id), "conversation", prompt, max_tokens=500, temperature=0,
                    ))
                except Exception as exc:
                    raise RuntimeError(f"benchmark generation failed ({type(exc).__name__})") from exc
                raw = str(getattr(completion, "text", "") or "").strip()
                try:
                    generated = json.loads(raw)
                except json.JSONDecodeError:
                    generated = {"answer": raw, "citations": []}
                if not isinstance(generated, dict):
                    generated = {"answer": raw, "citations": []}
                answer = str(generated.get("answer") or "")
                citations = [str(item) for item in generated.get("citations", []) if isinstance(item, str)]
                expected = set(map(str, case["expected_ids"]))
                answer_terms = [str(term) for term in case["answer_terms"]]
                generated = {
                    "answer": answer, "citations": citations,
                    "answer_hit": bool(answer_terms) and all(term.casefold() in answer.casefold() for term in answer_terms),
                    "citation_precision": len(expected.intersection(citations)) / len(citations) if citations else 0.0,
                    "citation_recall": len(expected.intersection(citations)) / len(expected),
                }
            results.append({
                "case_id": str(case.get("id") or case["question"]),
                "question": str(case["question"]),
                "expected_ids": sorted(expected), "ranked_ids": ranked,
                "ranked_refs": [str(item.get("ref") or "") for item in hits],
                "metrics": metrics, "generation": generated,
            })
        if library.index._db is not None:
            library.index._db.close()
    averages: dict[str, float] = {}
    for k in chosen_ks:
        for metric in (f"recall_at_{k}", f"citation_precision_at_{k}", f"answer_hit_at_{k}"):
            averages[metric] = sum(float(row["metrics"][metric]) for row in results) / len(results)
    if generate:
        for metric in ("answer_hit", "citation_precision", "citation_recall"):
            averages[f"generation_{metric}"] = sum(
                float(bool(row["generation"][metric])) if metric == "answer_hit"
                else float(row["generation"][metric]) for row in results
            ) / len(results)
    return {
        "schema_version": 1, "dataset_id": str(dataset["dataset_id"]),
        "dataset_schema_version": dataset["schema_version"],
        "retrieval_config": {**RETRIEVAL_CONFIG, "k": list(chosen_ks)},
        "generation_config": {
            "enabled": generate, "model": str(model_id or "not used"),
            "temperature": 0, "max_tokens": 500,
            "prompt_contract": "evidence-only JSON answer with cited record ids",
        },
        "case_count": len(results), "record_count": len(dataset["records"]),
        "averages": averages, "cases": results,
        "answer_hit_definition": "Retrieval answer_hit checks all expected terms in evidence; generation answer_hit checks all expected terms in the generated answer.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Memory Recall Benchmark · {report['dataset_id']}", "",
        f"- Records: {report['record_count']} · Questions: {report['case_count']}",
        f"- Retrieval: {report['retrieval_config']['engine']} · deterministic lexical leg; vectors disabled",
        f"- Generation: {report['generation_config']['model']} (enabled={report['generation_config']['enabled']}, temperature=0)",
        "| Metric | Score |", "|---|---:|",
    ]
    for name, value in report["averages"].items():
        lines.append(f"| {name} | {value:.3f} |")
    lines.extend(["", "## Per question", ""])
    for case in report["cases"]:
        lines.extend([
            f"### {case['case_id']}", "", f"Question: {case['question']}",
            f"Expected: {', '.join(case['expected_ids'])}",
            f"Ranked: {', '.join(case['ranked_ids']) or '(no matches)' }",
            ", ".join(f"{key}={value}" for key, value in case["metrics"].items()), "",
        ])
        if case.get("generation"):
            gen = case["generation"]
            lines[-1:-1] = [f"Generated answer: {gen['answer']}", f"Citations: {', '.join(gen['citations']) or '(none)'}",
                             f"generation_answer_hit={gen['answer_hit']} citation_precision={gen['citation_precision']:.3f}"]
    return "\n".join(lines)
