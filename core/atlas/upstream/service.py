"""给 API 和后台定时器用的服务层：检查、一键追新、即时更新、启动预演任务。"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any

import structlog

from atlas.upstream import check, inventory, staging
from atlas.upstream.model import HOT, OUTDATED

log = structlog.get_logger()

_check_lock = asyncio.Lock()
_checking = False


def is_checking() -> bool:
    return _checking


async def _skill_components() -> list[Any]:
    try:
        from atlas.api.skills_market_router import get_market

        rows = await get_market().check_updates()
    except Exception as exc:  # noqa: BLE001 —— 技能源连不上不影响其它项
        log.info("upstream.skills_check_failed", error=str(exc))
        return []
    return inventory.skills_from_updates(rows)


async def check_now() -> dict[str, Any]:
    """完整检查（含技能）。同时只跑一个；正在跑时直接等它的结果。"""
    global _checking
    async with _check_lock:
        _checking = True
        try:
            skills = await _skill_components()
            return await asyncio.to_thread(check.run_check, None, None, skills)
        finally:
            _checking = False


def start_check_background() -> bool:
    if _checking:
        return False
    task = asyncio.get_running_loop().create_task(check_now(), name="upstream-check")
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return True


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------


def select(ids: list[str] | None = None, category: str | None = None) -> list[dict[str, Any]]:
    """要处理的项：给了 ids 就按 ids（可含已失败过的版本——用户手动点的就再试）；
    给了分类就是该分类所有可处理项；都没给就是全部可处理项（跳过已知会失败的版本）。"""
    components = check.view()["components"]
    if ids:
        wanted = set(ids)
        return [item for item in components if item["id"] in wanted and item.get("actionable")]
    rows = [item for item in components if item.get("actionable")]
    if category:
        return [item for item in rows if item.get("category") == category]
    return [item for item in rows if not item.get("failed_latest")]


async def apply_hot(items: list[dict[str, Any]]) -> dict[str, Any]:
    """不用重启的项：技能（技能市场直接更新）、只在本机配置里的 MCP 版本号。"""
    results: dict[str, Any] = {}
    for item in items:
        try:
            if item["kind"] == "skill":
                from atlas.api.skills_market_router import get_market

                outcome = await get_market().update(item["name"])
                results[item["id"]] = {"status": "applied", "note": outcome.get("status")}
            elif item["kind"] == "mcp-npx":
                results[item["id"]] = {"status": "applied",
                                       "note": _bump_live_mcp(item["name"], item["current"],
                                                              item["latest"])}
            else:
                results[item["id"]] = {"status": "skipped", "note": "不是即时更新项"}
        except Exception as exc:  # noqa: BLE001 —— 单项失败记下来继续
            results[item["id"]] = {"status": "failed", "reason": str(exc)[:1000]}
            check.record_failure(item["id"], str(item.get("latest", "")), str(exc))
    return results


def _bump_live_mcp(name: str, old: str, new: str) -> str:
    from atlas.config import CONFIG_PATH

    text = CONFIG_PATH.read_text(encoding="utf-8")
    if f"{name}@{old}" not in text:
        raise RuntimeError(f"本机配置里找不到 {name}@{old}")
    CONFIG_PATH.write_text(text.replace(f"{name}@{old}", f"{name}@{new}"), encoding="utf-8")
    return f"{old} → {new}（下次启动该 MCP 服务时生效）"


def start_job(ids: list[str]) -> dict[str, Any]:
    """在后台起一个预演任务进程（脱离 Atlas：Atlas 重启它也继续跑）。"""
    root = check.upstream_root()
    current = staging.read_run(root)
    if current.get("state") == "running":
        return {"started": False, "reason": "已有追新任务在运行", "run": current}
    plan_path = root / "plan.json"
    plan_path.write_text(json.dumps({"ids": ids}, ensure_ascii=False), encoding="utf-8")
    from atlas.config import PROJECT_ROOT

    log_path = root / "job.log"
    args = [sys.executable, "-m", "atlas.upstream", "run", "--plan", str(plan_path)]
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                 | subprocess.BELOW_NORMAL_PRIORITY_CLASS  # 装包、跑测试不抢正在用的 Atlas
                 | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB：Electron 退出时不被一起杀掉
    with log_path.open("w", encoding="utf-8") as handle:
        try:
            process = subprocess.Popen(args, cwd=PROJECT_ROOT / "core", stdout=handle,
                                       stderr=subprocess.STDOUT, creationflags=flags,
                                       start_new_session=os.name != "nt")
        except OSError:
            # 所在作业对象不允许脱离时退回普通子进程
            process = subprocess.Popen(args, cwd=PROJECT_ROOT / "core", stdout=handle,
                                       stderr=subprocess.STDOUT,
                                       creationflags=flags & ~0x01000000)
    log.info("upstream.job_started", pid=process.pid, items=len(ids))
    return {"started": True, "pid": process.pid, "ids": ids}


async def apply(ids: list[str] | None = None, category: str | None = None) -> dict[str, Any]:
    items = select(ids, category)
    if not items:
        return {"started": False, "reason": "没有可以更新的项", "hot": {}}
    if not repo_supported():
        return {"started": False,
                "reason": "当前不是从 git 源码运行（安装包版本），只能检查不能追新",
                "hot": {}}
    hot = [item for item in items if item.get("strategy") == HOT
           and not (item["kind"] == "mcp-npx"
                    and "atlas.example.toml" in item.get("locations", []))]
    rest = [item["id"] for item in items if item not in hot]
    hot_results = await apply_hot(hot) if hot else {}
    job = start_job(rest) if rest else {"started": False, "reason": ""}
    if hot_results and not rest:
        start_check_background()  # 即时更新完刷新一下清单
    return {**job, "hot": hot_results}


def repo_supported() -> bool:
    from atlas.config import PROJECT_ROOT

    return (PROJECT_ROOT / ".git").exists() and (PROJECT_ROOT / "core" / "pyproject.toml").exists()


def pending_merge() -> dict[str, Any] | None:
    path = check.upstream_root() / staging.PENDING
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 后台定时
# ---------------------------------------------------------------------------

STARTUP_DELAY_SECONDS = 180
TICK_SECONDS = 3600


async def auto_loop() -> None:
    """启动 3 分钟后开始，每小时看一次：到检查时间就检查；自动模式下检查完直接追新。"""
    if os.environ.get("ATLAS_UPSTREAM_AUTO", "1") == "0" or not repo_supported():
        return
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            if check.check_due():
                view = await check_now()
                if view["settings"].get("mode") == "auto":
                    ids = [item["id"] for item in view["components"]
                           if item.get("actionable") and not item.get("failed_latest")
                           and item.get("status") == OUTDATED]
                    if ids:
                        result = await apply(ids)
                        log.info("upstream.auto_apply", started=result.get("started"),
                                 items=len(ids))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 定时任务不能死
            log.exception("upstream.auto_loop_failed")
        await asyncio.sleep(TICK_SECONDS)
