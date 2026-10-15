"""Derived search index over the memory library (rebuildable from the Markdown files).

Ported from OpenClaw memory-core:
- ``tokenize`` follows ``extensions/memory-core/src/memory/tokenize.ts`` (words, plus
  bigrams only inside runs of CJK characters), so two-character Chinese words such as
  "老王" or "面试" are searchable; SQLite's trigram tokenizer alone cannot match them.
- the provenance columns follow ``memory-schema-provenance.ts``: ``origin_class`` is set
  by code from the entry's source, never by the model, and unknown provenance is
  ``untrusted``.
- ranking is relevance x recency decay (30-day half-life for diary pages only) x importance.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import sqlite3
import struct
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import (
    DIARY,
    EPISODES,
    SRC_DREAM,
    SRC_EDITED,
    SRC_EPISODE,
    SRC_SAID,
    SRC_SELF,
    MemoryStore,
    Page,
    is_expired,
)

_CJK = r"぀-ゟ゠-ヿ㐀-䶿一-鿿가-힯"
_CJK_RUN = re.compile(f"[{_CJK}]+")
_WORD = re.compile(r"[^\W_][\w]*", re.UNICODE)
HALF_LIFE_DAYS = 30.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
  rowid INTEGER PRIMARY KEY,
  id TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,            -- fact | diary
  bucket TEXT NOT NULL,          -- current | history | diary
  text TEXT NOT NULL,
  key TEXT, src TEXT, at TEXT, until TEXT, quote TEXT, mode TEXT,
  ref TEXT,
  importance INTEGER NOT NULL DEFAULT 5,
  trigger TEXT,
  tokens TEXT NOT NULL,
  origin_class TEXT NOT NULL CHECK (origin_class IN ('owner','agent','untrusted','system','episode')),
  observed_at TEXT
);
CREATE INDEX IF NOT EXISTS items_path ON items(path);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(body, tokenize='trigram');
"""


def tokenize(text: str) -> set[str]:
    lower = (text or "").casefold()
    tokens = set(_WORD.findall(_CJK_RUN.sub(" ", lower)))
    for run in _CJK_RUN.findall(lower):
        if len(run) == 1:
            tokens.add(run)
        tokens.update(run[i - 1:i + 1] for i in range(1, len(run)))
    return tokens


def origin_class(src: str) -> str:
    if src == SRC_EPISODE:
        return "episode"
    if src in (SRC_SAID, SRC_EDITED):
        return "owner"
    if src == SRC_DREAM:
        return "system"
    if src:
        return "agent"
    return "untrusted"


def _diary_blocks(text: str) -> list[tuple[str, str]]:
    """Split a diary page into (heading, body) blocks at each ``## HH:MM`` heading."""
    blocks: list[tuple[str, str]] = []
    head, body = "", []
    for raw in text.splitlines():
        if raw.startswith("## "):
            if body:
                blocks.append((head, "\n".join(body).strip()))
            head, body = raw[3:].strip(), []
        elif not raw.startswith("# "):
            body.append(raw)
    if body and "\n".join(body).strip():
        blocks.append((head, "\n".join(body).strip()))
    return blocks


