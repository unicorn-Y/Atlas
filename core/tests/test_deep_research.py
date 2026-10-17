import asyncio
import json
import re

from atlas.research.deep import DeepResearcher, classify_source


class FakeWeb:
    def __init__(self):
        self.searched, self.fetched = [], []

    async def web_search(self, query, max_results=5):
        self.searched.append(query)
        slug = re.sub(r"\W+", "-", query)
        return {"results": [
            {"title": f"Docs {slug}", "url": f"https://docs.vendor.com/{slug}", "description": "official"},
            {"title": f"Blog {slug}", "url": f"https://medium.com/{slug}", "description": "blog"},
            {"title": "Same docs again", "url": f"https://docs.vendor.com/{slug}/", "description": "dup"},
        ]}

    async def web_fetch(self, url, max_chars=15000):
        self.fetched.append(url)
        return {"url": url, "title": "", "text": f"Page {url}. Price is $5 per 1k queries. " * 20}


async def fake_complete(messages, max_tokens):
    prompt = messages[-1]["content"]
    if "Generate a list of web search queries" in prompt and "Follow-up research directions" in prompt:
        goal = re.search(r"Previous research goal: (\w+)", prompt).group(1)
        return json.dumps({"queries": [{"query": f"{goal} rate limits"}, {"query": "search api pricing"}]})
    if "Generate a list of web search queries" in prompt:
        return json.dumps({"queries": [{"query": "search api pricing", "goal": "prices"},
                                       {"query": "search api quality benchmark", "goal": "quality"}]})
    if "extract up to 6 learnings" in prompt:
        ids = [int(n) for n in re.findall(r'id="S(\d+)"', prompt)]
        return json.dumps({"learnings": [{"text": f"Learning from {ids}", "sources": ids[:2]}],
                           "follow_up_questions": ["what about rate limits"]})
    if "Identify up to 8 key claims" in prompt:
        return "```json\n" + json.dumps({"claims": [
            {"claim": "price is $5", "status": "contradicted", "rationale": "two figures",
             "check_query": "verify search api price"},
        ]}) + "\n```"
    return "结论：价格约 $5 [1]，另一个数字 $7 [2]，不存在的 [99]。"


def test_deep_research_loops_rechecks_and_cites_only_real_sources():
    web = FakeWeb()
    progress = []

    async def on_progress(text):
        progress.append(text)

    researcher = DeepResearcher(fake_complete, web, breadth=2, depth=2, on_progress=on_progress)
    result = asyncio.run(researcher.run("对比 2026 年主流搜索 API 的价格和质量"))

    # depth 2: two first-round queries, each followed by a second round, plus one re-check.
    assert len(web.searched) >= 4
    assert "verify search api price" in web.searched
    # the trailing-slash duplicate is the same source and only one page per domain is read per query
    assert not any(url.endswith("/") for url in web.fetched)
    assert web.fetched[0].startswith("https://docs.vendor.com/")  # official docs read first
    report = result["report"]
    urls = {s["url"] for s in result["sources"]}
    linked = set(re.findall(r"\]\((https?://[^)]+)\)", report))
    assert linked and linked <= urls
    assert "[99]" not in report and "## 来源" in report
    assert "\\$5" in report and "\\$7" in report  # escaped so the UI does not render $…$ as math
    assert [s["n"] for s in result["sources"]] == list(range(1, len(result["sources"]) + 1))
    assert result["claims"][0]["status"] == "contradicted"
    assert any(p.startswith("搜索：") for p in progress)


def test_classify_source():
    assert classify_source("https://docs.tavily.com/pricing") == "official_docs"
    assert classify_source("https://exa.ai/pricing") == "vendor_docs"
    assert classify_source("https://github.com/x/y/issues/3") == "repo_issue"
    assert classify_source("https://zhuanlan.zhihu.com/p/1") == "forum"
    assert classify_source("https://blog.csdn.net/a/article/details/1") == "blog"
    assert classify_source("https://www.36kr.com/p/1") == "news"
