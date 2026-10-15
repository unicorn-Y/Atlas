"""全网发现的筛选：先按规则打分（相关度 × 热度 × 新鲜度）挑出候选，再让 Atlas 当前模型逐条
判断「值不值得吸收、Atlas 差在哪、从哪移植」。模型不可用时只用规则结果。"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger()

#: 相关度关键词 → 权重（命中越多越相关）。
KEYWORDS: dict[str, float] = {
    "agent": 2.0, "agentic": 2.0, "subagent": 3.0, "sub-agent": 3.0, "mcp": 3.0, "skill": 2.5,
    "claude code": 3.0, "codex": 3.0, "opencode": 3.0, "hermes": 2.5, "openclaw": 2.5, "cursor": 2.0,
    "gemini cli": 2.5, "goose": 2.0, "cline": 2.0, "coding": 1.5, "computer use": 3.0,
    "browser": 1.5, "memory": 2.0, "context": 1.5, "compaction": 2.5, "worktree": 2.5,
    "hook": 2.0, "plugin": 1.5, "sandbox": 1.5, "workflow": 1.5, "tool": 1.0, "voice": 1.0,
    "session": 1.5, "background": 1.0, "terminal": 1.0, "desktop": 1.0, "self-improving": 2.5,
    "智能体": 3.0, "代理": 1.5, "技能": 2.5, "插件": 1.5, "记忆": 2.0, "工作流": 1.5, "上下文": 1.5,
}
#: 明显无关的噪音。
NOISE = re.compile(r"\b(hiring|job|meme|funding round|crypto|nft|giveaway)\b|招聘|广告|抽奖", re.I)

#: 给模型的 Atlas 现状摘要（判断「Atlas 有没有」用）。
ATLAS_BRIEF = """Atlas 是一个 Electron + Python 的个人桌面 agent，目标是吸收各家最好的功能。已具备：
自有 agent 内核（Hermes 移植）、不限轮数、出错恢复、完成前自检、并行工具、插话/排队/立即转向、
文件读写编辑（容错匹配、保留换行）、LSP 诊断、ripgrep 搜索、前后台命令和真终端、网页搜索/抓取（多提供方链）、
待办、提问卡片、工具按需加载、上下文自动/手动/空闲压缩、规则文件分层、会话恢复/分叉/撤回、计划模式、持续目标、
旁问、子代理（委派、并行、验收、自定义角色）、独立会话（侧栏真实会话、提议卡片、自动回报、互发消息、独立 worktree）、
Claude 兼容 hooks/插件/命令/技能、MCP 客户端、技能市场、多服务商模型和密钥池、用量统计、/init、/review、
电脑操作和浏览器代理、录制成技能、常驻 Agent、群聊、渠道网关（Telegram/飞书/钉钉等）、心跳、定时自动化、设备接管、
本地模型托管、技能自学、上游追新。"""


def rule_score(item: dict[str, Any], now: datetime | None = None) -> float:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    if NOISE.search(text):
        return 0.0
    relevance = sum(weight for word, weight in KEYWORDS.items() if word in text)
    if relevance <= 0:
        return 0.0
    popularity = math.log10(1 + max(0.0, float(item.get("popularity") or 0)))
    freshness = 1.0
    published = item.get("published_at") or ""
    if published:
        try:
            age_days = ((now or datetime.now(UTC)) - datetime.fromisoformat(published.replace("Z", "+00:00"))).days
            freshness = max(0.3, 1.0 - age_days / 30)
        except ValueError:
            pass
    kind_bonus = {"release": 1.6, "page": 1.6, "mcp": 1.1, "skill": 1.1}.get(item.get("kind", ""), 1.0)
    seen_bonus = 1.0 + 0.3 * len(item.get("also_seen_in") or [])
    return round(min(relevance, 12) * (1 + popularity) * freshness * kind_bonus * seen_bonus, 2)


def shortlist(items: list[dict[str, Any]], seen: set[str], limit: int = 60) -> list[dict[str, Any]]:
    scored = []
    for item in items:
        if item["id"] in seen:
            continue
        score = rule_score(item)
        if score > 0:
            scored.append({**item, "score": score})
    scored.sort(key=lambda row: row["score"], reverse=True)
    # 每个来源最多占 40%，避免一个热闹的源挤掉别的源。
    cap, per_source, picked = max(5, int(limit * 0.4)), {}, []
    for row in scored:
        key = row["source"].split("/")[0]
        if per_source.get(key, 0) >= cap:
            continue
        per_source[key] = per_source.get(key, 0) + 1
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def _prompt(batch: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"[{row['id']}] ({row['source']}, {row['kind']}) {row['title']} — {row['summary'][:700]} <{row['url']}>"
        for row in batch)
    return (
        f"{ATLAS_BRIEF}\n\n下面是本周从全网抓到的新 agent、功能、MCP、技能、工具。逐条判断 Atlas 值不值得吸收。"
        "只看真正的新能力（不是融资/评测/吐槽）。更新日志页面里可能有多个功能，挑出值得吸收的那个最重要的写进 feature。\n"
        "只输出一个 JSON 数组，每条：{\"id\": 原样, \"verdict\": \"absorb\"|\"watch\"|\"skip\", "
        "\"feature\": \"一句中文：是什么能力、怎么做的\", \"atlas_gap\": \"Atlas 现在有没有、差在哪\", "
        "\"port_from\": \"从哪个开源仓库/文件移植，闭源就写参照哪份文档\", \"effort\": \"S|M|L\", \"value\": 1-5}\n\n"
        f"{rows}")


def _parse(text: str) -> list[dict[str, Any]]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return [row for row in data if isinstance(row, dict) and row.get("id")]


async def llm_judge(candidates: list[dict[str, Any]], *, batch_size: int = 15) -> tuple[list[dict[str, Any]], str]:
    """返回（带判断的条目，所用模型/降级说明）。"""
    try:
        from atlas import server

        manager = server.model_mgr
        if manager is None:
            raise RuntimeError("model manager not ready")
        model = manager.current_model
    except Exception as exc:  # noqa: BLE001
        return _rule_only(candidates), f"规则判断（模型不可用：{exc}）"
    judged: dict[str, dict[str, Any]] = {}
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        try:
            result = await manager.model_router.complete_for(
                model, "discovery_judge", [{"role": "user", "content": _prompt(batch)}], max_tokens=3000)
            for row in _parse(str(result.text or "")):
                judged[str(row["id"])] = row
        except Exception as exc:  # noqa: BLE001
            log.warning("discovery.judge_batch_failed", error=str(exc))
    out = []
    for item in candidates:
        verdict = judged.get(item["id"])
        if verdict is None:
            out.extend(_rule_only([item]))
            continue
        out.append({**item, "verdict": str(verdict.get("verdict") or "watch"),
                    "feature": str(verdict.get("feature") or item["title"]),
                    "atlas_gap": str(verdict.get("atlas_gap") or ""),
                    "port_from": str(verdict.get("port_from") or item["url"]),
                    "effort": str(verdict.get("effort") or "M"),
                    "value": int(verdict.get("value") or 3) if str(verdict.get("value") or "3").isdigit() else 3,
                    "judged_by": model})
    return out, f"模型判断：{model}" if judged else "规则判断（模型没有返回可解析结果）"


def _rule_only(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**item, "verdict": "absorb" if item.get("score", 0) >= 25 else "watch",
             "feature": item["title"], "atlas_gap": "待核对（规则判断，没有模型参与）",
             "port_from": item["url"], "effort": "M", "value": 3 if item.get("score", 0) >= 25 else 2,
             "judged_by": "rules"} for item in items]
