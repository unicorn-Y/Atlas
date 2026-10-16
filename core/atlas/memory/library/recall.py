"""Small public helpers for memory recall paths shared by Atlas subsystems."""

from __future__ import annotations

import re
from typing import Any

_CITATION_BLOCK = re.compile(r"<atlas-mem-citation>(.*?)</atlas-mem-citation>", re.DOTALL)
_CLAIM_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})\s*$")


def recheck_memory(
    error_text: str, *, limit: int = 3, library: Any | None = None,
) -> dict[str, Any]:
    """Run one lexical recheck of a tool error after repeated failures.

    M1 calls this only after two consecutive failures. It deliberately avoids
    query rewriting, vector search, and association expansion.
    """
    query = " ".join(str(error_text or "").split())[:4000]
    if not query:
        return {"query": "", "hits": [], "block": ""}
    if library is None:
        from . import get_library

        library = get_library()
    if library is None:
        return {"query": query, "hits": [], "block": ""}
    library.ready()
    library.index.sync()
    hits = library.index.search_lexical(query, limit=max(1, min(5, int(limit))))
    lines = [
        f"- [{hit.get('claim_id')}] {hit.get('text')}"
        for hit in hits
    ]
    block = "连续工具失败后重查记忆：\n" + "\n".join(lines) if lines else ""
    return {"query": query, "hits": hits, "block": block}


def parse_cited_claim_ids(answer: str) -> list[str]:
    """Extract IDs from `<claim_ids>` elements inside Atlas citation blocks."""
    ids: list[str] = []
    for block in _CITATION_BLOCK.findall(str(answer or "")):
        match = re.search(r"<claim_ids>(.*?)</claim_ids>", block, re.DOTALL)
        if not match:
            continue
        for line in match.group(1).splitlines():
            item = _CLAIM_LINE.match(line)
            if item and item.group(1) not in ids:
                ids.append(item.group(1))
    return ids


def record_citations(answer: str, *, run_id: str, message_id: str,
                     library: Any | None = None) -> list[str]:
    """Idempotently count claim citations from one persisted assistant message."""
    claim_ids = parse_cited_claim_ids(answer)
    if not claim_ids:
        return []
    if library is None:
        from . import get_library

        library = get_library()
    if library is None:
        return []
    stamp = _message_stamp(run_id, message_id)
    for claim_id in claim_ids:
        library.index.record_usage_event(
            f"citation:{stamp}:{claim_id}", claim_id, "agent_citation",
            metadata={"channel": "assistant"},
        )
    return claim_ids


def _message_stamp(run_id: str, message_id: str) -> str:
    import hashlib

    return hashlib.sha256(f"{run_id}\x1f{message_id}".encode("utf-8")).hexdigest()


__all__ = ["parse_cited_claim_ids", "record_citations", "recheck_memory"]
