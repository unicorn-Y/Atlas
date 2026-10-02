# Standalone fake LLM for C6 screenshots: content-routed so any request order works.
# Prints the base URL on stdout line 1, then serves until killed.
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))

from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall  # noqa: E402

WORKSPACE = sys.argv[1]

FINDINGS = json.dumps([{
    "file": "demo.py", "line": 3, "range": [3, 3], "severity": "blocker",
    "title": "demo() 返回了未定义的名称 LSP_BUG",
    "explanation": "return 语句引用了从未定义的 LSP_BUG，调用 demo() 会直接抛 NameError。",
    "evidence": "return LSP_BUG",
    "suggested_fix": "改为 return result。",
}], ensure_ascii=False)

PLAN = json.dumps({
    "goal": "完成当前请求",
    "subtasks": [{"id": "s1", "title": "完成当前请求", "verification": "结果已交付"}],
}, ensure_ascii=False)

DEMO_CODE = 'def demo(value):\n    result = value * 2\n    return LSP_BUG\n'


def responder(record):
    body = json.dumps(record.get("body") or {}, ensure_ascii=False)
    if "你是 Atlas 的子任务 Worker" in body:
        return Text(FINDINGS)
    # 顺序重要：submit 之后历史里 subtask_id 仍在，先判「已记录」才能收敛到总结。
    if "已记录" in body:
        return Text("审查完成：发现 1 个 blocker 问题（demo.py 引用未定义的名称），可在审查卡片里逐条处理。")
    if "用户请求审查" in body and "subtask_id" in body:
        return ToolCall("submit_findings", {
            "findings_json": FINDINGS,
            "scope": "working_tree",
            "scope_label": "当前未提交改动",
        })
    if "用户请求审查" in body:
        return ToolCall("delegate_task", {
            "goal": "独立代码审查：当前未提交改动。只读调查，最终只输出 findings JSON 数组。",
            "agent": "general",
            "permission_mode": "read_only",
        })
    # 工具结果 JSON 在请求体里是转义形式，匹配不要带引号。
    # 顺序重要：写完之后历史里两者都在，先判 bytes_written 才能收敛。
    if "bytes_written" in body:
        return Text("已把演示代码写入 demo.py。注意：demo() 里引用了未定义的名称，编辑诊断已经标出来了。")
    if "demo.py" in body and "total_lines" in body:
        return ToolCall("write_file", {"path": WORKSPACE.replace("\\", "/") + "/demo.py", "content": DEMO_CODE})
    if "把演示代码写入" in body:
        return ToolCall("read_file", {"path": WORKSPACE.replace("\\", "/") + "/demo.py"})
    return Text("好的，这一步已经完成。有其他需要随时说。")


with FakeLLMServer(default_text="好的，这一步已经完成。") as fake:
    fake._responder = responder
    original_aux = fake._aux

    def aux(record):
        if "Break the user's multi-step task" in json.dumps(record.get("body") or {}, ensure_ascii=False):
            return Text(PLAN)
        return original_aux(record)

    fake._aux = aux
    print(fake.base_url, flush=True)
    import threading

    threading.Event().wait()
