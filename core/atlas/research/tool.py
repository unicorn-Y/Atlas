"""Agent-facing ``deep_research`` tool over :class:`atlas.research.deep.DeepResearcher`.

Search and page reading go through the agent's :class:`atlas.tools.web.WebRuntime` (the
Atlas-owned provider chain in :mod:`atlas.websearch`); model calls go through the agent's
``ModelRouter`` with the user's ``research_model`` setting, else the current chat model.
"""

from __future__ import annotations

from typing import Any

from atlas.research.deep import DeepResearcher, Progress

DEEP_RESEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "deep_research",
        "description": (
            "Research a question on the live web in several rounds: splits it into sub-questions, "
            "searches, reads the most authoritative pages, cross-checks key claims across independent "
            "sources (re-searching conflicts), and returns a cited report with numbered source links. "
            "Use it for questions that need current, multi-source facts — comparisons, prices, market "
            "or product state, 'latest' anything, claims that must be verified. Takes 1-5 minutes. "
            "For a single quick fact use web_search instead. Give the user the report's conclusion and "
            "keep its source links."
        ),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string",
                "description": "The full research question, with the user's constraints (time range, region, criteria)."},
            "breadth": {"type": "integer", "minimum": 1, "maximum": 5,
                "description": "Sub-questions per round (default 3)."},
            "depth": {"type": "integer", "minimum": 1, "maximum": 3,
                "description": "Follow-up rounds (default 2). Use 1 for a quick survey, 3 for hard topics."},
        }, "required": ["question"], "additionalProperties": False},
    },
}


def _research_model(agent: Any) -> str:
    try:
        from atlas.config import load_user_settings

        settings = load_user_settings() or {}
    except Exception:  # noqa: BLE001 - settings are optional here
        settings = {}
    chosen = str(settings.get("research_model") or "").strip()
    return chosen or str(agent._model_mgr.current_model)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def run_deep_research_tool(agent: Any, args: dict[str, Any],
                                 on_progress: Progress | None = None) -> dict[str, Any]:
    model_id = _research_model(agent)
    router = agent._model_router

    async def complete(messages: list[dict[str, str]], max_tokens: int) -> str:
        result = await router.complete_for(model_id, "deep_research", messages,
                                           max_tokens=max_tokens, temperature=0.2)
        return str(getattr(result, "text", "") or "")

    researcher = DeepResearcher(
        complete, agent._web,
        breadth=_int(args.get("breadth"), 3), depth=_int(args.get("depth"), 2),
        on_progress=on_progress,
    )
    try:
        data = await researcher.run(str(args.get("question", "")))
    except (ValueError, RuntimeError) as exc:
        message = f"deep_research failed: {exc}"
        return {"data": {"error": message, "errors": researcher.errors[-10:]},
                "content": [{"type": "text", "text": message}], "is_error": True}
    stats = data["stats"]
    footer = (
        f"\n\n---\n调研统计：{stats['queries']} 次搜索，读了 {stats['pages_read']} 个网页，"
        f"引用 {len(data['sources'])} 个来源，用时 {stats['seconds']} 秒。"
        "\n（把上面的结论和来源链接交给用户；可以精简，但不要丢掉引用。）"
    )
    data["model"] = model_id
    return {
        "data": data,
        "content": [{"type": "text", "text": data["report"] + footer}],
        "is_error": False,
    }
