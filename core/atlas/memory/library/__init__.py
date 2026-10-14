"""Atlas memory library: the kernel-independent memory slot.

Every run calls :meth:`MemoryLibrary.recall` before the model sees the message and
:meth:`MemoryLibrary.observe_turn` after the reply; neither depends on which agent loop
(Atlas kernel, Hermes, anything later) produced the turn. See ``docs/memory/PLAN-V1.md``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from . import extract
from .index import MemoryIndex
from .forget import purge_history
from .queue import TurnQueue
from .store import (
    DIARY, ME, NOW, PEOPLE, RESIDENT_PAGES, SELF, SRC_EDITED, THINGS, Entry, MemoryStore, Page,
    is_expired, new_id, safe_name, tombstone_hashes,
)

log = structlog.get_logger(__name__)

RESIDENT_BUDGET_CHARS = 1500
RESIDENT_FLOOR_CHARS = 400
MAX_CUE_PAGES = 3
MAX_CUE_LINES = 6
MAX_SEARCH_FACTS = 3
SEARCH_MIN_SCORE = 0.18
_RECALL_INTENT = re.compile(
    r"上次|上回|之前|以前|还记得|记得吗|记不记得|我说过|跟你说过|那次|前几天|前阵子|那天|last time|remember",
    re.I,
)
INSTRUCTION = (
    "以下是 Atlas 记忆库里关于用户的记录，每条标了来源和日期。"
    "「你说的」「你改的」是用户本人确认过的；「推测」「它自己」不是用户说的。"
    "用户问到记录里没有的细节时，直接说不记得或不确定，绝不编造。"
    "和当前问题无关时不要硬提这些记忆。"
)

_SINGLETON: MemoryLibrary | None = None


def _now(config: Any = None) -> datetime:
    try:
        from atlas.time_context import now_local
        return now_local(config)
    except Exception:
        return datetime.now().astimezone()


def _label(entry_src: str, at: str) -> str:
    day = (at or "")[:10]
    return f"（{entry_src or '来源不明'}{' · ' + day if day else ''}）"


class MemoryLibrary:
    def __init__(self, root: Path, config: Any = None) -> None:
        self.store = MemoryStore(root)
        self.index = MemoryIndex(self.store)
        self.queue = TurnQueue(root)
        self.config = config
        self._turn_lock = asyncio.Lock()
        self._ready = False
        self._tasks: set[asyncio.Task[Any]] = set()

    # ---------- lifecycle ----------
    def ready(self) -> None:
        if not self._ready:
            self.store.ensure()
            self.index.sync()
            self._ready = True

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(f"memory.library.{key}", default) if self.config else default
        except Exception:
            return default

    # ---------- recall (before the model call) ----------
    def recall(self, message: str) -> dict[str, Any]:
        self.ready()
        self.index.sync()
        resident = self._resident_block()
        relevant, refs = self._relevant_block(message or "")
        return {
            "resident": resident,
            "relevant": relevant,
            "refs": refs,
            "system_block": f"{INSTRUCTION}\n\n{resident}" if resident else "",
        }

    def _resident_block(self) -> str:
        now = _now(self.config)
        prepared: list[tuple[str, list[str]]] = []
        selected: list[list[str]] = []
        used = 0
        for rel, title in ((ME, "关于你"), (NOW, "现状 / 进行中"), (SELF, "Atlas 自己")):
            entries = [e for e in self.store.read(rel).current if not is_expired(e, now)]
            entries.sort(key=lambda e: e.at, reverse=True)
            entries.sort(key=lambda e: -int(e.importance or 5))
            if rel == NOW:
                entries.sort(key=lambda e: e.until or "~")
            all_lines = []
            for entry in entries:
                line = f"- {entry.text}{_label(entry.src, entry.at)}"
                if entry.until:
                    line += f"（到 {entry.until[:16].replace('T', ' ')} 为止）"
                all_lines.append(line)
            prepared.append((title, all_lines))
            selected.append([])
        for i, (_title, lines) in enumerate(prepared):
            for line in lines:
                if sum(map(len, selected[i])) + len(line) > RESIDENT_FLOOR_CHARS:
                    continue
                selected[i].append(line)
                used += len(line)
        for i, (_title, lines) in enumerate(prepared):
            for line in lines:
                if line in selected[i] or used + len(line) > RESIDENT_BUDGET_CHARS:
                    continue
                selected[i].append(line)
                used += len(line)
        sections = [f"## {title}\n" + "\n".join(lines)
                    for (title, _), lines in zip(prepared, selected) if lines]
        return "\n\n".join(sections)

    def _relevant_block(self, message: str) -> tuple[str, list[str]]:
        parts: list[str] = []
        refs: list[str] = []
        now = _now(self.config)
        lowered = message.casefold()
        cue_pages = []
        for rel, names in self.index.entities():
            if any(name and name.casefold() in lowered for name in names):
                cue_pages.append(rel)
        for rel in cue_pages[:MAX_CUE_PAGES]:
            page = self.store.read(rel)
            current = [e for e in page.current if not is_expired(e, now)]
            lines = [f"- {e.text}{_label(e.src, e.at)}" for e in current[-MAX_CUE_LINES:]]
            if lines:
                alias = f"（也叫 {'、'.join(page.aliases)}）" if page.aliases else ""
                parts.append(f"## {page.title}{alias}\n" + "\n".join(lines))
                refs.extend(e.id for e in current[-MAX_CUE_LINES:])
        skip = set(RESIDENT_PAGES) | set(cue_pages)
        hits = [h for h in self.index.search(message, limit=MAX_SEARCH_FACTS * 2,
                                             kinds=("fact",), exclude_paths=tuple(skip), now=now)
                if h["score"] >= SEARCH_MIN_SCORE][:MAX_SEARCH_FACTS]
        if hits:
            parts.append("## 可能相关\n" + "\n".join(
                f"- {h['text']}{_label(h['src'], h['at'])}" for h in hits))
            refs.extend(h["id"] for h in hits)
        if _RECALL_INTENT.search(message):
            diary = [h for h in self.index.search(message, limit=3, kinds=("diary",), now=now)
                     if h["score"] > 0.05]
            if diary:
                parts.append("## 以前的对话记录（原文节选）\n" + "\n".join(
                    f"- [{h['at'][:16].replace('T', ' ')}] {' '.join(h['text'].split())[:240]}" for h in diary))
                refs.extend(h["id"] for h in diary)
        if not parts:
            return "", []
        return "Atlas 记忆库里和这句话有关的记录：\n\n" + "\n\n".join(parts), refs

    # ---------- search tool ----------
    def search(self, query: str, limit: int = 8, include_history: bool = False) -> list[dict[str, Any]]:
        self.ready()
        self.index.sync()
        keep = ("id", "path", "kind", "bucket", "text", "src", "at", "until", "quote", "score", "expired")
        return [{k: h.get(k) for k in keep}
                for h in self.index.search(query, limit=limit, include_history=include_history,
                                           now=_now(self.config))]

    # ---------- write (after the reply, in the background) ----------
    def schedule_turn(self, **kwargs: Any) -> None:
        user_text = (kwargs.get("user_text") or "").strip()
        if not user_text:
            return
        self.ready()
        self.queue.insert(created=_now(self.config).isoformat(timespec="seconds"),
                          session=kwargs.get("session", ""), mode=kwargs.get("mode", ""),
                          user_text=user_text, assistant_text=kwargs.get("assistant_text") or "")
        task = asyncio.create_task(self._drain(kwargs.get("model_mgr")))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain(self, model_mgr: Any) -> None:
        self.ready()
        async with self._turn_lock:
            for row in self.queue.pending():
                try:
                    now = datetime.fromisoformat(row["created"])
                    if row["stage"] == "new":
                        await asyncio.to_thread(self._write_diary, now, row["user_text"],
                                                row["assistant_text"], row["session"], row["mode"])
                        self.queue.stage_diary_done(row["id"])
                    result = await self.observe_turn(row, model_mgr, now)
                    self.queue.remove(row["id"])
                    log.info("memory.library.turn", session=row["session"], added=len(result.added),
                             changed=len(result.changed), ended=len(result.ended),
                             forgotten=len(result.forgotten), rejected=result.rejected)
                except Exception as exc:
                    self.queue.fail(row["id"], str(exc))
                    log.warning("memory.library.turn_failed", session=row["session"],
                                error=str(exc), error_type=type(exc).__name__)

    async def observe_turn(self, row: dict[str, Any], model_mgr: Any,
                           now: datetime) -> extract.ApplyResult:
        user_text, assistant_text = row["user_text"], row["assistant_text"]
        proposals: list[extract.Proposal] = []
        if len(user_text) >= 2 and model_mgr is not None:
            proposals = await self._extract(user_text, assistant_text, model_mgr, now)
        return await asyncio.to_thread(self._apply, proposals, user_text,
                                       row["session"], row["mode"], now)

    def _write_diary(self, now: datetime, user_text: str, assistant_text: str,
                     session: str, mode: str) -> None:
        self.ready()
        meta = '{"session":"%s"%s}' % (re.sub(r"[^\w-]", "", session)[:64],
                                       ',"mode":"expert"' if mode == "expert" else "")
        reply = " ".join((assistant_text or "").split())[:300]
        block = (f"## {now.strftime('%H:%M')}\n<!-- {meta} -->\n"
                 f"你：{user_text[:2000]}\n\n它：{reply or '（无文字回复）'}")
        if extract.contains_secret(block):
            block = f"## {now.strftime('%H:%M')}\n<!-- {meta} -->\n（这一轮含密码或密钥，未记录原文）"
        with self.store.lock:
            self.store.append_diary(now, block)

    def _model_id(self, model_mgr: Any) -> str:
        configured = str(self._cfg("writer_model", "") or "").strip()
        try:
            from atlas.config import load_user_settings
            settings = load_user_settings() or {}
        except Exception:
            settings = {}
        models = model_mgr.list_models()
        for candidate in (configured, settings.get("memory_model"),
                          settings.get("compression_model"), getattr(model_mgr, "current_model", None)):
            chosen = str(candidate or "").strip()
            if not chosen:
                continue
            match = next((m for m in models if chosen in {str(m.get("id") or ""),
                                                          str(m.get("litellm_model") or "")}), None)
            if match is not None:
                return str(match.get("id") or match.get("litellm_model"))
            if candidate == getattr(model_mgr, "current_model", None):
                return chosen
        raise RuntimeError("no memory writer model available")

    async def _extract(self, user_text: str, assistant_text: str, model_mgr: Any,
                       now: datetime) -> list[extract.Proposal]:
        router = getattr(model_mgr, "model_router", None)
        if router is None:
            return []
        model_id = self._model_id(model_mgr)
        known = await asyncio.to_thread(extract.known_facts, self.store)
        clock = f"{now.strftime('%Y-%m-%d %A %H:%M')} (UTC{now.strftime('%z')})"
        messages = extract.build_messages(user_text=user_text, assistant_text=assistant_text,
                                          known=known, clock=clock)
        result = await asyncio.wait_for(
            router.complete_for(model_id, "memory_library", messages, max_tokens=1200, temperature=0.1),
            timeout=float(self._cfg("writer_timeout_seconds", 90)),
        )
        return extract.parse_output(str(getattr(result, "text", "") or ""))

    def _apply(self, proposals: list[extract.Proposal], user_text: str, session: str,
               mode: str, now: datetime) -> extract.ApplyResult:
        with self.store.lock:
            ended = extract.expire(self.store, now)
            result = extract.apply(self.store, proposals, user_text=user_text,
                                   session=session, mode=mode, now=now)
            result.ended.extend(ended)
            message = result.message() if not result.empty else "日记"
            self.store.commit(message)
            if result.forgotten_texts:
                purge_history(self.store, result.forgotten_texts)
        self.index.sync()
        return result

    # ---------- user actions from the memory page ----------
    def edit_entry(self, entry_id: str, text: str) -> dict[str, Any]:
        text = " ".join((text or "").split())
        if not text:
            raise ValueError("内容不能为空")
        if extract.contains_secret(text):
            raise ValueError("看起来含有密码或密钥，记忆库不保存这类内容")
        with self.store.lock:
            found = self.store.find_entry(entry_id)
            if found is None:
                raise KeyError(entry_id)
            page, entry, _bucket = found
            before = entry.text
            entry.text, entry.src = text, SRC_EDITED
            if entry.key:
                entry.value = text
            entry.at = _now(self.config).isoformat(timespec="seconds")
            self.store.write(page)
            self.store.commit(f"你改了：{before} → {text}"[:400])
        self.index.sync()
        return {"id": entry_id, "text": text}

    def add_entry(self, rel: str, text: str) -> dict[str, Any]:
        rel = self._safe_rel(rel)
        text = " ".join((text or "").split())
        if not text or extract.contains_secret(text):
            raise ValueError("内容为空或含有密码、密钥")
        with self.store.lock:
            page = self.store.read(rel)
            entry = Entry(text=text, id=new_id(), src=SRC_EDITED,
                          at=_now(self.config).isoformat(timespec="seconds"))
            page.current.append(entry)
            self.store.write(page)
            self.store.commit(f"你加了：{text}"[:400])
        self.index.sync()
        return {"id": entry.id, "path": rel}

    def forget_entry(self, entry_id: str) -> dict[str, Any]:
        self.ready()
        with self.store.lock:
            found = self.store.find_entry(entry_id)
            if found is None:
                raise KeyError(entry_id)
            page, entry, bucket = found
            getattr(page, bucket).remove(entry)
            self.store.add_tombstones(tombstone_hashes(entry.key, entry.value, entry.text), "用户要求忘掉")
            self.store.write(page)
            diary_pages = self.store.redact_diary([entry.quote, entry.text, entry.value])
            self.store.commit("按你的要求忘掉了一条记忆")
            history = purge_history(self.store, [entry.text, entry.quote, entry.value])
        self.index.sync()
        return {"ok": True, "pages": [page.path], "diary_pages": diary_pages, "history": history,
                "not_covered": ["Atlas 的原始聊天记录（engine 会话库）", "你自己做的备份或同步副本"]}

    def set_aliases(self, rel: str, aliases: list[str]) -> None:
        rel = self._safe_rel(rel)
        with self.store.lock:
            page = self.store.read(rel)
            page.aliases = [a.strip() for a in aliases if a.strip()]
            self.store.write(page)
            self.store.commit(f"你改了 {page.title} 的别名")
        self.index.sync()

    def revert(self, sha: str) -> None:
        self.store.revert(sha)
        self.index.sync()

    def _safe_rel(self, rel: str) -> str:
        rel = (rel or "").replace("\\", "/").strip("/")
        if rel in RESIDENT_PAGES:
            return rel
        folder, _, name = rel.partition("/")
        if folder in (PEOPLE, THINGS) and name.endswith(".md") and "/" not in name:
            return f"{folder}/{safe_name(name[:-3])}.md"
        raise ValueError("unknown memory page")

    # ---------- views for the memory page ----------
    def page_view(self, rel: str) -> dict[str, Any]:
        self.ready()
        page = self.store.read(self._safe_rel(rel))
        return _page_dict(page)

    def overview(self) -> dict[str, Any]:
        self.ready()
        pages = []
        for rel in self.store.pages():
            page = self.store.read(rel)
            pages.append({"path": rel, "title": page.title, "kind": page.kind, "aliases": page.aliases,
                          "count": len(page.current), "history": len(page.history),
                          "updated": max((e.at for e in page.current + page.history if e.at), default="")})
        return {"root": str(self.store.root), "pages": pages}

    def changes(self, limit: int = 60, include_diary: bool = False) -> list[dict[str, Any]]:
        self.ready()
        rows = []
        for row in self.store.log(limit * 3 if not include_diary else limit):
            if not include_diary and row["message"] in ("日记", "记忆库建立"):
                continue
            files = self.store.show(row["sha"])
            files = [f for f in files if not f["path"].startswith(DIARY + "/") and not f["path"].startswith(".")]
            rows.append({**row, "files": files})
            if len(rows) >= limit:
                break
        return rows

    def today(self) -> dict[str, Any]:
        self.ready()
        start = _now(self.config).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        changes = [c for c in self.changes(limit=100) if c["time"] >= start]
        diary_turns = 0
        diary = self.store.root / DIARY / f"{_now(self.config).date().isoformat()}.md"
        if diary.exists():
            diary_turns = diary.read_text(encoding="utf-8").count("\n## ")
        return {
            "changes": changes,
            "now": _page_dict(self.store.read(NOW)),
            "turns": diary_turns,
            "pending_failed": self.queue.failed_count(),
        }


def _page_dict(page: Page) -> dict[str, Any]:
    def row(e: Entry) -> dict[str, Any]:
        return {"id": e.id, "text": e.text, "src": e.src, "at": e.at, "until": e.until,
                "quote": e.quote, "ended": e.ended, "why": e.why, "key": e.key}
    return {"path": page.path, "title": page.title, "kind": page.kind, "aliases": page.aliases,
            "current": [row(e) for e in page.current], "history": [row(e) for e in page.history],
            "notes": page.notes}


def get_library() -> MemoryLibrary | None:
    """Process-wide library, or None when ``[memory.library] enabled = false``."""
    global _SINGLETON
    from atlas.config import DATA_ROOT, get_config

    config = get_config()
    try:
        enabled = bool(config.get("memory.library.enabled", True))
    except Exception:
        enabled = True
    if not enabled:
        return None
    if _SINGLETON is None:
        root = str(config.get("memory.library.root", "") or "").strip()
        _SINGLETON = MemoryLibrary(Path(root) if root else DATA_ROOT / "data" / "memory", config)
    return _SINGLETON


__all__ = ["MemoryLibrary", "get_library", "INSTRUCTION"]
