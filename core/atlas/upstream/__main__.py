"""命令行入口。

    python -m atlas.upstream check              检查一遍并打印汇总
    python -m atlas.upstream run --plan FILE    执行追新（后台任务进程用）
    python -m atlas.upstream run --all          把所有可处理的项追到最新
    python -m atlas.upstream post-merge [--memos]
        更新器合并追新提交之后跑：把本机配置里 MCP 的版本号对齐到示例配置，必要时重建 MemOS
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print_summary(view: dict) -> None:
    summary = view["summary"]
    print(f"共 {summary['total']} 项，{summary['outdated']} 项有新版本，"
          f"{summary['actionable']} 项可一键更新，{summary['errors']} 项出错")
    for category in summary["categories"]:
        print(f"  {category['label']:<12} {category['total']:>4} 项  有更新 {category['outdated']}")
    for item in view["components"]:
        if item["status"] in {"outdated", "error", "held"}:
            print(f"  [{item['status']:<8}] {item['id']:<48} {item['current']} → {item['latest']}"
                  f"  {item.get('note', '')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atlas.upstream")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path)
    run.add_argument("--all", action="store_true")
    run.add_argument("--ids", nargs="*", default=[])
    post = sub.add_parser("post-merge")
    post.add_argument("--memos", action="store_true")
    args = parser.parse_args(argv)

    from atlas.upstream import check

    if args.command == "check":
        _print_summary(check.run_check())
        return 0
    if args.command == "run":
        from atlas.upstream import staging

        if args.plan:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))["ids"]
        elif args.all:
            plan = check.auto_plan()
        else:
            plan = list(args.ids)
        result = staging.run(plan)
        print(json.dumps({k: result.get(k) for k in ("state", "results", "commits", "pushed")},
                         ensure_ascii=False, indent=2))
        return 0 if result.get("state") in {"succeeded", "nothing", "partial"} else 1
    if args.command == "post-merge":
        from atlas.upstream import postmerge

        return postmerge.main(memos=args.memos)
    return 2


if __name__ == "__main__":
    sys.exit(main())
