"""Episodic → semantic consolidation: digest episodes into facts, propose then apply.

Raw episodes (``经历/``) and diary turns (``日记/``) pile up next to the curated
semantic pages (``我.md`` / ``现状.md`` / ``它自己.md``), and nothing reads one into
the other, so the semantic pages go stale while the episodes keep growing. A person
does the opposite: episodes get digested into durable knowledge.

The pass is deliberately split in two, because silently rewriting ``我.md`` is not
acceptable:

* **propose** (default) reads a window of episodes and diary turns, asks the
  consolidation model for *semantic* candidates, and writes ``语义候选.md`` — a
  reviewable list where every candidate carries the verbatim quote plus the
  file/date it came from. Nothing else in the library changes.
* **apply** takes the still-pending candidates from that file and adds them as
  entries. It only appends. A contradicting older entry is kept, its priority is
  lowered, and the replacement is recorded in the append-only
  ``supersede.jsonl`` ledger (:meth:`MemoryLibrary.record_supersession`).
  Consolidation never deletes an entry and never moves one out of a page.

Deduplication is deterministic: a candidate id is a hash of its key plus its
normalised value, live entries are matched by ``key``/value, and forgotten values
are matched against the tombstone file. Running the same window twice adds nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from .extract import contains_secret
from .store import SRC_DREAM, SRC_EPISODE, EPISODES, Entry, new_id, page_for_key, tombstone_hashes

log = structlog.get_logger(__name__)

# 提议文件放在记忆库根目录：它不在 store.pages() 里，所以不会被索引成"事实"，
# 但会跟着记忆库一起进 git，谁在什么时候提了什么都有据可查。
CANDIDATES_FILE = "语义候选.md"
MAX_SOURCES = 90
MAX_CANDIDATES = 8
MAX_PENDING = 40
SOURCE_BUDGET_CHARS = 18000
DEFAULT_WINDOW_DAYS = 14
_OFF = {"0", "off", "false", "no", "disable", "disabled"}

_JSON_FENCE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.S)
_REF = re.compile(r'"ref"\s*:\s*"([^"]+)"')
_CJK = re.compile(r"[\u4e00-\u9fff]")
_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[^\s.]+){0,4}$")
#: 探针回合：让人机回声一个固定 token，或"跑 echo 再把输出念给我"。
#: 这类话里没有可长期保留的说法，不该进入候选的原文池。
_PROBE = re.compile(
    r"(?:只)?(?:回复|回答|输出|说出)\s*(?:[一二两三四五六0-9]+\s*个(?:字|词|单词))"
    r"|reply\s+with\s+exactly"
    r"|用\s*terminal\s*[^。\n]{0,12}?(?:执行|跑|运行|echo)"
    r"|(?:执行|跑|运行)\s*echo\b",
    re.I,
)


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _stamp(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _candidate_id(key: str, value: str) -> str:
    """Deterministic id: the same fact from the same evidence always lands on the same id."""
    digest = hashlib.sha1((key.casefold() + "\x1f" + _norm(value)).encode("utf-8")).hexdigest()
    return "c_" + digest[:10]


@dataclass
class Source:
    """One quotable piece of evidence: an episode entry or one diary turn."""

    id: str
    kind: str  # "episode" | "diary"
    path: str
    date: str
    text: str
    at: str = ""
    ref: str = ""
    who: str = SRC_EPISODE

    @property
    def label(self) -> str:
        where = f"{self.path} {self.at}".strip() if self.at else self.path
        return f"{where}（{self.who}）"

    def row(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "date": self.date,
            "at": self.at,
            "who": self.who,
        }


# --------------------------------------------------------------------------- window


def _read_episodes(library: Any, cutoff: str, bucket: list[Source]) -> None:
    try:
        pages = list(library.store.pages())
    except Exception:  # noqa: BLE001 - a broken store must not break the caller's run
        return
    for rel in pages:
        if not str(rel).startswith(EPISODES + "/"):
            continue
        try:
            page = library.store.read(rel)
        except Exception:  # noqa: BLE001
            continue
        for index, entry in enumerate(getattr(page, "current", None) or []):
            at = str(getattr(entry, "at", "") or "")
            date = at[:10]
            if not date or date < cutoff:
                continue
            text = " ".join(str(getattr(entry, "text", "") or "").split())
            if not text:
                continue
            bucket.append(
                Source(
                    id=str(getattr(entry, "id", "") or f"{rel}#{index}"),
                    kind="episode",
                    path=str(rel),
                    date=date,
                    text=text,
                    at=at[11:16],
                    ref=str(getattr(entry, "ref", "") or ""),
                    who=SRC_EPISODE,
                )
            )


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split a diary page into ``(HH:MM, body)`` at each ``## `` heading."""
    blocks: list[tuple[str, str]] = []
    head, body = "", []
    for raw in text.splitlines():
        if raw.startswith("## "):
            if body and "\n".join(body).strip():
                blocks.append((head, "\n".join(body).strip()))
            head, body = raw[3:].strip(), []
        elif not raw.startswith("# "):
            body.append(raw)
    if body and "\n".join(body).strip():
        blocks.append((head, "\n".join(body).strip()))
    return blocks


