"""Skill & tool library: categories, item→category assignments, and the import catalog.

Layout under ``<data>/library/``::

    state.json     categories + assignments + last organize report
    catalog.json   collected-but-not-installed entries (from inbox JSONL)
    inbox/         drop *.jsonl here (web GPT deliveries); imported files move to inbox/imported/
    skills/        catalog skills fetched on demand (<category>/<name>/SKILL.md)

Manual assignments are never touched by "一键整理"; everything else can be
re-derived at any time, so the state file is cheap to lose.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

import structlog

from atlas.library.search import keyword_hits
from atlas.library.taxonomy import ALIASES, OTHER_ID, builtin_categories

log = structlog.get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ITEM_TYPES = ("skill", "tool")
# A classifier gets (items, categories) and returns {"assign": {key: id}, "new_categories": [...]}.
Classifier = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[dict[str, Any]]]


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", str(value or "").lower()).strip("-")
    if slug:
        return slug[:48]
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
    return f"c-{digest}"


def _now() -> float:
    return round(time.time(), 3)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:  # noqa: BLE001 — a corrupt file must not take the library down
        log.warning("library.read_failed", path=str(path), exc_info=True)
        return default


def classify_text(item: dict[str, Any]) -> str:
    name = str(item.get("name", "")).replace("-", " ").replace("_", " ").replace(".", " ")
    return " ".join(str(part) for part in (
        name, item.get("server", ""), item.get("title", ""), item.get("description", ""),
        item.get("when_to_use", ""), " ".join(item.get("tags") or []),
    ) if part)


class LibraryStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.skills_dir = self.root / "skills"
        self._lock = threading.RLock()
        self._state = self._load_state()
        self._catalog: dict[str, dict[str, Any]] = _read_json(self.root / "catalog.json", {})
        self.version = 0

    # -- persistence -----------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        state = _read_json(self.root / "state.json", {})
        categories = state.get("categories") if isinstance(state.get("categories"), list) else []
        known = {row.get("id") for row in categories if isinstance(row, dict)}
        # New built-ins appear for existing users; renamed built-ins keep the user's name.
        for row in builtin_categories():
            if row["id"] not in known:
                categories.append(row)
        return {
            "categories": [row for row in categories if isinstance(row, dict) and row.get("id")],
            "assignments": state.get("assignments") if isinstance(state.get("assignments"), dict) else {},
            "last_report": state.get("last_report"),
        }

    def _save(self) -> None:
        self.version += 1
        _write_json(self.root / "state.json", self._state)

    def _save_catalog(self) -> None:
        self.version += 1
        _write_json(self.root / "catalog.json", self._catalog)

    # -- categories --------------------------------------------------------------

    def categories(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._state["categories"]]

    def category(self, category_id: str) -> dict[str, Any] | None:
        return next((row for row in self._state["categories"] if row["id"] == category_id), None)

    def add_category(self, name: str, *, description: str = "", category_id: str | None = None,
                     keywords: Iterable[str] = (), created_by: str = "user") -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise ValueError("分类名不能为空")
        with self._lock:
            existing = next((row for row in self._state["categories"]
                             if row["name"] == name or row["id"] == category_id), None)
            if existing is not None:
                return dict(existing)
            base = slugify(category_id or name)
            cid, n = base, 2
            while self.category(cid) is not None:
                cid, n = f"{base}-{n}", n + 1
            row = {"id": cid, "name": name, "description": str(description or "").strip(),
                   "keywords": [str(k) for k in keywords if str(k).strip()][:30],
                   "builtin": False, "created_by": created_by, "created_at": _now()}
            self._state["categories"].append(row)
            self._save()
            return dict(row)

    def update_category(self, category_id: str, *, name: str | None = None,
                        description: str | None = None) -> dict[str, Any]:
        with self._lock:
            row = self.category(category_id)
            if row is None:
                raise KeyError(category_id)
            if name is not None and name.strip():
                row["name"] = name.strip()
            if description is not None:
                row["description"] = description.strip()
            self._save()
            return dict(row)

    def delete_category(self, category_id: str) -> int:
        """Remove a category; its items become unorganized. Returns how many were released."""
        with self._lock:
            if category_id == OTHER_ID:
                raise ValueError("「其他」分类不能删除")
            if self.category(category_id) is None:
                raise KeyError(category_id)
            self._state["categories"] = [r for r in self._state["categories"] if r["id"] != category_id]
            released = [key for key, row in self._state["assignments"].items()
                        if row.get("category") == category_id]
            for key in released:
                del self._state["assignments"][key]
            self._save()
            return len(released)

    # -- assignments -------------------------------------------------------------

    def assignment(self, key: str) -> dict[str, Any] | None:
        row = self._state["assignments"].get(key)
        if row and self.category(str(row.get("category"))) is not None:
            return row
        return None

    def assign(self, key: str, category_id: str, *, by: str = "manual") -> None:
        with self._lock:
            if self.category(category_id) is None:
                raise KeyError(category_id)
            self._state["assignments"][key] = {"category": category_id, "by": by, "at": _now()}
            self._save()

    def clear_assignment(self, key: str) -> None:
        with self._lock:
            if self._state["assignments"].pop(key, None) is not None:
                self._save()

    def last_report(self) -> dict[str, Any] | None:
        return self._state.get("last_report")

    # -- catalog (collected, not installed) ----------------------------------------

    def catalog(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._catalog)

    def catalog_entry(self, key: str) -> dict[str, Any] | None:
        return self._catalog.get(key)

    @staticmethod
    def normalize_entry(row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("type") or "").strip().lower()
        if kind not in _ITEM_TYPES:
            raise ValueError("type 必须是 skill 或 tool")
        name = slugify(str(row.get("name") or ""))
        if name.startswith("c-") and not str(row.get("name") or "").lower().startswith("c-"):
            raise ValueError("name 无效")
        description = str(row.get("description_zh") or row.get("description") or "").strip()
        if not description:
            raise ValueError("缺少 description")
        entry = {k: v for k, v in row.items() if v not in (None, "", [], {})}
        entry.update({"type": kind, "name": name, "description": description})
        if row.get("description") and row.get("description_zh"):
            entry["description_en"] = str(row["description"]).strip()
        if kind == "skill" and not str(row.get("raw_url") or "").startswith("https://"):
            raise ValueError("技能缺少可下载的 raw_url")
        if kind == "tool":
            entry.setdefault("kind", "mcp")
            if not (row.get("install") or row.get("remote_url")):
                raise ValueError("工具缺少 install 或 remote_url")
        # Never keep secrets even if a collector pasted one by mistake.
        install = entry.get("install")
        if isinstance(install, dict) and isinstance(install.get("env"), dict):
            install["env"] = {k: "" for k in install["env"]}
        return entry

    def import_entries(self, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        added = updated = 0
        errors: list[str] = []
        with self._lock:
            for index, row in enumerate(rows, start=1):
                try:
                    entry = self.normalize_entry(row if isinstance(row, dict) else {})
                except ValueError as exc:
                    if len(errors) < 50:
                        errors.append(f"第 {index} 条（{(row or {}).get('name', '?') if isinstance(row, dict) else '?'}）：{exc}")
                    continue
                key = f"{entry['type']}:{entry['name']}"
                previous = self._catalog.get(key)
                if previous is None:
                    added += 1
                elif str(previous.get("last_updated", "")) > str(entry.get("last_updated", "")):
                    continue  # keep the fresher record
                else:
                    updated += 1
                entry["imported_at"] = _now()
                self._catalog[key] = entry
            if added or updated:
                self._save_catalog()
        return {"added": added, "updated": updated, "errors": errors, "total": len(self._catalog)}

    def import_text(self, text: str) -> dict[str, Any]:
        """Accept JSONL or a JSON array (what the web GPT taskbook produces)."""
        stripped = text.strip().lstrip("﻿")
        rows: list[Any]
        bad = 0
        if stripped.startswith("["):
            rows = json.loads(stripped)
        else:
            rows = []
            for line in stripped.splitlines():
                line = line.strip().rstrip(",")
                if not line or line.startswith("//"):
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    bad += 1
        result = self.import_entries(rows)
        if bad:
            result["errors"].insert(0, f"{bad} 行不是合法 JSON，已跳过")
        return result

    def import_inbox(self) -> dict[str, Any]:
        self.inbox.mkdir(parents=True, exist_ok=True)
        done = self.inbox / "imported"
        totals = {"files": 0, "added": 0, "updated": 0, "errors": [], "total": len(self._catalog)}
        for path in sorted(self.inbox.glob("*.json*")):
            try:
                result = self.import_text(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — report per file
                totals["errors"].append(f"{path.name}：{exc}")
                continue
            totals["files"] += 1
            totals["added"] += result["added"]
            totals["updated"] += result["updated"]
            totals["errors"].extend(f"{path.name} {err}" for err in result["errors"][:20])
            totals["total"] = result["total"]
            done.mkdir(exist_ok=True)
            os.replace(path, done / f"{int(time.time())}-{path.name}")
        return totals

    def remove_catalog_entry(self, key: str) -> bool:
        with self._lock:
            if self._catalog.pop(key, None) is None:
                return False
            self._save_catalog()
            return True

    # -- organize ------------------------------------------------------------------

    def _resolve_declared(self, declared: str, suggestion: str = "") -> tuple[str | None, str | None]:
        """Map a declared category to an id. Returns (id, unknown_label)."""
        raw = str(declared or "").strip()
        if not raw:
            return None, None
        if raw.lower().startswith("new:"):
            label, _, inline_name = raw[4:].strip().partition("|")
            name = (inline_name.strip() or str(suggestion or "").split("：")[0].split(":")[0].strip()
                    or label)
            row = self.add_category(name, category_id=label, description=str(suggestion or ""),
                                    created_by="import")
            return row["id"], None
        lowered = raw.lower()
        if self.category(lowered) is not None:
            return lowered, None
        named = next((r for r in self._state["categories"] if r["name"] == raw), None)
        if named is not None:
            return named["id"], None
        alias = ALIASES.get(lowered) or ALIASES.get(slugify(raw))
        if alias and self.category(alias) is not None:
            return alias, None
        return None, raw

    def _rule_scores(self, item: dict[str, Any]) -> list[tuple[int, str]]:
        text = classify_text(item)
        scores = []
        for row in self._state["categories"]:
            if row["id"] == OTHER_ID:
                continue
            words = [*row.get("keywords", []), row["name"]]
            score = keyword_hits(text, words)
            # The name/server carry more signal than a long description.
            score += keyword_hits(f"{item.get('name', '')} {item.get('server', '')}".replace("-", " ").replace("_", " "), words)
            if score:
                scores.append((score, row["id"]))
        scores.sort(reverse=True)
        return scores

    async def organize(self, items: list[dict[str, Any]], *, classifier: Classifier | None = None,
                       full: bool = False, batch_size: int = 30, concurrency: int = 4,
                       batch_timeout: float = 90.0) -> dict[str, Any]:
        """Put every unorganized item (or every non-manual one when ``full``) into a category."""
        started = time.time()
        report: dict[str, Any] = {"scanned": 0, "assigned": 0, "by_declared": 0, "by_rule": 0,
                                  "by_model": 0, "by_fallback": 0, "unchanged": 0,
                                  "new_categories": [], "moved": [], "model_error": None}
        before_ids = {row["id"] for row in self._state["categories"]}
        pending: list[tuple[dict[str, Any], str | None, list[tuple[int, str]]]] = []
        results: dict[str, tuple[str, str]] = {}
        with self._lock:
            for item in items:
                key = item["key"]
                current = self.assignment(key)
                if current and (current.get("by") == "manual" or not full):
                    continue
                report["scanned"] += 1
                declared, unknown = self._resolve_declared(
                    str(item.get("declared_category") or ""), str(item.get("category_suggestion") or ""),
                )
                if declared:
                    results[key] = (declared, "declared")
                    continue
                scores = self._rule_scores(item)
                if scores and scores[0][0] >= 2 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                    results[key] = (scores[0][1], "rule")
                    continue
                pending.append((item, unknown, scores))

        if pending and classifier is not None:
            chunks = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
            gate = asyncio.Semaphore(concurrency)

            async def run(chunk: list[Any]) -> tuple[list[Any], dict[str, Any] | None]:
                async with gate:
                    try:
                        answer = await asyncio.wait_for(
                            classifier([row[0] for row in chunk], self.categories()), timeout=batch_timeout,
                        )
                        return chunk, answer
                    except Exception as exc:  # noqa: BLE001 — this batch falls back to rules
                        report["model_error"] = (str(exc) or type(exc).__name__)[:300]
                        log.warning("library.organize_model_failed", error=str(exc))
                        return chunk, None

            for chunk, answer in await asyncio.gather(*(run(chunk) for chunk in chunks)):
                if answer is None:
                    continue
                with self._lock:
                    for proposal in answer.get("new_categories") or []:
                        if isinstance(proposal, dict) and str(proposal.get("name") or "").strip():
                            self.add_category(str(proposal["name"]), category_id=proposal.get("id"),
                                              description=str(proposal.get("description") or ""),
                                              keywords=proposal.get("keywords") or (), created_by="organize")
                    assign = answer.get("assign") or {}
                    for item, _unknown, _scores in chunk:
                        target = str(assign.get(item["key"]) or "").strip()
                        cid, _ = self._resolve_declared(target) if target else (None, None)
                        if cid:
                            results[item["key"]] = (cid, "model")

        with self._lock:
            # Tools of one MCP server usually belong together: follow the server's majority.
            by_server: dict[str, dict[str, int]] = {}
            for item in items:
                server = str(item.get("server") or "")
                cid = (results.get(item["key"]) or (None,))[0] or (self.assignment(item["key"]) or {}).get("category")
                if server and cid and cid != OTHER_ID:
                    by_server.setdefault(server, {})[cid] = by_server.setdefault(server, {}).get(cid, 0) + 1
            for item, unknown, scores in pending:
                if item["key"] in results:
                    continue
                votes = by_server.get(str(item.get("server") or ""))
                if votes:
                    results[item["key"]] = (max(votes.items(), key=lambda kv: kv[1])[0], "rule")
                    continue
                if scores and (len(scores) == 1 or scores[0][0] > scores[1][0]):
                    results[item["key"]] = (scores[0][1], "fallback")
                elif unknown:
                    # 没有对应的分类就新建一个：沿用条目自带的分类名。
                    row = self.add_category(unknown, created_by="organize")
                    results[item["key"]] = (row["id"], "fallback")
                else:
                    results[item["key"]] = (OTHER_ID, "fallback")
            names = {row["id"]: row["name"] for row in self._state["categories"]}
            by_key = {item["key"]: item for item in items}
            for key, (cid, how) in results.items():
                previous = self._state["assignments"].get(key, {}).get("category")
                if previous == cid:
                    report["unchanged"] += 1
                    continue
                self._state["assignments"][key] = {"category": cid, "by": how, "at": _now()}
                report["assigned"] += 1
                report[f"by_{how}"] += 1
                if len(report["moved"]) < 200:
                    report["moved"].append({"key": key, "name": by_key[key].get("name"),
                                            "from": names.get(previous), "to": names.get(cid), "by": how})
            report["new_categories"] = [
                {"id": row["id"], "name": row["name"]}
                for row in self._state["categories"] if row["id"] not in before_ids
            ]
            report["seconds"] = round(time.time() - started, 2)
            report["at"] = _now()
            self._state["last_report"] = report
            self._save()
        return report
