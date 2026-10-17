"""Curated layer: one Markdown file per item, plus a derived SQLite FTS index."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# 提炼层四类：事实（项目/环境事实）、技能（怎么做某类活）、决策（为什么选 A 不选 B）、案例（强模型的完整好做法）
KINDS = ("事实", "技能", "决策", "案例")

_FRONT = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


@dataclass
class CuratedItem:
    kind: str
    title: str
    body: str
    source: str = ""          # 出处：如 claude-code:<session>/<uuid>、codex:<rollout>
    tags: list[str] = field(default_factory=list)
    model: str = ""           # 产出原始经验的模型，便于以后按老师筛选

    def slug(self) -> str:
        return re.sub(r'[\\/:*?"<>|\s]+', "-", self.title).strip("-")[:80] or "untitled"


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.curated = root / "curated"
        for kind in KINDS:
            (self.curated / kind).mkdir(parents=True, exist_ok=True)
        self.db_path = root / ".kb.sqlite"

    def write(self, item: CuratedItem) -> Path:
        if item.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        path = self.curated / item.kind / f"{item.slug()}.md"
        front = [
            f"title: {item.title}",
            f"kind: {item.kind}",
            f"source: {item.source}",
            f"model: {item.model}",
            f"tags: [{', '.join(item.tags)}]",
            f"updated: {datetime.now().isoformat(timespec='seconds')}",
        ]
        path.write_text("---\n" + "\n".join(front) + "\n---\n" + item.body.strip() + "\n", encoding="utf-8")
        return path

    def _items(self):
        for kind in KINDS:
            for path in sorted((self.curated / kind).glob("*.md")):
                text = path.read_text(encoding="utf-8")
                meta: dict[str, str] = {}
                body = text
                m = _FRONT.match(text)
                if m:
                    body = m.group(2)
                    for line in m.group(1).splitlines():
                        key, _, value = line.partition(":")
                        meta[key.strip()] = value.strip()
                yield kind, path, meta, body

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS items USING fts5("
            "path UNINDEXED, kind UNINDEXED, title, body, tags, source UNINDEXED, tokenize='trigram')"
        )
        return conn

    def reindex(self) -> int:
        with self._connect() as conn:
            conn.execute("DELETE FROM items")
            rows = [(p.relative_to(self.root).as_posix(), k, meta.get("title", p.stem), body,
                     meta.get("tags", ""), meta.get("source", ""))
                    for k, p, meta, body in self._items()]
            conn.executemany("INSERT INTO items VALUES (?,?,?,?,?,?)", rows)
        return len(rows)

    def search(self, query: str, kind: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        if not self.db_path.exists():
            self.reindex()
        with self._connect() as conn:
            # trigram 需要 ≥3 字；短词（如两个汉字）退回 LIKE
            if len(query) >= 3:
                sql = ("SELECT path, kind, title, snippet(items, 3, '[', ']', '…', 24), source "
                       "FROM items WHERE items MATCH ?")
                args: list[Any] = ['"' + query.replace('"', '""') + '"']
            else:
                sql = "SELECT path, kind, title, substr(body, 1, 200), source FROM items WHERE (title LIKE ? OR body LIKE ?)"
                args = [f"%{query}%", f"%{query}%"]
            if kind:
                sql += " AND kind = ?"
                args.append(kind)
            sql += " LIMIT ?"
            args.append(limit)
            rows = conn.execute(sql, args).fetchall()
        return [{"path": r[0], "kind": r[1], "title": r[2], "snippet": r[3], "source": r[4]} for r in rows]

    def counts(self) -> dict[str, int]:
        return {kind: len(list((self.curated / kind).glob("*.md"))) for kind in KINDS}