def _user_words(body: str) -> str:
    """Only the ``你：`` half of a diary turn: the user's own words, not Atlas's."""
    lines: list[str] = []
    keep = False
    for raw in body.splitlines():
        stripped = raw.strip()
        if stripped.startswith("你："):
            keep = True
            lines.append(stripped[2:])
        elif stripped.startswith("它："):
            keep = False
        elif keep:
            lines.append(stripped)
    return "\n".join(part for part in lines if part).strip()


def _read_diary(library: Any, cutoff: str, bucket: list[Source]) -> None:
    getter = getattr(library.store, "diary_pages", None)
    if not callable(getter):
        return
    try:
        rels = list(getter())
    except Exception:  # noqa: BLE001
        return
    root = getattr(library.store, "root", None)
    if root is None:
        return
    for rel in rels:
        name = str(rel).rsplit("/", 1)[-1]
        date = name[:-3] if name.endswith(".md") else name
        if not date or date < cutoff:
            continue
        try:
            text = (Path(root) / str(rel)).read_text(encoding="utf-8")
        except OSError:
            continue
        for head, body in _blocks(text):
            words = _user_words(body)
            # 测试/探针回合（"Reply with exactly one word: PONG"、"只回复两个字：收到"）
            # 不产生长期事实。
            if not words or (not _CJK.search(words) and len(words) < 80):
                continue
            if _PROBE.search(words) and len(words) < 200:
                continue
            ref = _REF.search(body)
            bucket.append(
                Source(
                    id=f"{rel}#{head}",
                    kind="diary",
                    path=str(rel),
                    date=date,
                    text=words[:1200],
                    at=head,
                    ref=ref.group(1) if ref else "",
                    who="你说的",
                )
            )


def _trim_sources(sources: list[Source], *, budget: int = SOURCE_BUDGET_CHARS,
                  limit: int = MAX_SOURCES) -> list[Source]:
    kept: list[Source] = []
    used = 0
    for source in reversed(sources):
        cost = len(source.text) + 60
        if kept and (used + cost > budget or len(kept) >= limit):
            break
        kept.append(source)
        used += cost
    kept.reverse()
    return kept


def _read_window(library: Any, window_days: int, now: datetime) -> list[Source]:
    cutoff = (now.date() - timedelta(days=max(1, window_days) - 1)).isoformat()
    bucket: list[Source] = []
    _read_episodes(library, cutoff, bucket)
    _read_diary(library, cutoff, bucket)
    bucket.sort(key=lambda s: (s.date, s.at))
    return _trim_sources(bucket)


# --------------------------------------------------------------------------- model


