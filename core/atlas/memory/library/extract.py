"""Turn one conversation turn into memory-library changes.

The extraction prompt is ported from Atlas' former MemOS fork
(``core/facts/observe.ts``, removed with the old memory systems), whose rules scored 30/30 with no misremembered facts in F3-A. Changes for
the library: keys may name people and projects in the user's own words so each lands on
its own page, and an ``alias`` op links names for the same person.

Guards kept from the fork: a proposal is applied only when its quote really occurs in the
user's message, and secrets are never written. Added here: values the user asked to forget
(tombstones) are dropped, and relative dates must already be resolved by the model.
"""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .store import (
    SRC_EDITED, SRC_SAID, Entry, MemoryStore, Page, new_id, page_for_key, safe_name, tombstone_hashes,
)

MAX_USER_CHARS = 4000
MAX_KNOWN = 150
KEY_RE = re.compile(r"^[a-z0-9_]+(\.[^\s.]+){0,4}$")
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:密码|password|passwd|pwd|口令|token|api[_ ]?key)\s*[:：=是为]\s*\S{4,})",
    re.I,
)

SYSTEM_PROMPT = """You maintain the long-term list of FACTS ABOUT THE USER for a personal assistant.
Read the user's latest message (the assistant's reply is context only) and propose changes to that list.

WHAT COUNTS AS A USER FACT
- Something the user TELLS you about themselves or their world: identity, where they live or work, family and people they know, possessions, health, habits, preferences and dislikes, ongoing projects and their constraints, decisions they have made, plans they will carry out themselves.
- USER ASSERTIONS ARE AUTHORITATIVE. The user is the source of truth about their own life.

WHAT IS NOT A USER FACT (never record these)
- Questions, information requests, requests for help, instructions for work happening now. Only a personal fact explicitly disclosed inside them counts: in "我女儿 6 岁了，她该上几年级？" record "用户的女儿 6 岁", not the grade question.
- Hypotheticals and conditionals ("如果/假如/假设我想……", "if I wanted to…") do not establish a plan, decision or preference.
- Conditions asked about in a question (e.g. asking whether a café has sockets) do not establish a preference or need.
- Assistant suggestions, search filters, examples.
- Text pasted from web pages, files or tool output: that is third-party content, not the user's own facts.
- Role-play, fiction, quoting someone else, or "pretend you are…" content.
- Things the user says about other people's opinions are facts about those people only if the user asserts them.
- Passwords, keys, tokens, card or ID numbers: never record them.

CHANGES
- If the user changes something already known ("改成周五了", "我搬到上海了", "不用 SQLite 了，改用 PostgreSQL"), emit op "set" with the SAME key as the known fact and the new value. The old value is kept as history automatically.
- If the user says a known fact is no longer true and gives no replacement ("我已经不养猫了"), emit op "retract" for that key.
- If the message only repeats a known fact with the same value, emit nothing for it.
- If the user asks you to forget something ("忘掉我住哪", "别记我对花生过敏这件事"), emit op "forget" for that key with the request as quote.

TEMPORARY FACTS
- Some facts are only true for a while: a state or event tied to a time ("我明天下午有面试", "这周在北京出差", "今天头疼", "下个月在休假"). Give them forget_after = the local date-time when they stop being true (end of that day / week / period), as ISO 8601 with the local UTC offset, resolved with the clock below.
- Lasting facts (where the user lives, family, preferences, allergies, standing project rules) have forget_after null.

KEYS
- key is dot-separated. The first part is one of: user, person, project.
- user.<attribute>: about the user. Attribute slugs are short lower-case English: user.home_city, user.employer, user.diet.allergy, user.preference.answer_style, user.plan.interview.
- person.<name>.<attribute>: about someone the user knows. <name> is how the USER calls them, in the user's language (person.老王.relation, person.妈妈.health). Use the same <name> every time.
- project.<name>.<attribute>: a project, product or event of the user's (project.Atlas.test_policy, project.搬家.date).
- REUSE the key of a known fact when the message is about the same attribute. One key = one attribute.
- If the user says two names are the same person ("王总就是老王"), emit op "alias" with key person.<known name> and value = the other name.

OUTPUT
- value: the bare value, in the user's language ("杭州", "周五", "对花生过敏").
- text: one short sentence stating the fact in the user's language. Write it WITHOUT a subject when it is about the user ("住在杭州", "对花生过敏"); name the person for person facts ("老王是我同事"). Resolve relative dates ("明天", "下周三") to an actual date using the clock below, and include it.
- quote: the exact span of the user's message that states the fact, copied character for character (no paraphrase, no translation). Proposals whose quote is not in the message are discarded.
- forget_after: ISO 8601 date-time with offset for temporary facts, otherwise null.
- triggers: 0-3 short words that should bring this fact to mind later (names, places, topics), in the user's language.
- stance: "said" when the user states it as true about their own life; "hypothetical" for if/假如/假设; "question" when it only appears inside a question; "quoted" when it is someone else's words, pasted text or role-play. Only "said" facts are kept.
- importance: 1-10, how much this matters for helping the user later (allergy, family, deadlines high; passing likes low).
- Return {"facts": []} when the message states no fact about the user. Most messages state none; do not invent."""

