"""Rebuildable, explainable one-hop associations from Markdown wikilinks.

Markdown remains the sole authority for links. This module keeps no persistent
graph and never writes pages; callers may rebuild the projection at any time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"(`+).*?\1", re.DOTALL)
_ENTRY_META_RE = re.compile(r"<!--\s*(\{.*\})\s*-->\s*$")


@dataclass(frozen=True, slots=True)
class WikiLink:
    """A link as it appears in source Markdown, without rewriting its text."""

    target: str
    section: str = ""
    alias: str = ""
    link_text: str = ""
    start: int = 0
    end: int = 0


@dataclass(frozen=True, slots=True)
class LinkEdge:
    source_path: str
    target_path: str
    link_text: str
    source_entry_id: str | None = None
    source_ref: Any = None


@dataclass(frozen=True, slots=True)
class OrphanLink:
    source_path: str
    target: str
    link_text: str
    source_entry_id: str | None = None
    reason: str = "unresolved_target"


@dataclass(slots=True)
class LinkIndex:
    """Ephemeral graph projection rebuilt exclusively from current Markdown."""

    pages: dict[str, str] = field(default_factory=dict)
    adjacency: dict[str, list[LinkEdge]] = field(default_factory=dict)
    orphans: list[OrphanLink] = field(default_factory=list)


def parse_wikilinks(text: str) -> list[WikiLink]:
    """Parse ``[[Page]]`` and ``[[Page#section|alias]]`` outside code/comments."""
    links: list[WikiLink] = []

    def mask(match: re.Match[str]) -> str:
        return " " * (match.end() - match.start())

    # Fenced blocks and comments are not navigable links.
    source = re.sub(r"(?ms)^\s*(```+|~~~+)[^\n]*\n.*?^\s*\1\s*$", mask, text)
    source = _COMMENT_RE.sub(mask, source)
    source = _INLINE_CODE_RE.sub(mask, source)
    for match in _WIKILINK_RE.finditer(source):
        raw = match.group(1)
        destination, sep, alias = raw.partition("|")
        target, hash_sep, section = destination.partition("#")
        target = target.strip()
        if not target:
            continue
        links.append(WikiLink(
            target=target,
            section=section.strip() if hash_sep else "",
            alias=alias.strip() if sep else "",
            link_text=text[match.start():match.end()],
            start=match.start(),
            end=match.end(),
        ))
    return links


def _normalise(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _page_key(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.casefold().endswith(".md"):
        value = value[:-3]
    return _normalise(value)


def _source_meta(raw_line: str, parsed_entry: Any = None) -> tuple[str | None, Any]:
    entry_id = getattr(parsed_entry, "id", None)
    source_ref = getattr(parsed_entry, "source_ref", None)
    if source_ref is None:
        match = _ENTRY_META_RE.search(raw_line)
        if match:
            try:
                metadata = json.loads(match.group(1))
            except (TypeError, ValueError):
                metadata = {}
            entry_id = entry_id or metadata.get("id")
            source_ref = metadata.get("source_ref")
    return (str(entry_id) if entry_id else None), source_ref


def _current_markdown_lines(raw: str) -> list[str]:
    """Return only page content outside explicit history sections."""
    lines: list[str] = []
    history = False
    for line in raw.splitlines():
        heading = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading:
            history = "历史" in heading.group(1) or "history" in heading.group(1).casefold()
            lines.append("")
        elif not history:
            lines.append(line)
    return lines


def build_link_index(store: Any) -> LinkIndex:
    """Build a fresh page/alias index and resolve explicit links in current pages."""
    rel_paths = set(store.pages())
    diary_pages = getattr(store, "diary_pages", None)
    if callable(diary_pages):
        rel_paths.update(diary_pages())
    rel_paths = sorted(rel_paths)
    index = LinkIndex()
    alias_paths: dict[str, set[str]] = {}
    page_objects: dict[str, Any] = {}

    for rel in rel_paths:
        page = store.read(rel)
        page_objects[rel] = page
        index.pages[rel] = str(getattr(page, "title", "") or Path(rel).stem)
        names = {Path(rel).stem, str(getattr(page, "title", "") or ""), rel, *getattr(page, "aliases", [])}
        for name in names:
            key = _page_key(str(name))
            if key:
                alias_paths.setdefault(key, set()).add(rel)

    for rel in rel_paths:
        page = page_objects[rel]
        raw_path = Path(store.root) / rel
        if not raw_path.is_file():
            continue
        raw = raw_path.read_text(encoding="utf-8")
        current_lines = _current_markdown_lines(raw)
        # Associate links in a fact line with its parsed current Entry, where possible.
        entry_by_text: dict[str, Any] = {}
        for entry in getattr(page, "current", []):
            entry_by_text.setdefault(" ".join(str(entry.text).split()), entry)

        for line in current_lines:
            stripped = line.strip()
            if not stripped:
                continue
            entry_match = re.match(r"^\s*[-*]\s+(.*?)\s*(?:<!--.*-->)?\s*$", line)
            entry = entry_by_text.get(" ".join(entry_match.group(1).split())) if entry_match else None
            entry_id, source_ref = _source_meta(line, entry)
            for link in parse_wikilinks(line):
                key = _page_key(link.target)
                targets = alias_paths.get(key, set())
                if not targets:
                    index.orphans.append(OrphanLink(rel, link.target, link.link_text, entry_id))
                    continue
                if len(targets) != 1:
                    index.orphans.append(OrphanLink(rel, link.target, link.link_text, entry_id,
                                                    "ambiguous_target"))
                    continue
                target_path = next(iter(targets))
                if target_path == rel:
                    continue
                edge = LinkEdge(rel, target_path, link.link_text, entry_id, source_ref)
                index.adjacency.setdefault(rel, []).append(edge)
    return index


def _seed_value(seed: Mapping[str, Any], key: str, default: Any = None) -> Any:
    return seed.get(key, default)


def expand_one_hop(
    seeds: Sequence[Mapping[str, Any]],
    link_index: LinkIndex,
    limit: int,
) -> list[dict[str, Any]]:
    """Return unique direct linked pages with the source link as explanation."""
    if limit <= 0:
        return []
    seed_paths = {str(_seed_value(seed, "path", "")) for seed in seeds}
    found: dict[str, dict[str, Any]] = {}
    for seed in seeds:
        via_page = str(_seed_value(seed, "path", ""))
        if not via_page:
            continue
        for edge in link_index.adjacency.get(via_page, []):
            if edge.target_path in seed_paths or edge.target_path in found:
                continue
            found[edge.target_path] = {
                "page_path": edge.target_path,
                "via_page": via_page,
                "link_text": edge.link_text,
                "seed_id": _seed_value(seed, "id"),
                "seed_source_ref": edge.source_ref if edge.source_ref is not None
                else _seed_value(seed, "source_ref"),
                "reason": f"由页面 {via_page} 的显式链接 {edge.link_text} 关联",
                "rank_reasons": ["explicit_wikilink_one_hop"],
            }
            if len(found) >= limit:
                return list(found.values())
    return list(found.values())


def rank_associations(
    seeds: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep association order aligned with M5 seed order; never alter its scores."""
    seed_order: dict[str, int] = {}
    for n, seed in enumerate(seeds):
        path = str(_seed_value(seed, "path", ""))
        if path and path not in seed_order:
            seed_order[path] = n
    return [dict(candidate) for _, candidate in sorted(
        enumerate(candidates),
        key=lambda item: (seed_order.get(str(item[1].get("via_page", "")), len(seed_order)), item[0]),
    )]


association_ppr_enabled = False