def _build_messages(sources: list[Source], now: datetime) -> list[dict[str, str]]:
    system = (
        "你在帮 Atlas 把「经历」整理成「长期记忆」。\n"
        "输入是最近一段时间的经历条目（经历/，一条是一轮对话的摘要）和日记原文"
        "（日记/，其中「你：」开头的是用户的原话）。\n\n"
        "只挑值得长期记住的语义事实：\n"
        "- 反复出现、多次说过的偏好或要求；\n"
        "- 稳定的工作方式、习惯、环境、常用工具；\n"
        "- 正在进行、跨多天的项目或长期目标。\n"
        "不要挑：一次性的任务细节、测试/探针回合、临时情绪、Atlas 自己的行为，"
        "以及用户没说、只是你推断的东西。\n\n"
        "四条硬规则：\n"
        "1. quote 必须原样出现在某一条 source 的 text 里：可以是连续的一小段，"
        "不能改写、不能拼接不同地方的字。\n"
        "2. sources 至少一个，且必须是输入里出现过的 source id。\n"
        "3. key 用小写点分，形如 user.preference.reply_style / user.env.os / "
        "user.project.atlas / self.trait.x。\n"
        "4. 拿不出原话就不要输出这一条。宁少勿多。\n\n"
        '只返回 JSON：{"candidates":[{"key","text","value","quote","sources":["…"],'
        '"importance":6,"reason":"为什么值得长期记住"}]}\n'
        "text 是一句完整的话（不超过 60 字），value 是紧凑取值；最多 8 条。"
    )
    payload = {
        "today": now.strftime("%Y-%m-%d %H:%M"),
        "sources": [
            {"id": s.id, "where": s.label, "date": s.date, "text": s.text[:600]}
            for s in sources
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _parse_candidates(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    rows = data.get("candidates") if isinstance(data, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _validate(row: dict[str, Any], by_id: dict[str, Source], now: datetime) -> tuple[dict[str, Any] | None, str]:
    """Turn one model row into a candidate with verified provenance, or reject it."""
    key = str(row.get("key") or "").strip()
    if not _KEY.match(key):
        return None, "key 不合规"
    text = " ".join(str(row.get("text") or "").strip().split())
    value = " ".join(str(row.get("value") or "").strip().split()) or text
    quote = " ".join(str(row.get("quote") or "").strip().split())
    if not text or not quote:
        return None, "缺说法或原话"
    if len(text) > 200 or len(quote) > 400:
        return None, "太长"
    if contains_secret(quote + text + value):
        return None, "看起来含密码或密钥"
    try:
        importance = max(1, min(10, int(row.get("importance") or 6)))
    except (TypeError, ValueError):
        importance = 6
    cited: list[Source] = []
    for source_id in row.get("sources") or []:
        source = by_id.get(str(source_id).strip())
        if source is not None and source not in cited:
            cited.append(source)
    if not cited:
        return None, "没引用输入里的来源"
    matched = [s for s in cited if _squash(quote) in _squash(s.text)]
    if not matched:
        return None, "原话在引用的来源里找不到"
    primary = matched[0]
    dates = sorted({s.date for s in matched})
    others = [s for s in matched if s is not primary]
    return (
        {
            "id": _candidate_id(key, value),
            "key": key,
            "text": text,
            "value": value,
            "quote": quote,
            "importance": importance,
            "reason": " ".join(str(row.get("reason") or "").strip().split())[:200],
            "evidence": f"{len(matched)} 条原文 / {len(dates)} 天",
            "kind": "recurring" if len(dates) >= 2 else "single",
            "sources": [
                {
                    "id": primary.id,
                    "path": primary.path,
                    "date": primary.date,
                    "at": primary.at,
                    "who": primary.who,
                    "quote": quote,
                },
                *[
                    {
                        "id": s.id,
                        "path": s.path,
                        "date": s.date,
                        "at": s.at,
                        "who": s.who,
                        "quote": "",
                    }
                    for s in others[:4]
                ],
            ],
            "primary_ref": primary.ref,
            "proposed_at": _stamp(now),
        },
        "",
    )


# --------------------------------------------------------------------------- report

_JSON_FIELDS = ("id", "key", "text", "value", "quote", "importance", "reason",
                "evidence", "kind", "sources", "status")


def _jsonable(candidate: dict[str, Any]) -> dict[str, Any]:
    return {name: candidate[name] for name in _JSON_FIELDS if name in candidate}


def _render_candidate(number: int, candidate: dict[str, Any]) -> list[str]:
    sources = "、".join(
        f"{s.get('path', '')} {s.get('at', '')}（{s.get('who', '')}）".strip()
        for s in candidate.get("sources") or []
    )
    lines = [
        f"### {number}. {candidate.get('text', '')}",
        "",
        f"- 键：`{candidate.get('key', '')}`",
    ]
    value = candidate.get("value")
    if value and value != candidate.get("text"):
        lines.append(f"- 值：{value}")
    lines.append(f"- 原话：「{candidate.get('quote', '')}」")
    lines.append(f"- 来源：{sources or '（无）'}")
    if candidate.get("evidence"):
        lines.append(f"- 重复：{candidate['evidence']}")
    if candidate.get("reason"):
        lines.append(f"- 理由：{candidate['reason']}")
    status = candidate.get("status") or {}
    if status.get("state") == "applied":
        lines.append(f"- 结果：已写入 {status.get('page', '')}（{status.get('entry', '')}，"
                     f"{status.get('at', '')}）")
    elif status.get("state") == "skipped":
        lines.append(f"- 结果：没写（{status.get('why', '')}）")
    lines.extend(["", "```json", json.dumps(_jsonable(candidate), ensure_ascii=False, indent=2,
                                            sort_keys=True), "```"])
    return lines


def _render_report(*, pending: list[dict[str, Any]], applied: list[dict[str, Any]],
                   skipped: list[dict[str, Any]], now: datetime, note: str) -> str:
    lines = [
        "# 语义候选",
        "",
        "<!-- 这是整理的提议，还不是记忆事实。确认之前不会写进我.md / 现状.md。 -->",
        "",
        f"生成时间：{_stamp(now)}",
        f"最近一次运行：{note or '（无）'}",
        "",
        "## 待确认",
        "",
        "每条都带着你说过的原话和出处；看过没问题再应用（apply）。"
        "应用只往文件里追加，遇到和旧说法冲突的只会降低旧条目的优先级，不会删除。",
        "",
    ]
    if not pending:
        lines.extend(["_暂时没有新候选。_", ""])
    for number, candidate in enumerate(pending, start=1):
        lines.extend(_render_candidate(number, candidate))
        lines.append("")
    lines.extend(["## 已应用", ""])
    if not applied:
        lines.extend(["_还没有。_", ""])
    for number, candidate in enumerate(applied, start=1):
        lines.extend(_render_candidate(number, candidate))
        lines.append("")
    lines.extend(["## 已跳过", ""])
    if not skipped:
        lines.extend(["_没有。_", ""])
    for number, candidate in enumerate(skipped, start=1):
        lines.extend(_render_candidate(number, candidate))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_report(text: str) -> dict[str, list[dict[str, Any]]]:
    """Read candidates back out of the report; the fenced JSON is the source of truth."""
    groups: dict[str, list[dict[str, Any]]] = {"pending": [], "applied": [], "skipped": []}
    for block in _JSON_FENCE.findall(text or ""):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not isinstance(data, dict) or not data.get("key") or not data.get("text"):
            continue
        state = str((data.get("status") or {}).get("state") or "")
        bucket = "applied" if state == "applied" else "skipped" if state == "skipped" else "pending"
        groups[bucket].append(data)
    return groups


def _load_report(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"pending": [], "applied": [], "skipped": []}
    return _parse_report(text)


def _save_report(path: Path, groups: dict[str, list[dict[str, Any]]], *, now: datetime,
                 note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _render_report(pending=groups["pending"], applied=groups["applied"],
                          skipped=groups["skipped"], now=now, note=note)
    path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- live facts


def _live_entries(store: Any) -> list[tuple[str, Entry]]:
    rows: list[tuple[str, Entry]] = []
    try:
        pages = list(store.pages())
    except Exception:  # noqa: BLE001
        return rows
    for rel in pages:
        try:
            page = store.read(rel)
        except Exception:  # noqa: BLE001
            continue
        for entry in getattr(page, "current", None) or []:
            rows.append((str(rel), entry))
    return rows


def _already_known(store: Any, key: str, value: str, text: str,
                   rows: list[tuple[str, Entry]]) -> str:
    """Return a short reason when this fact is already in the library, else ``""``."""
    try:
        if store.tombstoned(tombstone_hashes(key, value, text)):
            return "你要求忘掉过这条，不再写回"
    except Exception:  # noqa: BLE001
        pass
    for rel, entry in rows:
        if getattr(entry, "key", "") != key:
            continue
        current = _norm(str(getattr(entry, "value", "") or getattr(entry, "text", "")))
        if current == _norm(value) or _norm(str(getattr(entry, "text", ""))) == _norm(text):
            return f"已经在 {rel} 里"
    return ""


# --------------------------------------------------------------------------- apply


def _apply_one(library: Any, candidate: dict[str, Any], now: datetime,
               stamp: str) -> tuple[bool, str, dict[str, Any]]:
    """Append one candidate. Never deletes; a conflict only lowers the old priority."""
    store = library.store
    key = str(candidate.get("key") or "")
    text = " ".join(str(candidate.get("text") or "").split())[:200]
    value = " ".join(str(candidate.get("value") or "").split())[:200] or text
    quote = " ".join(str(candidate.get("quote") or "").split())[:400]
    if not key or not text:
        return False, "候选不完整", {}
    if contains_secret(quote + text + value):
        return False, "看起来含密码或密钥", {}
    rows = _live_entries(store)
    known = _already_known(store, key, value, text, rows)
    if known:
        return False, known, {}
    hits = [(rel, entry) for rel, entry in rows if getattr(entry, "key", "") == key]
    target = hits[0][0] if hits else page_for_key(key, temporary=False)
    try:
        importance = max(1, min(10, int(candidate.get("importance") or 6)))
    except (TypeError, ValueError):
        importance = 6
    entry = Entry(
        text=text,
        id=new_id(),
        key=key,
        value=value,
        src=SRC_DREAM,
        at=stamp,
        ref=str(candidate.get("primary_ref") or "")[:400],
        quote=quote,
        importance=importance,
    )
    page = store.read(target)
    page.current.append(entry)
    store.write(page)
    info: dict[str, Any] = {"entry": entry.id, "page": target}
    if hits:
        rel, old = hits[0]
        # 旧说法原地保留，只把优先级调低，再记一条取代关系。
        old_page = store.read(rel)
        for existing in getattr(old_page, "current", None) or []:
            if getattr(existing, "id", "") == getattr(old, "id", ""):
                existing.importance = max(1, int(getattr(existing, "importance", 5)) - 2)
        store.write(old_page)
        info["superseded"] = getattr(old, "id", "")
        info["lowered"] = True
        recorder = getattr(library, "record_supersession", None)
        if callable(recorder):
            try:
                recorder(getattr(old, "id", ""), entry.id, quote=quote, ref=entry.ref,
                         why="整理时读到新的说法")
            except Exception as exc:  # noqa: BLE001 - the entry is already stored
                info["supersede_error"] = f"{type(exc).__name__}: {exc}"
    return True, "", info


def _apply(library: Any, path: Path, now: datetime) -> dict[str, Any]:
    groups = _load_report(path)
    pending = groups["pending"]
    added = superseded = lowered = skipped = 0
    survivors: list[dict[str, Any]] = []
    lock = getattr(getattr(library, "store", None), "lock", None)
    with (lock if lock is not None else contextlib.nullcontext()):
        for candidate in pending:
            ok, why, info = _apply_one(library, candidate, now, _stamp(now))
            if not ok:
                skipped += 1
                candidate["status"] = {"state": "skipped", "at": _stamp(now), "why": why or "没有写入"}
                groups["skipped"].append(candidate)
                continue
            added += 1
            superseded += 1 if info.get("superseded") else 0
            lowered += 1 if info.get("lowered") else 0
            candidate["status"] = {
                "state": "applied",
                "at": _stamp(now),
                "entry": info.get("entry", ""),
                "page": info.get("page", ""),
                "why": info.get("supersede_error", ""),
            }
            groups["applied"].append(candidate)
            survivors.append(candidate)
        groups["pending"] = []
        commit = getattr(getattr(library, "store", None), "commit", None)
        if callable(commit) and added:
            try:
                commit(f"整理：语义候选写入 {added} 条"[:400])
            except Exception:  # noqa: BLE001 - git trouble must not lose the files
                pass
    try:
        _save_report(path, groups, now=now, note=f"应用了 {added} 条")
    except OSError:
        pass
    sync = getattr(getattr(library, "index", None), "sync", None)
    if callable(sync):
        try:
            sync()
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": True,
        "mode": "apply",
        "candidates": len(pending),
        "added": added,
        "superseded": superseded,
        "lowered": lowered,
        "skipped": skipped,
        "written": path.name,
        "error": None,
    }


# --------------------------------------------------------------------------- propose


def _disabled(library: Any) -> bool:
    flag = os.environ.get("ATLAS_MEMORY_CONSOLIDATE", "")
    if flag.strip().casefold() in _OFF:
        return True
    cfg = getattr(library, "_cfg", None)
    if callable(cfg):
        try:
            if cfg("consolidate", True) is False:
                return True
        except Exception:  # noqa: BLE001
            return False
    return False


async def _propose(library: Any, path: Path, model_mgr: Any, window_days: int,
                   now: datetime) -> dict[str, Any]:
    empty = {
        "ok": False,
        "mode": "propose",
        "window_days": window_days,
        "sources": 0,
        "candidates": 0,
        "added": 0,
        "superseded": 0,
        "lowered": 0,
        "skipped": 0,
        "written": "",
        "error": None,
    }
    # 没有模型就安静退出：定时整理不能因为缺模型就报错，更不能乱写文件。
    if model_mgr is None or getattr(model_mgr, "model_router", None) is None:
        return {**empty, "error": "没有可用的记忆整理模型", "error_type": "RuntimeError"}
    sources = _read_window(library, window_days, now)
    if not sources:
        return {**empty, "ok": True, "window_days": window_days}
    by_id = {source.id: source for source in sources}
    model_id = library._model_id(model_mgr)
    messages = _build_messages(sources, now)
    result = await asyncio.wait_for(
        model_mgr.model_router.complete_for(
            model_id, "memory_library", messages, max_tokens=2000, temperature=0.1
        ),
        timeout=float(library._cfg("writer_timeout_seconds", 90)),
    )
    rows = _parse_candidates(str(getattr(result, "text", "") or ""))
    groups = _load_report(path)
    rows_live = _live_entries(library.store)
    seen = {c.get("id") for c in groups["pending"] + groups["applied"] + groups["skipped"]}
    seen_keys = {_norm(f"{c.get('key')}\x1f{c.get('value') or c.get('text')}")
                 for c in groups["pending"]}
    fresh = rejected = 0
    for row in rows[:MAX_CANDIDATES]:
        candidate, reason = _validate(row, by_id, now)
        if candidate is None:
            rejected += 1
            log.debug("memory.library.consolidate_rejected", reason=reason,
                      key=str(row.get("key") or "")[:80])
            continue
        if candidate["id"] in seen:
            continue
        key = candidate["id"] and f"{candidate['key']}\x1f{candidate['value']}"
        if _norm(key) in seen_keys:
            continue
        known = _already_known(library.store, candidate["key"], candidate["value"],
                               candidate["text"], rows_live)
        if known:
            rejected += 1
            log.debug("memory.library.consolidate_rejected", reason=known,
                      key=candidate["key"][:80])
            continue
        seen.add(candidate["id"])
        seen_keys.add(_norm(key))
        groups["pending"].append(candidate)
        fresh += 1
    if len(groups["pending"]) > MAX_PENDING:
        groups["pending"] = groups["pending"][-MAX_PENDING:]
    note = f"最近 {window_days} 天 · {len(sources)} 条原文（提议 {fresh} 条）"
    try:
        _save_report(path, groups, now=now, note=note)
    except OSError as exc:
        return {**empty, "window_days": window_days, "sources": len(sources),
                "error": f"提议写不进去：{exc}", "error_type": type(exc).__name__}
    commit = getattr(getattr(library, "store", None), "commit", None)
    if callable(commit) and fresh:
        try:
            commit(f"整理：语义候选 {fresh} 条待确认"[:400])
        except Exception:  # noqa: BLE001
            pass
    return {
        **empty,
        "ok": True,
        "window_days": window_days,
        "sources": len(sources),
        "candidates": len(groups["pending"]),
        "rejected": rejected,
        "fresh": fresh,
        "written": path.name,
    }


async def run_consolidation(library: Any, model_mgr: Any = None, *, apply: bool = False,
                            window_days: int | None = None) -> dict[str, Any]:
    """Digest recent episodes into semantic candidates, or apply the pending ones.

    ``apply=False`` (default) only writes ``语义候选.md``. ``apply=True`` needs no
    model at all: it applies what is already in that file, appending entries and
    recording supersessions. Never raises; the scheduled dream path calls it.
    """
    now = datetime.now().astimezone()
    mode = "apply" if apply else "propose"
    days = int(window_days or DEFAULT_WINDOW_DAYS)
    default = {
        "ok": False,
        "mode": mode,
        "window_days": days,
        "sources": 0,
        "candidates": 0,
        "added": 0,
        "superseded": 0,
        "lowered": 0,
        "skipped": 0,
        "written": "",
        "error": None,
    }
    root = getattr(getattr(library, "store", None), "root", None)
    if root is None:
        return {**default, "error": "记忆库没有根目录", "error_type": "RuntimeError"}
    path = Path(root) / CANDIDATES_FILE
    if not apply and _disabled(library):
        return {**default, "ok": True, "mode": "off"}
    if not apply:
        cfg = getattr(library, "_cfg", None)
        if callable(cfg):
            try:
                days = int(cfg("consolidate_window_days", days) or days)
            except (TypeError, ValueError):
                pass
    try:
        if apply:
            return _apply(library, path, now)
        return await _propose(library, path, model_mgr, days, now)
    except Exception as exc:  # noqa: BLE001 - scheduled work must never raise
        log.warning("memory.library.consolidate_failed", error=str(exc),
                    error_type=type(exc).__name__, mode=mode)
        return {**default, "error": str(exc), "error_type": type(exc).__name__}


__all__ = ["CANDIDATES_FILE", "run_consolidation"]
