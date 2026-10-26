"""U47 integration checks: CLI routing, annual ledger API, and live Atlas UI over CDP."""

from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import click.testing
from websockets.sync.client import connect

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core"))


class CDP:
    def __init__(self, socket_url: str) -> None:
        self.socket = connect(socket_url, origin="http://127.0.0.1:9336", open_timeout=5)
        self.sequence = 0

    def close(self) -> None:
        self.socket.close()

    def reconnect_after_reload(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass
        with urllib.request.urlopen("http://127.0.0.1:9336/json/list", timeout=5) as response:
            targets = json.loads(response.read().decode("utf-8", errors="replace"))
        target = next((item for item in targets if item.get("type") == "page" and "/" in item.get("url", "")), None)
        if not target:
            raise AssertionError("Atlas renderer page was not found after reload")
        self.socket = connect(target["webSocketDebuggerUrl"], origin="http://127.0.0.1:9336", open_timeout=5)
        self.sequence = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sequence += 1
        command_id = self.sequence
        self.socket.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        while True:
            packet = json.loads(self.socket.recv(timeout=10))
            if packet.get("id") == command_id:
                if "error" in packet:
                    raise AssertionError(f"CDP {method} error: {packet['error']}")
                return packet.get("result", {})

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
            "userGesture": True, "timeout": 10_000,
        })
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise AssertionError(remote.get("description", "JavaScript evaluation failed"))
        return remote.get("value")


def wait_for(cdp: CDP, predicate: str, timeout: float = 10) -> Any:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = cdp.evaluate(predicate)
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for browser condition: {predicate}")


def click_element(cdp: CDP, selector_expression: str) -> None:
    point = cdp.evaluate(
        f"(() => {{ const e=({selector_expression}); if(!e) return null; "
        "const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()"
    )
    if not point:
        raise AssertionError(f"UI element not found for click: {selector_expression}")
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", **point})
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", **point, "button": "left", "clickCount": 1})
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **point, "button": "left", "clickCount": 1})


def fill_input(cdp: CDP, selector_expression: str, value: str) -> None:
    click_element(cdp, selector_expression)
    cdp.call("Input.insertText", {"text": value})


def check_cli_desktop_commands() -> None:
    from atlas import cli

    runner = click.testing.CliRunner()
    assert runner.invoke(cli.main, ["desktop", "--help"]).exit_code == 0
    assert runner.invoke(cli.main, ["gui", "--help"]).exit_code == 0
    fake_cwd = REPO_ROOT / "frontend"
    with patch.object(cli, "_desktop_dev_command", return_value=(["electron.exe", "electron.js"], fake_cwd)), \
            patch.object(cli, "_packaged_desktop_executable", return_value=None), \
            patch.object(cli, "_vite_is_listening", return_value=True), \
            patch.object(cli.subprocess, "Popen") as popen:
        result = runner.invoke(cli.main, ["gui"])
        assert result.exit_code == 0, result.output
        assert "已请求启动 Atlas 桌面端" in result.output
        assert popen.call_args.args[0] == ["electron.exe", "electron.js"]
        assert popen.call_args.kwargs["env"]["VITE_DEV_SERVER_URL"] == "http://127.0.0.1:5173"
    packaged = Path("C:/Program Files/Atlas/Atlas.exe")
    with patch.object(cli, "_desktop_dev_command", return_value=None), \
            patch.object(cli, "_packaged_desktop_executable", return_value=packaged), \
            patch.object(cli.subprocess, "Popen") as popen:
        result = runner.invoke(cli.main, ["desktop"])
        assert result.exit_code == 0, result.output
        assert popen.call_args.args[0] == [str(packaged)]
        assert popen.call_args.kwargs["cwd"] == str(packaged.parent)
    with patch.object(cli, "_desktop_dev_command", return_value=None), \
            patch.object(cli, "_packaged_desktop_executable", return_value=None):
        result = runner.invoke(cli.main, ["desktop"])
        assert result.exit_code != 0 and "无法启动 Atlas 桌面端" in result.output


