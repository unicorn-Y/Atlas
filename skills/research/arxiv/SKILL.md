---
name: arxiv
description: "Search arXiv papers by keyword, author, category, or ID."
version: 1.0.0
category: research
triggers:
  - pattern: "arxiv|论文|学术|paper|学术搜索"
  - pattern: "搜.*论文|找.*paper|查.*文献"
  - command: "/arxiv"
dependencies:
  mcp_servers:
    - brave-search
author: Atlas
tags: [research, arxiv, papers, academic, science, api]
related_skills: []
---

# arXiv Research

Search and retrieve academic papers from arXiv via their free REST API. No API key, no dependencies — just curl.

## When to Use

- 搜索学术论文
- 查找特定 arXiv 论文
- 生成 BibTeX 引用
- 跟踪特定领域最新论文
- NOT for: 非学术信息搜索（用 brave-search）

## Instructions

### Searching Papers

```bash
curl -s "https://export.arxiv.org/api/query?search_query=all:GRPO+reinforcement+learning&max_results=5&sortBy=submittedDate&sortOrder=descending" | python -c "
import sys, xml.etree.ElementTree as ET
ns = {'a': 'http://www.w3.org/2005/Atom'}
root = ET.parse(sys.stdin).getroot()
for i, entry in enumerate(root.findall('a:entry', ns)):
    title = entry.find('a:title', ns).text.strip().replace('\n', ' ')
    arxiv_id = entry.find('a:id', ns).text.strip().split('/abs/')[-1]
    published = entry.find('a:published', ns).text[:10]
    authors = ', '.join(a.find('a:name', ns).text for a in entry.findall('a:author', ns))
    summary = entry.find('a:summary', ns).text.strip()[:200]
    print(f'{i+1}. [{arxiv_id}] {title}')
    print(f'   Authors: {authors}')
    print(f'   Published: {published}')
    print(f'   Abstract: {summary}...')
    print(f'   PDF: https://arxiv.org/pdf/{arxiv_id}')
    print()
"
```

### Search Query Syntax

| Prefix | Searches | Example |
|--------|----------|---------|
| `all:` | All fields | `all:transformer+attention` |
| `ti:` | Title | `ti:large+language+models` |
| `au:` | Author | `au:vaswani` |
| `abs:` | Abstract | `abs:reinforcement+learning` |
| `cat:` | Category | `cat:cs.AI` |

Boolean: `+` (AND), `OR`, `ANDNOT`. Phrase: `ti:"chain+of+thought"`

### Sort and Pagination

| Parameter | Options |
|-----------|---------|
| `sortBy` | `relevance`, `lastUpdatedDate`, `submittedDate` |
| `sortOrder` | `ascending`, `descending` |
| `start` | Result offset (0-based) |
| `max_results` | Number of results (default 10) |

### Fetching Specific Papers

```bash
curl -s "https://export.arxiv.org/api/query?id_list=2402.03300"
curl -s "https://export.arxiv.org/api/query?id_list=2402.03300,2401.12345"
```

### Semantic Scholar (Citations, Related Papers)

```bash
# Paper details + citation count
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300?fields=title,authors,citationCount,year,abstract"

# Who cited this paper
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/citations?fields=title,authors,year,citationCount&limit=10"

# References from this paper
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/references?fields=title,authors,year,citationCount&limit=10"

# Recommendations
curl -s -X POST "https://api.semanticscholar.org/recommendations/v1/papers/" \
  -H "Content-Type: application/json" \
  -d '{"positivePaperIds": ["arXiv:2402.03300"]}'
```

### Complete Research Workflow

1. **Discover**: Search arXiv by keyword/category
2. **Assess impact**: Check citation count on Semantic Scholar
3. **Read abstract**: `https://arxiv.org/abs/ID`
4. **Read full paper**: `https://arxiv.org/pdf/ID`
5. **Find related work**: Semantic Scholar references endpoint
6. **Get recommendations**: Semantic Scholar recommendations

### Common Categories

| Category | Field |
|----------|-------|
| `cs.AI` | Artificial Intelligence |
| `cs.CL` | Computation and Language (NLP) |
| `cs.CV` | Computer Vision |
| `cs.LG` | Machine Learning |
| `cs.CR` | Cryptography and Security |
| `stat.ML` | Machine Learning (Statistics) |

### Rate Limits

| API | Rate |
|-----|------|
| arXiv | ~1 req / 3 seconds |
| Semantic Scholar | 1 req / second (free) |

## Notes

- arXiv returns Atom XML, Semantic Scholar returns JSON
- PDF: `https://arxiv.org/pdf/{id}` — Abstract: `https://arxiv.org/abs/{id}`
- ID versioning: `1706.03762v1` (specific) vs `1706.03762` (latest)
- Check `<summary>` for withdrawal notices before treating as valid
