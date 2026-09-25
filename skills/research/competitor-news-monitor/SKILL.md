---
name: competitor-news-monitor
description: "Watch named companies for material news; cited digests."
version: 1.0.0
category: research
triggers:
  - pattern: "竞品|竞争对手|competitor|监控.*公司|track.*company"
  - pattern: "competitive.*intelligence|市场.*监控"
  - command: "/compete"
dependencies:
  mcp_servers:
    - brave-search
author: Atlas
tags: [competitors, news, market-research, monitoring]
related_skills: [arxiv]
---

# Competitor News Monitor

Track a declared company set and report only material, new developments with primary-source evidence.

## When to Use

- "Monitor these competitors weekly."
- "Tell me when Company X changes pricing or launches a product."
- "Create a competitor intelligence digest."
- NOT for: one-off company research (use brave-search directly)

## Instructions

### Setup (once)

#### 1. Freeze the Watchlist
Record: canonical company names, domains, products, aliases, geography, event categories, cadence, audience, materiality threshold.

#### 2. Build Source Coverage
For each company include:
1. Official newsroom/blog and changelog
2. Pricing/product pages
3. Regulatory filings and investor relations
4. Status/security pages
5. Reputable trade and financial press
6. Job postings (weak supporting evidence)

Write watch contract to state file, then create scheduled task for recurring checks.

### Tick (each scheduled run)

#### 3. Collect Incrementally
Search from last cutoff with overlap for late indexing. A source failure = unknown coverage, not "no news" — record it.

#### 4. Deduplicate by Underlying Event
Collapse syndicated stories, rewrites, URL variants into one event. Keep corroboration attached.

#### 5. Assess Materiality
Score: directness, source authority, novelty, customer impact, strategic relevance, confidence. Separate facts from interpretation.

#### 6. Deliver or Stay Silent
Report per event: company, event, date, evidence links, what changed, why it matters, confidence. No material events → stay silent unless all-clear requested.

## Pitfalls

- Counting ten articles about one launch as ten developments
- Monitoring only broad search, missing official changelog
- Treating job postings as proof of product decisions
- Advancing cutoff past a failed source (silently losing coverage)

## Verification

- [ ] Every event cites a primary source, appears exactly once
- [ ] Source failures reported as coverage gaps
- [ ] Materiality decisions replay from watch contract
- [ ] Cutoff advanced only for successful sources
