"""Minimal Add/Search adapter for external memory evaluation suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas.memory.library import MemoryLibrary
from atlas.memory.library import extract
from atlas.memory.library.store import Entry, new_id


LOCOMO_REFINED_SOURCE = "https://github.com/mem-eval-suite/LoCoMo_refined"


def run_locomo(
    dataset_path: str | Path, *, data_dir: str | Path | None = None,
    judge: Any = None, limit_conversations: int | None = None,
    limit_questions: int | None = None, k: int = 10,
) -> dict[str, Any]:
    """Forward LoCoMo-Refined evaluation to the isolated benchmark runner."""
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"LoCoMo-Refined dataset not found at {path}; source: {LOCOMO_REFINED_SOURCE}"
        )
    from atlas.memory.locomo_eval import run_locomo as evaluate

    return evaluate(
        path, data_dir=data_dir, judge=judge,
        limit_conversations=limit_conversations,
        limit_questions=limit_questions, k=k,
    )


class MemoryAMLAdapter:
    """Expose exactly the Add and Search operations expected by AML runners."""

    def __init__(self, library: MemoryLibrary, *, workspace: str = "") -> None:
        self._library = library
        self._workspace = workspace

    def add(self, text: str, *, scope: str = "global", meta: dict[str, Any] | None = None) -> str:
        """Write one memory and return its stable entry ID without committing git."""
        metadata = dict(meta or {})
        allowed = {
            "key", "value", "src", "at", "ref", "until", "quote", "session", "mode",
            "ended", "why", "importance", "trigger", "steps", "outcome", "verified",
            "decisions", "files", "commands", "facts", "open_items", "dia_id",
        }
        unknown = metadata.keys() - allowed
        if unknown:
            raise ValueError(f"unsupported memory metadata: {', '.join(sorted(unknown))}")
        cleaned = " ".join((text or "").split())
        if not cleaned or extract.contains_secret(cleaned):
            raise ValueError("memory text is empty or contains a secret")
        self._library.ready()
        rel = self._library._safe_rel("事/aml-evaluation.md")
        dia_id = metadata.pop("dia_id", None)
        if dia_id is not None and not metadata.get("ref"):
            metadata["ref"] = str(dia_id)
        entry = Entry(text=cleaned, id=new_id(), scope=scope or "global", **metadata)
        with self._library.store.lock:
            page = self._library.store.read(rel)
            page.current.append(entry)
            self._library.store.write(page)
        self._library.index.sync()
        return entry.id

    def search(
        self, query: str, k: int = 10, *, scope: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return matching memory text and retrieval score, highest ranked first."""
        rows = self._library.search(query, limit=max(0, int(k)), scope=scope,
                                    workspace=self._workspace)
        return [(str(row.get("text") or ""), float(row.get("score") or 0.0)) for row in rows]
