"""Extract source-backed conversation episodes and atomic memory candidates.

SessionDB remains the transcript owner. This module only returns structured
proposals and writes readable Markdown through ``MemoryStore``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from .source_ref import SourceRef
from .store import (
    SRC_EDITED, Entry, MemoryStore, Page, new_id, page_for_key, safe_name, tombstone_hashes,
)

MAX_KNOWN = 150
MAX_SESSION_CHARS = 30000
KEY_RE = re.compile(r"^[a-z0-9_]+(\.[^\s.]+){0,4}$")
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:密码|password|passwd|pwd|口令|token|api[_ ]?key)\s*[:：=是为]\s*\S{4,})",
    re.I,
)
SOURCE_LEVELS = {"user_assertion", "tool_observation", "model_inference", "legacy_unknown"}
EXTRACTOR_VERSION = "m3-1"


class ExtractionSchemaError(ValueError):
    """The model returned syntactically valid JSON that violates the contract."""

SYSTEM_PROMPT = """你是 Atlas 记忆提炼器。你会读取 SessionDB 按时间排序的原始消息及可用的上次提炼结果。Markdown + git 是唯一记忆真源；SessionDB 是原文真源。只返回符合 schema 的 JSON，不输出解释。

第一层：会话经历。只要有值得回顾的工作过程、决定、文件、错误、数字或未完成事项，就必须输出 episode，即使没有任何新事实。仅空会话、闲聊、单纯确认才可 no_output。记录用户目标、过程顺序、每个决定及原因、实际文件路径、实际执行命令、报错原文（保留原语言和标点）、有单位的关键数字、实际结果、未完成项和用户纠正前后内容。没有证据的字段留空或数组为空；不得补全、猜测或把摘要当原文。每项细节都附能够打开对应 SessionDB 原消息的 source_ref。保留原说话者及 source_level；不要把助手、工具或外部 Agent 的观点写成用户陈述。

第二层：可选事实候选。扫描用户陈述、工具观察、模型推断中有来源支持的独立原子事实，包括身份、居住/工作、家庭关系、健康、习惯、喜好/厌恶、饮食/过敏、目标计划、正在做的项目和长期约束。临时事实提供可信 valid_from/valid_to；不确定的时间不猜日期。新信息才输出，结合有限已知事实和上次提炼避免重复；候选不是最终合并结果。key 表示事实主题；value 是值。source_level 只能为 user_assertion、tool_observation、model_inference。每个事实必须引用给定消息中的一个 source_ref。用户纠正永远最高；其余来源等级用户陈述 > 工具观察 > 模型推断；同等级较新有效事实优先。可标 supersedes/retracts，但不要删历史，也不要自行做最终冲突合并。