def read_json_url(url: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", errors="replace"))


def check_annual_api() -> None:
    port = os.environ.get("ATLAS_PORT", "8765")
    base = f"http://127.0.0.1:{port}"
    status, report = read_json_url(f"{base}/api/u4/thinkback")
    assert status == 200, report
    assert len(report["months"]) == 12
    assert report["year"] == int(report["start_date"][:4])
    if report["data_status"] == "empty":
        assert report["coverage_start"] is None and report["coverage_end"] is None
        assert all(not month["has_records"] for month in report["months"])
    else:
        assert report["coverage_start"] and report["coverage_end"]
        assert sum(month["runs"] for month in report["months"]) == report["usage"]["runs"]
        assert report["top_model"]
    status, empty_year = read_json_url(f"{base}/api/u4/thinkback?year=2000")
    assert status == 200 and empty_year["data_status"] == "empty"
    assert empty_year["coverage_start"] is None and empty_year["coverage_end"] is None
    assert all(not month["has_records"] for month in empty_year["months"])
    status, invalid = read_json_url(f"{base}/api/u4/thinkback?year=2099")
    assert status == 422 and "year must be between" in invalid["detail"]


def check_kernel_continuation_classifier() -> None:
    from atlas.kernel.loop import _is_unfulfilled_action_intent
    from real_model_check import AttemptResult, _report_failure

    assert _is_unfulfilled_action_intent("我现在就来生成这份文档。")
    assert _is_unfulfilled_action_intent("接下来我会创建报告。")
    assert _is_unfulfilled_action_intent("I'll create the document now.")
    assert not _is_unfulfilled_action_intent("文档已生成并保存。")
    assert not _is_unfulfilled_action_intent("我现在就来生成这份文档。文档已生成。")
    diagnostic = io.StringIO()
    with redirect_stdout(diagnostic):
        _report_failure("U47 diagnostic fixture", 1, AttemptResult(
            False, detail="HTTP status 503", exit_code=503,
            stderr_tail="api_key=never-show", run_log_path="fixture/run.jsonl",
            last_run_error_event='{"event":"model_error","status":503}',
        ), since=10**12)
    rendered = diagnostic.getvalue()
    assert "failure_category=HTTP 503" in rendered and "exit_code=503" in rendered
    assert "stderr_tail=api_key=[REDACTED]" in rendered
    assert "last_run_error_event=" in rendered and "run_log_path=fixture/run.jsonl" in rendered
    assert "never-show" not in rendered


def _continuation_events_since(since: float) -> int:
    try:
        from atlas.logs import LOG_DIR

        paths = [path for path in (LOG_DIR / "runs").rglob("*.jsonl")
                 if path.is_file() and path.stat().st_mtime >= since - 2]
    except Exception:
        return 0
    count = 0
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    if json.loads(line).get("event") == "unfulfilled_action_continuation":
                        count += 1
                except (json.JSONDecodeError, AttributeError):
                    continue
        except OSError:
            continue
    return count


def check_live_action_intent_five_runs() -> None:
    """Repeat the U22 document request five times against the configured real model."""
    from real_model_check import (
        classify_failure, latest_run_error_event, latest_run_log_path, redact_diagnostic,
    )

    prompt = (
        "Use create_document to create u22-live-template.docx in the current workspace. "
        "Make a concise project decision brief with a title, executive summary, assumptions, "
        "risks, and three owner/action rows. Use concrete sample wording and no placeholders. "
        "After creating the file, reply with a short confirmation."
    )
    command = [
        sys.executable, "-m", "atlas.cli", "exec", "--model", "deepseek-v4.1-flash",
        "--approve-writes", prompt,
    ]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        part for part in (str(REPO_ROOT / "core"), os.environ.get("PYTHONPATH", "")) if part
    )}
    successes = 0
    recovery_events = 0
    with tempfile.TemporaryDirectory(prefix="atlas-u47-u22-") as temporary:
        workspace = Path(temporary).resolve()
        target = workspace / "u22-live-template.docx"
        for sample in range(1, 6):
            target.unlink(missing_ok=True)
            started = time.time()
            exit_code: int | str
            stderr = ""
            try:
                result = subprocess.run(
                    [*command[:-1], "--workspace", str(workspace), command[-1]],
                    cwd=REPO_ROOT, env=environment, capture_output=True,
                    encoding="utf-8", errors="replace", timeout=300, check=False,
                )
                exit_code, stderr = result.returncode, result.stderr or ""
            except subprocess.TimeoutExpired as exc:
                exit_code = "timeout"
                raw = exc.stderr or ""
                stderr = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            except OSError as exc:
                exit_code, stderr = "spawn-error", str(exc)
            recovery_events += _continuation_events_since(started)
            if exit_code == 0 and target.is_file() and target.stat().st_size:
                successes += 1
                print(f"PASS U47 U22 real-model sample {sample}/5: document created", flush=True)
                continue
            category = classify_failure(stderr, "")
            print(
                f"FAIL U47 U22 real-model sample {sample}/5: exit_code={exit_code}; "
                f"failure_category={category}; run_log_path={latest_run_log_path(started)}; "
                f"stderr_tail={redact_diagnostic(stderr)}; "
                f"last_run_error_event={latest_run_error_event(started)}",
                flush=True,
            )
    print(f"U47 U22 five-run sample: {successes}/5 succeeded; "
          f"auto-continuation observed {recovery_events} time(s)", flush=True)
    assert successes == 5, f"U22 real-model request succeeded {successes}/5 times"