SYSTEM_PROMPT += """

EPISODES
- In addition to facts, return an episode object describing what happened this turn, for later questions such as what we discussed or how we did something.
- title: what the user wanted this turn, in the user's language, at most 30 characters.
- topics: 0-5 keywords such as product, project, person, or technology names.
- did: what Atlas actually did, at most 60 characters, based only on TOOLS USED and its reply; use "直接回答" when no tool was used.
- outcome: one sentence of at most 60 characters describing the result. State failure or incompletion honestly.
- skip: true for small talk, a reply of only "ok", or a connectivity-only test.
- decisions, files, commands, facts, open_items: each is a list of at most 5 items, each at most 80 characters. Use only this turn's user message, assistant reply and TOOLS USED; use [] when there is no evidence. Never invent.
- Episodes are conversation history, not user facts. Never copy episode content into facts.
"""

SCHEMA_HINT = (
    '{"facts":[{"op":"set|retract|forget|alias","key":"user.home_city","value":"杭州",'
    '"text":"住在杭州","quote":"我住在杭州","stance":"said","forget_after":null,"triggers":["杭州"],"importance":6}],'
    '"episode":{"title":"…","topics":["…"],"did":"…","outcome":"…","skip":false,'
    '"decisions":[],"files":[],"commands":[],"facts":[],"open_items":[]}}'
)


@dataclass
class Proposal:
    op: str
    key: str
    value: str = ""
    text: str = ""
    quote: str = ""
    forget_after: str = ""
    triggers: list[str] = field(default_factory=list)
    importance: int = 5
    stance: str = "said"


@dataclass
class Episode:
    title: str
    topics: list[str] = field(default_factory=list)
    did: str = ""
    outcome: str = ""
    skip: bool = False
    decisions: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    ended: list[str] = field(default_factory=list)
    forgotten: list[str] = field(default_factory=list)
    forgotten_texts: list[str] = field(default_factory=list)
    rejected: int = 0

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.ended or self.forgotten)

    def message(self) -> str:
        parts = []
        if self.added:
            parts.append("记下：" + "；".join(self.added))
        if self.changed:
            parts.append("更新：" + "；".join(self.changed))
        if self.ended:
            parts.append("不再成立：" + "；".join(self.ended))
        if self.forgotten:
            parts.append(f"按你的要求忘掉了 {len(self.forgotten)} 条")
        return " / ".join(parts)[:400] or "无变化"


def contains_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text or ""))


def known_facts(store: MemoryStore) -> list[tuple[str, str]]:
    known: list[tuple[str, str]] = []
    for rel in store.pages():
        for entry in store.read(rel).current:
            if entry.key:
                known.append((entry.key, entry.text if entry.src == SRC_EDITED else entry.value or entry.text))
    return known[-MAX_KNOWN:]


def build_messages(*, user_text: str, assistant_text: str, known: list[tuple[str, str]],
                   clock: str, steps: list[dict] | None = None,
                   verified: bool = False) -> list[dict[str, str]]:
    known_block = "\n".join(f"- {k} = {v}" for k, v in known) or "(none yet)"
    step_lines = []
    for step in (steps or [])[:30]:
        name = str(step.get("name") or "tool")
        mark = "✓" if step.get("ok") else "✗" if step.get("ok") is False else "…"
        note = " ".join(str(step.get("note") or "").split())[:200]
        step_lines.append(f"- {name} {mark}{' ' + note if note else ''}")
    tools_block = "TOOLS USED THIS TURN (name, ok, note):\n" + ("\n".join(step_lines) or "- (none)")
    payload = "\n\n".join([
        f"USER LOCAL CLOCK: {clock}",
        f"KNOWN USER FACTS (key = current value):\n{known_block}",
        "ASSISTANT'S PREVIOUS REPLY (context only, never a source of user facts):\n"
        + ((assistant_text or "")[:1500] or "(none)"),
        tools_block,
        f"VERIFIED BY A REAL CHECK: {'yes' if verified else 'no'}",
        f"USER MESSAGE:\n{user_text[:MAX_USER_CHARS]}",
        f"Return JSON only, shaped like: {SCHEMA_HINT}",
    ])
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": payload}]