安全和证据：永不记录密码、密钥、令牌、卡号或证件号。不要把工具/网页/文件中的第三方文字说成用户自己的话。source_ref 必须逐字选自输入消息清单，不能编造 UID、范围或引用。事实为空时返回 facts:[]。"""

SCHEMA_HINT = (
    '{"episode":{"title":"…","summary":"按时间概括本次会话","skip":false,"decisions":[{"text":"决定","reason":"理由","source_ref":{},"source_role":"user","source_level":"user_assertion"}],'
    '"files":[{"path":"实际路径","source_ref":{},"source_role":"assistant","source_level":"model_inference"}],'
    '"commands":[{"text":"实际命令","source_ref":{},"source_role":"tool","source_level":"tool_observation"}],'
    '"errors":[{"text":"原始报错","source_ref":{},"source_role":"tool","source_level":"tool_observation"}],'
    '"numbers":[{"text":"数字及单位","source_ref":{},"source_role":"user","source_level":"user_assertion"}],'
    '"unfinished":[{"text":"未完成事项","source_ref":{},"source_role":"assistant","source_level":"model_inference"}],'
    '"user_corrections":[{"before":"原内容","after":"纠正后","source_ref":{},"source_role":"user","source_level":"user_assertion"}],'
    '"source_refs":[{}],"source_level":"user_assertion|tool_observation|model_inference"},'
    '"facts":[{"key":"user.home_city","value":"杭州","source_level":"user_assertion","recorded_at":"ISO-8601",'
    '"valid_from":null,"valid_to":null,"supersedes":[],"retracts":[],"source_ref":{}}]}'
)


@dataclass
class Proposal:
    # Legacy fields remain for callers migrating from the turn extractor.
    op: str = "set"
    key: str = ""
    value: str = ""
    text: str = ""
    quote: str = ""
    forget_after: str = ""
    triggers: list[str] = field(default_factory=list)
    importance: int = 5
    stance: str = "said"
    source_level: str = "legacy_unknown"
    recorded_at: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    supersedes: list[str] = field(default_factory=list)
    retracts: list[str] = field(default_factory=list)
    source_ref: dict[str, Any] | None = None


@dataclass
class Episode:
    title: str
    topics: list[str] = field(default_factory=list)
    did: str = ""
    outcome: str = ""
    skip: bool = False
    decisions: list[Any] = field(default_factory=list)
    files: list[Any] = field(default_factory=list)
    commands: list[Any] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    open_items: list[Any] = field(default_factory=list)
    summary: str = ""
    errors: list[Any] = field(default_factory=list)
    numbers: list[Any] = field(default_factory=list)
    unfinished: list[Any] = field(default_factory=list)
    user_corrections: list[Any] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    source_level: str = "legacy_unknown"


@dataclass
class ApplyResult:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    ended: list[str] = field(default_factory=list)
    forgotten: list[str] = field(default_factory=list)
    forgotten_texts: list[str] = field(default_factory=list)
    rejected: int = 0
    episode_written: bool = False

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.ended or self.forgotten)

    def message(self) -> str:
        parts = []
        if self.added:
            parts.append("记住 " + "、".join(self.added[:3]))
        if self.changed:
            parts.append("更新 " + "、".join(self.changed[:3]))
        if self.ended:
            parts.append("结束 " + "、".join(self.ended[:3]))
        if self.forgotten:
            parts.append(f"忘掉 {len(self.forgotten)} 条")
        return "；".join(parts) or "没有新事实"


def contains_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text or ""))


def known_facts(store: MemoryStore) -> list[tuple[str, str]]:
    known: list[tuple[str, str]] = []
    for rel in store.pages():
        for entry in store.read(rel).current:
            if entry.key:
                known.append((entry.key, entry.text if entry.src == SRC_EDITED else entry.value or entry.text))
    return known[-MAX_KNOWN:]


def _ref_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, SourceRef):
        return value.to_dict()
    if isinstance(value, str):
        return SourceRef.from_ref(value).to_dict()
    if isinstance(value, dict):
        # Round-trip through the frozen type to reject unknown keys and invalid spans.
        return SourceRef(**value).to_dict()
    raise ValueError("source_ref must be a SourceRef object")


def _message_source_line(message: dict[str, Any]) -> str:
    raw = message.get("source_ref")
    ref = _ref_dict(raw)
    return json.dumps(ref, ensure_ascii=False, separators=(",", ":"))


def build_messages(*, user_text: str = "", assistant_text: str = "",
                   known: list[tuple[str, str]], clock: str,
                   steps: list[dict] | None = None, verified: bool = False,
                   messages: list[dict[str, Any]] | None = None,
                   previous: dict[str, Any] | None = None) -> list[dict[str, str]]:
    known_block = "\n".join(f"- {k} = {v}" for k, v in known) or "（暂无）"
    if messages is None:
        messages = []
        if user_text:
            messages.append({"role": "user", "text": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "text": assistant_text})
    lines = []
    remaining = MAX_SESSION_CHARS
    for item in messages:
        ref = item.get("source_ref")
        try:
            ref_text = json.dumps(_ref_dict(ref), ensure_ascii=False, separators=(",", ":")) if ref else ""
        except (TypeError, ValueError):
            continue
        content = str(item.get("text") or item.get("content") or "")
        if not content or remaining <= 0:
            continue
        content = content[:remaining]
        remaining -= len(content)
        role = str(item.get("role") or "unknown")
        lines.append(f"- role={role}; source_ref={ref_text}\n{content}")
    previous_text = json.dumps(previous or {}, ensure_ascii=False)[:8000]
    payload = "\n\n".join([
        f"LOCAL CLOCK: {clock}",
        f"KNOWN FACTS (limited):\n{known_block}",
        f"VERIFIED BY A REAL CHECK: {'yes' if verified else 'no'}",
        "CANONICAL MESSAGES (chronological; refs are the only valid evidence):\n" + ("\n".join(lines) or "（空）"),
        f"PREVIOUS EXTRACTION (context only; update incrementally and preserve existing episode):\n{previous_text}",
        f"JSON schema example:\n{SCHEMA_HINT}",
    ])
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": payload}]


def _items(value: Any, *, text_key: str = "text", limit: int = 30, chars: int = 2000) -> list[Any]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:limit]:
        if isinstance(item, dict):
            row = dict(item)
            if "source_ref" in row:
                row["source_ref"] = _ref_dict(row["source_ref"])
            for key, field_value in row.items():
                if isinstance(field_value, str):
                    row[key] = field_value.strip()[:chars]
            out.append(row)
        elif str(item).strip():
            out.append(" ".join(str(item).split())[:chars])
    return out


def parse_output(raw: str) -> tuple[list[Proposal], Episode | None]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("extractor returned no JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ValueError("extractor returned invalid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("facts", []), list):
        raise ExtractionSchemaError("extractor schema requires a facts array")
    out: list[Proposal] = []
    for item in data.get("facts", []):
        if not isinstance(item, dict):
            raise ExtractionSchemaError("fact candidate must be an object")
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        op = str(item.get("op") or "set").strip()
        level = str(item.get("source_level") or "").strip()
        try:
            source_ref = _ref_dict(item.get("source_ref"))
        except (TypeError, ValueError) as exc:
            raise ExtractionSchemaError("fact candidate requires a valid source_ref") from exc
        if (not KEY_RE.match(key) or (not value and op not in {"forget", "retract"})
                or level not in SOURCE_LEVELS - {"legacy_unknown"} or op not in {"set", "forget", "retract"}):
            raise ExtractionSchemaError("fact candidate has invalid key, value, or source_level")
        valid_from = item.get("valid_from")
        valid_to = item.get("valid_to")
        for name, temporal in (("valid_from", valid_from), ("valid_to", valid_to)):
            if temporal is not None:
                if not isinstance(temporal, str):
                    raise ExtractionSchemaError(f"{name} must be an ISO-8601 string or null")
                try:
                    datetime.fromisoformat(temporal)
                except ValueError as exc:
                    raise ExtractionSchemaError(f"{name} must be a valid ISO-8601 value") from exc
        try:
            importance = max(1, min(10, int(item.get("importance") or 5)))
        except (TypeError, ValueError):
            importance = 5
        out.append(Proposal(
            op=op, key=key, value=value,
            text=str(item.get("text") or value).strip(),
            source_level=level, recorded_at="",
            valid_from=valid_from, valid_to=valid_to,
            supersedes=[str(x) for x in item.get("supersedes", []) if str(x)][:20]
            if isinstance(item.get("supersedes", []), list) else [],
            retracts=[str(x) for x in item.get("retracts", []) if str(x)][:20]
            if isinstance(item.get("retracts", []), list) else [],
            source_ref=source_ref, importance=importance,
        ))
    raw_episode = data.get("episode")
    if raw_episode is not None and not isinstance(raw_episode, dict):
        raise ExtractionSchemaError("extractor schema requires an episode object or null")
    episode = None
    if raw_episode is not None:
        level = str(raw_episode.get("source_level") or "legacy_unknown")
        if level not in SOURCE_LEVELS:
            raise ExtractionSchemaError("episode has invalid source_level")
        refs = raw_episode.get("source_refs", [])
        if not isinstance(refs, list):
            raise ExtractionSchemaError("episode.source_refs must be an array")
        try:
            source_refs = [_ref_dict(ref) for ref in refs]
        except (TypeError, ValueError) as exc:
            raise ExtractionSchemaError("episode contains invalid source_ref") from exc
        episode = Episode(
            title=" ".join(str(raw_episode.get("title") or "").split())[:120],
            topics=[" ".join(str(t).split())[:40] for t in raw_episode.get("topics", []) if str(t).strip()][:10]
            if isinstance(raw_episode.get("topics", []), list) else [],
            did=" ".join(str(raw_episode.get("did") or "").split())[:200],
            outcome=" ".join(str(raw_episode.get("outcome") or "").split())[:500],
            skip=bool(raw_episode.get("skip", False)),
            decisions=_items(raw_episode.get("decisions", [])),
            files=_items(raw_episode.get("files", [])),
            commands=_items(raw_episode.get("commands", [])),
            facts=[" ".join(str(x).split())[:500] for x in raw_episode.get("facts", []) if str(x).strip()][:30]
            if isinstance(raw_episode.get("facts", []), list) else [],
            open_items=_items(raw_episode.get("unfinished", raw_episode.get("open_items", []))),
            summary=" ".join(str(raw_episode.get("summary") or "").split())[:4000],
            errors=_items(raw_episode.get("errors", [])),
            numbers=_items(raw_episode.get("numbers", [])),
            unfinished=_items(raw_episode.get("unfinished", [])),
            user_corrections=_items(raw_episode.get("user_corrections", [])),
            source_refs=source_refs, source_level=level,
        )
        if not episode.skip and (not episode.title or not episode.source_refs):
            raise ExtractionSchemaError("non-empty episode requires a title and source_refs")
    return out, episode


def _plain(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("path") or json.dumps(item, ensure_ascii=False))
    return str(item)


def _episode_lists(episode: Episode) -> dict[str, list[str]]:
    return {
        "decisions": [
            (f"{x.get('text','')}；理由：{x.get('reason','')}" if isinstance(x, dict) else _plain(x))[:1000]
            for x in episode.decisions if _plain(x).strip()
        ] + [f"用户纠正：{x.get('before','')} → {x.get('after','')}"[:1000]
             for x in episode.user_corrections if isinstance(x, dict)],
        "files": [_plain(x)[:500] for x in episode.files if _plain(x).strip()],
        "commands": [_plain(x)[:1000] for x in episode.commands if _plain(x).strip()],
        "facts": [*episode.facts, *[f"关键数字：{_plain(x)}"[:1000] for x in episode.numbers]],
        "open_items": [
            *[_plain(x)[:1000] for x in [*episode.unfinished, *episode.open_items] if _plain(x).strip()],
            *[f"报错原文：{_plain(x)}"[:2000] for x in episode.errors if _plain(x).strip()],
        ],
    }


def _set_metadata(entry: Entry, values: dict[str, Any]) -> None:
    supported = {f.name for f in fields(entry)}
    extra = getattr(entry, "extra_metadata", None)
    if not isinstance(extra, dict):
        extra = getattr(entry, "extra_meta", None)
    if not isinstance(extra, dict):
        extra = getattr(entry, "metadata", None)
    for key, value in values.items():
        if key in supported:
            setattr(entry, key, value)
        elif isinstance(extra, dict):
            extra[key] = value


def _metadata(entry: Entry) -> dict[str, Any]:
    getter = getattr(entry, "meta", None)
    value = getter() if callable(getter) else {}
    if not isinstance(value, dict):
        value = {}
    extra = getattr(entry, "extra_metadata", None)
    if not isinstance(extra, dict):
        extra = getattr(entry, "extra_meta", None)
    if isinstance(extra, dict):
        value = {**value, **extra}
    return value


def apply_episode(store: MemoryStore, episode: Episode | None, steps: list[dict], verified: bool,
                  session: str, now: datetime, mode: str = "", ref: str = "",
                  *, source_refs: list[dict[str, Any]] | None = None) -> bool:
    if episode is None or episode.skip or not episode.title:
        return False
    source_refs = source_refs or episode.source_refs
    title = episode.title[:120]
    detail = episode.summary or episode.outcome or episode.did
    if not detail and not any((episode.decisions, episode.files, episode.commands, episode.errors,
                               episode.numbers, episode.unfinished, episode.user_corrections)):
        return False
    serialized = json.dumps({"summary": episode.summary, "decisions": episode.decisions,
                              "files": episode.files, "commands": episode.commands,
                              "errors": episode.errors, "numbers": episode.numbers,
                              "unfinished": episode.unfinished,
                              "user_corrections": episode.user_corrections,
                              "source_refs": source_refs}, ensure_ascii=False)
    if contains_secret(title + detail + serialized):
        return False
    if store.tombstoned(tombstone_hashes("", "", title + detail)):
        return False
    day = now.date().isoformat()
    page = store.read(f"经历/{day}.md")
    entry = next((e for e in page.current if e.session == session), None)
    if entry is None:
        for rel in reversed(store.pages()):
            if not rel.startswith("经历/") or rel == page.path:
                continue
            prior = store.read(rel)
            entry = next((e for e in prior.current if e.session == session), None)
            if entry is not None:
                page = prior
                break
    text = f"{title}：{detail[:1500]}"[:2000]
    lists = _episode_lists(episode)
    source_ref = source_refs[-1] if source_refs else None
    source_ref_uri = SourceRef(**source_ref).to_ref() if source_ref else ref
    meta = {"source_level": episode.source_level, "recorded_at": now.isoformat(timespec="seconds"),
            "source_ref": source_ref, "extractor_version": EXTRACTOR_VERSION}
    details = {"summary": episode.summary, "decisions": episode.decisions,
               "files": episode.files, "commands": episode.commands, "errors": episode.errors,
               "numbers": episode.numbers, "unfinished": episode.unfinished,
               "user_corrections": episode.user_corrections, "source_refs": source_refs}
    if entry is None:
        entry = Entry(text=text, id=new_id(), src="经历", at=now.isoformat(timespec="seconds"),
                      session=session, mode=mode if mode == "expert" else "", ref=source_ref_uri,
                      outcome=episode.outcome[:500], verified=bool(verified), **lists)
        _set_metadata(entry, {**meta, "episode_summary": episode.summary,
                              "errors": episode.errors, "numbers": episode.numbers,
                              "user_corrections": episode.user_corrections,
                              "source_refs": list(source_refs), "episode_details": details})
        page.current.append(entry)
    else:
        if entry.src == SRC_EDITED:
            return False
        entry.text = text
        entry.outcome = episode.outcome[:500]
        entry.verified = bool(entry.verified or verified)
        entry.ref = source_ref_uri or entry.ref
        for name, values in lists.items():
            setattr(entry, name, list(dict.fromkeys([*getattr(entry, name), *values]))[-5:])
        # Keep rich structured fields in metadata when supported by the M2 codec.
        prior_refs = _metadata(entry).get("source_refs", getattr(entry, "source_refs", []))
        merged_refs = list(prior_refs) if isinstance(prior_refs, list) else []
        seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in merged_refs if isinstance(item, dict)}
        for item in source_refs:
            encoded = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if encoded not in seen:
                seen.add(encoded)
                merged_refs.append(item)
        old_meta = _metadata(entry)
        def merged(name: str, items: list[Any]) -> list[Any]:
            details_old = old_meta.get("episode_details", {})
            if name == "source_refs":
                combined = list(old_meta.get(name, [])) if isinstance(old_meta.get(name), list) else []
            elif isinstance(details_old, dict) and isinstance(details_old.get(name), list):
                combined = list(details_old[name])
            else:
                combined = list(old_meta.get(name, [])) if isinstance(old_meta.get(name), list) else []
            tokens = {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in combined}
            for value in items:
                token = json.dumps(value, sort_keys=True, ensure_ascii=False)
                if token not in tokens:
                    tokens.add(token)
                    combined.append(value)
            return combined
        details = {"summary": episode.summary,
                   "decisions": merged("decisions", episode.decisions),
                   "files": merged("files", episode.files),
                   "commands": merged("commands", episode.commands),
                   "errors": merged("errors", episode.errors),
                   "numbers": merged("numbers", episode.numbers),
                   "unfinished": merged("unfinished", episode.unfinished),
                   "user_corrections": merged("user_corrections", episode.user_corrections),
                   "source_refs": merged_refs}
        _set_metadata(entry, {**meta, "episode_summary": episode.summary,
                              "errors": merged("errors", episode.errors),
                              "numbers": merged("numbers", episode.numbers),
                              "user_corrections": merged("user_corrections", episode.user_corrections),
                              "source_refs": merged_refs, "episode_details": details})
    store.write(page)
    return True


def _locate(store: MemoryStore, key: str) -> tuple[Page, int] | None:
    for rel in store.pages():
        page = store.read(rel)
        for i, entry in enumerate(page.current):
            if entry.key == key:
                return page, i
    return None


def apply(store: MemoryStore, proposals: list[Proposal], *, user_text: str = "", session: str,
          mode: str, now: datetime, ref: str = "") -> ApplyResult:
    """Persist source-backed candidates in Markdown history for M4 to merge.

    Candidates are not made current here. The caller verifies each SourceRef
    against SessionDB before this function; M4 owns final conflict application.
    """
    result = ApplyResult()
    stamp = now.isoformat(timespec="seconds")
    for p in proposals:
        if (not KEY_RE.match(p.key) or (not p.value and p.op not in {"forget", "retract"})
                or contains_secret(p.text + p.value)):
            result.rejected += 1
            continue
        if not p.source_ref:
            # Compatibility callers may still send exact user quotations.
            if not p.quote or p.quote not in user_text:
                result.rejected += 1
                continue
            level = "user_assertion"
            source_ref = None
        else:
            try:
                source_ref = _ref_dict(p.source_ref)
            except (TypeError, ValueError):
                result.rejected += 1
                continue
            level = p.source_level if p.source_level in SOURCE_LEVELS else "legacy_unknown"
        if p.op in {"forget", "retract"}:
            if level != "user_assertion":
                result.rejected += 1
                continue
            found = _locate(store, p.key)
            if found is None:
                continue
            page, idx = found
            old = page.current.pop(idx)
            if p.op == "forget":
                store.add_tombstones(tombstone_hashes(old.key, old.value, old.text), "用户要求忘掉")
                store.redact_diary([old.quote, old.text, old.value])
                result.forgotten.append(old.id)
                result.forgotten_texts.extend([old.text, old.quote, old.value])
            else:
                old.ended, old.why = now.date().isoformat(), "用户表示不再成立"
                page.history.insert(0, old)
                result.ended.append(old.text)
            store.write(page)
            continue
        if p.op != "set":
            result.rejected += 1
            continue
        if store.tombstoned(tombstone_hashes(p.key, p.value, p.text)):
            result.rejected += 1
            continue
        text = p.text or p.value
        until = p.valid_to or p.forget_after
        entry = Entry(text=text, id=new_id(), key=p.key, value=p.value,
                      src="M3候选", at=stamp,
                      until=until or "", quote=p.quote[:300], session=session, mode=mode,
                      ref=SourceRef(**source_ref).to_ref() if source_ref else ref,
                      importance=p.importance, trigger=p.triggers)
        entry.why = "待 M4 整合"
        _set_metadata(entry, {"source_level": level, "recorded_at": stamp,
                              "valid_from": p.valid_from, "valid_to": p.valid_to,
                              "supersedes": p.supersedes, "retracts": p.retracts,
                              "source_ref": source_ref, "extractor_version": EXTRACTOR_VERSION})
        target = page_for_key(p.key, temporary=bool(until))
        page = store.read(target)
        if page.kind in ("person", "thing") and not page.current and not page.history:
            page.title = safe_name(p.key.split(".")[1])
        source_id = (source_ref or {}).get("message_uid", "")
        duplicate = next((old for old in [*page.current, *page.history]
                          if old.key == p.key and old.src == "M3候选"
                          and _metadata(old).get("extractor_version") == EXTRACTOR_VERSION
                          and (_metadata(old).get("source_ref") or {}).get("message_uid", "") == source_id
                          and (old.value or old.text) == p.value), None)
        if duplicate is not None:
            continue
        page.history.insert(0, entry)
        store.write(page)
        result.added.append(text)
    return result


def expire(store: MemoryStore, now: datetime) -> list[str]:
    """Move temporary facts whose ``until`` has passed to history (never delete)."""
    ended: list[str] = []
    for rel in store.pages():
        page = store.read(rel)
        keep: list[Entry] = []
        moved = False
        for entry in page.current:
            try:
                due = entry.until and datetime.fromisoformat(entry.until) <= now
            except ValueError:
                due = False
            if due:
                entry.ended, entry.why = now.date().isoformat(), "到期"
                page.history.insert(0, entry)
                ended.append(entry.text)
                moved = True
            else:
                keep.append(entry)
        if moved:
            page.current = keep
            store.write(page)
    return ended


__all__ = ["Proposal", "Episode", "ApplyResult", "build_messages", "parse_output", "apply",
           "apply_episode", "expire", "known_facts", "contains_secret", "EXTRACTOR_VERSION"]
