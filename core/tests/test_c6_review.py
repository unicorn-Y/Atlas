"""W3 / P2 /review focused tests (ATLAS-C6 contract section 5)."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from atlas.review import engine
from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


# ---------------------------------------------------------------------------
# Git fixtures ----------------------------------------------------------------


def _git(ws: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "tester@example.com")
    _git(tmp_path, "config", "user.name", "Tester")
    (tmp_path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


# ---------------------------------------------------------------------------
# is_review_request / parse_scope --------------------------------------------


def test_is_review_request_accepts_variants_and_rejects_lookalikes():
    assert engine.is_review_request("/review")
    assert engine.is_review_request("  /review  ")
    assert engine.is_review_request("/review branch feature-x")
    assert engine.is_review_request("/review　重点看鉴权")  # full-width space
    assert engine.is_review_request("/Review 重点")
    assert engine.is_review_request("/审查")
    assert not engine.is_review_request("/reviews")
    assert not engine.is_review_request("review my code please")
    assert not engine.is_review_request("")


def test_parse_scope_working_tree_branch_commit_and_prompt():
    assert engine.parse_scope("/review") == {
        "scope": "working_tree", "ref": None, "user_prompt": ""}
    assert engine.parse_scope("/review   重点看鉴权  ") == {
        "scope": "working_tree", "ref": None, "user_prompt": "重点看鉴权"}
    assert engine.parse_scope("/review branch feature/login 带上看鉴权") == {
        "scope": "branch", "ref": "feature/login", "user_prompt": "带上看鉴权"}
    assert engine.parse_scope("/review commit 6df1add") == {
        "scope": "commit", "ref": "6df1add", "user_prompt": ""}


# ---------------------------------------------------------------------------
# collect_diff ----------------------------------------------------------------


def test_collect_diff_working_tree(git_repo: Path):
    (git_repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    (git_repo / "notes.txt").write_text("untracked\n", encoding="utf-8")
    result = engine.collect_diff(str(git_repo), {"scope": "working_tree"})
    assert result["scope_label"] == "当前未提交改动"
    assert "-print('v1')" in result["diff_text"] and "+print('v2')" in result["diff_text"]
    assert result["untracked"] == ["notes.txt"]
    assert "app.py" in result["stat"]
    assert result["truncated"] is False


def test_collect_diff_branch_against_main(git_repo: Path):
    _git(git_repo, "checkout", "-b", "feature")
    (git_repo / "app.py").write_text("print('feature')\n", encoding="utf-8")
    _git(git_repo, "commit", "-am", "feature change")
    _git(git_repo, "checkout", "main")
    result = engine.collect_diff(str(git_repo), {"scope": "branch", "ref": "feature"})
    assert result["scope_label"] == "分支 feature 相对 main"
    assert "+print('feature')" in result["diff_text"]
    assert result["stat"].strip()


def test_collect_diff_commit(git_repo: Path):
    (git_repo / "app.py").write_text("print('committed')\n", encoding="utf-8")
    _git(git_repo, "commit", "-am", "second")
    sha = subprocess.run(["git", "-C", str(git_repo), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    result = engine.collect_diff(str(git_repo), {"scope": "commit", "ref": sha})
    assert result["scope_label"] == f"提交 {sha}"
    assert "+print('committed')" in result["diff_text"]


def test_collect_diff_rejects_non_git_and_unknown_refs(tmp_path_factory, git_repo: Path):
    plain = tmp_path_factory.mktemp("plain")
    with pytest.raises(ValueError, match="Git 仓库"):
        engine.collect_diff(str(plain), {"scope": "working_tree"})
    with pytest.raises(ValueError):
        engine.collect_diff(str(git_repo), {"scope": "branch", "ref": "no-such-branch"})
    with pytest.raises(ValueError):
        engine.collect_diff(str(git_repo), {"scope": "commit", "ref": "deadbeef"})


def test_collect_diff_truncates_long_diff(git_repo: Path):
    (git_repo / "big.txt").write_text("\n".join(f"line {i}" for i in range(3000)), encoding="utf-8")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "big")
    _git(git_repo, "checkout", "-b", "bigfeature")
    (git_repo / "big.txt").write_text("\n".join(f"changed {i}" for i in range(3000)), encoding="utf-8")
    _git(git_repo, "commit", "-am", "big change")
    _git(git_repo, "checkout", "main")
    result = engine.collect_diff(str(git_repo), {"scope": "branch", "ref": "bigfeature"})
    assert result["truncated"] is True
    assert result["diff_text"].count("\n") <= engine.MAX_DIFF_LINES + 3
    assert "已截断" in result["diff_text"]


# ---------------------------------------------------------------------------
# Prompts ---------------------------------------------------------------------


def test_build_child_goal_contains_briefing_contract():
    scope_result = {
        "scope": "working_tree", "ref": None, "scope_label": "当前未提交改动",
        "diff_text": "-old\n+new", "stat": " app.py | 2 +-", "untracked": ["new.py"],
        "truncated": False,
    }
    goal = engine.build_child_goal(scope_result, "重点看鉴权")
    for fragment in ("只读", "review_command", "JSON 数组", "blocker", "major", "minor",
                     "空数组", "evidence", "重点看鉴权", "new.py", "+new", "suggested_fix"):
        assert fragment in goal, fragment


def test_build_dispatch_prompt_instructs_delegate_and_submit():
    scope_result = {
        "scope": "branch", "ref": "feature", "scope_label": "分支 feature 相对 main",
        "diff_text": "+x", "stat": "", "truncated": False,
    }
    prompt = engine.build_dispatch_prompt(scope_result, "")
    assert "delegate_task" in prompt and "submit_findings" in prompt
    assert "分支 feature 相对 main" in prompt
    assert 'scope="branch"' in prompt
    assert "审查员简报" in prompt and "+x" in prompt
    assert "没有发现问题" in prompt


# ---------------------------------------------------------------------------
# parse_findings --------------------------------------------------------------


def test_parse_findings_valid_invalid_empty():
    raw = """