def parse_output(raw: str) -> tuple[list[Proposal], Episode | None]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return [], None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return [], None
    out: list[Proposal] = []
    for item in data.get("facts") or []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "set").strip()
        key = str(item.get("key") or "").strip()
        if op not in {"set", "retract", "forget", "alias"} or not KEY_RE.match(key):
            continue
        triggers = item.get("triggers") or []
        try:
            importance = max(1, min(10, int(item.get("importance") or 5)))
        except (TypeError, ValueError):
            importance = 5
        out.append(Proposal(
            op=op, key=key,
            value=str(item.get("value") or "").strip(),
            text=str(item.get("text") or "").strip(),
            quote=str(item.get("quote") or "").strip(),
            forget_after=str(item.get("forget_after") or "").strip(),
            triggers=[str(t).strip() for t in triggers if str(t).strip()][:3]
            if isinstance(triggers, list) else [],
            importance=importance,
            stance=str(item.get("stance") or "said").strip(),
        ))
    raw_episode = data.get("episode")
    episode = None
    if isinstance(raw_episode, dict):
        try:
            topics = raw_episode.get("topics") or []
            episode = Episode(
                title=" ".join(str(raw_episode.get("title") or "").split())[:30],
                topics=[" ".join(str(t).split())[:40] for t in topics if str(t).strip()][:5]
                if isinstance(topics, list) else [],
                did=" ".join(str(raw_episode.get("did") or "").split())[:60],
                outcome=" ".join(str(raw_episode.get("outcome") or "").split())[:60],
                skip=bool(raw_episode.get("skip", False)),
                **{name: [" ".join(str(item).split())[:80] for item in raw_episode.get(name, [])
                          if str(item).strip()][:5]
                   for name in ("decisions", "files", "commands", "facts", "open_items")
                   if isinstance(raw_episode.get(name, []), list)},
            )
        except (TypeError, ValueError):
            episode = None
    return out, episode


def apply_episode(store: MemoryStore, episode: Episode | None, steps: list[dict], verified: bool,
                  session: str, now: datetime, mode: str = "", ref: str = "") -> bool:
    if episode is None or episode.skip or not episode.title:
        return False
    did = episode.did or "直接回答"
    text = f"{episode.title}：{did}"[:120]
    if contains_secret(text + episode.outcome + json.dumps(steps, ensure_ascii=False)):
        return False
    hashes = tombstone_hashes("", "", text)
    if store.tombstoned(hashes):
        return False
    day = now.date().isoformat()
    rel = f"经历/{day}.md"
    page = store.read(rel)
    entry = next((e for e in page.current if e.session == session), None)
    safe_steps = []
    for step in (steps or [])[:30]:
        name = str(step.get("name") or "tool")
        mark = "✓" if step.get("ok") else "✗"
        note = " ".join(str(step.get("note") or "").split())[:200]
        safe_steps.append(f"{name} {mark}{' ' + note if note else ''}")
    if entry is None:
        entry = Entry(text=text, id=new_id(), src="经历", at=now.isoformat(timespec="seconds"),
                      session=session, mode=mode if mode == "expert" else "",
                      trigger=episode.topics[:3], steps=safe_steps[:8], outcome=episode.outcome,
                      verified=bool(verified), ref=ref, **_episode_lists(episode))
        page.current.append(entry)
    else:
        original_title = entry.text.split("：", 1)[0]
        old_did = entry.text.split("：", 1)[1] if "：" in entry.text else ""
        parts = [p for p in old_did.split("；") if p]
        merged = "；".join(parts if did in parts else [*parts, did])
        entry.text = f"{original_title}：{merged[-max(1, 400 - len(original_title) - 1):]}"
        entry.outcome = episode.outcome
        entry.steps = (entry.steps + safe_steps)[-8:]
        entry.verified = bool(entry.verified or verified)
        entry.trigger = list(dict.fromkeys([*entry.trigger, *episode.topics]))[:3]
        entry.ref = ref or entry.ref
        for name, values in _episode_lists(episode).items():
            setattr(entry, name, list(dict.fromkeys([*getattr(entry, name), *values]))[-5:])
        entry.at = now.isoformat(timespec="seconds")
        if mode == "expert":
            entry.mode = "expert"
    store.write(page)
    return True


