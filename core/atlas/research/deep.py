# Ported from dzhng/deep-research@1f8f3e285bbc23e80b98a66a64effab9069f3ad4: src/deep-research.ts, src/prompt.ts (MIT)
# Ported from nicobailon/pi-web-access@d47dc040552505e3b135d0136a0b15eaf4bdba52: source-check.ts (MIT)
# Prompts adapted from assafelovic/gpt-researcher@3582a6841fe7dc801e2a34e34ee408641aea9bce:
#   gpt_researcher/prompts.py generate_search_queries_prompt / curate_sources / generate_report_prompt (Apache-2.0)
# Prompts adapted from langchain-ai/open_deep_research@1b7d2e80db9faa586165c60e09096dbbfd483a64:
#   src/open_deep_research/prompts.py final_report_generation_prompt (MIT)
"""Multi-round web research with source grading and cross-checking.

The loop is dzhng/deep-research's ``deepResearch``: generate a few search queries, search,
read the best pages, distil cited learnings plus follow-up questions, then recurse with half
the breadth until depth runs out. Atlas additions: every learning keeps the ids of the
sources it came from; sources are graded with pi-web-access's ``classifySource`` rules
(plus Chinese sites) and the best-graded pages are read first; key claims are then
assessed with Pi's ``ClaimStatus`` vocabulary (an LLM pass instead of Pi's placeholder),
and contradicted or single-source claims get one targeted re-check search before the
report is written. Sources are numbered by code, so the model cannot invent links.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

Complete = Callable[[list[dict[str, str]], int], Awaitable[str]]
Progress = Callable[[str], Awaitable[None]]

CLAIM_STATUSES = ("supported", "contradicted", "unclear", "missing-evidence")


class WebTools(Protocol):
    async def web_search(self, query: str, max_results: int = 5) -> dict[str, Any]: ...
    async def web_fetch(self, url: str, max_chars: int = 15000) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Source grading (pi-web-access source-check.ts classifySource, plus Chinese sites)
# ---------------------------------------------------------------------------

_OFFICIAL_DOCS_HOSTS = re.compile(r"^(developers\.|docs\.|learn\.|reference\.|developer\.)|\.github\.io$", re.I)
_OFFICIAL_DOCS_PATHS = re.compile(r"/(docs?|reference)(/|\b)", re.I)
_VENDOR_DOCS_PATHS = re.compile(r"/(documentation|docs?|pricing|price|api)(/|$)", re.I)
_REPO_ISSUE_PATHS = re.compile(r"/(issues|pull|pulls|discussions)/", re.I)
_BLOG_HOSTS = re.compile(
    r"(medium\.com|substack\.com|dev\.to|hashnode\.|csdn\.net|juejin\.cn|cnblogs\.com|jianshu\.com|"
    r"segmentfault\.com|mp\.weixin\.qq\.com|sohu\.com|baijiahao\.baidu\.com|toutiao\.com)", re.I)
_BLOG_PATHS = re.compile(r"/blogs?/", re.I)
_FORUM_HOSTS = re.compile(
    r"(stackoverflow\.com|serverfault\.com|superuser\.com|discourse\.|community\.|reddit\.com|"
    r"news\.ycombinator\.com|zhihu\.com|v2ex\.com|tieba\.baidu\.com|linux\.do)", re.I)
_FORUM_PATHS = re.compile(r"/(forum|forums|threads|t)/", re.I)
_NEWS_HOSTS = re.compile(
    r"(reuters\.com|bloomberg\.com|techcrunch\.com|theverge\.com|arstechnica\.com|wired\.com|cnet\.com|"
    r"zdnet\.com|venturebeat\.com|36kr\.com|ithome\.com|huxiu\.com|thepaper\.cn|caixin\.com|jiqizhixin\.com|"
    r"qbitai\.com|infoq\.(com|cn))", re.I)
_NEWS_PATHS = re.compile(r"/news(/|$)", re.I)

# Lower is better: read authoritative pages first (GPT Researcher curate_sources: favour
# authoritative and data-bearing sources, keep others unless clearly untrustworthy).
QUALITY_RANK = {"official_docs": 0, "vendor_docs": 1, "news": 2, "repo_issue": 3,
                "unknown": 4, "forum": 5, "blog": 5}


def classify_source(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unknown"
    host, path = parts.hostname or "", parts.path or ""
    if not host:
        return "unknown"
    if _REPO_ISSUE_PATHS.search(path):
        return "repo_issue"
    if _BLOG_HOSTS.search(host) or _BLOG_PATHS.search(path):
        return "blog"
    if _FORUM_HOSTS.search(host) or _FORUM_PATHS.search(path):
        return "forum"
    if _NEWS_HOSTS.search(host) or _NEWS_PATHS.search(path):
        return "news"
    if _OFFICIAL_DOCS_HOSTS.search(host) or _OFFICIAL_DOCS_PATHS.search(path):
        return "official_docs"
    if _VENDOR_DOCS_PATHS.search(path):
        return "vendor_docs"
    return "unknown"


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    parts = host.split(".")
    # Collapse to the registrable-ish domain so docs.x.com and x.com count as one voice.
    if len(parts) > 2 and parts[-2] in {"com", "co", "org", "net", "gov", "edu", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), (parts.netloc or "").lower(),
                       parts.path.rstrip("/") or "/", parts.query, ""))


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if not c.isspace() and not c.isdigit()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "一" <= c <= "鿿") / len(letters)


def parse_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError("model did not return JSON")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    return json.loads(cleaned[start:end + 1])


@dataclass
class Source:
    n: int
    url: str
    title: str = ""
    snippet: str = ""
    published: str = ""
    quality: str = "unknown"
    domain: str = ""
    text: str = ""
    fetched: bool = False
    fetch_error: str = ""

    def public(self) -> dict[str, Any]:
        row = {"n": self.n, "title": self.title, "url": self.url, "quality": self.quality,
               "fetched": self.fetched}
        if self.published:
            row["published"] = self.published
        if self.fetch_error:
            row["fetch_error"] = self.fetch_error[:160]
        return row


@dataclass
class Learning:
    text: str
    sources: list[int] = field(default_factory=list)


def _system_prompt(today: str) -> str:
    # dzhng/deep-research src/prompt.ts, trimmed; "the source is irrelevant" dropped because
    # Atlas grades sources on purpose.
    return (
        f"You are an expert researcher. Today is {today}. Follow these instructions when responding:\n"
        "- You may be asked to research subjects that are after your knowledge cutoff; assume the "
        "user is right when presented with news, and trust the provided sources over your memory.\n"
        "- Be highly organized, accurate and thorough; mistakes erode trust.\n"
        "- Keep exact numbers, prices, versions and dates exactly as the sources state them.\n"
        "- You may speculate or predict, but flag it clearly.\n"
        "- When asked for JSON, output only the JSON object, no prose or code fences."
    )


class DeepResearcher:
    """One research run. Not reusable: create one per question."""

    def __init__(self, complete: Complete, web: WebTools, *, breadth: int = 3, depth: int = 2,
                 pages_per_query: int = 3, page_chars: int = 8000, results_per_query: int = 8,
                 concurrency: int = 3, max_rechecks: int = 2, on_progress: Progress | None = None,
                 today: str | None = None) -> None:
        self._complete = complete
        self._web = web
        self.breadth = max(1, min(int(breadth), 6))
        self.depth = max(1, min(int(depth), 3))
        self.pages_per_query = max(1, int(pages_per_query))
        self.page_chars = max(1000, int(page_chars))
        self.results_per_query = max(3, int(results_per_query))
        self.max_rechecks = max(0, int(max_rechecks))
        self._sem = asyncio.Semaphore(max(1, int(concurrency)))
        self._on_progress = on_progress
        self.today = today or date.today().isoformat()
        self._system = _system_prompt(self.today)
        self.sources: dict[str, Source] = {}
        self.learnings: list[Learning] = []
        self.queries: list[str] = []
        self.errors: list[str] = []
        self.llm_calls = 0

    # -- plumbing -----------------------------------------------------------

    async def _progress(self, text: str) -> None:
        if self._on_progress is not None:
            try:
                await self._on_progress(text)
            except Exception:  # noqa: BLE001 - progress is best effort
                pass

    async def _ask(self, prompt: str, max_tokens: int) -> str:
        self.llm_calls += 1
        return await self._complete(
            [{"role": "system", "content": self._system}, {"role": "user", "content": prompt}],
            max_tokens,
        )

    async def _ask_json(self, prompt: str, max_tokens: int) -> Any:
        text = await self._ask(prompt, max_tokens)
        try:
            return parse_json(text)
        except (ValueError, json.JSONDecodeError):
            # Usually a reply cut off at the token limit: retry once with more room.
            text = await self._ask(prompt + "\n\nReturn ONLY valid JSON. No prose, no code fences. Be brief.",
                                   max_tokens * 2)
            try:
                return parse_json(text)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"model did not return JSON ({len(text)} chars): {text[:160]!r}") from exc

    def _by_n(self) -> dict[int, Source]:
        return {s.n: s for s in self.sources.values()}

    # -- the loop (dzhng deepResearch) -------------------------------------

    async def run(self, question: str) -> dict[str, Any]:
        started = time.monotonic()
        question = question.strip()
        if not question:
            raise ValueError("question is required")
        await self._dive(question, question, self.breadth, self.depth)
        if not self.learnings:
            raise RuntimeError("没有从网上找到可用资料：" + ("；".join(self.errors[-3:]) or "搜索无结果"))
        await self._progress("交叉核实关键结论…")
        claims = await self._verify(question)
        if await self._recheck(question, claims):
            await self._progress("复核后重新评估…")
            claims = await self._verify(question)
        await self._progress("撰写报告…")
        report, cited = await self._report(question, claims)
        pages = sum(1 for s in self.sources.values() if s.fetched)
        return {
            "question": question,
            "report": report,
            "sources": [{**s.public(), "n": i} for i, s in enumerate(cited, 1)],
            "claims": claims,
            "stats": {"queries": len(self.queries), "pages_read": pages,
                      "sources_seen": len(self.sources), "learnings": len(self.learnings),
                      "llm_calls": self.llm_calls, "seconds": round(time.monotonic() - started, 1)},
            "errors": self.errors[-10:],
        }

    async def _dive(self, question: str, prompt: str, breadth: int, depth: int) -> None:
        try:
            queries = await self._queries(question, prompt, breadth)
        except Exception as exc:  # noqa: BLE001 - a failed branch must not sink the run
            self.errors.append(f"生成搜索词失败: {exc}")
            return
        next_breadth = math.ceil(breadth / 2)

        async def branch(item: dict[str, str]) -> None:
            try:
                async with self._sem:
                    ids = await self._search_and_read(item["query"])
                    follow = await self._learn(question, item, ids, next_breadth)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{item['query']}: {exc}")
                return
            if depth > 1 and follow:
                next_prompt = (
                    f"Previous research goal: {item.get('goal', '')}\n"
                    "Follow-up research directions:\n" + "\n".join(follow)
                )
                await self._dive(question, next_prompt, next_breadth, depth - 1)

        await asyncio.gather(*(branch(item) for item in queries))

    async def _queries(self, question: str, prompt: str, count: int) -> list[dict[str, str]]:
        known = "\n".join(f"- {item.text}" for item in self.learnings[-30:])
        done = "\n".join(f"- {q}" for q in self.queries[-30:])
        language_hint = (
            "The question is in Chinese: mix Chinese and English queries — English for international "
            "products/vendors/papers, Chinese for China-specific topics."
            if cjk_ratio(question) >= 0.3 else ""
        )
        text = (
            f"Overall research question: <question>{question}</question>\n"
            f"Current research prompt: <prompt>{prompt}</prompt>\n\n"
            f"Generate a list of web search queries to research this. Return at most {count} queries, "
            "fewer if the prompt is narrow. Each query must be unique and not similar to the others "
            "or to the queries already run. Each query must be a plain natural-language phrase: do NOT "
            "use operators such as site:, filetype:, OR, AND, NOT — many backends return nothing for them. "
            f"Assume the current date is {self.today}; add the year when recency matters. {language_hint}\n"
            + (f"\nQueries already run:\n{done}\n" if done else "")
            + (f"\nLearnings so far (use them to make queries more specific):\n{known}\n" if known else "")
            + '\nReturn JSON: {"queries": [{"query": "...", "goal": "what this query should find and '
            'how to go deeper once results are in"}]}'
        )
        data = await self._ask_json(text, 4000)
        rows = data.get("queries", []) if isinstance(data, dict) else data
        seen = {q.casefold() for q in self.queries}
        out: list[dict[str, str]] = []
        for row in rows if isinstance(rows, list) else []:
            query = str(row.get("query", "") if isinstance(row, dict) else row).strip()
            if not query or query.casefold() in seen:
                continue
            seen.add(query.casefold())
            self.queries.append(query)
            out.append({"query": query, "goal": str(row.get("goal", "")) if isinstance(row, dict) else ""})
            if len(out) >= count:
                break
        return out

    async def _search_and_read(self, query: str) -> list[int]:
        await self._progress(f"搜索：{query}")
        try:
            result = await self._web.web_search(query, self.results_per_query)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"搜索失败 {query}: {exc}")
            return []
        ids: list[int] = []
        for row in result.get("results") or []:
            url = str(row.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            key = normalize_url(url)
            source = self.sources.get(key)
            if source is None:
                title = str(row.get("title") or "").strip()
                source = Source(n=len(self.sources) + 1, url=url,
                                title="" if title.upper() in {"N/A", "NONE", "NULL"} else title,
                                snippet=str(row.get("description") or ""),
                                published=str(row.get("published") or ""),
                                quality=classify_source(url), domain=domain_of(url))
                self.sources[key] = source
            if source.n not in ids:
                ids.append(source.n)
        picks = self._pick_sources(ids)
        if picks:
            await self._progress("阅读：" + "、".join(s.domain or s.url for s in picks))
            await asyncio.gather(*(self._read(s) for s in picks))
        return ids

    def _pick_sources(self, ids: list[int]) -> list[Source]:
        """Best-graded unread pages first, one per domain (search rank breaks ties)."""
        by_n = self._by_n()
        candidates = [by_n[n] for n in ids if not by_n[n].fetched and not by_n[n].fetch_error]
        candidates.sort(key=lambda s: (QUALITY_RANK.get(s.quality, 4), ids.index(s.n)))
        picks: list[Source] = []
        domains: set[str] = set()
        for source in candidates:
            if source.domain in domains:
                continue
            domains.add(source.domain)
            picks.append(source)
            if len(picks) >= self.pages_per_query:
                break
        return picks

    async def _read(self, source: Source) -> None:
        try:
            page = await self._web.web_fetch(source.url, self.page_chars)
        except Exception as exc:  # noqa: BLE001
            source.fetch_error = str(exc) or type(exc).__name__
            return
        text = str(page.get("text") or "").strip()
        if len(text) < 200:
            source.fetch_error = "页面正文太短或为空"
            return
        source.text = text[: self.page_chars]
        source.fetched = True
        if page.get("title") and str(page["title"]).strip().upper() != "N/A" and not source.title:
            source.title = str(page["title"])

    async def _learn(self, question: str, item: dict[str, str], ids: list[int],
                     follow_count: int) -> list[str]:
        """dzhng processSerpResult: cited learnings + follow-up questions from one query."""
        by_n = self._by_n()
        blocks: list[str] = []
        for n in ids:
            source = by_n[n]
            meta = f'id="S{n}" quality="{source.quality}" url="{source.url}"'
            if source.published:
                meta += f' published="{source.published}"'
            if source.fetched:
                blocks.append(f"<source {meta}>\n{source.title}\n{source.text}\n</source>")
            elif source.snippet:
                blocks.append(f"<source {meta} snippet_only=\"true\">\n{source.title}\n{source.snippet}\n</source>")
        if not blocks:
            return []
        text = (
            f"Overall research question: <question>{question}</question>\n"
            f"Search query: <query>{item['query']}</query>\nQuery goal: {item.get('goal', '')}\n\n"
            "From the contents below, extract up to 6 learnings. Each learning must be unique, concise "
            "and information-dense: include entities (companies, products, people), exact metrics, "
            "prices, numbers and dates, and say when a figure is dated or region-specific. Only use what "
            "the contents say. Prefer authoritative, recent sources with concrete data; ignore content "
            "that is irrelevant, outdated, or clearly untrustworthy. snippet_only sources are search "
            "snippets, not full pages — use them only for leads.\n"
            "Every learning must list the ids of the sources that state it (numbers only, e.g. [3, 7]).\n"
            f"Also give up to {follow_count} follow-up questions that would advance the overall research "
            "(gaps, conflicts to resolve, things to verify).\n\n"
            + "\n".join(blocks)
            + '\n\nReturn JSON: {"learnings": [{"text": "...", "sources": [3]}], '
            '"follow_up_questions": ["..."]}'
        )
        data = await self._ask_json(text, 8000)
        valid = set(ids)
        known = {item_.text.casefold() for item_ in self.learnings}
        for row in data.get("learnings", []) if isinstance(data, dict) else []:
            if not isinstance(row, dict):
                continue
            body = str(row.get("text") or "").strip()
            refs = []
            for ref in row.get("sources") or []:
                try:
                    num = int(str(ref).lstrip("Ss"))
                except ValueError:
                    continue
                if num in valid and num not in refs:
                    refs.append(num)
            if body and refs and body.casefold() not in known:
                known.add(body.casefold())
                self.learnings.append(Learning(body, refs))
        follow = data.get("follow_up_questions", []) if isinstance(data, dict) else []
        return [str(q).strip() for q in follow if str(q).strip()][:follow_count]

    # -- cross-checking (pi-web-access ClaimAssessment, LLM-backed) ---------

    def _learning_lines(self) -> str:
        by_n = self._by_n()
        lines = []
        for i, item in enumerate(self.learnings, 1):
            refs = ", ".join(f"S{n}:{by_n[n].domain}/{by_n[n].quality}" for n in item.sources)
            domains = {by_n[n].domain for n in item.sources}
            lines.append(f"L{i} [{len(domains)} domain(s): {refs}] {item.text}")
        return "\n".join(lines)

    async def _verify(self, question: str) -> list[dict[str, Any]]:
        text = (
            f"Research question: <question>{question}</question>\n\n"
            "Below are learnings gathered from web sources, each tagged with how many independent "
            "domains back it and their grade (official_docs > vendor_docs > news > repo_issue > "
            "unknown > forum/blog).\n\n" + self._learning_lines() + "\n\n"
            "Identify up to 8 key claims the answer to the question depends on. Assess each:\n"
            "- supported: at least two independent domains agree, or the official/vendor source states it;\n"
            "- contradicted: sources disagree (say exactly how, e.g. different prices or dates);\n"
            "- unclear: only one non-official source, or the evidence is vague or dated;\n"
            "- missing-evidence: the question needs it but no learning covers it.\n"
            "For every claim that is not supported, give one plain search query that would settle it.\n"
            'Return JSON: {"claims": [{"claim": "...", "status": "supported|contradicted|unclear|'
            'missing-evidence", "supporting": ["L1"], "contradicting": ["L4"], "rationale": "...", '
            '"confidence": 0.0, "check_query": "..."}]}'
        )
        try:
            data = await self._ask_json(text, 10000)
        except Exception as exc:  # noqa: BLE001 - report can still be written without it
            self.errors.append(f"交叉核实失败: {exc}")
            return []
        claims = []
        for row in data.get("claims", []) if isinstance(data, dict) else []:
            if not isinstance(row, dict) or not str(row.get("claim") or "").strip():
                continue
            status = str(row.get("status") or "unclear").strip()
            claims.append({
                "claim": str(row["claim"]).strip(),
                "status": status if status in CLAIM_STATUSES else "unclear",
                "supporting": [str(x) for x in row.get("supporting") or []],
                "contradicting": [str(x) for x in row.get("contradicting") or []],
                "rationale": str(row.get("rationale") or ""),
                "confidence": row.get("confidence"),
                "check_query": str(row.get("check_query") or "").strip(),
            })
        return claims

    async def _recheck(self, question: str, claims: list[dict[str, Any]]) -> bool:
        order = {"contradicted": 0, "missing-evidence": 1, "unclear": 2}
        todo = sorted((c for c in claims if c["status"] in order and c["check_query"]),
                      key=lambda c: order[c["status"]])[: self.max_rechecks]
        todo = [c for c in todo if c["check_query"].casefold() not in {q.casefold() for q in self.queries}]
        if not todo:
            return False

        async def one(claim: dict[str, Any]) -> None:
            query = claim["check_query"]
            self.queries.append(query)
            await self._progress(f"复核（{claim['status']}）：{claim['claim'][:60]}")
            try:
                async with self._sem:
                    ids = await self._search_and_read(query)
                    await self._learn(question, {"query": query, "goal": "verify: " + claim["claim"]}, ids, 0)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"复核失败 {query}: {exc}")

        before = len(self.learnings)
        await asyncio.gather(*(one(c) for c in todo))
        return len(self.learnings) > before

    # -- report (open_deep_research final_report + GPT Researcher rules) ----

    async def _report(self, question: str, claims: list[dict[str, Any]]) -> tuple[str, list[Source]]:
        by_n = self._by_n()
        cited_ns = sorted({n for item in self.learnings for n in item.sources})
        # open_deep_research citation rule: number sources sequentially without gaps.
        renumber = {old: new for new, old in enumerate(cited_ns, 1)}
        cited = [by_n[n] for n in cited_ns]
        learnings = "\n".join(
            f"- {item.text} " + "".join(f"[{renumber[n]}]" for n in item.sources) for item in self.learnings
        )
        sources = "\n".join(
            f"[{renumber[s.n]}] {s.title or s.domain} — {s.domain} ({s.quality}"
            + (f", {s.published}" if s.published else "") + ")"
            for s in cited
        )
        claim_lines = "\n".join(
            f"- [{c['status']}] {c['claim']} — {c['rationale']}" for c in claims
        ) or "(no cross-check available)"
        chinese = cjk_ratio(question) >= 0.3
        text = (
            f"Research question: <question>{question}</question>\nToday is {self.today}.\n\n"
            f"<Learnings>\n{learnings}\n</Learnings>\n\n<Sources>\n{sources}\n</Sources>\n\n"
            f"<CrossCheck>\n{claim_lines}\n</CrossCheck>\n\n"
            "Write the final answer to the research question from these learnings only.\n"
            "- Aim for roughly 1,500-3,000 words (Chinese: 2,500-5,000 characters); dense, not padded.\n"
            "- Start with a short direct conclusion (2-5 sentences) — your own concrete, well-argued "
            "judgement, not a vague summary. Then the detail.\n"
            "- Write money as '5 美元' / 'USD 5' / '¥30', never with a bare $ sign (it renders as math).\n"
            "- Organize with ## headings; use markdown tables for comparisons (prices, limits, quality).\n"
            "- Every substantive claim, figure or price MUST carry an inline citation using the source "
            "numbers above, like [3] or [2][5]. Only cite numbers that appear in <Sources>; never invent "
            "sources or URLs.\n"
            "- Prefer official and recent sources; when sources disagree, say so and give both figures "
            "with their citations.\n"
            "- End with a section on verification: which key points are well corroborated, which rest "
            "on a single source or conflict, and what remains uncertain.\n"
            "- Do NOT write a sources/references list — it is appended automatically. Do not refer to "
            "yourself or describe your process.\n"
            + ("- Write the entire answer in Chinese (keep product names and units as-is).\n" if chinese
               else "- Write in the same language as the question.\n")
        )
        body = (await self._ask(text, 16000)).strip()
        body = re.sub(r"(?<!\\)\$", r"\\$", body)  # a bare $ pair renders as LaTeX in the UI
        # Keep only the sources the report actually cites, renumbered by first use
        # (open_deep_research: sequential, no gaps), as clickable [[n]](url); drop
        # numbers that do not exist.
        order: dict[int, int] = {}
        for match in re.finditer(r"\[(\d{1,3})\](?!\()", body):
            num = int(match.group(1))
            if 1 <= num <= len(cited) and num not in order:
                order[num] = len(order) + 1
        if not order:  # the model cited nothing: list everything the learnings came from
            order = {i: i for i in range(1, len(cited) + 1)}
        final = [cited[num - 1] for num in order]

        def link(match: re.Match[str]) -> str:
            num = int(match.group(1))
            return f"[[{order[num]}]]({cited[num - 1].url})" if num in order else ""

        body = re.sub(r"\[(\d{1,3})\](?!\()", link, body)
        cited = final
        heading = "## 来源" if chinese else "## Sources"
        listing = "\n".join(
            f"{i}. [{(s.title or s.domain).strip()}]({s.url})" + (f" — {s.published}" if s.published else "")
            for i, s in enumerate(cited, 1)
        )
        return f"{body}\n\n{heading}\n\n{listing}\n", cited
