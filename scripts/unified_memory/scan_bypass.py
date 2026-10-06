#!/usr/bin/env python3
"""T01.3 单一调用路径静态扫描（UM01 收口：绕过统一写路径的调用点清单）。

复用 T00.1 :mod:`baseline` 的纯静态 AST 盘点（不 import sqlite3/aiosqlite/atlas，
绝不连接任何数据库），在活代码上重新扫描并对照 authority-map 判定：

  1. 消费者调用点 —— core/atlas + core/scripts 内全部 ``<memory>.<method>(``
     调用必须落在 MemoryStore 公开方法上（enabled 时写方法由 T01.2 委托统一
     服务）；未知方法名 → bypass。
  2. 直摸 ``_db`` / ``_db_path`` —— 必须在 authority-map ``direct_db_consumers``
     白名单（有 replacement_plan）内；白名单外的直摸 → bypass。
     T01.3 已把两处白名单点（conversations_router rewind 回写、session_sync
     迁移清单）改为 MemoryStore 公开方法，活代码直摸应为 0。
  3. 组成点 —— server.py / cli.py / runtime/hub.py 三个 MemoryStore 构造点
     必须用统一的 ``MemoryStore(unified=...)`` composition（enabled 才构造
     facade，disabled 保持旧行为）。
  4. 代理路由 —— application.create_app 必须按 ``memory.unified.enabled``
     条件挂载 unified_memory_router（UI/API 的唯一统一入口）。
  5. 委托接线证明 —— ``tables_written`` 含 MEMORY_AUTHORITY 表的 MemoryStore
     方法，其方法体（或传递闭包）必须出现 ``_unified_or_none`` 探针
     （T01.2 委托/关闭开关）；否则 enabled 时该写入会绕过统一路径。

输出 JSON（``--out``）并打印摘要；存在 unmapped_bypasses 时退出码 2。

用法：
  python scripts/unified_memory/scan_bypass.py [--out <path>] [--repo <path>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline  # noqa: E402 — 复用 T00.1 纯静态盘点函数，不复制粘贴

TASK_ID = "T01.3"
SCHEMA_VERSION = "1.0"

#: T01.3 统一 composition 的三个生产构造点（authority-map construction_points
#: 中的 Atlas 运行入口；core/scripts/baseline_metrics.py 是度量脚本，不入组成面）
COMPOSITION_POINTS = (
    ("core/atlas/server.py", "lifespan"),
    ("core/atlas/cli.py", "chat"),
    ("core/atlas/runtime/hub.py", "hub_main"),
)

MEMORY_SOURCE = "core/atlas/memory/__init__.py"
APP_FACTORY = "core/atlas/api/application.py"


def _segment(source_lines: list[str], start: int, end: int) -> str:
    return "\n".join(source_lines[max(start - 1, 0):end])


def build_scan(repo_root: Path | None = None) -> dict:
    repo = repo_root or baseline.REPO_ROOT
    data = baseline.build_baseline(repo)  # 纯静态；绝不打开任何数据库

    bypasses: list[dict] = []

    # ---- 1/2：消费者与直摸 _db（baseline 已重新扫描活代码） ----
    # baseline 把「未知方法调用」「无计划直摸」记入 unmapped_memory_consumers；
    # 有 replacement_plan 的直摸属白名单（RUNTIME_AUTHORITY 保留，不算绕过）。
    for entry in data["unmapped_memory_consumers"]:
        bypasses.append({"kind": entry.get("kind", "unmapped_consumer"), **{
            key: entry[key] for key in ("file", "line", "method", "receiver", "detail")
            if key in entry
        }})
    whitelisted_direct_db = [
        {
            "file": entry["file"],
            "lines": entry["lines"],
            "note": "authority-map direct_db_consumers 白名单（replacement_plan 在案）",
        }
        for entry in data["direct_db_consumers"] if entry.get("replacement_plan")
    ]
    planless_direct_db = [
        entry for entry in data["direct_db_consumers"] if not entry.get("replacement_plan")
    ]
    for entry in planless_direct_db:
        bypasses.append({
            "kind": "direct_db_without_plan",
            "file": entry["file"], "lines": entry["lines"],
            "receiver": entry.get("receiver"),
        })

    # ---- 3：组成点统一 composition ----
    composition_points = []
    for rel, entry_name in COMPOSITION_POINTS:
        path = repo / rel
        source = path.read_text(encoding="utf-8") if path.exists() else ""
        unified = "MemoryStore(unified=" in source
        composition_points.append({
            "file": rel, "entry": entry_name, "exists": path.exists(),
            "uses_unified_composition": unified,
        })
        if path.exists() and not unified:
            bypasses.append({
                "kind": "composition_missing",
                "file": rel,
                "detail": "MemoryStore 构造未走 MemoryStore(unified=...) 统一组成",
            })

    # ---- 4：代理路由按配置挂载 ----
    factory_path = repo / APP_FACTORY
    factory_source = factory_path.read_text(encoding="utf-8")
    proxy_wired = (
        "unified_memory_router" in factory_source
        and "memory.unified.enabled" in factory_source
    )
    if not proxy_wired:
        bypasses.append({
            "kind": "proxy_router_not_config_gated",
            "file": APP_FACTORY,
            "detail": "create_app 未按 memory.unified.enabled 条件挂载 "
                      "unified_memory_router",
        })

    # ---- 5：MEMORY_AUTHORITY 写方法的统一探针闭包 ----
    # 只检查 authority-map 判定必须委托的方法（replacement=DELEGATE_TO_UNIFIED）；
    # KEEP_RUNTIME 方法（如 init 的幂等建表 DDL）由 map 白名单预 cleared。
    memory_path = repo / MEMORY_SOURCE
    source = memory_path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    methods = data["methods"]
    write_methods = [
        m for m in methods
        if m["replacement"] == "DELEGATE_TO_UNIFIED"
        and any(data["classifications"].get(t) == "MEMORY_AUTHORITY"
                for t in m["tables_written"])
    ]
    # 闭包：方法体（或其调用的方法，传递地）出现 _unified_or_none 探针。
    # （build_baseline 的 methods 条目自带 line/end_line，直接用它。）
    adjacency = baseline._parse_methods(source)[1]
    probed = {
        m["name"] for m in methods
        if "_unified_or_none" in _segment(source_lines, m["line"], m["end_line"])
    }
    changed = True
    while changed:
        changed = False
        for name, callees in adjacency.items():
            if name in probed:
                continue
            if any(callee in probed for callee in callees):
                probed.add(name)
                changed = True
    delegated_writes = []
    for method in write_methods:
        if method["name"] in probed:
            delegated_writes.append(method["name"])
        else:
            bypasses.append({
                "kind": "memory_write_without_unified_probe",
                "method": method["name"],
                "file": MEMORY_SOURCE,
                "line": method["line"],
                "tables_written": method["tables_written"],
                "detail": "写 MEMORY_AUTHORITY 表但方法体及闭包无 _unified_or_none "
                          "探针；enabled 时会绕过统一写路径",
            })

    bypasses.sort(key=lambda item: (
        str(item.get("file", item.get("method", ""))),
        int(item.get("line", 0) or 0),
    ))
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unmapped_bypasses": bypasses,
        "composition_points": composition_points,
        "proxy_router_config_gated": proxy_wired,
        "memory_write_methods_probed": sorted(delegated_writes),
        "whitelisted_direct_db": whitelisted_direct_db,
        "live_direct_db_consumers": data["direct_db_consumers"],
        "consumer_call_site_count": data["summary"]["consumer_call_site_count"],
        "scanned_files": data["static_analysis"]["scanned_files"],
        "production_db_opened": data["production_db_opened"],
        "summary": {
            "bypass_count": len(bypasses),
            "composition_point_count": len(composition_points),
            "memory_write_method_count": len(write_methods),
            "probed_write_method_count": len(delegated_writes),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T01.3 单一调用路径静态扫描")
    parser.add_argument(
        "--out", type=Path, nargs="?", const=None, default=None,
        help="JSON 输出路径（缺省只打印摘要）")
    parser.add_argument("--repo", type=Path, default=baseline.REPO_ROOT)
    args = parser.parse_args(argv)

    result = build_scan(args.repo)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    summary = result["summary"]
    print(
        f"bypasses={summary['bypass_count']} "
        f"composition_points={summary['composition_point_count']} "
        f"memory_write_methods={summary['memory_write_method_count']} "
        f"probed={summary['probed_write_method_count']} "
        f"consumer_call_sites={result['consumer_call_site_count']}"
    )
    for item in result["unmapped_bypasses"]:
        print(f"BYPASS: {json.dumps(item, ensure_ascii=False)}", file=sys.stderr)
    if summary["bypass_count"]:
        print("FAIL: 存在绕过统一写路径的调用点", file=sys.stderr)
        return 2
    print("OK: 未发现绕过统一写路径的调用点（unmapped_bypasses=[]）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
