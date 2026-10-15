"""全网发现的信息源：各家更新日志、GitHub（新仓库 / trending / releases）、HN、Reddit、
MCP 注册表、技能市场、国内论坛，以及用 Atlas 自己的网页搜索兜底 X 和小平台。

每个抓取器返回统一的 item 字典::

    {"id", "source", "kind", "title", "url", "summary", "published_at", "popularity", "lang"}

``kind``：release（已有产品的新版本）、repo（新项目）、post（讨论/发布帖）、
mcp（MCP 服务器）、skill（技能）、page（更新日志页面）。

全部短超时、单源失败只记错误不影响其它源；网络走环境代理（httpx ``trust_env``）。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(15.0, connect=8.0)
UA = "Atlas-Discovery/1.0 (+personal agent; contact: local)"

#: 已经在跟的产品仓库：看它们的新版本说明（功能级别的变化都在这里）。
RELEASE_REPOS = [
    "anthropics/claude-code", "openai/codex", "NousResearch/hermes-agent", "openclaw/openclaw",
    "anomalyco/opencode", "badlogic/pi-mono", "block/goose", "google-gemini/gemini-cli",
    "cline/cline", "browser-use/browser-use", "zai-org/ZCode", "All-Hands-AI/OpenHands",
    "modelcontextprotocol/modelcontextprotocol",
]
#: 新仓库搜索（最近 N 天创建、按星排序）。
GITHUB_QUERIES = [
    "topic:ai-agents", "topic:mcp-server", "topic:claude-code", "topic:agent-skills",
    "topic:coding-agent", "topic:computer-use", "agent in:name,description",
]
HN_QUERIES = ["agent", "MCP", "Claude Code", "Codex", "coding agent", "agentic", "skills"]
SUBREDDITS = ["LocalLLaMA", "ClaudeAI", "ChatGPTCoding", "AI_Agents", "mcp", "OpenAI"]
#: 网页搜索兜底（X、产品博客、国内媒体、小平台）；由 Atlas 自己的搜索服务执行。
WEB_QUERIES = [
    "site:x.com new agent feature launch this week",
    "site:x.com Claude Code OR Codex new feature",
    "new AI coding agent released this week",
    "new MCP server launch",
    "AI agent 新功能 发布 本周",
    "智能体 开源 新项目 发布",
    "site:linux.do agent 新功能",
    "site:v2ex.com agent 新工具",
]
#: 更新日志聚合页：抓正文交给模型提炼。
CHANGELOG_PAGES = [
    "https://code.claude.com/docs/en/changelog",
    "https://releasebot.io/updates/openai/codex",
    "https://aiagentstore.ai/ai-agent-news/this-week",
    "https://www.gradually.ai/en/changelogs/claude-code/",
]


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _item(source: str, kind: str, title: str, url: str, summary: str = "", published_at: str = "",
          popularity: float = 0.0, lang: str = "en") -> dict[str, Any]:
    return {"id": _id(source, url or title), "source": source, "kind": kind,
            "title": re.sub(r"\s+", " ", unescape(title or "")).strip()[:200],
            "url": url, "summary": re.sub(r"\s+", " ", unescape(summary or "")).strip()[:1500],
            "published_at": published_at, "popularity": float(popularity or 0), "lang": lang}


def _github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=8,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _gh_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def github_releases(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    headers, items = _gh_headers(), []
    for repo in RELEASE_REPOS:
        response = await client.get(f"https://api.github.com/repos/{repo}/releases",
                                    params={"per_page": 8}, headers=headers)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        for release in response.json():
            published = release.get("published_at") or ""
            if published and datetime.fromisoformat(published.replace("Z", "+00:00")) < since:
                continue
            items.append(_item("github-release", "release", f"{repo} {release.get('name') or release.get('tag_name')}",
                               release.get("html_url", ""), release.get("body") or "", published,
                               popularity=50))
    return items


async def github_new_repos(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    headers, items = _gh_headers(), []
    for query in GITHUB_QUERIES:
        response = await client.get("https://api.github.com/search/repositories", headers=headers, params={
            "q": f"{query} created:>{since.date().isoformat()}", "sort": "stars", "order": "desc", "per_page": 15})
        if response.status_code in (403, 422):
            continue
        response.raise_for_status()
        for repo in response.json().get("items", []):
            items.append(_item("github-new", "repo", repo["full_name"], repo["html_url"],
                               repo.get("description") or "", repo.get("created_at") or "",
                               popularity=repo.get("stargazers_count", 0)))
    return items


async def github_trending(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    response = await client.get("https://github.com/trending", params={"since": "weekly"},
                                headers={"User-Agent": UA})
    response.raise_for_status()
    items = []
    for block in re.findall(r'<article class="Box-row">(.*?)</article>', response.text, re.S):
        link = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', block)
        if not link:
            continue
        desc = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', block, re.S)
        stars = re.search(r'([\d,]+)\s+stars this week', block)
        items.append(_item("github-trending", "repo", link.group(1).strip(), f"https://github.com/{link.group(1).strip()}",
                           re.sub(r"<[^>]+>", "", desc.group(1)) if desc else "", "",
                           popularity=float(stars.group(1).replace(",", "")) if stars else 0))
    return items


async def hackernews(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    items = []
    for query in HN_QUERIES:
        response = await client.get("https://hn.algolia.com/api/v1/search_by_date", params={
            "query": query, "tags": "story", "hitsPerPage": 30,
            "numericFilters": f"created_at_i>{int(since.timestamp())},points>30"})
        response.raise_for_status()
        for hit in response.json().get("hits", []):
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            items.append(_item("hackernews", "post", hit.get("title") or "", url,
                               f"HN {hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments "
                               f"(https://news.ycombinator.com/item?id={hit.get('objectID')})",
                               hit.get("created_at") or "", popularity=hit.get("points", 0)))
    return items


async def reddit(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    items = []
    for sub in SUBREDDITS:
        response = await client.get(f"https://www.reddit.com/r/{sub}/top.json", params={"t": "week", "limit": 25},
                                    headers={"User-Agent": UA})
        if response.status_code in (403, 429):
            continue
        response.raise_for_status()
        for child in response.json().get("data", {}).get("children", []):
            post = child.get("data", {})
            created = datetime.fromtimestamp(post.get("created_utc", 0), UTC)
            if created < since:
                continue
            items.append(_item(f"reddit/r/{sub}", "post", post.get("title", ""),
                               post.get("url_overridden_by_dest") or f"https://www.reddit.com{post.get('permalink', '')}",
                               (post.get("selftext") or "")[:800], created.isoformat(),
                               popularity=post.get("score", 0)))
    return items


async def mcp_registry(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    response = await client.get("https://registry.modelcontextprotocol.io/v0/servers", params={
        "limit": 100, "updated_since": since.strftime("%Y-%m-%dT%H:%M:%SZ")})
    response.raise_for_status()
    items = []
    for entry in response.json().get("servers", []):
        server = entry.get("server", entry)
        meta = (entry.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
        if meta.get("isLatest") is False:
            continue
        repo = (server.get("repository") or {}).get("url") or server.get("websiteUrl") or ""
        items.append(_item("mcp-registry", "mcp", server.get("name", ""), repo or
                           f"https://registry.modelcontextprotocol.io/v0/servers?search={server.get('name', '')}",
                           server.get("description", ""), meta.get("publishedAt") or meta.get("updatedAt") or "",
                           popularity=10))
    return items


async def skills_market(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    """Agent Skills 市场（skills.sh，Atlas 技能中心已接的同一提供方），按安装量排。"""
    from atlas.skills.acquisition import SkillsShProvider

    provider, items = SkillsShProvider(client), []
    for query in ("agent", "browser", "coding", "research", "memory", "mcp"):
        result = await provider.search(query, limit=15)
        for row in result.get("results", []):
            installs = (row.get("provenance") or {}).get("installs") or 0
            items.append(_item("skills.sh", "skill", f"{row.get('source')}/{row.get('name')}",
                               row.get("install_url") or row.get("source_url") or "",
                               f"skills.sh 技能，安装量 {installs}", "", popularity=float(installs or 0)))
    return items


async def cn_forums(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    items = []
    try:
        response = await client.get("https://www.v2ex.com/api/topics/hot.json", headers={"User-Agent": UA})
        response.raise_for_status()
        for topic in response.json():
            items.append(_item("v2ex", "post", topic.get("title", ""), topic.get("url", ""),
                               (topic.get("content") or "")[:600],
                               datetime.fromtimestamp(topic.get("created", 0), UTC).isoformat(),
                               popularity=topic.get("replies", 0), lang="zh"))
    except (httpx.HTTPError, ValueError):
        pass
    response = await client.get("https://linux.do/top.json", params={"period": "weekly"}, headers={"User-Agent": UA})
    if response.status_code == 200:
        for topic in response.json().get("topic_list", {}).get("topics", []):
            items.append(_item("linux.do", "post", topic.get("title", ""),
                               f"https://linux.do/t/topic/{topic.get('id')}", topic.get("excerpt") or "",
                               topic.get("created_at") or "", popularity=topic.get("like_count", 0), lang="zh"))
    return items


async def web_search(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    from atlas.websearch.service import get_service

    service, items = get_service(), []
    for query in WEB_QUERIES:
        result = await service.search(query, 8)
        for row in result.get("results", []) if isinstance(result, dict) else []:
            items.append(_item("web-search", "post", row.get("title", ""), row.get("url", ""),
                               row.get("snippet") or row.get("description") or "", row.get("published_at") or "",
                               popularity=5, lang="zh" if re.search(r"[一-鿿]", query) else "en"))
    return items


async def changelog_pages(client: httpx.AsyncClient, since: datetime) -> list[dict[str, Any]]:
    from atlas.websearch.service import get_service

    pages = await get_service().extract(CHANGELOG_PAGES, char_limit=12000)
    return [_item("changelog-page", "page", page.get("title") or page.get("url", ""), page.get("url", ""),
                  str(page.get("content") or "")[:6000], "", popularity=40)
            for page in pages if page.get("content")]


FETCHERS: dict[str, Callable[[httpx.AsyncClient, datetime], Awaitable[list[dict[str, Any]]]]] = {
    "github_releases": github_releases, "github_new_repos": github_new_repos,
    "github_trending": github_trending, "hackernews": hackernews, "reddit": reddit,
    "mcp_registry": mcp_registry, "skills_market": skills_market, "cn_forums": cn_forums,
    "web_search": web_search, "changelog_pages": changelog_pages,
}


async def collect(days: int = 7, only: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """并发跑全部信息源；返回（去重后的 items，{源: 错误}）。"""
    since = datetime.now(UTC) - timedelta(days=days)
    errors: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, trust_env=True) as client:
        names = [name for name in FETCHERS if not only or name in only]

        async def guarded(name: str) -> list[dict[str, Any]]:
            try:
                return await asyncio.wait_for(FETCHERS[name](client, since), timeout=180)
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响其它源
                errors[name] = f"{type(exc).__name__}: {exc}"[:300]
                return []

        batches = await asyncio.gather(*(guarded(name) for name in names))
    merged: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for item in batch:
            key = item["url"].rstrip("/").lower() or item["id"]
            if key in merged:
                merged[key]["popularity"] = max(merged[key]["popularity"], item["popularity"])
                merged[key].setdefault("also_seen_in", []).append(item["source"])
            else:
                merged[key] = item
    return list(merged.values()), errors
