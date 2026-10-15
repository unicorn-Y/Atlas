"""全网发现：抓取 → 筛选 → 报告 + 移植任务书草稿，并由 Atlas 自己按间隔定时跑。

产出：
* 报告 ``<data>/evolution/discovery/reports/<YYYY-MM-DD-HHMM>.md``（中文，按值得吸收程度排序）；
* 每条「absorb」写一份 ``tasks/taskbooks/ATLAS-AUTO-<日期>-disc-<slug>.draft.md``，登记进
  E4 草稿索引（drafts.json），在「自动追新」页的草稿区出现，批准后走原有的隔离分支流程；
* 状态 ``<data>/evolution/discovery/state.json``：上次运行、已见条目（不重复报）、各源错误。

定时：``evolution.discovery.enabled``（默认开）与 ``evolution.discovery.interval_hours``（默认 24）。
不用任何外部定时服务。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from atlas.evolution.discovery.judge import llm_judge, shortlist
from atlas.evolution.discovery.sources import collect

log = structlog.get_logger()

MAX_SEEN = 5000
_running: asyncio.Task[dict[str, Any]] | None = None
_scheduler: asyncio.Task[None] | None = None


def discovery_root() -> Path:
    from atlas.evolution.watcher import evolution_root

    path = evolution_root() / "discovery"
    (path / "reports").mkdir(parents=True, exist_ok=True)
    return path


def load_state() -> dict[str, Any]:
    try:
        data = json.loads((discovery_root() / "state.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    path = discovery_root() / "state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return slug or "item"


def render_report(rows: list[dict[str, Any]], errors: dict[str, str], *, total: int, days: int,
                  judged_by: str, started: datetime, drafts: list[dict[str, Any]]) -> str:
    absorb = [row for row in rows if row.get("verdict") == "absorb"]
    watch = [row for row in rows if row.get("verdict") == "watch"]
    sources: dict[str, int] = {}
    for row in rows:
        sources[row["source"]] = sources.get(row["source"], 0) + 1
    lines = [
        f"# 全网新功能发现 · {started.astimezone().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"范围：最近 {days} 天。抓到 {total} 条，去重和规则筛选后 {len(rows)} 条进入判断（{judged_by}）。",
        f"值得吸收 {len(absorb)} 条，值得关注 {len(watch)} 条；生成任务书草稿 {len(drafts)} 份。",
        "",
        "信息源：" + "、".join(f"{name} {count}" for name, count in sorted(sources.items(), key=lambda kv: -kv[1])),
    ]
    if errors:
        lines += ["", "抓取失败的源（不影响其它源）：", *[f"- {name}：{error}" for name, error in errors.items()]]

    def block(row: dict[str, Any]) -> list[str]:
        return [
            f"### {row.get('feature') or row['title']}",
            f"- 来源：[{row['title']}]({row['url']})（{row['source']}，热度 {int(row.get('popularity') or 0)}，规则分 {row.get('score')}）",
            f"- Atlas 现状：{row.get('atlas_gap') or '—'}",
            f"- 从哪移植：{row.get('port_from') or '—'}",
            f"- 工作量：{row.get('effort', 'M')}，价值：{row.get('value', 3)}/5",
            "",
        ]

    lines += ["", "## 值得吸收", ""]
    for row in sorted(absorb, key=lambda r: (-int(r.get("value") or 0), -float(r.get("score") or 0))):
        lines += block(row)
    if not absorb:
        lines += ["（本轮没有）", ""]
    lines += ["## 值得关注", ""]
    for row in sorted(watch, key=lambda r: -float(r.get("score") or 0))[:40]:
        lines.append(f"- [{row.get('feature') or row['title']}]({row['url']}) — {row['source']}；{row.get('atlas_gap') or ''}")
    if drafts:
        lines += ["", "## 生成的任务书草稿", "", *[f"- `{d['file']}`" for d in drafts]]
    return "\n".join(lines) + "\n"


def write_drafts(rows: list[dict[str, Any]], today: date, limit: int) -> list[dict[str, Any]]:
    """为最值得吸收的若干条写移植任务书草稿，并登记进 E4 草稿索引。"""
    from atlas.evolution.taskbook_draft import DRAFT_PREFIX, drafts_root, load_index, save_index

    picked = sorted((row for row in rows if row.get("verdict") == "absorb"),
                    key=lambda r: (-int(r.get("value") or 0), -float(r.get("score") or 0)))[:limit]
    index, target, out = load_index(), drafts_root(), []
    target.mkdir(parents=True, exist_ok=True)
    for row in picked:
        draft_id = f"{DRAFT_PREFIX}-{today.strftime('%Y%m%d')}-disc-{_slug(row['title'])}"
        body = "\n".join([
            f"# {draft_id}.draft",
            "",
            "状态：草稿（全网发现自动生成，未批准）。批准后在隔离分支施工，合并永远需要人工操作。",
            "",
            "## 要吸收的功能",
            f"- {row.get('feature') or row['title']}",
            f"- 来源：{row['url']}（{row['source']}）",
            f"- 发现时间：{datetime.now(UTC).date().isoformat()}，热度 {int(row.get('popularity') or 0)}",
            "",
            "## Atlas 现状与差距",
            f"- {row.get('atlas_gap') or '先核对 Atlas 代码再定'}",
            "",
            "## 移植方式（拿来主义）",
            f"- 参照：{row.get('port_from') or row['url']}",
            "- 先找该功能最强的开源实现，按文件翻译成 Atlas 自己的代码，不依赖原项目的包；",
            "  文件头写 `# Ported from owner/repo@提交号: 路径`，并登记到 core/atlas/engine_core/PORTED.md。",
            "- 闭源产品只按官方文档和行为复刻，写清参照的文档地址。",
            "",
            "## 验收",
            "- [ ] 在真实 Atlas 界面里能用（不只是单测）",
            "- [ ] 至少比原版多一处更好用的细节，写在结果里",
            "- [ ] 既有测试不被改坏；新模块只写必要的少量单测",
            f"- 预估工作量：{row.get('effort', 'M')}",
            "",
        ])
        path = target / f"{draft_id}.draft.md"
        path.write_text(body, encoding="utf-8")
        record = {
            "id": draft_id, "capability_id": "DISC", "capability": row.get("feature") or row["title"],
            "source": row["source"], "repo": row["url"], "repo_file": "", "ref": "latest",
            "suggestion": "UPGRADE", "why_stronger": row.get("atlas_gap", ""),
            "atlas_implementation": row.get("atlas_gap", ""), "status": "draft", "file": str(path),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"), "branch": None,
            "origin": "discovery",
        }
        previous = index["drafts"].get(draft_id) or {}
        if previous.get("status") == "approved":
            record.update(status="approved", branch=previous.get("branch"))
        index["drafts"][draft_id] = record
        out.append(record)
    save_index(index)
    return out


async def run_discovery(*, days: int = 7, only: list[str] | None = None, use_model: bool = True,
                        max_drafts: int = 6, shortlist_size: int = 60) -> dict[str, Any]:
    started = datetime.now(UTC)
    state = load_state()
    seen = set(state.get("seen") or [])
    items, errors = await collect(days=days, only=only)
    candidates = shortlist(items, seen, limit=shortlist_size)
    if use_model:
        rows, judged_by = await llm_judge(candidates)
    else:
        from atlas.evolution.discovery.judge import _rule_only

        rows, judged_by = _rule_only(candidates), "规则判断"
    drafts = write_drafts(rows, started.date(), max_drafts)
    name = started.astimezone().strftime("%Y-%m-%d-%H%M")
    report = render_report(rows, errors, total=len(items), days=days, judged_by=judged_by,
                           started=started, drafts=drafts)
    path = discovery_root() / "reports" / f"{name}.md"
    path.write_text(report, encoding="utf-8")
    (discovery_root() / "reports" / f"{name}.json").write_text(
        json.dumps({"rows": rows, "errors": errors}, ensure_ascii=False, indent=1), encoding="utf-8")
    state["seen"] = (list(seen) + [row["id"] for row in rows])[-MAX_SEEN:]
    state.update(last_run_at=started.isoformat(), last_report=name, last_errors=errors,
                 last_counts={"collected": len(items), "judged": len(rows),
                              "absorb": sum(1 for r in rows if r.get("verdict") == "absorb"),
                              "drafts": len(drafts)})
    save_state(state)
    log.info("discovery.completed", report=str(path), **state["last_counts"])
    return {"report": name, "path": str(path), "counts": state["last_counts"], "errors": errors,
            "drafts": [d["id"] for d in drafts], "judged_by": judged_by}


def start_run(**kwargs: Any) -> bool:
    """后台跑一次；已在跑就返回 False。"""
    global _running
    if _running is not None and not _running.done():
        return False
    _running = asyncio.get_running_loop().create_task(run_discovery(**kwargs))
    return True


def status() -> dict[str, Any]:
    state = load_state()
    reports = sorted((p.stem for p in (discovery_root() / "reports").glob("*.md")), reverse=True)[:30]
    running = _running is not None and not _running.done()
    error = None
    if _running is not None and _running.done() and not _running.cancelled() and _running.exception():
        error = str(_running.exception())
    return {"running": running, "last_run_at": state.get("last_run_at"), "last_report": state.get("last_report"),
            "last_counts": state.get("last_counts"), "last_errors": state.get("last_errors"),
            "reports": reports, "error": error, "settings": _settings()}


def read_report(name: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}", name):
        return None
    path = discovery_root() / "reports" / f"{name}.md"
    if not path.exists():
        return None
    data_path = path.with_suffix(".json")
    rows = json.loads(data_path.read_text(encoding="utf-8")).get("rows", []) if data_path.exists() else []
    return {"name": name, "markdown": path.read_text(encoding="utf-8"), "rows": rows}


def _settings() -> dict[str, Any]:
    from atlas.config import get_config

    config = get_config()
    return {"enabled": config.get("evolution.discovery.enabled", True) is not False,
            "interval_hours": float(config.get("evolution.discovery.interval_hours", 24) or 24),
            "days": int(config.get("evolution.discovery.days", 7) or 7)}


async def _scheduler_loop() -> None:
    await asyncio.sleep(300)  # 启动后先让主体就绪
    while True:
        try:
            settings = _settings()
            last = load_state().get("last_run_at")
            due = not last or datetime.now(UTC) - datetime.fromisoformat(last) >= timedelta(
                hours=settings["interval_hours"])
            if settings["enabled"] and due:
                start_run(days=settings["days"])
        except Exception:
            log.exception("discovery.scheduler_failed")
        await asyncio.sleep(1800)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is None or _scheduler.done():
        try:
            _scheduler = asyncio.get_running_loop().create_task(_scheduler_loop())
        except RuntimeError:
            _scheduler = None
