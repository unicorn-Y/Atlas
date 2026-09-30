"""Run repository checks and normalize their diagnostics for the agent UI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MAX_ITEMS = 200


def parse_ruff_json(raw: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [{
        "file": row.get("filename", ""), "line": row.get("location", {}).get("row"),
        "col": row.get("location", {}).get("column"), "severity": "error",
        "code": row.get("code", ""), "message": row.get("message", ""),
    } for row in rows if isinstance(row, dict)][:MAX_ITEMS]


def parse_tsc_output(raw: str) -> list[dict[str, Any]]:
    result = []
    for line in raw.splitlines():
        match = re.match(r"^(.*)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.*)$", line)
        if match:
            result.append({
                "file": match.group(1), "line": int(match.group(2)),
                "col": int(match.group(3)), "severity": "error",
                "code": match.group(4), "message": match.group(5),
            })
    return result[:MAX_ITEMS]


def parse_test_summary(raw: str) -> dict[str, int] | None:
    match = re.search(
        r"(?:(\d+)\s+passed)?[,\s]+(?:(\d+)\s+failed)?(?:[,\s]+(?:(\d+)\s+skipped))?",
        raw, re.IGNORECASE,
    )
    if not match or not any(value is not None for value in match.groups()):
        return None
    return {"passed": int(match.group(1) or 0), "failed": int(match.group(2) or 0),
            "skipped": int(match.group(3) or 0)}


def parse_pytest_junit(path: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {"passed": 0, "failed": 0, "skipped": 0}, []
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {key: 0 for key in ("passed", "failed", "skipped")}
    items = []
    for suite in suites:
        totals["failed"] += int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
        totals["skipped"] += int(suite.attrib.get("skipped", 0))
        totals["passed"] += max(0, int(suite.attrib.get("tests", 0)) -
                                int(suite.attrib.get("failures", 0)) -
                                int(suite.attrib.get("errors", 0)) -
                                int(suite.attrib.get("skipped", 0)))
    for case in root.iter("testcase"):
        node = next((child for child in case if child.tag in {"failure", "error"}), None)
        if node is not None:
            items.append({
                "file": case.attrib.get("file", ""), "line": None, "col": None,
                "severity": "error", "code": node.tag,
                "message": (node.attrib.get("message") or node.text or "").strip()[:1000],
                "test": case.attrib.get("name", ""),
            })
        elif any(child.tag == "skipped" for child in case):
            items.append({
                "file": case.attrib.get("file", ""), "line": None, "col": None,
                "severity": "info", "code": "skipped", "message": "测试已跳过",
                "test": case.attrib.get("name", ""),
            })
    return totals, items[:MAX_ITEMS]


def parse_vitest_json(raw: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"passed": 0, "failed": 0, "skipped": 0}, []
    totals = data.get("numPassedTests", 0), data.get("numFailedTests", 0), data.get("numPendingTests", 0)
    items = []
    for file_result in data.get("testResults", []):
        for assertion in file_result.get("assertionResults", []):
            if assertion.get("status") not in {"failed", "pending", "skipped"}:
                continue
            failed = assertion.get("status") == "failed"
            items.append({
                "file": file_result.get("name", ""), "line": None, "col": None,
                "severity": "error" if failed else "info",
                "code": assertion.get("status", ""),
                "message": "\n".join(assertion.get("failureMessages", []))[:1000]
                or assertion.get("title", ""), "test": assertion.get("fullName", ""),
            })
    return {"passed": totals[0], "failed": totals[1], "skipped": totals[2]}, items[:MAX_ITEMS]


def _item(file: str, line: int | None, col: int | None, message: str, code: str = "") -> dict[str, Any]:
    return {"file": file, "line": line, "col": col, "severity": "error", "code": code, "message": message}


def _run(command: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str, int]:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
        return completed.returncode, (completed.stdout + completed.stderr)[-500_000:], int((time.monotonic() - started) * 1000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc), int((time.monotonic() - started) * 1000)


async def run_checks(root: str, kind: str = "all", paths: list[str] | None = None) -> list[dict[str, Any]]:
    base = Path(root).expanduser().resolve()
    if kind not in {"lint", "typecheck", "test", "all"}:
        raise ValueError("kind must be lint, typecheck, test, or all")
    if not base.is_dir():
        return [_result(kind, "atlas", 0, [_item(str(base), None, None, "项目目录不存在")], failed=1)]
    selected = []
    for value in paths or []:
        path = (base / value).resolve()
        if not path.is_relative_to(base):
            raise ValueError("paths must stay inside the workspace")
        selected.append(str(path.relative_to(base)))
    async def execute(command: list[str], tool: str, parser: Any = None) -> dict[str, Any]:
        code, output, duration = await asyncio.to_thread(_run, command, base)
        counts = {"passed": int(code == 0), "failed": int(code != 0), "skipped": 0}
        if parser:
            parsed = parser(output)
            if isinstance(parsed, tuple):
                counts, items = parsed
            else:
                items = parsed
                counts = {"passed": int(code == 0), "failed": len(items) if items else int(code != 0), "skipped": 0}
        else:
            items = [] if code == 0 else [_item("", None, None, output[-3000:])]
        return _result(kind, tool, duration, items, **counts)

    results = []
    is_python = (base / "pyproject.toml").exists() or (base / "setup.cfg").exists()
    is_node = (base / "package.json").exists()
    if is_python:
        py = str(Path(os.sys.executable))
        config_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (base / "pyproject.toml", base / "setup.cfg") if p.exists())
        if kind in {"lint", "all"} and (shutil.which("ruff") or (base / ".venv" / "Scripts" / "ruff.exe").exists()):
            cmd = ["ruff", "check", *(selected or ["."]), "--output-format=json"]
            results.append(await execute(cmd, "ruff", parse_ruff_json))
        if kind in {"typecheck", "all"} and (
            "[tool.mypy]" in config_text or "[mypy]" in config_text
        ):
            cmd = [py, "-m", "mypy", *(selected or ["."])]
            results.append(await execute(cmd, "mypy"))
        if kind in {"test", "all"}:
            fd, junit = tempfile.mkstemp(prefix="atlas-checks-", suffix=".xml")
            os.close(fd)
            try:
                results.append(await execute([py, "-m", "pytest", "-p", "no:cacheprovider", "--basetemp", str(Path(tempfile.gettempdir()) / "atlas-checks-pytest"), "--junitxml", junit, *(selected or [])], "pytest", lambda _raw: parse_pytest_junit(junit)))
            finally:
                Path(junit).unlink(missing_ok=True)
    if is_node:
        try:
            package = json.loads((base / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            package = {}
        scripts = package.get("scripts", {})
        if kind in {"lint", "all"} and scripts.get("lint"):
            cmd = ["npm", "run", "lint", "--", "--format", "json"]
            results.append(await execute(cmd, "eslint", lambda raw: _parse_eslint(raw)))
        if kind in {"typecheck", "all"}:
            if scripts.get("typecheck"):
                results.append(await execute(["npm", "run", "typecheck"], "tsc", parse_tsc_output))
            elif (base / "node_modules" / ".bin" / "tsc").exists():
                results.append(await execute(["npx", "tsc", "--noEmit"], "tsc", parse_tsc_output))
        if kind in {"test", "all"} and scripts.get("test"):
            test_tool = "vitest" if "vitest" in str(scripts["test"]) else "jest" if "jest" in str(scripts["test"]) else "npm-test"
            cmd = ["npm", "run", "test", "--", "--reporter=json"] if test_tool == "vitest" else ["npm", "test", "--", "--reporters=json"] if test_tool == "jest" else ["npm", "run", "test"]
            results.append(await execute(cmd, test_tool, parse_vitest_json if test_tool in {"vitest", "jest"} else None))
    return results or [_result(kind, "atlas", 0, [], passed=0, failed=0, skipped=0, note="未找到适用的检查工具")]


def _parse_eslint(raw: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [{"file": m.get("filePath", ""), "line": m.get("line"), "col": m.get("column"),
             "severity": "error" if m.get("severity") == 2 else "warning", "code": m.get("ruleId") or "",
             "message": m.get("message", "")} for row in rows for m in row.get("messages", [])][:MAX_ITEMS]


def _result(kind: str, tool: str, duration: int, items: list[dict[str, Any]], **counts: Any) -> dict[str, Any]:
    return {"kind": kind, "tool": tool, "passed": counts.get("passed", 0), "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0), "duration_ms": duration, "items": items[:MAX_ITEMS],
            **({"note": counts["note"]} if "note" in counts else {})}
