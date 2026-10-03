"""C6 主链端到端验收（任务书 §7 E2E）。

一条 fake-model 主链串起本波三条能力：代码 workspace → 编辑引入错误（LSP 新诊断
事件 + 工具结果中文报告）→ `/review` 派只读审查员（review.findings 事件）→ 普通消息
修复（诊断清零、不再有事件）。全程真实代码路径（WebSocket → run → 工具 → 子代理），
只有模型和 LSP server 是假的。

后端根目录放在 ``D:\\Atlas\\_tmp\\lsp-fixtures`` 下（gitignore 区域）：LSP 工作区门控
只放行 git worktree 内文件，系统 tmp_path 会被拒。harness 复用
``test_c6_lsp_e2e.py`` 的 IsolatedBackend 模式。
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from tests.fakes.fake_llm_provider import Text, ToolCall

from tests.test_c6_lsp_e2e import FIXTURE_BASE, IsolatedBackend  # noqa: F401 — 复用 harness

CLEAN = "alpha = 1\nbeta = 2\n\ndef main():\n    return alpha\n"
BUG_ONE = "alpha = 1\nbeta = 2\n\ndef main():\n    return LSP_BUG\n"

FINDINGS_JSON = json.dumps([{
    "file": "e2e_bug.py", "line": 5, "range": [5, 5], "severity": "blocker",
    "title": "main() 引用了未定义的名称 LSP_BUG",
    "explanation": "return 语句引用了从未定义的 LSP_BUG，调用 main() 必然抛 NameError。",
    "evidence": "return LSP_BUG",
    "suggested_fix": "改回 return alpha。",
}], ensure_ascii=False)


def _git_init_workspace(workspace: Path) -> None:
    """带已提交基线的 git workspace：run 1 的改写对 working-tree diff 可见。"""
    subprocess.run(["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace), "config", "user.email", "c6@example.invalid"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace), "config", "user.name", "C6 E2E"],
                   check=True, capture_output=True)
    (workspace / "e2e_bug.py").write_text(CLEAN, encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "e2e_bug.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace), "commit", "-m", "baseline"], check=True,
                   capture_output=True)


@pytest.fixture()
def chain_root():
    import os
    import shutil

    root = FIXTURE_BASE / f"chain_{uuid.uuid4().hex[:10]}"
    (root / "workspace").mkdir(parents=True)
    _git_init_workspace(root / "workspace")
    yield root
    if os.environ.get("C6_LSP_E2E_KEEP"):
        return
    shutil.rmtree(root, ignore_errors=True)


@pytest_asyncio.fixture
async def chain_backend(chain_root):
    from tests.fakes.fake_llm_provider import FakeLLMServer

    with FakeLLMServer() as fake:
        server = IsolatedBackend(chain_root, fake)
        try:
            await server.ready()
            yield server
        finally:
            await server.close()


@pytest.mark.asyncio
async def test_edit_review_fix_main_chain(chain_backend, chain_root):
    backend = chain_backend
    workspace = chain_root / "workspace"
    target = workspace / "e2e_bug.py"
    conversation = await backend.conversation()

    turns = 0

    def responder(record):
        nonlocal turns
        turns += 1
        if turns == 1:  # run 1：先读后写（防覆盖闸要求见过全文）
            return ToolCall("read_file", {"path": str(target)})
        if turns == 2:
            return ToolCall("write_file", {"path": str(target), "content": BUG_ONE})
        if turns == 3:
            return Text("已写入有问题的版本。")
        if turns == 4:  # run 2 主链第 1 轮：派只读审查员（规划请求走 aux,见下）
            return ToolCall("delegate_task", {
                "goal": (
                    "独立代码审查：当前未提交改动。只读调查。"
                    "最终只输出一个 findings JSON 数组（file/line/range/severity/title/"
                    "explanation/evidence/suggested_fix），没有问题输出 []。"
                ),
                "agent": "general",
                "permission_mode": "read_only",
            })
        if turns == 5:  # 审查员子代理（真实 delegate 链路里它的模型请求打同一个假服务）
            # JSON 用代码围栏包住：引擎的 truncated-stop 守卫会对“≥200 字符且结尾
            # 没有句读”的回复强制续跑一轮，裸 JSON 数组正好命中；那轮续跑会在
            # 子代理上下文里抢走下一轮的 submit_findings（子代理的事件队列会被
            # 委派循环丢弃，review.findings 就到不了运行事件流）。围栏结尾的 ```
            # 在守卫的豁免名单里，子代理一轮回合即干净收尾。
            return Text("```json\n" + FINDINGS_JSON + "\n```")
        if turns == 6:  # 父运行原样提交 findings
            return ToolCall("submit_findings", {
                "findings_json": FINDINGS_JSON,
                "scope": "working_tree",
                "scope_label": "当前未提交改动",
            })
        if turns == 7:
            return Text("审查完成：发现 1 个 blocker 问题，请查看审查卡片。")
        if turns == 8:  # run 3：普通消息回到正常执行入口，先读后修
            return ToolCall("read_file", {"path": str(target)})
        if turns == 9:
            return ToolCall("write_file", {"path": str(target), "content": CLEAN})
        return Text("已修复，main() 恢复返回 alpha。")

    # 派发提示词含编号步骤会触发任务规划器；规划请求不带 tools（aux 类），
    # 不走上面的 responder——在 aux 通道按系统提示词识别并返回计划 JSON。
    original_aux = backend.fake._aux
    plan_json = json.dumps({
        "goal": "审查当前未提交改动",
        "subtasks": [{"id": "review", "title": "派只读审查员审查",
                      "verification": "submit_findings 已提交审查结论"}],
    }, ensure_ascii=False)

    def aux_with_plan(record):
        body = json.dumps(record.get("body") or {}, ensure_ascii=False)
        if "Break the user's multi-step task" in body:
            return Text(plan_json)
        return original_aux(record)

    backend.fake._aux = aux_with_plan
    backend.fake._responder = responder

    backend.fake._responder = responder

    # --- run 1：编辑引入错误 → LSP 新诊断 ------------------------------------
    _, events_1 = await backend.run("把 e2e_bug.py 改成有 bug 的版本",
                                    conversation=conversation, workspace=str(workspace))
    lsp_1 = [e for e in events_1 if e.get("event") == "lsp.diagnostics"]
    assert len(lsp_1) == 1, [e.get("event") for e in events_1]
    assert lsp_1[0]["data"]["count"] == 1
    assert lsp_1[0]["data"]["path"] == "e2e_bug.py"
    assert lsp_1[0]["data"]["diagnostics"][0]["severity"] == "error"

    # --- run 2：/review → 拦截 → 只读审查员 → review.findings ----------------
    _, events_2 = await backend.run("/review", conversation=conversation, workspace=str(workspace))

    # 拦截生效：发往后端的派发提示词包含 delegate/submit 指令（而不是原始 "/review"）
    bodies = json.dumps(backend.fake.main_requests(), ensure_ascii=False)
    assert "delegate_task" in bodies and "submit_findings" in bodies

    findings_events = [e for e in events_2 if e.get("event") == "review.findings"]
    assert len(findings_events) == 1, [e.get("event") for e in events_2]
    data = findings_events[0]["data"]
    assert data["scope"] == "working_tree"
    assert data["scope_label"] == "当前未提交改动"
    assert len(data["findings"]) == 1
    finding = data["findings"][0]
    assert finding["file"] == "e2e_bug.py" and finding["severity"] == "blocker"
    assert finding["line"] == 5 and finding["title"]

    # 真实 delegate 链路跑过：子任务生命周期事件进入了主时间线
    assert any(str(e.get("event", "")).startswith("subtask.") for e in events_2), \
        [e.get("event") for e in events_2]

    # --- run 3：普通消息修复 → 诊断清零，且 0 条不刷事件 ----------------------
    _, events_3 = await backend.run("把 e2e_bug.py 修好",
                                    conversation=conversation, workspace=str(workspace))
    assert not [e for e in events_3 if e.get("event") == "lsp.diagnostics"], \
        [e.get("event") for e in events_3]
    fix_results = [json.dumps(e.get("data", {}).get("result", []), ensure_ascii=False)
                   for e in events_3 if e.get("event") == "tool.completed"
                   and e.get("data", {}).get("name") == "write_file"]
    assert fix_results, [e.get("event") for e in events_3]
    assert "本次编辑引入的诊断" not in fix_results[0]
    assert target.read_text(encoding="utf-8") == CLEAN
