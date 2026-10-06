"""T06.2 重启接续与副作用对账（UM06）。

四块判据（02_wave_tasks T06.2）：

  1. ``test_restart_does_not_repeat_completed_side_effect`` —— 判据语义原样：
     首轮跑完（真实 local_file 写 fixture 文件收据）→ ``h.restart("atlas")``
     真进程重启 → 续接请求 → 断言外部写操作计数 == 1（不重复副作用）+ focus
     attend 返回已验证步骤（原证据 refs 保留）+ 服务端权威版本正确递增
     （重启后先 attend 回读旧 revision 再 old+1 commit —— 新链路不再触发 409）。
  2. 多未完成任务：无明确焦点 → 澄清（装配不自动选边 —— 不带 task_id 的运行
     不触碰任何焦点；带 task_id 才续该任务）；两个 task 的 attend 硬隔离。
  3. UNKNOWN/失败收据：进 pending 而非 verified；助手「完成」文本不等于已
     完成（status 仍 ACTIVE）；UNKNOWN 收据的真实文件存在性对账（确定性
     钩子）在真重启后的续接运行里更新状态。
  4. 真进程重启（atlas+memoryos）+ 模型选择改变（fake-model → fake-model-b）
     后焦点仍可用 —— focus 投影不携带模型身份。

fake 模型边界（如实登记）：fake 提供商按脚本回放，模型行为本身不可训练；
「有焦点的模型不重做已验证步骤」由脚本镜像（续接脚本不含写操作），链路侧的
真实保证是 attend 装配（含收据状态）注入上下文 + 权威版本单调递增 + 副作用
计数 == 1。判据里的逻辑操作名 write-fixture-file 映射到真实工具名 local_file
（Atlas 无按逻辑操作名注册的工具，计数只从真实 tool.completed 事件提取）。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径；
重启类测试用 ``um_fresh``（函数级隔离实例），不干扰会话级共享 harness。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \\
    -m pytest core/tests/unified_memory/test_restart_continuation.py \\
    -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import json
import uuid

import pytest

from atlas.memory.reconcile import (
    STATUS_MISSING,
    STATUS_OK,
    STATUS_UNRESOLVED,
    reconcile_focus_receipts,
    reconcile_unknown_receipt,
)

from tests.unified_memory.harness import UMHarness

SUBJECT = "atlas-fixture"


def _proxy_attend(h: UMHarness, task_id: str) -> dict:
    response = h.api("GET", f"/api/unified-memory/focus/{task_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _proxy_commit(h: UMHarness, task_id: str, **snapshot) -> dict:
    response = h.api("POST", "/api/unified-memory/focus", json={
        "context": {**h.default_context(), "task_id": task_id},
        "task_id": task_id,
        "authority_revision": snapshot.pop("authority_revision", 1),
        **snapshot,
    })
    assert response.status_code in (200, 201), response.text
    return response.json()


# ------------------------------------------------------------------ 单元：对账钩子

@pytest.mark.unit
def test_reconcile_unknown_receipt_deterministic_file_check(tmp_path):
    """UNKNOWN 收据的确定性文件存在性检查：OK / MISSING / UNRESOLVED 三态。"""
    existing = tmp_path / "exports" / "archived.csv"
    existing.parent.mkdir(parents=True)
    existing.write_text("a,b\n", encoding="utf-8")

    ok = reconcile_unknown_receipt(
        {"tool": "local_file", "status": "UNKNOWN", "path": str(existing)})
    assert ok["status"] == STATUS_OK and ok["checked"] is True
    assert ok["method"] == "file_exists"
    assert ok["checked_paths"] == [{"path": str(existing), "exists": True}]

    missing = reconcile_unknown_receipt(
        {"tool": "local_file", "status": "UNKNOWN",
         "path": str(tmp_path / "exports" / "never-written.csv")})
    assert missing["status"] == STATUS_MISSING and missing["checked"] is True

    unresolved = reconcile_unknown_receipt(
        {"tool": "some_api", "status": "UNKNOWN", "ref": "endpoint:x"})
    assert unresolved["status"] == STATUS_UNRESOLVED
    assert unresolved["checked"] is False
    assert "未接线" in unresolved["note"]          # 真实 API/窗口检查留偏差

    # 相对路径按 base_dir 解析；非 UNKNOWN 条目原样通过不重复检查
    (tmp_path / "out.txt").write_text("x", encoding="utf-8")
    relative = reconcile_unknown_receipt({"status": "UNKNOWN", "path": "out.txt"},
                                         base_dir=tmp_path)
    assert relative["status"] == STATUS_OK
    done = reconcile_unknown_receipt({"status": "OK", "path": "anything"})
    assert done["status"] == "OK" and done["checked"] is False


@pytest.mark.unit
def test_reconcile_focus_receipts_batch_and_purity():
    """批量对账：UNKNOWN 条目获得 reconcile 结果；输入不被修改。"""
    existing_file = "does-matter"      # 相对路径 + base_dir 由调用方定
    focus = {
        "external_receipts": [
            {"tool": "local_file", "status": "UNKNOWN", "path": existing_file},
            {"tool": "window_api", "status": "UNKNOWN"},
        ],
        "pending": [{"item": "generate-index 结果未知", "status": "UNKNOWN"}],
    }
    import copy

    frozen = copy.deepcopy(focus)
    result = reconcile_focus_receipts(focus, base_dir="/nonexistent-base")
    assert focus == frozen                              # 纯函数：输入不变
    receipts = result["receipts"]
    assert receipts[0]["status"] == STATUS_MISSING      # 可检查 → 确定性结论
    assert receipts[0]["reconcile"]["method"] == "file_exists"
    assert receipts[1]["status"] == "UNKNOWN"           # 不可检查 → 保持 UNKNOWN
    assert result["pending"][0]["status"] == "UNKNOWN"
    assert result["unresolved"] == 2 and result["resolved"] == 0


# ------------------------------------------------------------------ 集成：判据 1

@pytest.mark.integration
def test_restart_does_not_repeat_completed_side_effect(um_fresh):
    """判据语义原样：首轮真实写收据 → 真进程重启 → 续接不重复副作用。"""
    h = um_fresh()
    h.seed("interrupted_task")
    from tests.fakes.fake_llm_provider import Text, ToolCall

    fixture_file = h.workspace / "exports" / "index-summary.txt"
    assert not fixture_file.exists()

    # 首轮：脚本一个真实 write_file 写操作（模型面名 → local_file/write，
    # 外部副作用）+ 完成回复
    h._fake.push(
        ToolCall("write_file", {"path": str(fixture_file),
                                "content": "archived index\n"}),
        Text("已写入收据文件，任务A首轮完成。"),
    )
    first = h.chat("继续任务A：把 csv 归档并生成 index。", task_id="task-a")
    assert first["status"] == "completed", first["failure"]
    assert fixture_file.exists(), "首轮真实外部写副作用应已发生"
    assert first["external_operation_counts"].get("write_file") == 1

    attend1 = _proxy_attend(h, "task-a")
    assert attend1["found"] is True
    assert attend1["steps"], "finalize 应把真实工具收据提交为已验证步骤"
    steps_json = json.dumps(attend1["steps"], ensure_ascii=False)
    assert "ATLAS_TOOL_OBSERVATION" in steps_json, \
        "已验证步骤必须引用 T02.2 capture 的 TOOL_RESULT 观察"
    rev1 = attend1["authority_revision"]
    assert rev1 >= 2                                    # begin(rev1) + finalize(rev1+1)

    # 真进程重启（数据目录不变）
    h.restart("atlas")

    # 续接请求（同 task_id、新会话入口）：有焦点的续接不重做外部写操作
    h._fake.push(Text("任务A的收据已在上一轮验证，无需重复外部操作。"))
    second = h.chat("继续刚才那个任务。", task_id="task-a")
    assert second["status"] == "completed", second["failure"]

    attend2 = _proxy_attend(h, "task-a")
    rev2 = attend2["authority_revision"]
    assert rev2 > rev1, "重启续接必须回读旧权威版本再递增（old+1，不触发 409）"

    # 外部写操作计数 == 1：两次真实运行合计，副作用只发生一次
    total_writes = (first["external_operation_counts"].get("write_file", 0)
                    + second["external_operation_counts"].get("write_file", 0))
    assert total_writes == 1

    # 续接 attend 返回已验证步骤，且原证据 refs 原样保留（压缩/重启不丢）
    assert attend2["steps"] == attend1["steps"]


# ------------------------------------------------------------------ 集成：判据 2

@pytest.mark.integration
def test_multiple_unfinished_tasks_need_explicit_focus(um_fresh):
    """多未完成任务：装配不自动选边 —— 无 task_id 不触碰任何焦点，带才续。"""
    h = um_fresh()
    h.seed("interrupted_task")
    from tests.fakes.fake_llm_provider import Text

    for task, goal in (("task-a", "任务A：整理 exports 目录"),
                       ("task-b", "任务B：另一个不相关任务")):
        _proxy_commit(h, task, goal=goal,
                      steps=[{"item": f"{task} 已验证步骤", "status": "OK"}])
    attend_a = _proxy_attend(h, "task-a")
    attend_b = _proxy_attend(h, "task-b")
    # 多任务硬隔离：attend 精确按 (subject, task_id) 取行
    assert attend_a["task_id"] == "task-a" and attend_b["task_id"] == "task-b"
    assert "任务B" not in json.dumps(attend_a, ensure_ascii=False)
    assert "任务A" not in json.dumps(attend_b, ensure_ascii=False)
    rev_a0 = attend_a["authority_revision"]
    rev_b0 = attend_b["authority_revision"]

    # 无明确焦点的续接请求 → 澄清（装配不自动选边）：不带 task_id 的运行
    # 不触碰任何焦点（两个焦点的权威版本都不推进）
    h._fake.push(Text("要继续任务A还是任务B？请明确一下。"))
    unclear = h.chat("继续刚才那个任务。")
    assert unclear["status"] == "completed"
    assert _proxy_attend(h, "task-a")["authority_revision"] == rev_a0
    assert _proxy_attend(h, "task-b")["authority_revision"] == rev_b0

    # 续接请求带 task_id 才续：只有该任务的权威版本递增
    h._fake.push(Text("收到，继续任务A。"))
    picked = h.chat("继续任务A。", task_id="task-a")
    assert picked["status"] == "completed", picked["failure"]
    assert _proxy_attend(h, "task-a")["authority_revision"] > rev_a0
    assert _proxy_attend(h, "task-b")["authority_revision"] == rev_b0


# ------------------------------------------------------------------ 集成：判据 3

@pytest.mark.integration
def test_unknown_receipt_goes_to_pending_not_verified(um_fresh):
    """失败收据进 pending 而非 verified；助手「完成」文本不是已完成任务。"""
    h = um_fresh()
    h.seed("interrupted_task")
    from tests.fakes.fake_llm_provider import Text, ToolCall

    # 首轮：工具真实失败（读取不存在的文件），随后助手文本自称「全部完成」
    h._fake.push(
        ToolCall("read_file", {"path": str(h.workspace / "exports" / "missing.csv")}),
        Text("任务已全部完成。"),
    )
    run = h.chat("处理任务C的导出文件。", task_id="task-c")
    assert run["status"] == "completed", run["failure"]

    attend = _proxy_attend(h, "task-c")
    # 助手自报完成不是验证：状态仍是权威声明的 RUNNING（投影 ACTIVE）
    assert attend["status"] != "COMPLETED"
    assert attend["steps"] == [], "失败收据不得进入已验证步骤"
    assert attend["pending"], "失败/未知外部结果必须进 pending"
    assert any(entry.get("status") in {"FAILED", "UNKNOWN"}
               for entry in attend["pending"])


@pytest.mark.integration
def test_unknown_receipt_reconciled_before_recommit_after_restart(um_fresh):
    """重跑前对账：UNKNOWN 收据（真实路径）在续接运行 begin 时确定性检查并
    更新状态，再随快照重提交 —— 不重复调用有副作用的工具。"""
    h = um_fresh()
    h.seed("interrupted_task")
    from tests.fakes.fake_llm_provider import Text

    real_file = h.workspace / "exports" / "archived.csv"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("a,b\n", encoding="utf-8")
    _proxy_commit(
        h, "task-d",
        goal="任务D：整理 exports（进程中断，结果未知）",
        pending=[{"item": "generate-index 结果未知", "status": "UNKNOWN",
                  "path": str(real_file)}],
        external_receipts=[{"tool": "local_file", "status": "UNKNOWN",
                            "path": str(real_file)}],
        authority_revision=1,
    )
    h.restart("atlas")                       # 真进程重启后续接

    h._fake.push(Text("收到，继续任务D。"))
    run = h.chat("继续任务D。", task_id="task-d")
    assert run["status"] == "completed", run["failure"]

    attend = _proxy_attend(h, "task-d")
    receipts = {json.dumps(entry, sort_keys=True): entry
                for entry in attend["external_receipts"]}
    reconciled = [entry for entry in attend["external_receipts"]
                  if entry.get("tool") == "local_file"]
    assert reconciled, "UNKNOWN 收据必须随快照携带"
    entry = reconciled[0]
    assert entry["status"] == STATUS_OK, "文件真实存在 → 对账为 OK（效果可观察）"
    assert entry["reconcile"]["method"] == "file_exists"
    assert entry["reconcile"]["checked_paths"][0]["exists"] is True
    assert attend["authority_revision"] >= 2


# ------------------------------------------------------------------ 集成：判据 4

@pytest.mark.integration
def test_focus_survives_restart_and_model_change(um_fresh):
    """真进程重启（atlas+memoryos）+ 模型选择改变后焦点仍可用（不依赖模型身份）。"""
    h = um_fresh()
    evidence = "atlas:ATLAS_TOOL_OBSERVATION:tc-e1:2:UPSERT"
    _proxy_commit(
        h, "task-e",
        goal="任务E：带原证据 refs 的已验证步骤",
        steps=[{"item": "工具 local_file 执行成功（真实收据）", "status": "OK",
                "evidence_refs": [evidence]}],
        authority_revision=1,
    )
    h.restart("atlas")
    h.restart("memoryos")                    # 焦点持久在 MemoryOS 数据目录

    # 模型选择改变（fake-model → fake-model-b）+ 新会话入口续接
    from tests.fakes.fake_llm_provider import Text

    h._fake.push(Text("这是切换模型后的续接回答。"))
    run = h.chat("任务E现在进展如何？", task_id="task-e", model="fake-model-b")
    assert run["status"] == "completed", run["failure"]

    attend = _proxy_attend(h, "task-e")
    assert attend["found"] is True
    assert attend["authority_revision"] > 1, "续接运行回读旧版本后递增提交"
    assert attend["steps"][0]["evidence_refs"] == [evidence], \
        "压缩/切模型/重启后原证据 refs 原样保留"
    payload_json = json.dumps(attend, ensure_ascii=False)
    assert "fake-model" not in payload_json, "focus 投影不携带模型身份"
    assert attend["status"] != "COMPLETED"
