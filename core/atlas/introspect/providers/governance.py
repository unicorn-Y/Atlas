"""Introspection provider: the project ledger.

Atlas carries a second kind of knowledge that no code index can hold — the record
of its own recurring mistakes, distilled into rules. Without a formal ledger that
knowledge lives in conversation history, so the same drift gets corrected twice,
then three times, and each correction feels like the first.

This provider parses that ledger so a session can start by asking "what have I
already been told not to do" instead of relearning it.

Deliberate distinction: ``data/memory/事/Atlas.md`` is *product memory* — user
facts about the Atlas project, written by the agent for the agent. The ledger at
the repository root is *process memory* — rules about how work on this repository
must be done. They are different documents in different git repositories with
different lifecycles, and conflating them is itself a mistake the ledger records.

The parser is forgiving by design: a ledger that fails to parse is worse than no
ledger, because it silently answers "no rules" to a question that has an answer.
Unrecognised lines are preserved as raw text rather than dropped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema

# Two clause shapes exist in the wild and both must parse, because the ledger is
# written by a *skill* whose documented format is not the one this parser was
# first written against:
#
#   heading form   ## [L1] 标题            <- what an earlier draft assumed
#   skill form     - [L1] (seen 2x, severity: high)   <- atlas-ledger v2.2 §4
#
# A parser that only knows the first form returns zero clauses for a perfectly
# valid ledger, i.e. it silently answers "no rules apply" — the exact failure this
# provider's docstring promises not to commit. Supporting one format and calling
# the other malformed would have been the same bug with a better excuse.
_CLAUSE_HEAD = re.compile(r"^#{2,4}\s*\[?(L\d+|O\d+)\]?\s*(.*)$")
_CLAUSE_ITEM = re.compile(r"^[-*]\s+\[?(L\d+|O\d+)\]?\s*(.*)$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$")

#: ``(seen 2x, severity: high)`` — the metadata line atlas-ledger attaches to a
#: clause head. Parsed into fields so ``by_severity`` and retirement keep working
#: regardless of which clause shape the ledger uses.
_META = re.compile(r"^\((.*)\)$")
_META_PART = re.compile(r"([A-Za-z_]+)\s*[:：]?\s*([^,，]+)")

#: ``WHEN: text`` with an optional bullet and optional indentation. The skill
#: format indents fields under a list item and omits the bullet entirely, so a
#: bullet is not optional-but-expected here; it is genuinely absent.
_FIELD = re.compile(
    r"^\s*(?:[-*]\s+)?([A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff'’ ]*?)\s*[:：]\s*(.*)$"
)


def _ledger_path() -> Path:
    from atlas.config import PROJECT_ROOT

    return PROJECT_ROOT / "Atlas.md"


def _split_meta(text: str) -> tuple[dict[str, str], str]:
    """Pull ``(seen 2x, severity: high)`` off a clause head.

    atlas-ledger writes the metadata as a parenthesised suffix on the *same* line
    as the id, so leaving it in ``title`` would make every clause's title read
    "（seen 2x, severity: high）" and would hide severity from ``by_severity``.
    """
    match = _META.match(text.strip())
    if not match:
        return {}, text.strip()
    fields: dict[str, str] = {}
    for key, value in _META_PART.findall(match.group(1)):
        fields[key.strip()] = value.strip()
    return fields, ""


def _parse(text: str) -> dict[str, Any]:
    """Split the ledger into clauses and observations.

    A clause starts at an ``L<n>`` id and owns every line until the next id or
    section. Both the heading form and the atlas-ledger list form are accepted;
    ``WHEN``/``DON'T``/``INSTEAD`` are kept verbatim because they are the
    actionable part, other ``key: value`` lines become fields.

    Wrapped values are joined back together. atlas-ledger's own format wraps the
    rule text across indented lines with no marker, so a parser that stops at the
    first line records ``INSTEAD: 先分清…（它可能在别的路径、`` and silently drops
    the instruction that actually tells you what to do. Continuation is tracked
    per field so a wrapped ``WHEN`` does not swallow the ``DON'T`` that follows.
    """
    clauses: list[dict[str, Any]] = []
    sections: list[str] = []
    current: dict[str, Any] | None = None
    section = ""
    #: Which of when/dont/instead the previous line assigned, so an indented line
    #: with no ``key:`` of its own can be appended to it. ``None`` means the last
    #: line was structural and a bare line goes to ``extra`` instead.
    open_field: str | None = None

    def _append(field: str, value: str) -> None:
        # Joined with a space, not concatenated: wrapped lines in the ledger are
        # broken mid-sentence at a space boundary, so gluing them back without one
        # produces "get_app_services /application.py" — readable to a human who
        # knows the code, corrupted as a rule an LLM is asked to follow.
        existing = current[field]  # type: ignore[index]
        current[field] = f"{existing} {value}".strip() if existing else value  # type: ignore[index]

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        section_match = _SECTION.match(line)
        if section_match:
            section = section_match.group(1)
            sections.append(section)
            current = None
            open_field = None
            continue

        head = _CLAUSE_HEAD.match(line) or _CLAUSE_ITEM.match(line)
        if head:
            meta, title = _split_meta(head.group(2))
            current = {
                "id": head.group(1),
                "title": title,
                "kind": "clause" if head.group(1).startswith("L") else "observation",
                "section": section,
                "fields": dict(meta),
                "when": "",
                "dont": "",
                "instead": "",
                "extra": [],
            }
            clauses.append(current)
            open_field = None
            continue

        if current is None:
            continue

        key_value = _FIELD.match(line)
        if key_value:
            key = key_value.group(1).strip()
            value = key_value.group(2).strip()
            upper = key.upper().replace("’", "'")
            if upper == "WHEN":
                current["when"] = value
                open_field = "when"
            elif upper in ("DON'T", "DONT", "DO NOT"):
                current["dont"] = value
                open_field = "dont"
            elif upper == "INSTEAD":
                current["instead"] = value
                open_field = "instead"
            else:
                current["fields"][key] = value
                open_field = None
            continue

        # No `key:` on this line: it is either the wrapped tail of the field just
        # read, or, after a structural line, genuinely unrecognised text.
        if open_field is not None:
            _append(open_field, line.strip())
        else:
            current["extra"].append(line.strip())

    return {"sections": sections, "clauses": clauses}


def _document() -> dict[str, Any]:
    path = _ledger_path()
    if not path.exists():
        return {"path": str(path), "exists": False, "text": ""}
    return {"path": str(path), "exists": True, "text": path.read_text(encoding="utf-8")}


def _summary(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    doc = _document()
    if not doc["exists"]:
        return {
            "exists": False,
            "path": doc["path"],
            "note": "仓库根还没有 Atlas.md。没有台账时，重复犯的错只能靠记忆避免。",
        }
    parsed = _parse(doc["text"])
    clauses = [c for c in parsed["clauses"] if c["kind"] == "clause"]
    observations = [c for c in parsed["clauses"] if c["kind"] == "observation"]
    retired = [
        c["id"]
        for c in parsed["clauses"]
        if c["fields"].get("RETIRED", "").lower() in ("true", "yes", "已退休")
    ]
    severities: dict[str, int] = {}
    for clause in clauses:
        level = str(clause["fields"].get("severity", "未标注")).lower()
        severities[level] = severities.get(level, 0) + 1
    return {
        "exists": True,
        "path": doc["path"],
        "sections": parsed["sections"],
        "clauses": len(clauses),
        "observations": len(observations),
        "retired": retired,
        "by_severity": severities,
        "clause_budget": {"limit": 15, "used": len(clauses)},
    }


def _list_clauses(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    doc = _document()
    if not doc["exists"]:
        return {"exists": False, "path": doc["path"], "clauses": []}
    parsed = _parse(doc["text"])
    kind = str(args.get("kind") or "").strip().lower()
    search = str(args.get("search") or "").strip().lower()
    rows = parsed["clauses"]
    if kind:
        rows = [row for row in rows if row["kind"] == kind]
    if search:
        rows = [
            row
            for row in rows
            if search in row["title"].lower()
            or search in row["when"].lower()
            or search in row["dont"].lower()
        ]
    return {"exists": True, "count": len(rows), "clauses": rows}


def _clause_detail(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    doc = _document()
    if not doc["exists"]:
        raise KeyError("仓库根没有 Atlas.md，无法查条款。")
    wanted = args["id"].upper()
    for clause in _parse(doc["text"])["clauses"]:
        if clause["id"].upper() == wanted:
            return clause
    raise KeyError(f"台账里没有条款 {wanted!r}")


def _terms(text: str) -> list[str]:
    """Tokenise for matching, including languages that do not put spaces in words.

    The first version split on non-word characters and kept tokens longer than one
    character. That works for English and returns **one token for an entire
    Chinese sentence**, so a Chinese ``action`` could only match by appearing
    verbatim inside a clause — practically never. ``check`` therefore answered
    "no rules apply" for every Chinese request, which is exactly the false
    negative the provider docstring calls the most expensive wrong answer.

    Latin runs stay whole words. CJK runs are reduced to character bigrams:
    two characters is the smallest span that carries meaning in Chinese, and it
    keeps "后端" matching "后端服务" without the noise of single characters, which
    would match almost every clause.
    """
    terms: list[str] = []
    for run in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
        if "\u4e00" <= run[0] <= "\u9fff":
            if len(run) == 1:
                continue
            terms.extend(run[i : i + 2] for i in range(len(run) - 1))
        elif len(run) > 1:
            terms.append(run)
    return terms


def _check(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Find clauses whose WHEN matches a described action.

    Substring matching on the clause text, deliberately dumb: an LLM reads the
    result and decides applicability. Semantic matching here would make the
    provider an opinionated judge, and a false negative would read as "no rule
    applies" — the most expensive wrong answer this surface can give.

    ``action`` and the clause text are compared through the same tokeniser so a
    Chinese query can match a Chinese clause at all; see :func:`_terms`.
    """
    doc = _document()
    if not doc["exists"]:
        return {"exists": False, "matches": [], "note": "还没有台账。"}
    action = args["action"]
    terms = _terms(action)
    matches = []
    for clause in _parse(doc["text"])["clauses"]:
        haystack = " ".join(
            [clause["title"], clause["when"], clause["dont"], clause["instead"]]
        ).lower()
        hits = [term for term in terms if term in haystack]
        if hits:
            matches.append({**clause, "matched_terms": hits})
    matches.sort(key=lambda row: -len(row["matched_terms"]))
    return {
        "exists": True,
        "action": action,
        "count": len(matches),
        "matches": matches,
        "matched_terms": len(terms),
    }


PROVIDER = Provider(
    id="governance",
    title="台账",
    summary="仓库根的流程台账：已经定下的条款、待确认的观察，以及某类动作撞上了哪条。",
    methods=(
        Method(
            name="summary",
            summary="台账概况：条款/观察数量、严重度分布、条款预算占用。",
            input_schema=object_schema(),
            run=_summary,
        ),
        Method(
            name="clauses",
            summary="列出条款，可按类型或关键字筛选。",
            input_schema=object_schema(
                {
                    "kind": {"type": "string", "description": "clause 或 observation。"},
                    "search": {"type": "string", "description": "在标题与规则文本里搜索。"},
                }
            ),
            run=_list_clauses,
        ),
        Method(
            name="clause",
            summary="看单条条款的完整文本。",
            input_schema=object_schema(
                {"id": {"type": "string", "description": "条款编号，如 L3 或 O2。"}},
                required=("id",),
            ),
            run=_clause_detail,
        ),
        Method(
            name="check",
            summary="用一段动作描述去匹配台账里可能相关的条款。",
            input_schema=object_schema(
                {"action": {"type": "string", "description": "你打算做的事的一句话描述。"}},
                required=("action",),
            ),
            run=_check,
        ),
    ),
)
