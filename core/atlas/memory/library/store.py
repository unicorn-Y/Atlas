"""Transparent memory library: Markdown pages under ``data/memory`` versioned by git.

Layout follows OpenClaw memory-core (``USER.md`` / ``MEMORY.md`` / ``memory/YYYY-MM-DD.md``),
renamed for Atlas:

    我.md          facts about the user (always in context)
    现状.md        ongoing / temporary things (always in context)
    它自己.md      Atlas' own stances and mistakes (always in context, user-editable)
    人/<名字>.md   one page per person, with an alias line
    事/<名字>.md   one page per project or event
    日记/<date>.md raw per-turn log, searched on demand

The Markdown files are the source of truth; ``.index.sqlite`` is derived and rebuilt
from them. Each fact is one list line whose metadata rides in a trailing HTML comment
(OpenClaw's annotation style), so a person can edit the text in any editor.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ME, NOW, SELF = "我.md", "现状.md", "它自己.md"
PEOPLE, THINGS, DIARY = "人", "事", "日记"
EPISODES = "经历"
RESIDENT_PAGES = (ME, NOW, SELF)
TOMBSTONES = ".tombstones.jsonl"

# Who a fact came from. Only the first two are about the user's own word.
SRC_SAID, SRC_EDITED, SRC_GUESS, SRC_SELF = "你说的", "你改的", "推测", "它自己"
SRC_EPISODE = "经历"
SRC_DREAM = "整理"

_PAGE_HEADER = {
    ME: "关于你。每行一条，可以直接改；你改过的行会标成「你改的」。",
    NOW: "进行中、有时限的事。过了时间会自动移到历史。",
    SELF: "Atlas 自己：表过的态、犯过的错、和你之间的事。你也可以改。",
}
_ENTRY_RE = re.compile(r"^\s*[-*]\s+(?P<text>.*?)\s*(?:<!--\s*(?P<meta>\{.*\})\s*-->)?\s*$")
_ALIAS_RE = re.compile(r"^\s*别名[:：]\s*(?P<names>.+?)\s*$")
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Entry:
    text: str
    id: str = ""
    key: str = ""
    value: str = ""
    src: str = SRC_SAID
    at: str = ""
    ref: str = ""
    until: str = ""
    quote: str = ""
    session: str = ""
    mode: str = ""
    ended: str = ""
    why: str = ""
    importance: int = 5
    trigger: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    outcome: str = ""
    verified: bool = False
    decisions: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    source_level: str | None = None
    recorded_at: str = ""
    valid_from: str = ""
    valid_to: str = ""
    supersedes: list[str] = field(default_factory=list)
    retracts: list[str] = field(default_factory=list)
    source_ref: dict[str, Any] | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.source_level is None:
            self.source_level = {
                SRC_SAID: "user_assertion",
                SRC_EDITED: "user_assertion",
                SRC_GUESS: "model_inference",
            }.get(self.src, "legacy_unknown")
        if not self.recorded_at and self.at:
            self.recorded_at = self.at
        if not self.valid_to:
            self.valid_to = self.until

    def meta(self) -> dict[str, Any]:
        data = dict(self.extra_metadata)
        data.update({k: v for k, v in asdict(self).items()
                     if k not in ("text", "extra_metadata") and v not in ("", [], None)})
        if data.get("importance") == 5:
            data.pop("importance")
        return data

    def line(self) -> str:
        meta = json.dumps(self.meta(), ensure_ascii=False, separators=(",", ":"))
        # "--" would close the HTML comment early.
        meta = meta.replace("--", "-\\u002d")
        text = " ".join(self.text.split())
        return f"- {text} <!-- {meta} -->"

    @classmethod
    def parse(cls, raw: str) -> Entry | None:
        match = _ENTRY_RE.match(raw)
        if not match or not match.group("text"):
            return None
        text = match.group("text").strip()
        meta: dict[str, Any] = {}
        if match.group("meta"):
            try:
                meta = json.loads(match.group("meta"))
            except ValueError:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if not meta:
            # A line written by hand: the person owns it.
            return cls(text=text, id=stable_id(text), src=SRC_EDITED,
                       source_level="user_assertion")
        known = {k: v for k, v in meta.items() if k in cls.__dataclass_fields__ and k != "text"}
        unknown = {k: v for k, v in meta.items()
                   if k not in cls.__dataclass_fields__ and k != "text"}
        known["extra_metadata"] = unknown
        if "recorded_at" not in known:
            known["recorded_at"] = str(known.get("at") or "")
        if "valid_to" not in known:
            known["valid_to"] = str(known.get("until") or meta.get("expires") or "")
        entry = cls(text=text, **known)
        entry.id = entry.id or stable_id(text)
        return entry


@dataclass
class Page:
    path: str
    title: str
    aliases: list[str] = field(default_factory=list)
    current: list[Entry] = field(default_factory=list)
    history: list[Entry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        if self.path.startswith(PEOPLE + "/"):
            return "person"
        if self.path.startswith(THINGS + "/"):
            return "thing"
        if self.path.startswith(EPISODES + "/"):
            return "episode"
        return {ME: "me", NOW: "now", SELF: "self"}.get(self.path, "other")

    def render(self) -> str:
        lines = [f"# {self.title}"]
        header = _PAGE_HEADER.get(self.path)
        if header:
            lines.append(f"<!-- {header} -->")
        if self.aliases:
            lines.append(f"别名：{'、'.join(self.aliases)}")
        lines.extend(["", "## 现在"])
        lines.extend(entry.line() for entry in self.current)
        if self.notes:
            lines.append("")
            lines.extend(self.notes)
        if self.history:
            lines.extend(["", "## 历史"])
            lines.extend(entry.line() for entry in self.history)
        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def parse(cls, path: str, text: str) -> Page:
        page = cls(path=path, title=Path(path).stem)
        section = "现在"
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                page.title = stripped[2:].strip() or page.title
                continue
            if stripped.startswith("## "):
                section = "历史" if "历史" in stripped else "现在"
                continue
            if stripped.startswith("<!--") and stripped.endswith("-->") and "{" not in stripped:
                continue
            alias = _ALIAS_RE.match(raw)
            if alias:
                page.aliases = split_names(alias.group("names"))
                continue
            entry = Entry.parse(raw)
            if entry is not None:
                (page.history if section == "历史" else page.current).append(entry)
            elif stripped:
                page.notes.append(raw.rstrip())
        return page


def stable_id(text: str) -> str:
    return "m_" + hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()[:10]


def new_id() -> str:
    return "m_" + uuid.uuid4().hex[:10]


def split_names(raw: str) -> list[str]:
    return [name.strip() for name in re.split(r"[、,，/;；]", raw) if name.strip()]


def safe_name(name: str) -> str:
    cleaned = _BAD_NAME.sub("", name).strip().strip(".")
    return cleaned[:60] or "未命名"


def page_for_key(key: str, *, temporary: bool) -> str:
    """Map an extracted fact key to the page that owns it."""
    parts = key.split(".")
    if len(parts) >= 2 and parts[0] == "person":
        return f"{PEOPLE}/{safe_name(parts[1])}.md"
    if len(parts) >= 2 and parts[0] == "project":
        return f"{THINGS}/{safe_name(parts[1])}.md"
    if parts[0] == "self":
        return SELF
    return NOW if temporary else ME


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def tombstone_hashes(key: str, value: str, text: str) -> set[str]:
    hashes = {hashlib.sha256(("t\x1f" + _norm(text)).encode("utf-8")).hexdigest()}
    if key and value:
        hashes.add(hashlib.sha256(("kv\x1f" + key + "\x1f" + _norm(value)).encode("utf-8")).hexdigest())
    return hashes


def is_expired(entry_or_until: Entry | str, now: datetime) -> bool:
    until = entry_or_until.until if isinstance(entry_or_until, Entry) else entry_or_until
    if not until:
        return False
    try:
        expiry = datetime.fromisoformat(until)
        if expiry.tzinfo is None and now.tzinfo is not None:
            expiry = expiry.replace(tzinfo=now.tzinfo)
        return expiry <= now
    except (TypeError, ValueError):
        return False


class MemoryStore:
    """File + git access. One process-wide lock serialises every write."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.lock = threading.RLock()
        self._git_ok: bool | None = None

    # ---------- setup ----------
    def ensure(self) -> None:
        with self.lock:
            for sub in (PEOPLE, THINGS, DIARY, EPISODES):
                (self.root / sub).mkdir(parents=True, exist_ok=True)
            for name in RESIDENT_PAGES:
                path = self.root / name
                if not path.exists():
                    path.write_text(Page(path=name, title=Path(name).stem).render(), encoding="utf-8")
            ignore = self.root / ".gitignore"
            if not ignore.exists():
                ignore.write_text(".index.sqlite*\n", encoding="utf-8")
            ignore_text = ignore.read_text(encoding="utf-8")
            for pattern in (".queue.sqlite", ".git-before-forget-*", ".git-rewrite-tmp"):
                if pattern not in ignore_text.splitlines():
                    with ignore.open("a", encoding="utf-8") as handle:
                        if ignore_text and not ignore_text.endswith(("\n", "\r")):
                            handle.write("\n")
                        handle.write(pattern + "\n")
                    ignore_text += pattern + "\n"
            if self._git_available() and not self._git_healthy():
                # Missing, or left half-written by a killed process: `git init` is safe
                # on an existing directory and keeps whatever objects survived.
                self._git("init", "-q")
                self.commit("记忆库建立")
            if self._git_available() and self._git_healthy():
                self._git("config", "core.autocrlf", "false")

    def _git_healthy(self) -> bool:
        if not (self.root / ".git" / "HEAD").exists():
            return False
        result = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=self.root,
                                capture_output=True, timeout=30, check=False)
        return result.returncode == 0

    # ---------- pages ----------
    def read(self, rel: str) -> Page:
        path = self.root / rel
        if not path.exists():
            return Page(path=rel, title=Path(rel).stem)
        return Page.parse(rel, path.read_text(encoding="utf-8"))

    def write(self, page: Page) -> None:
        path = self.root / page.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(page.render(), encoding="utf-8")
        tmp.replace(path)

    def pages(self) -> list[str]:
        found = [name for name in RESIDENT_PAGES if (self.root / name).exists()]
        for sub in (PEOPLE, THINGS, EPISODES):
            folder = self.root / sub
            if folder.exists():
                found.extend(f"{sub}/{p.name}" for p in sorted(folder.glob("*.md")))
        return found

    def diary_pages(self) -> list[str]:
        folder = self.root / DIARY
        return [f"{DIARY}/{p.name}" for p in sorted(folder.glob("*.md"))] if folder.exists() else []

    def find_entry(self, entry_id: str) -> tuple[Page, Entry, str] | None:
        for rel in self.pages():
            page = self.read(rel)
            for bucket in ("current", "history"):
                for entry in getattr(page, bucket):
                    if entry.id == entry_id:
                        return page, entry, bucket
        return None

    def append_diary(self, when: datetime, block: str) -> str:
        rel = f"{DIARY}/{when.date().isoformat()}.md"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {when.date().isoformat()}\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n" + block.rstrip() + "\n")
        return rel

    def redact_diary(self, needles: list[str]) -> int:
        """Blank out forgotten text in the raw diary so search cannot bring it back."""
        needles = sorted({n.strip() for n in needles if n and len(n.strip()) >= 2},
                         key=len, reverse=True)
        changed = 0
        for rel in [*self.diary_pages(),
                    *(f"{EPISODES}/{p.name}" for p in sorted((self.root / EPISODES).glob("*.md")))]:
            path = self.root / rel
            text = path.read_text(encoding="utf-8")
            new = text
            for needle in needles:
                new = new.replace(needle, "（已按你的要求忘掉）")
            if new != text:
                path.write_text(new, encoding="utf-8")
                changed += 1
        return changed

    # ---------- tombstones ----------
    def tombstoned(self, hashes: set[str]) -> bool:
        path = self.root / TOMBSTONES
        if not path.exists() or not hashes:
            return False
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(raw).get("h") in hashes:
                    return True
            except ValueError:
                continue
        return False

    def add_tombstones(self, hashes: set[str], reason: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with (self.root / TOMBSTONES).open("a", encoding="utf-8") as handle:
            for value in sorted(hashes):
                handle.write(json.dumps({"h": value, "at": stamp, "why": reason}, ensure_ascii=False) + "\n")

    # ---------- git ----------
    def _git_available(self) -> bool:
        if self._git_ok is None:
            try:
                subprocess.run(["git", "--version"], capture_output=True, check=True, timeout=10)
                self._git_ok = True
            except (OSError, subprocess.SubprocessError):
                self._git_ok = False
        return self._git_ok

    def _git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", "-c", "user.name=Atlas", "-c", "user.email=atlas@localhost",
             "-c", "core.quotepath=false", "-c", "i18n.logOutputEncoding=utf-8", *args],
            cwd=self.root, capture_output=True, timeout=60, check=False,
        )
        out = result.stdout.decode("utf-8", errors="replace")
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or out)
        return out

    def commit(self, message: str) -> str | None:
        if not self._git_available():
            return None
        with self.lock:
            self._git("-c", "core.autocrlf=false", "add", "-A")
            if not self._git("status", "--porcelain").strip():
                return None
            self._git("commit", "-q", "-m", message)
            return self._git("rev-parse", "HEAD").strip()

    def log(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._git_available() or not (self.root / ".git").exists():
            return []
        out = self._git("log", f"-n{int(limit)}", "--format=%H%x1f%at%x1f%s%x1e", check=False)
        rows = []
        for record in out.split("\x1e"):
            parts = record.strip().split("\x1f")
            if len(parts) == 3:
                rows.append({"sha": parts[0], "time": int(parts[1]), "message": parts[2]})
        return rows

    def show(self, sha: str) -> list[dict[str, Any]]:
        """Readable diff of one commit: per file, removed and added fact texts."""
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            raise ValueError("bad commit id")
        out = self._git("show", "--format=", "--unified=0", "--no-color", sha, check=False)
        files: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw in out.splitlines():
            if raw.startswith("diff --git "):
                current = {"path": raw.split(" b/", 1)[-1].strip(), "added": [], "removed": []}
                files.append(current)
            elif raw.startswith(("+++ ", "--- ")):
                continue
            elif current is not None and raw[:1] in "+-":
                entry = Entry.parse(raw[1:])
                text = entry.text if entry else raw[1:].strip()
                if not text or text.startswith(("#", "<!--")):
                    continue
                if text == "（已按你的要求忘掉）" or self.tombstoned(tombstone_hashes("", "", text)):
                    continue
                if raw[0] == "+" and entry is not None and entry.ended:
                    current.setdefault("ended", []).append(text)
                else:
                    current["added" if raw[0] == "+" else "removed"].append(text)
        for f in files:
            ended = f.setdefault("ended", [])
            # A line whose text survives on both sides only changed metadata.
            same = set(f["added"]) & set(f["removed"])
            f["added"] = [t for t in f["added"] if t not in same]
            f["removed"] = [t for t in f["removed"] if t not in same and t not in ended]
        return [f for f in files if f["added"] or f["removed"] or f["ended"]]

    def revert(self, sha: str) -> str | None:
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            raise ValueError("bad commit id")
        with self.lock:
            message = "这次变动里有你要求忘掉的内容，不能撤销"
            if not self._git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False).strip():
                raise ValueError(message)
            for file in self.show(sha):
                if any(self.tombstoned(tombstone_hashes("", "", text))
                       for text in file.get("removed", [])):
                    raise ValueError(message)
            try:
                self._git("revert", "--no-edit", sha)
            except RuntimeError:
                self._git("revert", "--abort", check=False)
                raise
            for rel in self.pages():
                if any(entry.text == "（已按你的要求忘掉）" or
                       self.tombstoned(tombstone_hashes(entry.key, entry.value, entry.text))
                       for entry in self.read(rel).current):
                    self._git("reset", "--hard", "HEAD~1")
                    raise ValueError(message)
            return self._git("rev-parse", "HEAD").strip()
