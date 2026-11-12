"""Atlas memory library: the kernel-independent memory slot.

Every run calls :meth:`MemoryLibrary.recall` before the model sees the message and
:meth:`MemoryLibrary.observe_turn` after the reply; neither depends on which agent loop
(Atlas kernel, Hermes, anything later) produced the turn. See ``docs/memory/PLAN-V1.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from . import extract
from .index import MemoryIndex
from .forget import purge_history
from .queue import TurnQueue
from .store import (
    DIARY, EPISODES, ME, NOW, PEOPLE, RESIDENT_PAGES, SELF, SRC_EDITED, SRC_EPISODE, SRC_SAID, THINGS, Entry,
    MemoryStore, Page, is_expired, new_id, safe_name, tombstone_hashes,
)
from .supersede import KIND_RETRACT, KIND_SUPERSEDE, SupersedeLedger

log = structlog.get_logger(__name__)

RESIDENT_BUDGET_CHARS = 1500
RESIDENT_FLOOR_CHARS = 400
MAX_CUE_PAGES = 3
MAX_CUE_LINES = 6
MAX_SEARCH_FACTS = 3
SEARCH_MIN_SCORE = 0.18
_DEFAULT_WORKSPACE_PATTERNS = [r"[\\/]\.tmp[\\/]", r"[\\/]audit[-_]", r"pytest", r"[\\/]Temp[\\/]"]
_DEFAULT_TEXT_PATTERNS = [r"ATLAS_AUDIT", r"^\s*\[[^\]]*(补测|审计|测试|audit|smoke)[^\]]*\]",
                          r"这是(隔离运行|只读权限|受控的长任务)?.{0,6}测试"]
_RECALL_INTENT = re.compile(
    r"刚才|上次|上回|之前|以前|还记得|记得吗|记不记得|我说过|跟你说过|那次|前几天|前阵子|那天|"
    r"记得我|记住了什么|你知道我|聊过|做过|last time|remember",
    re.I,
)
INSTRUCTION = (
    "以下是 Atlas 记忆库里关于用户的记录，每条标了来源和日期。"
    "「你说的」「你改的」是用户本人确认过的；「推测」「它自己」不是用户说的。"
    "「整理」是 Atlas 自己归纳的，以出处原文为准。"
    "用户问到记录里没有的细节时，直接说不记得或不确定，绝不编造。"
    "「经历」是 Atlas 根据对话自己整理的，说明聊过和做过什么，不是用户确认过的事实；回答「之前怎么做的」时，要分清哪些步骤真验证过。"
    "和当前问题无关时不要硬提这些记忆。"
    "标着「已过时 · 已被…取代」的旧说法仍然留着可查，但一律以新说法为准，不要拿旧的说事。"
)

_SINGLETON: MemoryLibrary | None = None


class ModelUnavailable(RuntimeError):
    """The turn is durable but cannot be extracted until a writer model is ready."""


def _now(config: Any = None) -> datetime:
    try:
        from atlas.time_context import now_local
        return now_local(config)
    except Exception:
        return datetime.now().astimezone()


def _label(entry_src: str, at: str) -> str:
    day = (at or "")[:10]
    if entry_src == "整理":
        return f"（整理 · {day}）" if day else "（整理）"
    if entry_src == SRC_EPISODE:
        return f"（经历 · {day}）" if day else "（经历）"
    return f"（{entry_src or '来源不明'}{' · ' + day if day else ''}）"


def _skip_reason(workspace: str, user_text: str, config: Any = None) -> str:
    def configured(key: str, defaults: list[str]) -> list[str]:
        try:
            patterns = config.get(f"memory.library.{key}", defaults) if config else defaults
            if not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns):
                return defaults
            for pattern in patterns:
                re.compile(pattern)
            return patterns
        except Exception:
            return defaults

    try:
        normalized = str(workspace or "").strip()
        if not normalized:
            raise ValueError
        if any(re.search(p, normalized, re.I) for p in configured("skip_workspace_patterns", _DEFAULT_WORKSPACE_PATTERNS)):
            return "workspace"
        root = Path(tempfile.gettempdir()).resolve()
        candidate = Path(normalized).resolve()
        if candidate == root or root in candidate.parents:
            return "workspace"
    except (OSError, RuntimeError, ValueError):
        pass
    if any(re.search(p, user_text or "", re.I) for p in configured("skip_text_patterns", _DEFAULT_TEXT_PATTERNS)):
        return "text"
    return ""


class MemoryLibrary:
    def __init__(self, root: Path, config: Any = None, *, vcs: bool = True) -> None:
        self.store = MemoryStore(root, vcs=vcs)
        self.index = MemoryIndex(self.store)
        self.queue = TurnQueue(root)
        # 只追加、不删改的取代账本，和记忆库放在一起（同一次 git 提交里可查）。
        self.supersedes = SupersedeLedger(self.store.root)
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

    def _skip_reason(self, workspace: str, user_text: str) -> str:
        return _skip_reason(workspace, user_text, self.config)

    # ---------- recall (before the model call) ----------
    def recall(self, message: str) -> dict[str, Any]:
        self.ready()
        self.index.sync()
        resident = self._resident_block()
        relevant, refs, source_paths = self._relevant_block(message or "")
        resident_sources = []
        for rel, title in ((ME, "关于你"), (NOW, "现状 / 进行中"), (SELF, "Atlas 自己")):
            if f"## {title}\n" in resident:
                resident_sources.append(rel)
        if "## 最近在聊 / 在做\n" in resident:
            resident_sources.append("recent-episodes (last 7 days)")
        return {
            "resident": resident,
            "relevant": relevant,
            "refs": refs,
            "source_paths": source_paths,
            "resident_sources": resident_sources,
            "system_block": f"{INSTRUCTION}\n\n{resident}" if resident else "",
        }

    def recall_resident(self) -> dict[str, Any]:
        """Resident-only recall: no index sync, no corpus scan.

        ``recall()`` runs ``index.sync()`` (a sha1 per page) and ``_idf()``
        (a full-corpus scan) before it can answer, so its cost grows with the
        library. When that work overruns the pre-model budget the caller still
        deserves the memories that come from plain file reads: who the user is,
        what is in progress, and what Atlas itself is. Those pages are the bulk
        of what makes Atlas feel like it remembers, and reading them is
        independent of corpus size.
        """
        self.store.ensure()
        resident = self._resident_block()
        resident_sources = []
        for rel, title in ((ME, "关于你"), (NOW, "现状 / 进行中"), (SELF, "Atlas 自己")):
            if f"## {title}\n" in resident:
                resident_sources.append(rel)
        if "## 最近在聊 / 在做\n" in resident:
            resident_sources.append("recent-episodes (last 7 days)")
        return {
            "resident": resident,
            "relevant": "",
            "refs": [],
            "source_paths": [],
            "resident_sources": resident_sources,
            "system_block": f"{INSTRUCTION}\n\n{resident}" if resident else "",
            "degraded": True,
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
        episodes = self._recent_episodes(now, 7, 6)
        if episodes:
            recent = [f"- [{e.at[5:10]}] {e.text} → {e.outcome}" for e in episodes]
            episode_section = "## 最近在聊 / 在做\n"
            kept = []
            for line in recent:
                remaining = 500 - len(episode_section) - sum(len(x) + 1 for x in kept)
                if remaining <= 0:
                    break
                kept.append(line[:remaining])
            sections.append(episode_section + "\n".join(kept))
        return "\n\n".join(sections)

    def _recent_episodes(self, now: datetime, days: int, limit: int) -> list[Entry]:
        cutoff = now.date().toordinal() - days + 1
        entries = []
        for rel in self.store.pages():
            if not rel.startswith(EPISODES + "/"):
                continue
            page_day = Path(rel).stem
            try:
                if datetime.fromisoformat(page_day).date().toordinal() < cutoff:
                    continue
            except ValueError:
                continue
            entries.extend(self.store.read(rel).current)
        entries.sort(key=lambda e: e.at, reverse=True)
        return entries[:limit]

    def _relevant_block(self, message: str) -> tuple[str, list[str], list[str]]:
        parts: list[str] = []
        refs: list[str] = []
        source_paths: list[str] = []
        now = _now(self.config)
        lowered = message.casefold()
        cue_pages = []
        for rel, names in self.index.entities():
            if any(name and name.casefold() in lowered for name in names):
                cue_pages.append(rel)
        old_notes = self.supersede_notes()
        for rel in cue_pages[:MAX_CUE_PAGES]:
            page = self.store.read(rel)
            current = [e for e in page.current if not is_expired(e, now)]
            shown = current[-MAX_CUE_LINES:]
            lines = [f"- {e.text}{_label(e.src, e.at)}" + (f" [ref:{e.ref}]" if e.ref else "")
                     + (f" {old_notes[e.id]}" if e.id in old_notes else "")
                     for e in shown]
            if lines:
                alias = f"（也叫 {'、'.join(page.aliases)}）" if page.aliases else ""
                parts.append(f"## {page.title}{alias}\n" + "\n".join(lines))
                source_paths.append(rel)
                refs.extend(e.ref for e in shown if e.ref)
        skip = set(RESIDENT_PAGES) | set(cue_pages)
        hits = [h for h in self.index.search(message, limit=MAX_SEARCH_FACTS * 4,
                                             kinds=("fact", "dream"), exclude_paths=tuple(skip), now=now)
                if h["score"] >= SEARCH_MIN_SCORE]
        # A superseded line is kept for audit but must not outrank the statement that
        # corrected it, so the ordering puts live lines first and the marker explains why.
        hits.sort(key=lambda h: (h["id"] in old_notes, -h["score"]))
        hits = hits[:MAX_SEARCH_FACTS]
        if hits:
            lines = []
            for h in hits:
                line = (f"- {h['text']}{_label(h['src'], h['at'])}"
                        + (f" [ref:{h['ref']}]" if h.get("ref") else ""))
                note = old_notes.get(str(h.get("id") or ""))
                if note:
                    line += f" {note}"
                lines.append(line)
            parts.append("## 可能相关\n" + "\n".join(lines))
            source_paths.extend(str(hit.get("path") or "") for hit in hits if hit.get("path"))
            refs.extend(h.get("ref") for h in hits if h.get("ref"))
        resident_ids = {e.id for e in self._recent_episodes(now, 7, 6)}
        detailed = bool(_RECALL_INTENT.search(message))
        episode_hits = [h for h in self.index.search(message, limit=12, kinds=("episode",), now=now)
                        if h["score"] >= SEARCH_MIN_SCORE and (detailed or h["id"] not in resident_ids)][:3]
        if episode_hits:
            lines = []
            for hit in episode_hits:
                source_page = self.store.read(str(hit.get("path") or ""))
                entry = next((item for item in source_page.current if item.id == hit["id"]), None)
                line = f"- [{hit['at'][:10]}] {hit['text']} → {entry.outcome if entry else ''}"
                if entry and entry.ref:
                    line += f" [ref:{entry.ref}]"
                if detailed and entry:
                    details = []
                    for label, values in (("决定", entry.decisions), ("文件", entry.files),
                                          ("命令", entry.commands), ("关键数字", entry.facts),
                                          ("没做完", entry.open_items), ("步骤", entry.steps)):
                        if values:
                            details.append(f"{label}：{'、'.join(values)}")
                    if details:
                        line += "；" + "；".join(details)
                    line += f"；{'已验证' if entry.verified else '未验证'}"
                lines.append(line)
                if entry and entry.ref:
                    refs.append(entry.ref)
            parts.append("## 以前做过的相关的事\n" + "\n".join(lines))
            source_paths.extend(str(hit.get("path") or "") for hit in episode_hits if hit.get("path"))
        if _RECALL_INTENT.search(message):
            diary = [h for h in self.index.search(message, limit=3, kinds=("diary",), now=now)
                     if h["score"] > 0.05]
            if diary:
                parts.append("## 以前的对话记录（原文节选）\n" + "\n".join(
                    f"- [{h['at'][:16].replace('T', ' ')}] {' '.join(h['text'].split())[:240]}"
                    + (f" [ref:{h['ref']}]" if h.get("ref") else "") for h in diary))
                refs.extend(h.get("ref") for h in diary if h.get("ref"))
                source_paths.extend(str(hit.get("path") or "") for hit in diary if hit.get("path"))
        corrections = self._supersede_section()
        if corrections:
            parts.insert(0, corrections)
            source_paths.extend(RESIDENT_PAGES)
        if not parts:
            return "", [], []
        detailed = bool(_RECALL_INTENT.search(message))
        refs = list(dict.fromkeys(refs))
        if detailed and refs:
            parts.append('需要细节可用 memory_search(open="<ref>") 打开原对话：' + "、".join(refs[:3]))
        block = "Atlas 记忆库里和这句话有关的记录：\n\n" + "\n\n".join(parts)
        return block[:3000 if detailed else 1200], refs[:3] if detailed else refs, list(dict.fromkeys(source_paths))

    # ---------- search tool ----------
    def search(self, query: str, limit: int = 8, include_history: bool = False,
               kinds: tuple[str, ...] = ("fact", "dream", "diary"), *,
               scope: str | None = None, workspace: str = "") -> list[dict[str, Any]]:
        self.ready()
        self.index.sync()
        project_root = ""
        if workspace and not workspace.startswith("ssh://"):
            try:
                project_root = subprocess.run(
                    ["git", "-C", workspace, "rev-parse", "--show-toplevel"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=3, check=True,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                try:
                    project_root = str(Path(workspace).resolve())
                except OSError:
                    pass
        project_scope = (f"project:{hashlib.sha256(project_root.casefold().encode('utf-8')).hexdigest()[:16]}"
                         if project_root else None)
        keep = ("id", "path", "kind", "bucket", "text", "src", "at", "ref", "until", "quote", "score", "expired")
        rows = [{k: h.get(k) for k in keep}
                for h in self.index.search(query, limit=limit, include_history=include_history,
                                           kinds=kinds, now=_now(self.config), scope=scope,
                                           project_scope=project_scope)]
        # A superseded fact stays searchable (it is still a true record of what was once
        # said) but the model must see which of two contradicting lines won.
        pairs = self.supersedes.superseded_map()
        if pairs:
            notes = self.supersede_notes()
            for row in rows:
                newer = pairs.get(str(row.get("id") or ""))
                if newer:
                    row["superseded_by"] = newer
                    row["outdated"] = notes.get(str(row.get("id") or ""), "")
            rows.sort(key=lambda row: bool(row.get("superseded_by")))
        return rows

    # ---------- write (after the reply, in the background) ----------
    def schedule_turn(self, **kwargs: Any) -> None:
        user_text = (kwargs.get("user_text") or "").strip()
        if not user_text:
            return
        workspace = str(kwargs.get("workspace") or "")
        reason = self._skip_reason(workspace, user_text)
        if reason:
            log.info("memory.library.skipped", session=kwargs.get("session", ""), reason=reason)
            return
        try:
            self.index.set_event_loop(asyncio.get_running_loop())
        except RuntimeError:
            pass
        self.ready()
        self.queue.insert(created=_now(self.config).isoformat(timespec="seconds"),
                          session=kwargs.get("session", ""), mode=kwargs.get("mode", ""),
                          user_text=user_text, assistant_text=kwargs.get("assistant_text") or "",
                          workspace=workspace,
                          steps=json.dumps(kwargs.get("steps") or [], ensure_ascii=False),
                          verified=bool(kwargs.get("verified", False)),
                          turn_started=str(kwargs.get("turn_started") or ""))
        task = asyncio.create_task(self._drain(kwargs.get("model_mgr")))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain(self, model_mgr: Any) -> None:
        self.ready()
        async with self._turn_lock:
            for row in self.queue.pending():
                try:
                    now = datetime.fromisoformat(row["created"])
                    ref = self._turn_source_ref(str(row["session"]), str(row.get("user_text") or ""),
                                                row.get("turn_started") or now.isoformat(timespec="seconds"))
                    if not ref:
                        raise ValueError("source user message is unavailable; refusing to save memory without a source ref")
                    if row["stage"] == "new":
                        await asyncio.to_thread(self._write_diary, now, row["user_text"],
                                                row["assistant_text"], row["session"], row["mode"], ref)
                        self.queue.stage_diary_done(row["id"])
                    result = await self.observe_turn(row, model_mgr, now)
                    self.queue.remove(row["id"])
                    log.info("memory.library.turn", session=row["session"], added=len(result.added),
                             changed=len(result.changed), ended=len(result.ended),
                             forgotten=len(result.forgotten), rejected=result.rejected)
                except ModelUnavailable:
                    log.info("memory.library.turn_deferred", session=row["session"], reason="no_model")
                except Exception as exc:
                    self.queue.fail(row["id"], str(exc))
                    log.warning("memory.library.turn_failed", session=row["session"],
                                error=str(exc), error_type=type(exc).__name__)

    async def observe_turn(self, row: dict[str, Any], model_mgr: Any,
                           now: datetime) -> extract.ApplyResult:
        user_text, assistant_text = row["user_text"], row["assistant_text"]
        proposals: list[extract.Proposal] = []
        episode = None
        try:
            steps = json.loads(row.get("steps") or "[]")
        except (TypeError, ValueError):
            steps = []
        if len(user_text) >= 2:
            explicit = self._explicit_memory_proposal(user_text)
            if explicit is not None:
                proposals = [explicit]
            elif model_mgr is None:
                raise ModelUnavailable("no memory writer model available")
            else:
                proposals, episode = await self._extract_full(user_text, assistant_text, model_mgr, now,
                                                              steps, bool(row.get("verified", 0)))
        ref = self._turn_source_ref(str(row["session"]), user_text,
                                    row.get("turn_started") or now.isoformat(timespec="seconds"))
        if not ref:
            raise ValueError("source user message is unavailable; refusing to save memory without a source ref")
        return await asyncio.to_thread(self._apply, proposals, user_text,
                                       row["session"], row["mode"], now, episode=episode,
                                       steps=steps, verified=bool(row.get("verified", 0)), ref=ref,
                                       workspace=str(row.get("workspace") or ""))

    @staticmethod
    def _turn_source_ref(session: str, user_text: str, fallback: str = "") -> str:
        """Use the persisted user message id so a memory citation opens its source turn.

        Returns "" when the transcript is unavailable. That empty ref is load-bearing:
        the caller refuses to persist a memory it cannot point back to, so we never
        invent a plausible-looking reference. `fallback` is kept in the signature for
        callers that pass the turn start time.
        """
        try:
            from atlas.config import DATA_ROOT
            from atlas.engine.session_sync import read_session_all_messages

            rows = read_session_all_messages(DATA_ROOT / "engine", session)
            expected = " ".join(user_text.split())
            for row in reversed(rows):
                if row.get("role") != "user":
                    continue
                content = row.get("content")
                if isinstance(content, str) and (not expected or " ".join(content.split()) == expected):
                    message_id = str(row.get("id") or "").strip()
                    if message_id:
                        return f"{session}@{message_id}"
        except Exception:
            log.debug("memory.library.source_message_lookup_failed", session=session, exc_info=True)
        return ""

    @staticmethod
    def _explicit_memory_proposal(user_text: str) -> extract.Proposal | None:
        """Only direct user-authored remember requests enter the deterministic path."""
        match = re.match(r"^\s*(?:请)?(?:记住|记下来|记下|以后记得)\s*[：:，,]?\s*(.{2,500})\s*$",
                         user_text, re.S)
        if not match:
            return None
        fact = " ".join(match.group(1).split()).strip("\"'“”‘’ ")
        if len(fact) < 2 or extract.contains_secret(fact):
            return None
        category = ("preference" if re.search(r"喜欢|偏好|习惯|不喜欢|prefer|like", fact, re.I)
                    else "project" if re.search(r"项目|仓库|代码库|project|repository", fact, re.I)
                    else "note")
        import hashlib
        digest = hashlib.sha1(fact.encode("utf-8")).hexdigest()[:10]
        return extract.Proposal(op="set", key=f"user.{category}.{digest}", value=fact,
                                text=fact, quote=match.group(1).strip(), stance="said")

    def _write_diary(self, now: datetime, user_text: str, assistant_text: str,
                     session: str, mode: str, ref: str = "") -> None:
        self.ready()
        meta = '{"session":"%s","ref":"%s"%s}' % (re.sub(r"[^\w-]", "", session)[:64], ref,
                                       ',"mode":"expert"' if mode == "expert" else "")
        reply = " ".join((assistant_text or "").split())[:1500]
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

    async def _extract_full(self, user_text: str, assistant_text: str, model_mgr: Any,
                            now: datetime, steps: list[dict], verified: bool):
        router = getattr(model_mgr, "model_router", None)
        if router is None:
            raise ModelUnavailable("no memory writer model available")
        try:
            model_id = self._model_id(model_mgr)
        except RuntimeError as exc:
            if str(exc) == "no memory writer model available":
                raise ModelUnavailable(str(exc)) from exc
            raise
        known = await asyncio.to_thread(extract.known_facts, self.store)
        clock = f"{now.strftime('%Y-%m-%d %A %H:%M')} (UTC{now.strftime('%z')})"
        messages = extract.build_messages(user_text=user_text, assistant_text=assistant_text,
                                          known=known, clock=clock, steps=steps, verified=verified)
        result = await asyncio.wait_for(
            router.complete_for(model_id, "memory_library", messages, max_tokens=1600, temperature=0.1),
            timeout=float(self._cfg("writer_timeout_seconds", 90)),
        )
        return extract.parse_output(str(getattr(result, "text", "") or ""))

    async def _extract(self, user_text: str, assistant_text: str, model_mgr: Any,
                       now: datetime) -> list[extract.Proposal]:
        proposals, _episode = await self._extract_full(user_text, assistant_text, model_mgr, now, [], False)
        return proposals

    def _apply(self, proposals: list[extract.Proposal], user_text: str, session: str,
               mode: str, now: datetime, *, episode: extract.Episode | None = None,
               steps: list[dict] | None = None, verified: bool = False,
               ref: str = "", workspace: str = "") -> extract.ApplyResult:
        with self.store.lock:
            ended = extract.expire(self.store, now)
            result = extract.apply(self.store, proposals, user_text=user_text,
                                   session=session, mode=mode, now=now, ref=ref,
                                   workspace=workspace)
            episode_changed = extract.apply_episode(self.store, episode, steps or [], verified,
                                                    session, now, mode, ref)
            result.ended.extend(ended)
            message = result.message() if not result.empty else (
                f"经历：{episode.title}" if episode_changed and episode else "日记")
            self.store.commit(message)
            if result.forgotten_texts:
                self._purge(result.forgotten_texts)
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

    def add_entry(self, rel: str, text: str, *, session: str = "", ref: str = "",
                  scope: str = "global") -> dict[str, Any]:
        rel = self._safe_rel(rel)
        text = " ".join((text or "").split())
        if not text or extract.contains_secret(text):
            raise ValueError("内容为空或含有密码、密钥")
        with self.store.lock:
            page = self.store.read(rel)
            entry = Entry(text=text, id=new_id(), src=SRC_EDITED,
                          at=_now(self.config).isoformat(timespec="seconds"),
                          session=session, ref=ref, scope=scope or "global")
            page.current.append(entry)
            self.store.write(page)
            self.store.commit(f"你加了：{text}"[:400])
        self.index.sync()
        return {"id": entry.id, "path": rel}

    # ---------- supersede ledger (append-only, nothing is deleted) ----------
    def _locate_entry(self, entry_id: str) -> tuple[Page, Entry, str]:
        """Find one entry and refuse an ambiguous id.

        Hand-written page lines carry ``stable_id(text)``, so two identical lines in
        different pages can share an id. Marking the wrong one would be silent data
        damage, so ambiguity is an error rather than a guess.
        """
        entry_id = str(entry_id or "").strip()
        if not entry_id:
            raise ValueError("缺少记忆 id")
        found: list[tuple[Page, Entry, str]] = []
        for rel in self.store.pages():
            page = self.store.read(rel)
            for bucket in ("current", "history"):
                for entry in getattr(page, bucket):
                    if entry.id == entry_id:
                        found.append((page, entry, bucket))
        if not found:
            raise KeyError(entry_id)
        if len(found) > 1:
            where = "、".join(sorted({page.path for page, _entry, _bucket in found}))
            raise ValueError(f"这个 id 在 {where} 里出现了不止一次，无法确定要标记哪一条")
        return found[0]

    def record_supersession(self, old_id: str, new_id: str = "", *, quote: str = "",
                            ref: str = "", session: str = "", new_text: str = "",
                            why: str = "", verified: bool = False) -> dict[str, Any]:
        """Record that a newer statement replaces an older one. Never edits either entry.

        ``new_id`` may be empty when the correction is already the user's current wording
        but has not been stored as an entry yet; the quote then carries the evidence.
        """
        self.ready()
        old_id, new_id = str(old_id or "").strip(), str(new_id or "").strip()
        quote = " ".join(str(quote or "").split())
        why = " ".join(str(why or "").split())
        new_text = " ".join(str(new_text or "").split())
        if not quote and not why:
            raise ValueError("要记下取代关系，得带上用户的原话或一句理由")
        if extract.contains_secret(quote) or extract.contains_secret(new_text):
            raise ValueError("看起来含有密码或密钥，记忆库不保存这类内容")
        with self.store.lock:
            page, old_entry, _bucket = self._locate_entry(old_id)
            new_entry: Entry | None = None
            if new_id:
                if new_id == old_id:
                    raise ValueError("一条记忆不能取代它自己")
                new_entry = self._locate_entry(new_id)[1]
                # Walking the existing chain first turns a cycle into a refusal instead of a loop.
                if self.supersedes.resolve(new_id) == old_id:
                    raise ValueError("这两条记忆互相取代了，会形成环；请先核对哪一条才是新的")
            record = self.supersedes.append(
                kind=KIND_SUPERSEDE, old=old_id, new=new_id,
                quote=quote or why, ref=ref or (new_entry or old_entry).ref,
                session=session or (new_entry or old_entry).session,
                old_text=old_entry.text,
                new_text=new_text or (new_entry.text if new_entry else ""),
                why=why, verified=verified,
            )
            self.store.commit(("你确认了新说法：%s → %s" % (old_entry.text, new_entry.text if new_entry else new_text))[:400])
        self.index.sync()
        return {"ok": True, "record": record.row(), "old": {"id": old_id, "path": page.path, "text": old_entry.text},
                "new": {"id": new_id, "text": new_entry.text if new_entry else new_text}}

    def retract_supersession(self, target: str, *, why: str = "") -> dict[str, Any]:
        """Cancel a pair by appending a ``retract`` line; the original record stays on disk."""
        self.ready()
        target = str(target or "").strip()
        if not target:
            raise ValueError("缺少要撤销的取代记录")
        known = {record.id for record in self.supersedes.records()} | set(self.supersedes.pairs())
        if target not in known:
            raise KeyError(target)
        with self.store.lock:
            record = self.supersedes.append(kind=KIND_RETRACT, old=target,
                                           why=" ".join(str(why or "").split()))
            self.store.commit(f"你撤销了一条取代关系：{target}"[:400])
        return {"ok": True, "record": record.row()}

    def effective_entries(self, rel: str | None = None) -> dict[str, Any]:
        """Current entries minus those a live entry has replaced.

        Superseded entries are still returned separately: they remain readable for audit
        and are only lowered in priority, never removed.
        """
        self.ready()
        pairs = self.supersedes.superseded_map()
        live: list[dict[str, Any]] = []
        retired: list[dict[str, Any]] = []
        for path in ([self._safe_rel(rel)] if rel else self.store.pages()):
            page = self.store.read(path)
            for entry in page.current:
                row = {"id": entry.id, "path": path, "text": entry.text, "src": entry.src,
                       "at": entry.at, "ref": entry.ref, "quote": entry.quote,
                       "superseded_by": pairs.get(entry.id, "")}
                (retired if entry.id in pairs else live).append(row)
        return {"effective": live, "superseded": retired,
                "counts": {"effective": len(live), "superseded": len(retired),
                           "pairs": len(pairs)}}

    def supersession_audit(self, *, limit: int = 200) -> dict[str, Any]:
        """The raw trail, newest first, retractions included."""
        self.ready()
        return {"ledger": self.supersedes.path.name, "count": len(self.supersedes.active()),
                "entries": self.supersedes.audit(limit=limit)}

    def supersession_marks(self, entry_ids: list[str]) -> dict[str, str]:
        """``entry id -> newer id`` for the given ids, for recall marking."""
        if not entry_ids:
            return {}
        pairs = self.supersedes.superseded_map()
        return {entry_id: pairs[entry_id] for entry_id in entry_ids if entry_id in pairs}

    def supersede_notes(self) -> dict[str, str]:
        """``entry id -> one-line note`` for entries a newer statement has replaced.

        The note carries the newer wording, so the model reading the recall block sees the
        correction in place instead of only a dangling id. It never says "deleted": the old
        line stays visible, on purpose.
        """
        pairs = self.supersedes.superseded_map()
        if not pairs:
            return {}
        newer_text: dict[str, str] = {}
        for record in self.supersedes.active():
            text = " ".join(str(record.new_text or "").split())[:60]
            if not text:
                continue
            # A pair may name an existing entry (``new``) or carry only the newer wording,
            # because memory is written after the turn ends; both must reach the note.
            # A pair with no newer entry keys off its own old id, so it can never land on
            # the empty string and hand its wording to an unrelated entry.
            if record.new:
                newer_text[record.new] = text
            newer_text.setdefault(record.old, text)
        notes: dict[str, str] = {}
        for old, newest in pairs.items():
            text = newer_text.get(newest, "") if newest else newer_text.get(old, "")
            notes[old] = (f"（已过时 · 已被「{text}」取代）" if text
                          else f"（已过时 · 已被 {newest} 取代）")
        return notes

    def _supersede_section(self) -> str:
        """Corrections to memories that already sit in the cached resident block.

        The resident text itself must stay byte-identical (it is the cacheable system
        prefix), so a mid-conversation correction cannot be written into it. This section
        travels with the per-turn recall instead and names both sides, which is what stops
        the model from quoting the stale line it can still see above.
        """
        notes = self.supersede_notes()
        if not notes:
            return ""
        latest: dict[str, str] = {}
        for record in self.supersedes.active():
            latest[record.old] = " ".join(str(record.new_text or "").split())[:80] or record.new
        lines: list[str] = []
        for rel in RESIDENT_PAGES:
            page = self.store.read(rel)
            for entry in page.current:
                if entry.id not in notes or not latest.get(entry.id):
                    continue
                lines.append(f"- 旧：{entry.text}{_label(entry.src, entry.at)}"
                             f" → 新：{latest[entry.id]}（以新的为准，旧的留着可查）")
                if len(lines) >= MAX_SEARCH_FACTS:
                    break
            if len(lines) >= MAX_SEARCH_FACTS:
                break
        if not lines:
            return ""
        return "## 有更近的说法（以新的为准）\n" + "\n".join(lines)

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
            # No topic words, and no short halves ("直接回答"): they would wipe unrelated diary lines.
            needles = [entry.quote, entry.text, entry.value, entry.outcome]
            if entry.src == SRC_EPISODE and "：" in entry.text:
                needles.extend(part for part in entry.text.split("：", 1) if len(part.strip()) >= 6)
            diary_pages = self.store.redact_diary(needles)
            # The supersede ledger quotes the user's words a second time (snapshot), so a
            # forgotten entry must be blanked there too or the purge below could not finish.
            ledger_lines = self.supersedes.redact(needles)
            self.store.commit("按你的要求忘掉了一条记忆")
            history = self._purge([entry.text, entry.quote, entry.value])
        self.index.sync()
        return {"ok": True, "pages": [page.path], "diary_pages": diary_pages,
                "ledger_lines": ledger_lines, "history": history,
                "not_covered": ["Atlas 的原始聊天记录（engine 会话库）", "你自己做的备份或同步副本"]}

    def _purge(self, needles: list[str]) -> dict[str, Any]:
        # The entry is already gone from the pages; a failed history rewrite must not
        # undo that or hide it, so report it instead of raising.
        try:
            return purge_history(self.store, needles)
        except Exception as exc:
            log.warning("memory.library.purge_failed", error=str(exc), error_type=type(exc).__name__)
            return {"rewritten": False, "commits": 0, "error": str(exc)}

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
        if folder in (PEOPLE, THINGS, "代理") and name.endswith(".md") and "/" not in name:
            return f"{folder}/{safe_name(name[:-3])}.md"
        raise ValueError("unknown memory page")

    def agent_memory_read(self, agent_id: str, query: str = "", limit: int = 8) -> dict[str, Any]:
        """Read global resident memory and the caller's own visible scope."""
        self.ready()
        digest = __import__("hashlib").sha256(str(agent_id or "main").encode()).hexdigest()[:16]
        own = self.store.read(f"代理/{digest}.md")
        own_rows = [entry.text for entry in own.current]
        child_scopes = {}
        if not agent_id:
            for path in sorted((self.store.root / "代理").glob("*.md")):
                child_scopes[path.stem] = [entry.text for entry in self.store.read(
                    path.relative_to(self.store.root).as_posix()).current]
        hits = self.search(query, limit=max(1, min(20, limit))) if query.strip() else []
        return {
            "global": self._resident_block(), "agent_scope": own_rows,
            "child_scopes": child_scopes, "matches": hits, "agent_scope_path": own.path,
        }

    def agent_memory_write(self, agent_id: str, text: str, *, session: str = "") -> dict[str, Any]:
        """Write a user-visible, source-labelled fact into the agent's Markdown page."""
        text = " ".join(str(text or "").split())[:1000]
        if not text or extract.contains_secret(text):
            raise ValueError("内容为空或含有密码、密钥")
        ref = self._turn_source_ref(session, "")
        if not ref:
            raise ValueError("无法定位本轮用户消息；拒绝保存没有出处的记忆")
        digest = __import__("hashlib").sha256(str(agent_id or "main").encode()).hexdigest()[:16]
        rel = f"代理/{digest}.md"
        with self.store.lock:
            page = self.store.read(rel)
            entry = Entry(text=text, id=new_id(), src="子代理观察", scope=f"agent:{digest}",
                          at=_now(self.config).isoformat(timespec="seconds"), session=session, ref=ref)
            page.current.append(entry)
            self.store.write(page)
            self.store.commit(f"子代理记忆：{text}"[:400])
        self.index.sync()
        return {"id": entry.id, "path": rel, "scope": f"agent:{digest}"}

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
        episodes = []
        episode_page = self.store.read(f"{EPISODES}/{_now(self.config).date().isoformat()}.md")
        for row in _page_dict(episode_page)["current"]:
            episodes.append(row)
        return {
            "changes": changes,
            "now": _page_dict(self.store.read(NOW)),
            "turns": diary_turns,
            "episodes": episodes,
            "pending_failed": self.queue.failed_count(),
        }


def _page_dict(page: Page) -> dict[str, Any]:
    def row(e: Entry) -> dict[str, Any]:
        return {"id": e.id, "text": e.text, "src": e.src, "at": e.at, "ref": e.ref,
                "until": e.until,
                "quote": e.quote, "ended": e.ended, "why": e.why, "key": e.key,
                "outcome": e.outcome, "steps": e.steps, "verified": e.verified,
                "decisions": e.decisions, "files": e.files, "commands": e.commands,
                "facts": e.facts, "open_items": e.open_items}
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
        root = os.environ.get("ATLAS_TEST_MEMORY_ROOT", "").strip()
        if not root:
            root = str(config.get("memory.library.root", "") or "").strip()
        _SINGLETON = MemoryLibrary(Path(root) if root else DATA_ROOT / "data" / "memory", config)
    return _SINGLETON


__all__ = ["MemoryLibrary", "get_library", "INSTRUCTION"]
