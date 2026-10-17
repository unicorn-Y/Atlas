"""Knowledge base: experience imported from strong models, readable by any model.

Design: docs/knowledge/DESIGN.md. Separate from the memory library (``data/memory``,
which is about the user); this one holds *how to work* — distilled from Claude Code /
Codex / Atlas sessions so a weaker or swapped-in model can follow the same methods.

Layout under ``data/knowledge``:

- ``raw/<source>/...``      原始会话日志，原样存档（冷存储，不直接给模型看）
- ``curated/<kind>/*.md``   提炼层：事实 / 技能 / 决策 / 案例（Markdown + frontmatter）
- ``evals/*.jsonl``         评测题，换模型时用来比新旧
- ``.kb.sqlite``            派生的全文索引（可随时重建）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .importers import IMPORTERS, ImportResult
from .store import KINDS, CuratedItem, KnowledgeStore

_SINGLETON: "KnowledgeBase | None" = None


class KnowledgeBase:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = KnowledgeStore(root)

    def import_source(self, source: str, path: str | None = None) -> ImportResult:
        importer = IMPORTERS.get(source)
        if importer is None:
            raise KeyError(f"unknown source: {source} (known: {', '.join(IMPORTERS)})")
        return importer(self.root / "raw" / source, Path(path) if path else None)

    def add(self, item: CuratedItem) -> Path:
        path = self.store.write(item)
        self.store.reindex()
        return path

    def search(self, query: str, kind: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        return self.store.search(query, kind=kind, limit=limit)

    def stats(self) -> dict[str, Any]:
        raw = self.root / "raw"
        sources = {p.name: sum(1 for f in p.rglob("*") if f.is_file())
                   for p in raw.iterdir() if p.is_dir()} if raw.exists() else {}
        evals = self.root / "evals"
        return {
            "root": str(self.root),
            "raw": sources,
            "curated": self.store.counts(),
            "evals": sorted(p.name for p in evals.glob("*.jsonl")) if evals.exists() else [],
        }


def get_knowledge_base() -> KnowledgeBase | None:
    """Process-wide knowledge base, or None when ``[knowledge] enabled = false``."""
    global _SINGLETON
    from atlas.config import DATA_ROOT, get_config

    config = get_config()
    try:
        if not bool(config.get("knowledge.enabled", True)):
            return None
        root = str(config.get("knowledge.root", "") or "").strip()
    except Exception:
        root = ""
    if _SINGLETON is None:
        _SINGLETON = KnowledgeBase(Path(root) if root else DATA_ROOT / "data" / "knowledge")
    return _SINGLETON


__all__ = ["KINDS", "CuratedItem", "KnowledgeBase", "get_knowledge_base"]