def _quote_ok(quote: str, user_text: str) -> bool:
    squash = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
    return bool(quote) and squash(quote) in squash(user_text)


def _episode_lists(episode: Episode) -> dict[str, list[str]]:
    return {name: list(dict.fromkeys(" ".join(str(item).split())[:80]
                                     for item in getattr(episode, name) if str(item).strip()))[-5:]
            for name in ("decisions", "files", "commands", "facts", "open_items")}


def _locate(store: MemoryStore, key: str) -> tuple[Page, int] | None:
    for rel in store.pages():
        page = store.read(rel)
        for i, entry in enumerate(page.current):
            if entry.key == key:
                return page, i
    return None


def apply(store: MemoryStore, proposals: list[Proposal], *, user_text: str, session: str,
          mode: str, now: datetime, ref: str = "", workspace: str = "") -> ApplyResult:
    """Apply proposals to the Markdown pages. Caller holds ``store.lock`` and commits."""
    result = ApplyResult()
    stamp = now.isoformat(timespec="seconds")
    today = now.date().isoformat()
    project_root = ""
    if workspace and not workspace.startswith("ssh://"):
        try:
            project_root = subprocess.run(
                ["git", "-C", workspace, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            try:
                project_root = str(Path(workspace).resolve())
            except OSError:
                pass
    project_scope = hashlib.sha256(project_root.casefold().encode("utf-8")).hexdigest()[:16] if project_root else ""

    def target_for(key: str, temporary: bool) -> str:
        if project_scope and key.startswith(("project.", "user.project.")):
            return f"项目/{project_scope}.md"
        return page_for_key(key, temporary=temporary)
    for p in proposals:
        if p.op in {"set", "alias"} and p.stance != "said":
            result.rejected += 1
            continue
        if not _quote_ok(p.quote, user_text) or contains_secret(p.quote + p.text + p.value):
            result.rejected += 1
            continue
        found = _locate(store, p.key)
        if p.op == "alias":
            if not p.key.startswith("person.") or not p.value:
                result.rejected += 1
                continue
            rel = page_for_key(p.key, temporary=False)
            page = store.read(rel)
            if p.value not in page.aliases and p.value != page.title:
                page.aliases.append(p.value)
                store.write(page)
                result.changed.append(f"{page.title} 也叫 {p.value}")
            continue
        if p.op in {"retract", "forget"}:
            if found is None:
                continue
            page, i = found
            old = page.current.pop(i)
            if p.op == "forget":
                store.add_tombstones(tombstone_hashes(old.key, old.value, old.text), "用户要求忘掉")
                store.redact_diary([old.quote, old.text, old.value])
                result.forgotten.append(old.id)
                result.forgotten_texts.extend([old.text, old.quote, old.value])
            else:
                old.ended, old.why = today, "你说不再成立"
                page.history.insert(0, old)
                result.ended.append(old.text)
            store.write(page)
            continue
        # op == "set"
        text = p.text or p.value
        if not text or store.tombstoned(tombstone_hashes(p.key, p.value, text)):
            result.rejected += 1
            continue
        entry = Entry(
            text=text, id=new_id(), key=p.key, value=p.value, src=SRC_SAID, at=stamp,
            until=p.forget_after, quote=p.quote[:300], session=session, mode=mode, ref=ref,
            importance=p.importance, trigger=p.triggers,
            scope=(f"project:{project_scope}" if project_scope and
                   p.key.startswith(("project.", "user.project.")) else "global"),
        )
        if found is not None:
            page, i = found
            old = page.current[i]
            if (old.value or old.text).strip() == (p.value or text).strip():
                continue
            old.ended, old.why = today, f"改成：{text}"
            page.current.pop(i)
            page.history.insert(0, old)
            target = target_for(p.key, temporary=bool(p.forget_after))
            if target == page.path:
                page.current.append(entry)
                store.write(page)
            else:
                store.write(page)
                dest = store.read(target)
                dest.current.append(entry)
                store.write(dest)
            result.changed.append(text)
        else:
            target = target_for(p.key, temporary=bool(p.forget_after))
            page = store.read(target)
            if page.kind in ("person", "thing") and not page.current and not page.history:
                page.title = safe_name(p.key.split(".")[1])
            page.current.append(entry)
            store.write(page)
            result.added.append(text)
    return result


def expire(store: MemoryStore, now: datetime) -> list[str]:
    """Move temporary facts whose ``until`` has passed to history (they are not deleted)."""
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
