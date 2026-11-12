"""Append-only supersede ledger: which memory record replaced which, and on whose words.

A memory entry the user later contradicts must not be deleted (only an explicit "忘掉"
removes anything) and must not keep the same weight as the statement that corrected it.
This module keeps that relationship as data instead of rewriting the Markdown pages: one
JSON line per event, stored next to the pages it talks about.

Why JSONL rather than a table in ``.index.sqlite``:

- the memory library's source of truth is human-readable Markdown under git; the person
  auditing ``我.md`` must be able to read and diff the ledger the same way, and
  ``MemoryStore.commit`` already puts every file in the root under version control;
- append-only is structural here. A line is written once and never rewritten, so a
  supersede event can not silently overwrite the record it marked (the reason
  ``.tombstones.jsonl`` and ``journey.jsonl`` are plain JSONL too);
- the search index is derived and git-ignored, so it is the wrong home for the only copy
  of an audit trail.

Records are also a snapshot: ``old_text`` / ``new_text`` keep the wording at the moment
the relationship was recorded, so the trail still reads correctly after the entry has
been edited. Removal of a pair is itself a record (``kind="retract"``), never a rewrite.

The one exception to append-only is forgetting, not correcting: a snapshot copies the
user's own words into a second file, so ``forget_entry`` also blanks them here (see
``redact``) and the git history purge can finish. Otherwise "忘掉" would leave the text
behind in a file nobody thinks to check. The pair itself always survives, so the trail
never claims two contradicting statements were never reconciled.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

#: File name inside the memory root (same directory as 我.md / 现状.md).
LEDGER = "supersede.jsonl"
KIND_SUPERSEDE = "supersede"
KIND_RETRACT = "retract"
MAX_QUOTE_CHARS = 800
MAX_TEXT_CHARS = 400

#: Serialises appends across threads; the library also holds ``store.lock``.
_LOCK = threading.RLock()


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass(frozen=True)
class Record:
    """One ledger line. ``kind="retract"`` uses ``old`` as the retracted record id."""

    id: str
    kind: str
    at: str
    old: str
    new: str = ""
    quote: str = ""
    ref: str = ""
    session: str = ""
    old_text: str = ""
    new_text: str = ""
    why: str = ""
    verified: bool = False

    @property
    def is_retract(self) -> bool:
        return self.kind == KIND_RETRACT

    def row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "at": self.at,
            "old": self.old,
            "new": self.new,
            "quote": self.quote,
            "ref": self.ref,
            "session": self.session,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "why": self.why,
            "verified": self.verified,
        }

    @classmethod
    def parse(cls, raw: str) -> Record | None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        old = _clean(data.get("old"), 120)
        if not old:
            return None
        kind = str(data.get("kind") or KIND_SUPERSEDE)
        if kind not in (KIND_SUPERSEDE, KIND_RETRACT):
            return None
        new = _clean(data.get("new"), 120)
        # A correction is not always a stored entry yet (memory is written after the turn
        # ends), so a pair may carry only the newer wording in ``new_text``.
        if kind == KIND_SUPERSEDE and not (new or _clean(data.get("new_text"), 120)):
            return None
        return cls(
            id=_clean(data.get("id"), 60) or "s_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10],
            kind=kind,
            at=_clean(data.get("at"), 40),
            old=old,
            new=new,
            quote=str(data.get("quote") or "")[:MAX_QUOTE_CHARS],
            ref=_clean(data.get("ref"), 200),
            session=_clean(data.get("session"), 200),
            old_text=str(data.get("old_text") or "")[:MAX_TEXT_CHARS],
            new_text=str(data.get("new_text") or "")[:MAX_TEXT_CHARS],
            why=_clean(data.get("why"), 400),
            verified=bool(data.get("verified", False)),
        )


class SupersedeLedger:
    """Read/write access to ``supersede.jsonl``; the only mutation is appending a line."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / LEDGER
        self._memo: tuple[tuple[int, int], list[Record]] | None = None

    # ---------- reading ----------
    def signature(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return (0, 0)

    def records(self) -> list[Record]:
        """Every line, in file order. Unreadable lines are skipped, never fatal."""
        signature = self.signature()
        if self._memo is not None and self._memo[0] == signature:
            return self._memo[1]
        rows: list[Record] = []
        if self.path.exists():
            try:
                text = self.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                log.warning("memory.supersede.unreadable", path=str(self.path))
                text = ""
            for raw in text.splitlines():
                if not raw.strip():
                    continue
                record = Record.parse(raw)
                if record is None:
                    log.warning("memory.supersede.bad_line", line=raw[:200])
                    continue
                rows.append(record)
        self._memo = (signature, rows)
        return rows

    def active(self) -> list[Record]:
        """Supersede pairs that still stand: retractions removed, later pair wins.

        A ``retract`` line names either one pairing record (``old`` is a record id) or a
        memory entry (``old`` is an entry id), which cancels every pair naming it on the
        older side. Record ids are ``s_``-prefixed and entry ids ``m_``-prefixed, so the
        two can never be confused.
        """
        rows = self.records()
        cancelled_records: set[str] = set()
        cancelled_entries: set[str] = set()
        for record in rows:
            if not record.is_retract:
                continue
            if record.old.partition("_")[0] == "s":
                cancelled_records.add(record.old)
            else:
                cancelled_entries.add(record.old)
        live: dict[str, Record] = {}
        for record in rows:
            if record.is_retract or record.id in cancelled_records or record.old in cancelled_entries:
                continue
            live[record.old] = record
        return list(live.values())

    def pairs(self) -> dict[str, str]:
        """``old id -> new id`` for every live pair."""
        return {record.old: record.new for record in self.active()}

    def count(self) -> int:
        return len(self.active())

    def resolve(self, entry_id: str, *, limit: int = 16) -> str:
        """Follow a supersede chain to the newest id; cycles stop at the first repeat."""
        seen = {entry_id}
        current = entry_id
        pairs = self.pairs()
        for _ in range(limit):
            nxt = pairs.get(current)
            if not nxt or nxt in seen:
                break
            seen.add(nxt)
            current = nxt
        return current

    def superseded_map(self) -> dict[str, str]:
        """``old id -> newest id in its chain`` for entries that are still superseded.

        An entry whose replacement was itself replaced stays superseded, and pointing at the
        end of the chain is what the caller actually wants to cite.
        """
        return {record.old: self.resolve(record.old) for record in self.active()}

    def retracted_ids(self) -> set[str]:
        return {record.old for record in self.records() if record.is_retract}

    def for_entry(self, entry_id: str) -> list[Record]:
        """Every live record naming this entry, on either side, newest last."""
        rows = [record for record in self.active()
                if entry_id in (record.old, record.new)]
        return sorted(rows, key=lambda record: record.at)

    def audit(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Full trail newest first, retractions included, so nothing is invisible."""
        rows = sorted(self.records(), key=lambda record: record.at, reverse=True)
        return [record.row() for record in rows[:max(1, limit)]]

    # ---------- writing (append only) ----------
    def append(self, *, kind: str, old: str, new: str = "", quote: str = "", ref: str = "",
               session: str = "", old_text: str = "", new_text: str = "", why: str = "",
               verified: bool = False) -> Record:
        record = Record(
            id="s_" + uuid.uuid4().hex[:10],
            kind=kind,
            at=_stamp(),
            old=_clean(old, 120),
            new=_clean(new, 120),
            quote=str(quote or "")[:MAX_QUOTE_CHARS],
            ref=_clean(ref, 200),
            session=_clean(session, 200),
            old_text=str(old_text or "")[:MAX_TEXT_CHARS],
            new_text=str(new_text or "")[:MAX_TEXT_CHARS],
            why=_clean(why, 400),
            verified=bool(verified),
        )
        if not record.old:
            raise ValueError("ledger record needs a target id")
        line = json.dumps(record.row(), ensure_ascii=False)
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._memo = None
        return record

    # ---------- the single exception to append-only ----------
    def redact(self, needles: list[str]) -> int:
        """Blank forgotten wording out of the snapshots. Returns how many lines changed.

        Append-only means no event is ever rewritten away, but a snapshot copies the user's
        own words into a second file, so "忘掉" has to reach it too: ``forget_entry`` already
        blanks the diary and rewrites the whole git history for exactly this reason, and a
        ledger that kept the text would quietly defeat that. Only the quoted wording is
        replaced, never the fact that a pair exists, so the trail stays truthful.

        This is the only function that rewrites the file, it is called only from
        ``forget_entry`` (the one user-initiated deletion path), and it is not reachable
        from the ledger API, the tool, or the HTTP router.
        """
        clean = sorted({item.strip() for item in needles if item and len(item.strip()) >= 2},
                       key=len, reverse=True)
        if not clean or not self.path.exists():
            return 0
        from .forget import REDACTED

        with _LOCK:
            original = self.path.read_text(encoding="utf-8", errors="replace")
            lines: list[str] = []
            changed = 0
            for raw in original.splitlines():
                new = raw
                for needle in clean:
                    new = new.replace(needle, REDACTED)
                if new != raw:
                    changed += 1
                lines.append(new)
            if not changed:
                return 0
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(self.path)
            self._memo = None
        return changed


__all__ = [
    "KIND_RETRACT",
    "KIND_SUPERSEDE",
    "LEDGER",
    "Record",
    "SupersedeLedger",
]
