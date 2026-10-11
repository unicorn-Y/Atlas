"""Dependency-free BM25 retrieval over library items.

Tokens are lowercase ASCII words (kebab/snake/camel parts split) plus CJK
character bigrams, so "帮我做个PPT" matches a skill described as "PowerPoint
幻灯片 pptx". Good enough for thousands of entries in a few milliseconds and
costs nothing per turn, which is the point: the model only ever sees the top
hits, never the whole library.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "for", "with", "on", "by", "is", "are", "be",
    "use", "using", "used", "when", "this", "that", "it", "from", "as", "at", "your", "you", "can",
    "into", "via", "any", "all", "tool", "tools", "skill", "skills", "mcp", "server",
    "的", "了", "和", "是", "在", "我", "帮", "一个", "用", "把",
})


def tokenize(text: str) -> list[str]:
    raw = _CAMEL_RE.sub(" ", str(text or ""))
    lowered = raw.lower()
    tokens = [word for word in _WORD_RE.findall(lowered) if word not in _STOP and len(word) > 1]
    for run in _CJK_RE.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1) if run[i:i + 2] not in _STOP)
    return tokens


def item_text(item: dict[str, Any]) -> str:
    """The searchable text of one library item; the name counts twice."""
    parts = [
        item.get("name", ""), item.get("name", ""), item.get("title", ""), item.get("description", ""),
        item.get("when_to_use", ""), " ".join(item.get("tags") or []), item.get("category_name", ""),
        item.get("server", ""), " ".join(item.get("category_keywords") or []),
    ]
    return " ".join(str(part) for part in parts if part)


class Bm25Index:
    """Immutable BM25 index; rebuild when the item set changes."""

    def __init__(self, items: Sequence[dict[str, Any]], *, k1: float = 1.4, b: float = 0.7) -> None:
        self.items = list(items)
        self._docs = [Counter(tokenize(item_text(item))) for item in self.items]
        self._lengths = [sum(doc.values()) for doc in self._docs]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        df: Counter[str] = Counter()
        for doc in self._docs:
            df.update(doc.keys())
        total = len(self._docs)
        self._idf = {term: math.log(1 + (total - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        self._k1, self._b = k1, b

    def search(self, query: str, *, limit: int = 10, min_score: float = 0.0,
               where: Any = None) -> list[tuple[float, dict[str, Any]]]:
        terms = [term for term in dict.fromkeys(tokenize(query)) if term in self._idf]
        if not terms:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for index, doc in enumerate(self._docs):
            item = self.items[index]
            if where is not None and not where(item):
                continue
            length_norm = 1 - self._b + self._b * (self._lengths[index] / self._avg if self._avg else 1)
            score = 0.0
            for term in terms:
                freq = doc.get(term)
                if freq:
                    score += self._idf[term] * freq * (self._k1 + 1) / (freq + self._k1 * length_norm)
            if score > min_score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("name", ""))))
        return scored[:limit]


def keyword_hits(text: str, keywords: Iterable[str]) -> int:
    """Count category keywords present in text (whole-word for ASCII, substring for CJK)."""
    lowered = f" {str(text or '').lower()} "
    words = set(_WORD_RE.findall(lowered))
    hits = 0
    for keyword in keywords:
        key = str(keyword).lower().strip()
        if not key:
            continue
        if _CJK_RE.search(key) or " " in key or "." in key or "_" in key:
            hits += key in lowered
        elif key.endswith("*") or len(key) > 6 and key.isalpha() and key not in words:
            hits += any(word.startswith(key.rstrip("*")) for word in words)
        else:
            hits += key in words
    return hits