def check_live_ui() -> None:
    status, targets = read_json_url("http://127.0.0.1:9336/json/list")
    assert status == 200
    target = next((item for item in targets if item.get("type") == "page" and "/" in item.get("url", "")), None)
    assert target, "Atlas renderer page was not found on CDP 9336"
    cdp = CDP(target["webSocketDebuggerUrl"])
    test_title = f"U47验收-{int(time.time())}"
    title = json.dumps(test_title, ensure_ascii=False)
    page_button = f"Array.from(document.querySelectorAll('button[title]')).find(e=>e.title==={title})"
    section_present = f"Array.from(document.querySelectorAll('section[aria-label]')).some(e=>e.getAttribute('aria-label')==='自定义页面：'+{title})"
    restore_todos = False
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        restore_todos = bool(cdp.evaluate("Boolean(document.querySelector('div.fixed.z-40')?.innerText.includes('我的待办'))"))
        if restore_todos:
            click_element(cdp, "document.querySelector('div.fixed.z-40 button[title=\"折叠\"]')")

        # Custom page: create through the native dialog, edit content, reload, and delete.
        click_element(cdp, "document.querySelector('button[aria-label=\"新建自定义页面\"]')")
        wait_for(cdp, "Boolean(document.querySelector('[role=dialog] input'))")
        fill_input(cdp, "document.querySelector('[role=dialog] input')", test_title)
        click_element(cdp, "document.querySelector('[role=dialog] button[type=submit]')")
        wait_for(cdp, f"Boolean({page_button})")
        click_element(cdp, page_button)
        edit_button = "Array.from(document.querySelectorAll('button')).find(e=>e.textContent.trim()==='编辑页面')"
        wait_for(cdp, f"Boolean({edit_button})")
        click_element(cdp, edit_button)
        wait_for(cdp, "Boolean(document.querySelector('textarea[aria-label=\"页面内容（Markdown）\"]'))")
        fill_input(cdp, "document.querySelector('textarea[aria-label=\"页面内容（Markdown）\"]')", "# U47 Live UI\n\n内容持久化检查")
        finish_edit = "Array.from(document.querySelectorAll('button')).find(e=>e.textContent.trim()==='完成编辑')"
        click_element(cdp, finish_edit)
        wait_for(cdp, f"({section_present}) && Array.from(document.querySelectorAll('section[aria-label]')).find(e=>e.getAttribute('aria-label')==='自定义页面：'+{title}).innerText.includes('内容持久化检查')")
        cdp.call("Page.reload")
        cdp.reconnect_after_reload()
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        wait_for(cdp, "document.readyState === 'complete'")
        wait_for(cdp, f"Boolean({page_button})")
        click_element(cdp, page_button)
        wait_for(cdp, f"({section_present}) && Array.from(document.querySelectorAll('section[aria-label]')).find(e=>e.getAttribute('aria-label')==='自定义页面：'+{title}).innerText.includes('内容持久化检查')")
        page_menu = json.dumps(test_title + " 页面选项", ensure_ascii=False)
        click_element(cdp, f"Array.from(document.querySelectorAll('button[aria-label]')).find(e=>e.getAttribute('aria-label')==={page_menu})")
        wait_for(cdp, "[...document.querySelectorAll('[role=menuitem]')].some(e=>e.textContent.trim()==='删除页面')")
        click_element(cdp, "[...document.querySelectorAll('[role=menuitem]')].find(e=>e.textContent.trim()==='删除页面')")
        wait_for(cdp, "Boolean(document.querySelector('[role=dialog] button'))")
        click_element(cdp, "[...document.querySelectorAll('[role=dialog] button')].find(e=>e.textContent.trim()==='删除页面')")
        wait_for(cdp, f"!({page_button})")

        # Zoom presets persist and the compact user setting is restored after the check.
        click_element(cdp, "document.querySelector('button[aria-label^=\"侧栏缩放\"]')")
        wait_for(cdp, "[...document.querySelectorAll('[role=menuitem]')].some(e=>e.textContent.includes('紧凑'))")
        click_element(cdp, "[...document.querySelectorAll('[role=menuitem]')].find(e=>e.textContent.includes('紧凑 · 218 px'))")
        wait_for(cdp, "localStorage.getItem('atlas.preference.sidebar-zoom')==='compact'")
        compact_width = "Boolean(document.querySelector('aside > div[style*=\"width\"]')) && Math.abs(parseFloat(getComputedStyle(document.querySelector('aside > div')).width)-218)<1"
        wait_for(cdp, compact_width)
        cdp.call("Page.reload")
        cdp.reconnect_after_reload()
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        wait_for(cdp, f"document.readyState === 'complete' && localStorage.getItem('atlas.preference.sidebar-zoom')==='compact' && ({compact_width})")
        click_element(cdp, "document.querySelector('button[aria-label^=\"侧栏缩放\"]')")
        wait_for(cdp, "[...document.querySelectorAll('[role=menuitem]')].some(e=>e.textContent.includes('默认 · 238 px'))")
        click_element(cdp, "[...document.querySelectorAll('[role=menuitem]')].find(e=>e.textContent.includes('默认 · 238 px'))")
        wait_for(cdp, "localStorage.getItem('atlas.preference.sidebar-zoom')==='default'")

        # Annual review is a live renderer route backed by the real annual endpoint.
        click_element(cdp, "document.querySelector('button[aria-label=\"更多页面\"]')")
        wait_for(cdp, "[...document.querySelectorAll('[role=menuitem]')].some(e=>e.textContent.trim()==='年度回顾')")
        click_element(cdp, "[...document.querySelectorAll('[role=menuitem]')].find(e=>e.textContent.trim()==='年度回顾')")
        timeline = wait_for(cdp, "document.querySelector('[aria-label=\"年度时间线\"]')?.innerText.includes('播放回顾') && document.querySelector('[aria-label=\"年度使用回顾\"]')?.innerText.includes('账本首末记录：')")
        assert timeline
        if cdp.evaluate("document.querySelector('[aria-label=\"年度时间线\"] button[aria-label=\"播放年度回顾\"]') && !document.querySelector('[aria-label=\"播放年度回顾\"]')?.disabled"):
            click_element(cdp, "document.querySelector('button[aria-label=\"播放年度回顾\"]')")
            wait_for(cdp, "Boolean(document.querySelector('button[aria-label=\"暂停回顾播放\"]'))")
            click_element(cdp, "document.querySelector('button[aria-label=\"暂停回顾播放\"]')")
    finally:
        if restore_todos and cdp.evaluate("Boolean(document.querySelector('div.fixed.z-40[title^=\"展开待办\"]'))"):
            click_element(cdp, "document.querySelector('div.fixed.z-40[title^=\"展开待办\"]')")
        cdp.close()


def main() -> int:
    check_cli_desktop_commands()
    check_annual_api()
    check_kernel_continuation_classifier()
    check_live_ui()
    check_live_action_intent_five_runs()
    print("U47 CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