审查完成，结论如下。
```json
[{"file": "src/app.py", "line": "12", "range": [12, 20], "severity": "MAJOR",
  "title": "空指针风险", "explanation": "可能为 None", "evidence": "x = None",
  "suggested_fix": "判空"},
 {"file": "", "title": "缺文件", "explanation": "x"},
 {"file": "b.py", "title": "", "explanation": "y"},
 "junk",
 {"file": "c.py", "line": null, "range": [1], "severity": "catastrophic",
  "title": "小问题", "explanation": "e"}]
```
"""
    findings = engine.parse_findings(raw)
    assert len(findings) == 2
    first = findings[0]
    assert first["file"] == "src/app.py"
    assert first["line"] == 12 and first["range"] == [12, 20]
    assert first["severity"] == "major"
    assert first["evidence"] == "x = None" and first["suggested_fix"] == "判空"
    second = findings[1]
    assert second["severity"] == "minor"
    assert second["line"] is None and second["range"] is None
    assert engine.parse_findings("") == []
    assert engine.parse_findings("没有发现任何问题。") == []
    assert engine.parse_findings("[]") == []


def test_parse_findings_tolerates_trailing_commas_and_plain_array():
    findings = engine.parse_findings('前缀文字 [{"file":"a.py","title":"t","explanation":"e",},] 后缀')
    assert len(findings) == 1
    assert findings[0]["file"] == "a.py"
    assert findings[0]["severity"] == "minor"


# ---------------------------------------------------------------------------
# review_command --------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "rm -rf build", "git push origin main", "echo hi > out.txt",
    "git reset --hard HEAD~1", "npm install left-pad", "pip install requests",
    "chmod +x run.sh", "git clean -fd", "del file.txt", "git checkout -- app.py",
])
def test_review_command_refuses_write_patterns(command: str):
    with pytest.raises(ValueError, match="只读|拒绝"):
        engine.run_review_command(command, cwd=str(Path.cwd()))


@pytest.mark.parametrize("command", ["git status", "git log --oneline -5", "ls"])
def test_check_command_read_only_allows_reads(command: str):
    assert engine.check_command_read_only(command) is None


def test_review_command_runs_git_status_and_python(git_repo: Path):
    data, text = engine.run_review_command("git status --porcelain", cwd=str(git_repo))
    assert data["returncode"] == 0 and "truncated" in data
    _data, text = engine.run_review_command(f'"{sys.executable}" -c "print(1)"', cwd=str(git_repo))
    assert "(exit code 0)" in text and "\n1" in text


def test_review_command_timeout_and_truncation(git_repo: Path):
    with pytest.raises(ValueError, match="超时"):
        engine.run_review_command(
            f'"{sys.executable}" -c "import time; time.sleep(5)"', cwd=str(git_repo), timeout=1)
    data, text = engine.run_review_command(
        f'"{sys.executable}" -c "print(\'A\' * 20000)"', cwd=str(git_repo))
    assert data["truncated"] is True
    assert len(text) < engine.COMMAND_OUTPUT_CHARS + 200
    assert "已截断" in text


def test_review_command_requires_existing_cwd(tmp_path: Path):
    with pytest.raises(ValueError, match="cwd 目录不存在"):
        engine.run_review_command("git status", cwd=str(tmp_path / "missing"))


# ---------------------------------------------------------------------------
# submit_findings -------------------------------------------------------------

_FINDING = {
    "file": "src/app.py", "line": 12, "range": None, "severity": "major",
    "title": "空指针风险", "explanation": "可能为 None", "evidence": "x = None",
    "suggested_fix": "判空",
}


def _fake_ctx(workspace: str) -> SimpleNamespace:
    return SimpleNamespace(event_queue=asyncio.Queue(), workspace=workspace, conversation_id="c6")


@pytest.mark.asyncio
async def test_submit_findings_emits_queue_event(tmp_path: Path):
    ctx = _fake_ctx(str(tmp_path))
    data, text = await engine.handle_agent_tool(
        "submit_findings", {"findings_json": json.dumps([_FINDING]),
                            "scope": "working_tree", "scope_label": "当前未提交改动"}, ctx)
    assert "已记录 1 条发现" in text
    event = ctx.event_queue.get_nowait()
    assert event["type"] == "review.findings"
    assert event["data"]["scope"] == "working_tree"
    assert event["data"]["scope_label"] == "当前未提交改动"
    assert event["data"]["workspace"] == str(tmp_path)
    assert event["data"]["findings"] == [engine._normalize_finding(_FINDING)]


@pytest.mark.asyncio
async def test_submit_findings_empty_array_still_emits(tmp_path: Path):
    ctx = _fake_ctx(str(tmp_path))
    _data, text = await engine.handle_agent_tool("submit_findings", {"findings_json": "[]"}, ctx)
    assert "已记录 0 条发现" in text and "没有发现问题" in text
    event = ctx.event_queue.get_nowait()
    assert event["data"]["findings"] == []
    assert event["data"]["scope"] == "working_tree"


@pytest.mark.asyncio
async def test_registry_handler_emits_via_active_context(tmp_path: Path):
    from atlas.engine import tool_registry

    ctx = _fake_ctx(str(tmp_path))
    loop = asyncio.get_running_loop()
    tool_registry._active_contexts["c6-registry"] = (object(), ctx, loop)
    try:
        handler = engine._make_registry_handler("submit_findings")
        result = await asyncio.to_thread(
            handler, {"findings_json": json.dumps([_FINDING])}, session_id="c6-registry")
        assert "已记录 1 条发现" in result
        event = ctx.event_queue.get_nowait()
        assert event["type"] == "review.findings" and len(event["data"]["findings"]) == 1
        refused = await asyncio.to_thread(
            engine._make_registry_handler("review_command"),
            {"command": "rm -rf x"}, session_id="c6-registry")
        assert "只读" in refused
    finally:
        tool_registry._active_contexts.pop("c6-registry", None)


# ---------------------------------------------------------------------------
# Registration + route ---------------------------------------------------------


@pytest.mark.asyncio
async def test_register_review_tools_and_schema_route():
    from fastapi import FastAPI
    import httpx
    from tools.registry import registry

    engine.register_review_tools()
    engine.register_review_tools()  # idempotent
    assert registry.get_entry("review_command") is not None
    assert registry.get_entry("submit_findings") is not None

    app = FastAPI()
    engine.register_review_routes(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://atlas-test") as client:
        response = await client.get("/api/review/schema")
    assert response.status_code == 200
    payload = response.json()
    assert payload["severities"] == ["blocker", "major", "minor"]
    assert payload["finding"]["required"] == ["file", "severity", "title", "explanation"]


# ---------------------------------------------------------------------------
# Child-runtime posture through the real loop ----------------------------------
#
# These scripts call the review tools by name, so tool_search deferral is switched
# off in the test Hermes home (production routes deferred tools through the
# tool_call bridge into the same registry entries / dispatch branches).

_EAGER_TOOLS_CONFIG = "api_max_retries: 1\ntools:\n  tool_search:\n    enabled: off"


@pytest.mark.asyncio
async def test_reviewer_child_write_tool_refused(tmp_path: Path, monkeypatch):
    target = tmp_path / "forbidden.txt"
    events, requests, _ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("write_file", {"path": str(target), "content": "nope"}),
        Text("blocked"),
    ], hermes_config=_EAGER_TOOLS_CONFIG, permission_mode="read_only",
        tool_allow=["read_file", "search_files", "review_command"])
    assert not target.exists()
    tool_rows = [row for row in requests[1]["messages"] if row["role"] == "tool"]
    assert tool_rows and any(("只读" in str(row.get("content")) or "不允许" in str(row.get("content")))
                             for row in tool_rows)


@pytest.mark.asyncio
async def test_reviewer_child_review_command_allowed(git_repo: Path, monkeypatch):
    events, requests, _ctx = await run_script(git_repo, monkeypatch, [
        ToolCall("review_command", {"command": "git status --porcelain"}),
        Text("checked"),
    ], hermes_config=_EAGER_TOOLS_CONFIG, permission_mode="read_only",
        tool_allow=["read_file", "search_files", "review_command"])
    tool_rows = [row for row in requests[1]["messages"] if row["role"] == "tool"]
    assert tool_rows and "exit code 0" in str(tool_rows[-1]["content"])


@pytest.mark.asyncio
async def test_parent_review_flow_delegate_then_submit(tmp_path: Path, monkeypatch):
    from unittest.mock import AsyncMock

    child_text = (
        "审查完成。发现 1 个问题：\n"
        + json.dumps([_FINDING], ensure_ascii=False)
    )
    delegate = AsyncMock(return_value={"status": "completed", "result": child_text, "evidence": []})

    def configure(agent):
        agent._delegation = SimpleNamespace(delegate_task=delegate)

    briefing_goal = engine.build_child_goal(
        {"scope": "working_tree", "ref": None, "scope_label": "当前未提交改动",
         "diff_text": "+print('v2')", "stat": " app.py | 2 +-", "truncated": False}, "")
    findings_json = json.dumps([_FINDING], ensure_ascii=False)
    events, requests, ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("delegate_task", {"goal": briefing_goal}),
        ToolCall("submit_findings", {"findings_json": findings_json,
                                     "scope": "working_tree",
                                     "scope_label": "当前未提交改动"}),
        Text("审查总结：major 1 条。"),
    ], configure_agent=configure, hermes_config=_EAGER_TOOLS_CONFIG,
        tool_allow=["delegate_task", "submit_findings"])

    assert delegate.await_count == 1
    # The child briefing (goal) carries the read-only reviewer contract.
    assert "只读" in str(delegate.call_args.args[0])
    child_options = delegate.call_args.kwargs["atlas_options"]
    assert child_options["tool_allow"] == ["delegate_task", "submit_findings"]
    # submit_findings emitted the review.findings queue event with the 2.2 schema.
    queue_events = []
    while not ctx.event_queue.empty():
        queue_events.append(ctx.event_queue.get_nowait())
    findings_events = [item for item in queue_events if item.get("type") == "review.findings"]
    assert len(findings_events) == 1
    data = findings_events[0]["data"]
    assert data["scope"] == "working_tree"
    assert data["scope_label"] == "当前未提交改动"
    assert data["workspace"] == str(tmp_path)
    assert data["findings"][0]["severity"] == "major"
    assert data["findings"][0]["file"] == "src/app.py"
    # The parent saw the Chinese confirmation on the tool result.
    tool_rows = [row for row in requests[2]["messages"] if row["role"] == "tool"]
    assert any("已记录 1 条发现" in str(row.get("content")) for row in tool_rows)
