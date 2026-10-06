"""Unified-memory acceptance runner (T00.2).

Usage:
    python scripts/unified_memory/run_acceptance.py --mode component
    python scripts/unified_memory/run_acceptance.py --mode integration --json-out result.json

``component`` mode actually executes the frozen component lane:

    core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory \
        -o addopts= -m 'unit or integration' -q --basetemp <artifacts>

from the Atlas repo root after refusing any production data root. Every other
mode (integration/desktop/live/longitudinal) is honestly reported as
``NOT_AVAILABLE_YET`` with exit code 2 — no fake success (00_master_task.md §8,
02_wave_tasks.md T00.2).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ATLAS_REPO = Path(__file__).resolve().parents[2]
CORE_DIR = ATLAS_REPO / "core"
ATLAS_VENV_PYTHON = CORE_DIR / ".venv" / "Scripts" / "python.exe"
PRODUCTION_ATLAS_DATA = ATLAS_REPO / "data"
MODES = ("component", "integration", "desktop", "live", "longitudinal")

RESULT_SCHEMA_VERSION = "um-result-1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _base_result(mode: str) -> dict[str, object]:
    return {
        "schema": RESULT_SCHEMA_VERSION,
        "mode": mode,
        "status": "UNKNOWN",
        "started_at": _now(),
        "finished_at": None,
        "exit_code": None,
        "reason": None,
        "command": None,
        "repos": {
            "atlas": {"path": str(ATLAS_REPO)},
        },
        "environment": {
            "python": str(ATLAS_VENV_PYTHON),
            "atlas_data_dir_env": os.environ.get("ATLAS_DATA_DIR"),
        },
        "stdout_tail": None,
        "stderr_tail": None,
        "failed_tests": [],
    }


def _refuse_production_data_root() -> None:
    value = os.environ.get("ATLAS_DATA_DIR")
    if value and Path(value).resolve() == PRODUCTION_ATLAS_DATA.resolve():
        raise SystemExit(
            f"ATLAS_DATA_DIR={value} 指向生产数据根；component 验收拒绝运行。"
            "留空或指向 artifacts/ 下的隔离目录。"
        )


def _run_component(artifacts: Path) -> dict[str, object]:
    _refuse_production_data_root()
    basetemp = artifacts / "basetemp"
    basetemp.mkdir(parents=True, exist_ok=True)
    command = [
        str(ATLAS_VENV_PYTHON), "-m", "pytest", "core/tests/unified_memory",
        "-o", "addopts=", "-m", "unit or integration", "-q",
        "--basetemp", str(basetemp),
    ]
    result = _base_result("component")
    result["command"] = " ".join(command)
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.run(
        command, cwd=str(ATLAS_REPO), env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=1800,
    )
    result["finished_at"] = _now()
    result["exit_code"] = proc.returncode
    result["stdout_tail"] = proc.stdout[-8000:]
    result["stderr_tail"] = proc.stderr[-4000:]
    failed = [line.strip() for line in proc.stdout.splitlines()
              if line.startswith("FAILED") or line.startswith("ERROR")]
    result["failed_tests"] = failed
    result["status"] = "PASSED" if proc.returncode == 0 else "FAILED"
    if proc.returncode != 0:
        result["reason"] = "pytest 非零退出；未通过项见 failed_tests 与 stdout_tail"
    return result


def _not_available(mode: str) -> dict[str, object]:
    result = _base_result(mode)
    result["finished_at"] = _now()
    result["status"] = "NOT_AVAILABLE_YET"
    result["exit_code"] = 2
    reasons = {
        "integration": (
            "UM01–UM12 尚未交付：/v1/unified/* 服务入口、unified_client/facade 与"
            "跨入口接线不存在，integration 验收无可执行对象。"
        ),
        "desktop": (
            "UM12 尚未交付：MemoryPage 记忆界面与打包版桌面接线不存在，桌面验收"
            "无可执行对象。"
        ),
        "live": (
            "UM13 门禁要求真实模型配置；当前 runner 未接 ModelManager live 配置，"
            "且冻结 320 用例执行器属 UM13。不得用 fake provider 冒充 live 成绩。"
        ),
        "longitudinal": (
            "30 天持续使用窗口未开始（00_master_task.md §9：时间未到不得宣称"
            "长期验证完成）。"
        ),
    }
    result["reason"] = reasons.get(mode, "该模式尚未实现")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="component")
    parser.add_argument(
        "--json-out", type=Path, default=None,
        help="把统一 result schema 写到该路径（默认打印到 stdout）",
    )
    parser.add_argument(
        "--artifacts", type=Path,
        default=ATLAS_REPO / "artifacts" / "unified-memory" / "UM00" / "T00.2",
    )
    args = parser.parse_args(argv)

    started = time.monotonic()
    if args.mode == "component":
        result = _run_component(args.artifacts)
    else:
        result = _not_available(args.mode)
    result["duration_s"] = round(time.monotonic() - started, 1)

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
        print(f"result written: {args.json_out}", file=sys.stderr)
    print(rendered)
    return int(result["exit_code"] or 0)


if __name__ == "__main__":
    raise SystemExit(main())
