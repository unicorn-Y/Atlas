"""Atlas memory library: the kernel-independent memory slot.

Every run calls :meth:`MemoryLibrary.recall` before the model sees the message and
:meth:`MemoryLibrary.observe_turn` after the reply; neither depends on which agent loop
(Atlas kernel, Hermes, anything later) produced the turn. See ``docs/memory/PLAN-V1.md``.
"""

from __future__ import annotations

import asyncio
import json
import re
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
    DIARY, EPISODES, ME, NOW, PEOPLE, RESIDENT_PAGES, SELF, SRC_EDITED, SRC_EPISODE, THINGS, Entry, MemoryStore, Page,
    is_expired, new_id, safe_name, tombstone_hashes,
)

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

    def _skip_reason(self, workspace: str, user_text: str) -> str:
        return _skip_reason(workspace, user_text, self.config)

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
                refs.extend(e.ref for e in current[-MAX_CUE_LINES:] if e.ref)
        skip = set(RESIDENT_PAGES) | set(cue_pages)
        hits = [h for h in self.index.search(message, limit=MAX_SEARCH_FACTS * 2,
                                             kinds=("fact", "dream"), exclude_paths=tuple(skip), now=now)
                if h["score"] >= SEARCH_MIN_SCORE][:MAX_SEARCH_FACTS]
        if hits:
            parts.append("## 可能相关\n" + "\n".join(
                f"- {h['text']}{_label(h['src'], h['at'])}" for h in hits))
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
        if _RECALL_INTENT.search(message):
            diary = [h for h in self.index.search(message, limit=3, kinds=("diary",), now=now)
                     if h["score"] > 0.05]
            if diary:
                parts.append("## 以前的对话记录（原文节选）\n" + "\n".join(
                    f"- [{h['at'][:16].replace('T', ' ')}] {' '.join(h['text'].split())[:240]}" for h in diary))
                refs.extend(h.get("ref") for h in diary if h.get("ref"))
        if not parts:
            return "", []
        detailed = bool(_RECALL_INTENT.search(message))
        refs = list(dict.fromkeys(refs))
        if detailed and refs:
            parts.append('需要细节可用 memory_search(open="<ref>") 打开原对话：' + "、".join(refs[:3]))
        block = "Atlas 记忆库里和这句话有关的记录：\n\n" + "\n\n".join(parts)
        return block[:3000 if detailed else 1200], refs[:3] if detailed else refs

    # ---------- search tool ----------
    def search(self, query: str, limit: int = 8, include_history: bool = False,
               kinds: tuple[str, ...] = ("fact", "dream", "diary")) -> list[dict[str, Any]]:
        self.ready()
        self.index.sync()
        keep = ("id", "path", "kind", "bucket", "text", "src", "at", "ref", "until", "quote", "score", "expired")
        return [{k: h.get(k) for k in keep}
                for h in self.index.search(query, limit=limit, include_history=include_history,
                                           kinds=kinds, now=_now(self.config))]

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
        self.ready()
        session = str(kwargs.get("session") or "")
        if not session:
            return
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import read_session_all_messages

        engine_root = Path(str(self._cfg("engine_root", "") or DATA_ROOT / "engine"))
        messages = read_session_all_messages(engine_root, session)
        selected = [m for m in messages if m.get("role") in {"user", "assistant", "tool"}][-6:]
        uids = [str(m.get("id") or "") for m in selected if m.get("id")]
        if not uids:
            log.info("memory.library.skipped", session=session, reason="no_stable_message_uids")
            return
        # Legacy API remains callable, but only stable references cross into the queue.
        self.schedule_lifecycle({"conversation_id": session, "message_uids": uids,
                                 "event_kind": "turn_end",
                                 "occurred_at": _now(self.config).isoformat(timespec="seconds"),
                                 "scope": "turn"}, model_mgr=kwargs.get("model_mgr"))

    def schedule_lifecycle(self, event: dict[str, Any], *, model_mgr: Any = None) -> None:
        """Queue a UID-only lifecycle signal and wake the memory worker."""
        if not isinstance(event, dict):
            raise TypeError("lifecycle event must be a mapping")
        required = ("conversation_id", "message_uids", "event_kind", "occurred_at", "scope")
        if any(key not in event for key in required):
            raise ValueError("lifecycle event is missing required pointer fields")
        forbidden = {"content", "text", "user_text", "assistant_text", "transcript", "messages"}
        if forbidden.intersection(event):
            raise ValueError("lifecycle events must not contain transcript content")
        # M1 owns lifecycle normalization, idempotency, and queue persistence.
        from .lifecycle import enqueue
        from .lifecycle import start_watcher

        self.ready()
        enqueue(self.queue, event)
        start_watcher(self.queue, lambda: self._wake_drain(model_mgr))
        self._wake_drain(model_mgr)

    def _wake_drain(self, model_mgr: Any) -> None:
        task = asyncio.create_task(self._drain(model_mgr))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain(self, model_mgr: Any) -> None:
        self.ready()
        async with self._turn_lock:
            for row in self.queue.pending():
                try:
                    result = await self.observe_turn(row, model_mgr, _now(self.config))
                    self.queue.remove(row["id"])
                    log.info("memory.library.turn", session=row.get("conversation_id") or row.get("session", ""),
                             outcome="episode_written" if result.episode_written else
                             "facts_written" if not result.empty else "no_output",
                             added=len(result.added),
                             changed=len(result.changed), ended=len(result.ended),
                             forgotten=len(result.forgotten), rejected=result.rejected)
                except Exception as exc:
                    self.queue.fail(row["id"], str(exc))
                    log.warning("memory.library.turn_failed", session=row.get("conversation_id") or row.get("session", ""),
                                attempts=row.get("attempts"), outcome="failed",
                                error=str(exc), error_type=type(exc).__name__)

    async def observe_turn(self, row: dict[str, Any], model_mgr: Any,
                           now: datetime) -> extract.ApplyResult:
        # Compatibility for old schedule_turn queue rows; M1 migrates these to UID rows.
        if row.get("user_text") is not None:
            user_text = str(row.get("user_text") or "")
            try:
                steps = json.loads(row.get("steps") or "[]")
            except (TypeError, ValueError):
                steps = []
            if not user_text or model_mgr is None:
                raise RuntimeError("legacy turn cannot be processed without input and model")
            messages = [{"role": "user", "text": user_text}]
            assistant = str(row.get("assistant_text") or "")
            if assistant:
                messages.append({"role": "assistant", "text": assistant})
            proposals, episode = await self._extract_full(messages, model_mgr, now, previous={})
            return await asyncio.to_thread(self._apply, proposals, user_text,
                                           str(row.get("session") or ""), str(row.get("mode") or ""), now,
                                           episode=episode, steps=steps, verified=bool(row.get("verified", 0)))

        conversation_id = str(row.get("conversation_id") or row.get("session") or "")
        if not conversation_id:
            raise ValueError("lifecycle row has no conversation_id")
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import read_session_all_messages

        engine_root = Path(str(self._cfg("engine_root", "") or DATA_ROOT / "engine"))
        canonical = read_session_all_messages(engine_root, conversation_id)
        if not canonical:
            raise RuntimeError("SessionDB transcript is unavailable")
        uid_set = {str(uid) for uid in row.get("message_uids", []) if str(uid)}
        scope = str(row.get("scope") or "turn")
        event_kind = str(row.get("event_kind") or "")
        full = scope in {"session", "full", "idle", "session_idle", "session_end", "legacy_unanchored"} or \
            event_kind in {"session_idle", "session_end", "on_session_idle", "on_session_end",
                           "on_delegation", "pre_compress", "delegation_return", "session_recovery"}
        selected = canonical if full else [m for m in canonical if str(m.get("id") or "") in uid_set]
        processed = self._processed_source_uids(conversation_id)
        selected = [m for m in selected if str(m.get("id") or "") not in processed]
        if not selected:
            # Already processed source UIDs are an idempotent success. An empty
            # unresolved scope remains a retryable lifecycle/data-integrity error.
            if full or uid_set.issubset({str(m.get("id") or "") for m in canonical}):
                return extract.ApplyResult()
            raise RuntimeError("lifecycle UID scope did not resolve to SessionDB messages")
        messages = self._messages_with_refs(conversation_id, selected)
        session = conversation_id
        previous = self._previous_episode(session)
        proposals, episode = await self._extract_full(messages, model_mgr, now, previous=previous)
        if full:
            episode = episode or extract.Episode("", skip=True)
        else:
            # Turn-end extraction remains light: keep the diary and new facts, defer the
            # session-sized episode until idle/session-end.
            episode = None
        self._verify_provenance(conversation_id, proposals, episode, messages, engine_root)
        user_text = "\n".join(m["text"] for m in messages if m["role"] == "user")
        diary = None
        if not full:
            assistant_text = "\n".join(m["text"] for m in messages if m["role"] == "assistant")
            ref = messages[-1]["source_ref"]
            diary = (now, user_text, assistant_text, session, "",
                     extract.SourceRef(**ref).to_ref())
        return await asyncio.to_thread(self._apply, proposals, user_text, session,
                                       str(row.get("mode") or ""), now, episode=episode,
                                       ref=messages[-1]["source_ref"] and
                                       extract.SourceRef(**messages[-1]["source_ref"]).to_ref(),
                                       diary=diary)

    def _messages_with_refs(self, conversation_id: str,
                            messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for message in messages:
            uid = str(message.get("id") or message.get("message_uid") or "")
            if not uid:
                raise RuntimeError("SessionDB message is missing its stable UID")
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            content = message.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(x.get("text") or x) if isinstance(x, dict) else str(x)
                                     for x in content)
            ref = extract.SourceRef(conversation_id=conversation_id, message_uid=uid,
                                    tool_call_id=str(metadata.get("tool_call_id") or "") or None,
                                    observed_role=str(message.get("role") or "unknown"),
                                    observed_at=str(message.get("created_at") or "") or None)
            out.append({"id": uid, "role": str(message.get("role") or "unknown"),
                        "text": str(content or ""), "source_ref": ref.to_dict(),
                        "metadata": metadata})
        return out

    def _previous_episode(self, session: str) -> dict[str, Any]:
        for rel in reversed(self.store.pages()):
            if not rel.startswith(EPISODES + "/"):
                continue
            page = self.store.read(rel)
            entry = next((e for e in page.current if e.session == session), None)
            if entry is None:
                continue
            meta = entry.meta()
            return {"title": entry.text.split("：", 1)[0], "summary": meta.get("episode_summary", ""),
                    "outcome": entry.outcome, "decisions": entry.decisions, "files": entry.files,
                    "commands": entry.commands, "facts": entry.facts,
                    "source_refs": meta.get("source_refs", [])}
        return {}

    def _processed_source_uids(self, conversation_id: str) -> set[str]:
        processed: set[str] = set()
        for rel in self.store.pages():
            page = self.store.read(rel)
            for entry in [*page.current, *page.history]:
                # A fact candidate may be only one of several outputs for the
                # same UID. It is deduplicated independently and must not act
                # as the lifecycle watermark for the whole source message.
                if getattr(entry, "src", "") == "M3候选":
                    continue
                meta = entry.meta() if callable(getattr(entry, "meta", None)) else {}
                version = meta.get("extractor_version")
                if version != extract.EXTRACTOR_VERSION:
                    continue
                refs = list(getattr(entry, "source_refs", []) or [])
                if isinstance(meta.get("source_refs"), list):
                    refs.extend(meta["source_refs"])
                single = getattr(entry, "source_ref", None)
                if single:
                    refs.append(single)
                raw_ref = entry.ref
                if raw_ref and str(raw_ref).startswith("atlas://source/v1?"):
                    try:
                        refs.append(extract.SourceRef.from_ref(str(raw_ref)).to_dict())
                    except ValueError:
                        pass
                for ref in refs:
                    try:
                        parsed = extract.SourceRef(**ref) if isinstance(ref, dict) else extract.SourceRef.from_ref(str(ref))
                    except (TypeError, ValueError):
                        continue
                    if parsed.conversation_id == conversation_id:
                        processed.add(parsed.message_uid)
        return processed

    def processed_source_uids(self, conversation_id: str) -> set[str]:
        """Expose M3's durable UID watermark to M1's queue rebuild helper."""
        self.ready()
        return self._processed_source_uids(conversation_id)

    def _verify_provenance(self, conversation_id: str, proposals: list[extract.Proposal],
                           episode: extract.Episode | None, messages: list[dict[str, Any]],
                           engine_root: Path) -> None:
        available = {json.dumps(m["source_ref"], ensure_ascii=False, sort_keys=True): m for m in messages}
        refs = [p.source_ref for p in proposals if p.source_ref]
        if episode:
            refs.extend(episode.source_refs)
        for raw in refs:
            ref = extract.SourceRef(**raw)
            if ref.conversation_id != conversation_id:
                raise ValueError("extractor returned a SourceRef for another conversation")
            key = json.dumps(ref.to_dict(), ensure_ascii=False, sort_keys=True)
            match = available.get(key)
            if match is None:
                raise ValueError("extractor SourceRef must exactly match an input message reference")
            from atlas.engine.session_sync import session_message_evidence

            evidence = session_message_evidence(engine_root, conversation_id, ref.message_uid)
            if not evidence or str(evidence.get("message_uid") or "") != ref.message_uid:
                raise ValueError("SourceRef UID is not verifiable in SessionDB")
            role = str(match.get("role") or "unknown")
            for proposal in proposals:
                if proposal.source_ref and proposal.source_ref.get("message_uid") == ref.message_uid:
                    if proposal.source_level == "user_assertion" and role != "user":
                        raise ValueError("user_assertion must cite a user message")
                    if proposal.source_level == "tool_observation" and role not in {"tool", "tool_call"}:
                        raise ValueError("tool_observation must cite a tool message")
        if episode:
            for ref in episode.source_refs:
                if json.dumps(ref, ensure_ascii=False, sort_keys=True) not in available:
                    raise ValueError("episode source_refs must exactly match input message references")

    def _write_diary(self, now: datetime, user_text: str, assistant_text: str,
                     session: str, mode: str, ref: str = "") -> None:
        self.ready()
        diary_path = self.store.root / DIARY / f"{now.date().isoformat()}.md"
        if ref and diary_path.exists() and ref in diary_path.read_text(encoding="utf-8"):
            return
        metadata = {"session": session, "ref": ref, "extractor_version": extract.EXTRACTOR_VERSION}
        if mode == "expert":
            metadata["mode"] = "expert"
        meta = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
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

    async def _extract_full(self, messages: list[dict[str, Any]], model_mgr: Any,
                            now: datetime, *, previous: dict[str, Any] | None = None):
        router = getattr(model_mgr, "model_router", None)
        if router is None:
            raise RuntimeError("memory writer model router is unavailable")
        model_id = self._model_id(model_mgr)
        known = await asyncio.to_thread(extract.known_facts, self.store)
        clock = f"{now.strftime('%Y-%m-%d %A %H:%M')} (UTC{now.strftime('%z')})"
        prompt = extract.build_messages(messages=messages, known=known, clock=clock, previous=previous)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                result = await asyncio.wait_for(
                    router.complete_for(model_id, "memory_library", prompt, max_tokens=6000, temperature=0.1),
                    timeout=float(self._cfg("writer_timeout_seconds", 90)),
                )
                return extract.parse_output(str(getattr(result, "text", "") or ""))
            except extract.ExtractionSchemaError:
                raise
            except Exception as exc:  # providers and JSON decoders expose several transient error types
                last_error = exc
                if attempt == 2:
                    break
                log.warning("memory.library.extract_retry", attempt=attempt + 1,
                            outcome="retry", error_type=type(exc).__name__)
                await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))
        raise RuntimeError(f"memory extraction failed after 3 attempts: {last_error}") from last_error

    async def _extract(self, user_text: str, assistant_text: str, model_mgr: Any,
                       now: datetime) -> list[extract.Proposal]:
        messages = [{"role": "user", "text": user_text}, {"role": "assistant", "text": assistant_text}]
        proposals, _episode = await self._extract_full(messages, model_mgr, now, previous={})
        return proposals

    def _apply(self, proposals: list[extract.Proposal], user_text: str, session: str,
               mode: str, now: datetime, *, episode: extract.Episode | None = None,
               steps: list[dict] | None = None, verified: bool = False,
               ref: str = "", diary: tuple[datetime, str, str, str, str, str] | None = None) -> extract.ApplyResult:
        with self.store.lock:
            ended = extract.expire(self.store, now)
            result = extract.apply(self.store, proposals, user_text=user_text,
                                   session=session, mode=mode, now=now, ref=ref)
            episode_changed = extract.apply_episode(self.store, episode, steps or [], verified,
                                                    session, now, mode, ref,
                                                    source_refs=episode.source_refs if episode else None)
            result.episode_written = episode_changed
            result.ended.extend(ended)
            if diary:
                self._write_diary(*diary)
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
            # No topic words, and no short halves ("直接回答"): they would wipe unrelated diary lines.
            needles = [entry.quote, entry.text, entry.value, entry.outcome]
            if entry.src == SRC_EPISODE and "：" in entry.text:
                needles.extend(part for part in entry.text.split("：", 1) if len(part.strip()) >= 6)
            diary_pages = self.store.redact_diary(needles)
            self.store.commit("按你的要求忘掉了一条记忆")
            history = self._purge([entry.text, entry.quote, entry.value])
        self.index.sync()
        return {"ok": True, "pages": [page.path], "diary_pages": diary_pages, "history": history,
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
                "facts": e.facts, "open_items": e.open_items,
                "source_level": e.source_level, "recorded_at": e.recorded_at,
                "valid_from": e.valid_from, "valid_to": e.valid_to,
                "supersedes": e.supersedes, "retracts": e.retracts,
                "source_ref": e.source_ref}
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