class MemoryIndex:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.path = store.root / ".index.sqlite"
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._idf_cache: tuple[int, dict[str, float]] | None = None
        self._embedding_task: asyncio.Task[Any] | None = None
        self._embedding_state = "building"
        self._vector_cache: dict[str, list[dict[str, Any]]] = {}
        self._vector_matrix_cache: dict[tuple[str, int], tuple[list[dict[str, Any]], Any, Any]] | None = None
        self._entities_cache: list[tuple[str, list[str]]] | None = None

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.executescript(_SCHEMA)
            schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='items'").fetchone()[0]
            if "'episode'" not in schema:
                db.executescript("""
                    ALTER TABLE items RENAME TO items_old;
                    CREATE TABLE items_new (
                      rowid INTEGER PRIMARY KEY, id TEXT NOT NULL, path TEXT NOT NULL,
                      kind TEXT NOT NULL, bucket TEXT NOT NULL, text TEXT NOT NULL,
                      key TEXT, src TEXT, at TEXT, until TEXT, quote TEXT, mode TEXT, ref TEXT,
                      importance INTEGER NOT NULL DEFAULT 5, trigger TEXT, tokens TEXT NOT NULL,
                      origin_class TEXT NOT NULL CHECK (origin_class IN ('owner','agent','untrusted','system','episode')),
                      observed_at TEXT
                    );
                    INSERT INTO items_new(id,path,kind,bucket,text,key,src,at,until,quote,mode,
                      importance,trigger,tokens,origin_class,observed_at)
                    SELECT id,path,kind,bucket,text,key,src,at,until,quote,mode,
                      importance,trigger,tokens,origin_class,observed_at FROM items_old;
                    DROP TABLE items_old;
                    ALTER TABLE items_new RENAME TO items;
                    CREATE INDEX IF NOT EXISTS items_path ON items(path);
                """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
            if "ref" not in columns:
                db.execute("ALTER TABLE items ADD COLUMN ref TEXT")
            db.execute(
                "CREATE TABLE IF NOT EXISTS vectors("
                "id TEXT PRIMARY KEY, dim INTEGER NOT NULL, vec BLOB NOT NULL, text_hash TEXT NOT NULL)"
            )
            self._db = db
        return self._db

    # ---------- sync ----------
    def sync(self) -> int:
        """Re-index every file whose content hash changed; drop vanished files."""
        with self._lock:
            db = self._conn()
            known = {row["path"]: row["sha"] for row in db.execute("SELECT path, sha FROM files")}
            present = self.store.pages() + self.store.diary_pages()
            changed = 0
            for rel in present:
                try:
                    raw = (self.store.root / rel).read_bytes()
                except OSError:
                    continue
                sha = hashlib.sha1(raw).hexdigest()
                if known.get(rel) == sha:
                    continue
                self._reindex(db, rel, raw.decode("utf-8", errors="replace"))
                db.execute("INSERT OR REPLACE INTO files(path, sha) VALUES(?, ?)", (rel, sha))
                changed += 1
            for rel in set(known) - set(present):
                self._drop(db, rel)
                db.execute("DELETE FROM files WHERE path = ?", (rel,))
                changed += 1
            if changed:
                db.commit()
                self._idf_cache = None
                self._vector_cache.clear()
                self._vector_matrix_cache = None
                self._entities_cache = None
            self._schedule_embeddings()
            return changed

    def rebuild(self) -> None:
        with self._lock:
            db = self._conn()
            db.executescript("DELETE FROM items; DELETE FROM items_fts; DELETE FROM files;")
            db.commit()
        self.sync()

    def _drop(self, db: sqlite3.Connection, rel: str) -> None:
        rows = [row["rowid"] for row in db.execute("SELECT rowid FROM items WHERE path = ?", (rel,))]
        ids = [row["id"] for row in db.execute("SELECT id FROM items WHERE path = ?", (rel,))]
        db.executemany("DELETE FROM items_fts WHERE rowid = ?", [(r,) for r in rows])
        db.executemany("DELETE FROM vectors WHERE id = ?", [(item_id,) for item_id in ids])
        db.execute("DELETE FROM items WHERE path = ?", (rel,))

    def _insert(self, db: sqlite3.Connection, row: dict[str, Any]) -> None:
        searchable = " ".join(filter(None, [row.get("search_text") or row["text"],
                                             row.get("quote") or "", row.get("trigger") or ""]))
        row["tokens"] = " ".join(sorted(tokenize(searchable)))
        cur = db.execute(
            "INSERT INTO items(id, path, kind, bucket, text, key, src, at, until, quote, mode, ref,"
            " importance, trigger, tokens, origin_class, observed_at)"
            " VALUES(:id, :path, :kind, :bucket, :text, :key, :src, :at, :until, :quote, :mode, :ref,"
            " :importance, :trigger, :tokens, :origin_class, :observed_at)",
            row,
        )
        db.execute("INSERT INTO items_fts(rowid, body) VALUES(?, ?)", (cur.lastrowid, searchable))

    def _reindex(self, db: sqlite3.Connection, rel: str, text: str) -> None:
        self._drop(db, rel)
        if rel.startswith(DIARY + "/"):
            day = Path(rel).stem
            for n, (head, body) in enumerate(_diary_blocks(text)):
                mode = "expert" if '"mode":"expert"' in body else ""
                ref_match = re.search(r'"ref":"([^"\\]*)"', body)
                clean = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
                if not clean:
                    continue
                self._insert(db, {
                    "id": f"d_{day}_{n}", "path": rel, "kind": "diary", "bucket": "diary",
                    "text": clean, "key": "", "src": "", "at": f"{day}T{head or '00:00'}",
                    "until": "", "quote": "", "mode": mode,
                    "ref": ref_match.group(1) if ref_match else "", "importance": 5, "trigger": "",
                    "origin_class": "system", "observed_at": day,
                })
            return
        page = Page.parse(rel, text)
        if rel.startswith(EPISODES + "/"):
            for entry in page.current:
                self._insert(db, {
                    "id": entry.id, "path": rel, "kind": "episode", "bucket": "current",
                    "text": entry.text, "search_text": " ".join([entry.text, entry.outcome,
                                                                     *entry.trigger]),
                    "key": "", "src": entry.src, "at": entry.at, "until": "",
                    "quote": "", "mode": entry.mode, "ref": entry.ref, "importance": 5,
                    "trigger": " ".join(entry.trigger), "origin_class": origin_class(entry.src),
                    "observed_at": entry.at,
                })
            return
        names = [page.title, *page.aliases] if page.kind in ("person", "thing") else []
        for bucket in ("current", "history"):
            for entry in getattr(page, bucket):
                self._insert(db, {
                    "id": entry.id, "path": rel,
                    "kind": "dream" if entry.src == SRC_DREAM else "fact", "bucket": bucket,
                    "text": entry.text, "key": entry.key, "src": entry.src, "at": entry.at,
                    "until": entry.until, "quote": entry.quote, "mode": entry.mode, "ref": entry.ref,
                    "importance": int(entry.importance or 5),
                    "trigger": " ".join([*entry.trigger, *names]),
                    "origin_class": origin_class(entry.src), "observed_at": entry.at,
                })

    # ---------- search ----------
    def _idf(self, db: sqlite3.Connection) -> dict[str, float]:
        total = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if self._idf_cache and self._idf_cache[0] == total:
            return self._idf_cache[1]
        counts: dict[str, int] = {}
        for row in db.execute("SELECT tokens FROM items"):
            for token in row["tokens"].split():
                counts[token] = counts.get(token, 0) + 1
        idf = {t: math.log(1 + total / c) for t, c in counts.items()}
        self._idf_cache = (total, idf)
        return idf

    def _keyword_search(self, query: str, *, limit: int = 8, kinds: tuple[str, ...] = ("fact", "diary"),
               include_history: bool = False, now: datetime | None = None,
               exclude_paths: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        with self._lock:
            db = self._conn()
            idf = self._idf(db)
            useful = {t for t in q_tokens if t in idf}
            if not useful:
                return []
            long_terms = [t for t in useful if len(t) >= 3]
            short_terms = [t for t in useful if len(t) < 3]
            rowids: set[int] = set()
            if long_terms:
                match = " OR ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
                rowids.update(r[0] for r in db.execute(
                    "SELECT rowid FROM items_fts WHERE items_fts MATCH ? LIMIT 400", (match,)))
            for term in short_terms:
                rowids.update(r[0] for r in db.execute(
                    "SELECT rowid FROM items WHERE (' ' || tokens || ' ') LIKE ? LIMIT 400",
                    (f"% {term} %",)))
            if not rowids:
                return []
            marks = ",".join("?" * len(rowids))
            rows = [dict(r) for r in db.execute(f"SELECT * FROM items WHERE rowid IN ({marks})", list(rowids))]
        now = now or datetime.now().astimezone()
        excluded = set(exclude_paths)
        q_weight = sum(idf[t] for t in useful) or 1.0
        results = []
        for row in rows:
            if (row["kind"] not in kinds or row["path"] in excluded or
                    (row["bucket"] == "history" and not include_history)):
                continue
            expired = is_expired(row["until"], now)
            if expired and not include_history:
                continue
            item_tokens = set(row["tokens"].split())
            hit = useful & item_tokens
            if not hit:
                continue
            item_weight = sum(idf.get(t, 0.0) for t in item_tokens) or 1.0
            matched = sum(idf[t] for t in hit)
            # Harmonic blend of "how much of the query" and "how much of the item" matched.
            q_cov, i_cov = matched / q_weight, matched / item_weight
            relevance = 2 * q_cov * i_cov / (q_cov + i_cov)
            importance = 1.0 + (int(row["importance"] or 5) - 5) / 10.0
            row["score"] = round(relevance * importance, 4)
            row["matched"] = sorted(hit)
            if expired:
                row["expired"] = True
            row.pop("tokens", None)
            results.append(row)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def _schedule_embeddings(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._embedding_task is None or self._embedding_task.done():
            self._embedding_state = "building"
            self._embedding_task = loop.create_task(asyncio.to_thread(self.embed_missing))

    def embed_missing(self) -> int:
        from .embed import embed_texts

        added = 0
        try:
            db = self._conn()
            rows = []
            for row in db.execute("SELECT i.id,i.text,v.text_hash FROM items i LEFT JOIN vectors v ON i.id=v.id"):
                row = dict(row)
                digest = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
                if row["text_hash"] != digest:
                    rows.append(row)
            rows = rows[:100000]
            for start in range(0, len(rows), 64):
                batch = rows[start:start + 64]
                vectors = embed_texts([row["text"] for row in batch])
                if vectors is None:
                    self._embedding_state = "unavailable"
                    return added
                with self._lock:
                    for row, vector in zip(batch, vectors):
                        packed = struct.pack(f"{len(vector)}f", *vector)
                        db.execute("INSERT OR REPLACE INTO vectors(id,dim,vec,text_hash) VALUES(?,?,?,?)",
                                   (row["id"], len(vector), packed,
                                    hashlib.sha256(row["text"].encode("utf-8")).hexdigest()))
                    db.commit()
                added += len(batch)
            if added:
                self._vector_cache.clear()
                self._vector_matrix_cache = None
            self._embedding_state = "ready"
            return added
        except Exception:  # noqa: BLE001 - vector failures must not take down lexical search.
            self._embedding_state = "unavailable"
            return added

    @property
    def embedding_state(self) -> str:
        if self._embedding_task is not None and not self._embedding_task.done():
            return "building"
        return self._embedding_state

    def _vector_search(self, query: str, *, kinds: tuple[str, ...], include_history: bool,
                       now: datetime, exclude_paths: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = self._vector_cache.get(query)
        if rows is None:
            from .embed import embed_texts

            vectors = embed_texts([query])
            if not vectors:
                return []
            import numpy as np

            q = np.asarray(vectors[0], dtype=np.float32)
            qnorm = float(np.linalg.norm(q))
            if not qnorm:
                return []
            if self._vector_matrix_cache is None:
                grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
                with self._lock:
                    for source in self._conn().execute(
                        "SELECT i.*,v.dim,v.vec FROM items i JOIN vectors v ON i.id=v.id"
                    ):
                        row = dict(source)
                        grouped.setdefault((row["kind"], int(row["dim"])), []).append(row)
                matrices = {}
                for key, candidates in grouped.items():
                    matrix = np.stack([
                        np.frombuffer(row["vec"], dtype=np.float32) for row in candidates
                    ])
                    matrices[key] = (candidates, matrix, np.linalg.norm(matrix, axis=1))
                self._vector_matrix_cache = matrices
            if not self._vector_matrix_cache:
                return []
            rows = []
            for (kind, dim), (candidates, matrix, norms) in self._vector_matrix_cache.items():
                if dim != q.size:
                    continue
                scores = np.divide(matrix @ q, norms * qnorm,
                                   out=np.zeros(len(candidates), dtype=np.float32), where=norms > 0)
                size = min(400, len(candidates))
                top = np.argpartition(scores, -size)[-size:]
                top = top[np.argsort(scores[top])[::-1]]
                for index in top:
                    row = dict(candidates[int(index)])
                    row["vector_score"] = max(0.0, float(scores[index]))
                    row.pop("vec", None)
                    rows.append(row)
            self._vector_cache[query] = rows
            if len(self._vector_cache) > 8:
                self._vector_cache.pop(next(iter(self._vector_cache)))
        excluded = set(exclude_paths)
        results = [row for row in rows if row["kind"] in kinds and row["path"] not in excluded
                   and (include_history or (row["bucket"] != "history" and not is_expired(row["until"], now)))]
        results.sort(key=lambda row: row["vector_score"], reverse=True)
        return results[:400]

    def search(self, query: str, *, limit: int = 8, kinds: tuple[str, ...] = ("fact", "diary"),
               include_history: bool = False, now: datetime | None = None,
               exclude_paths: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        from .hybrid import merge_scores

        now = now or datetime.now().astimezone()
        requested = tuple(k for k in kinds if k != "raw")
        keyword = self._keyword_search(query, limit=400, kinds=requested,
                                       include_history=include_history, now=now,
                                       exclude_paths=exclude_paths) if requested else []
        vector = self._vector_search(query, kinds=requested, include_history=include_history,
                                     now=now, exclude_paths=exclude_paths) if requested else []
        include_raw = "raw" in kinds
        results = merge_scores(keyword, vector, now=now, limit=400 if include_raw else limit)
        if include_raw:
            from .sources import search_raw

            results.extend(search_raw(query, limit))
            results.sort(key=lambda row: float(row.get("score", 0)), reverse=True)
            results = results[:limit]
        return results

    def facts(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            db = self._conn()
            if paths:
                marks = ",".join("?" * len(paths))
                cur = db.execute(
                    f"SELECT * FROM items WHERE kind='fact' AND bucket='current' AND path IN ({marks})", paths)
            else:
                cur = db.execute("SELECT * FROM items WHERE kind='fact' AND bucket='current'")
            return [dict(r) for r in cur]

    def entities(self) -> list[tuple[str, list[str]]]:
        """(page path, names) for every person / thing page, used for cue triggering."""
        with self._lock:
            if self._entities_cache is None:
                self._entities_cache = []
                for rel in self.store.pages():
                    if rel.startswith(("人/", "事/")):
                        page = self.store.read(rel)
                        self._entities_cache.append((rel, [page.title, *page.aliases]))
            return list(self._entities_cache)


__all__ = ["MemoryIndex", "tokenize", "origin_class", "SRC_SELF"]
