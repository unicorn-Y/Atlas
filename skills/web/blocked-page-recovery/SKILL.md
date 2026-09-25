---
name: blocked-page-recovery
description: "Recover blocked/paywalled/WAF'd pages via fallback ladder."
version: 1.0.0
category: web
triggers:
  - pattern: "403|429|blocked|paywall|cloudflare|被墙|被拦|打不开|访问不了"
  - pattern: "recover.*page|恢复.*页面|绕过.*墙"
  - command: "/recover"
dependencies:
  mcp_servers:
    - brave-search
author: Atlas
tags: [web, archives, wayback, paywall, waf, fallback]
related_skills: []
---

# Blocked-Page Recovery

When a page won't fetch — 403/429, Cloudflare "Just a moment...", a paywall, or a bot-detection interstitial — don't give up and don't loop on the same URL. Third-party services often hold a copy. Work down this ladder, cheapest first.

## When to Use

- 页面返回 403/429/5xx
- Cloudflare 或其他 WAF 拦截
- 付费墙/登录墙阻止访问
- NOT for: 正常可访问的页面

## The Ladder

```
1. Wayback Machine  — archive.org "available" API  (snapshot + timestamp)
2. archive.today    — domain rotation: archive.ph → .md → .li → .is
3. Jina Reader      — only if JINA_API_KEY is set  (live server-side render)
4. API-first pivot  — look for /api/, /graphql, .json, or RSS on the same host
5. Real browser     — browser tool as the last, most expensive resort
```

## Provenance Discipline (Non-Negotiable)

| Route | Provenance | How to Cite |
|-------|-----------|-------------|
| Wayback / archive.today | `snapshot` | Cite WITH the snapshot date. Never present as live page. |
| Jina Reader | `live` | Server-side re-render; cite normally. |
| Live fetch / browser | `live` | Cite normally. |

If the user needs *current* data (prices, breaking news), a snapshot is context, not an answer — say so.

## Instructions

### 1. Wayback Machine (try first)

```bash
# Discovery: returns closest snapshot URL + timestamp
curl -sL "https://archive.org/wayback/available?url={URL}"
# Then fetch archived_snapshots.closest.url

# CDX index for multiple snapshots
curl -sL "https://web.archive.org/cdx/search/cdx?url={URL}&output=json&limit=10"
```

Works for: any publicly crawled URL. Fails for: robots-blocked, never-crawled, JS-only SPAs.

### 2. archive.today (paywalls, deleted content)

```bash
for d in archive.ph archive.md archive.li archive.is; do
  curl -sL --max-time 20 "https://$d/newest/{URL}" -o /tmp/page.html \
    -w "%{http_code}" && break
done
```

**Validate the body, not the status code** — a 429 still ships rate-limit HTML.

### 3. Jina Reader (requires JINA_API_KEY)

```bash
curl -s -H "Authorization: Bearer $JINA_API_KEY" "https://r.jina.ai/{URL}"
```

Handles JS SPAs that archives can't. Skip when env var is unset.

### 4. API-first Pivot

After 2-3 blocked attempts, stop fighting the HTML and look for:
- `/api/...`, `/graphql`, or `.json` variants of the page URL
- RSS/Atom feed (`/feed`, `/rss`)
- Sitemap (`/sitemap.xml`) revealing canonical URLs

## Fake Successes — Routes that LIE

- **Google Cache is dead** (since mid-2024). Returns 200 with JS redirect, not a cache.
- **AMP caches** mostly return meta-refresh stubs pointing back at the original URL.
- **Rate-limit bodies**: archive.today 429 pages are multi-KB HTML. Check for actual content.

Detection: body under byte floor; meta-refresh stubs; interstitial titles ("Just a moment", "Redirecting").

## Proxy Relays: Don't

Generic web proxies are MITM by construction. Never send cookies or auth headers through one. Prefer archives with timestamped provenance.
