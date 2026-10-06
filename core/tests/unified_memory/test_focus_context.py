"""T06.1 Atlas-side：FocusContext（memory/context.py）与焦点代理闭环（UM06）。

两块：
  * 单元（fake client / 纯函数）：
    - FocusContext begin/commit/attend/observe 到 UnifiedMemoryClient 的形状
      映射（authority_revision 必须由调用方传入 —— 权威边界；缺 task_id /
      缺 revision → FocusContextError，不发 HTTP）；
    - disabled 时 attend 返回 enabled=False + 空装配（不编造焦点前情）、
      commit 显式 ServiceUnavailable（权威快照不得静默丢弃）；
    - 本地 purpose 门（LEARN 等 → FocusContextError；通用召回走 recall）；
    - ``compress_context`` 纯函数：压缩保留 focus 与原证据 refs、
      SUMMARY 不得顶替任务状态条目、当前用户消息标注优先（T06.2 接线点）。
  * 集成（UMHarness 真双服务）：
    - FocusContext（真 UnifiedMemoryClient 指向 harness MemoryOS）commit →
      observe → attend(CONTINUE_TASK) 闭环经真服务；
    - 任务书判据 ``test_focus_is_task_scoped`` 语义原样（ attend 面）：
      经 **Atlas 代理** /api/unified-memory/focus/{task_id} 装配，不同
      task_id 不串（多任务焦点隔离）；
    - 代理面 T06.1 三路由真透传（POST /focus、GET /focus/{task_id}、
      POST /focus/{focus_id}/observe）。

隔离规则同 harness：全部 TEST 事件类、主体 = atlas-fixture，不触生产路径。

运行：
  cd /d/Atlas && ATLAS_DATA_DIR= PYTHONUTF8=1 core/.venv/Scripts/python.exe \\
    -m pytest core/tests/unified_memory/test_focus_context.py \\
    -o addopts= -m 'unit or integration' -q
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from atlas.memory.context import FocusContext, FocusContextError, compress_context
from atlas.memory.unified_client import UnifiedMemoryClient

from tests.unified_memory.harness import TEST_INTERNAL_TOKEN, UMHarness

UID = uuid.uuid4().hex[:8]   # 本文件的 task 命名空间（会话级 harness 共库）
SUBJECT = "atlas-fixture"    # harness 绑定主体（_memoryos_env）


# ------------------------------------------------------------------ fakes

class FakeFocusClient:
    """UnifiedMemoryClient 的 focus 面最小假件（单元测试只看形状映射）。"""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled_flag = enabled
        self.update_focus_calls: list[dict] = []
        self.attend_calls: list[dict] = []
        self.observe_calls: list[tuple[str, dict]] = []
        self.attend_response: dict = {"found": True, "goal": "g"}

    async def update_focus(self, request: dict) -> dict:
        self.update_focus_calls.append(request)
        return {"focus_id": "fcs-fake", "focus_ref": "focus:fcs-fake",
                "task_id": request["task_id"], "found": True}

    async def attend_focus(self, task_id: str, *, purpose="CONTINUE_TASK",
                           subject=None, max_records=None) -> dict:
        self.attend_calls.append({"task_id": task_id, "purpose": purpose,
                                  "subject": subject,
                                  "max_records": max_records})
        return dict(self.attend_response)

    async def observe_focus(self, focus_id: str, request: dict) -> dict:
        self.observe_calls.append((focus_id, request))
        return {"event_id": "obs-fake", "focus_id": focus_id}


class FakeFacade:
    def __init__(self, client) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._client, "enabled_flag", True))

    def client(self):
        return self._client

    def default_context(self, **overrides):
        base = {"owner_id": "o", "memory_subject_id": SUBJECT,
                "client_id": "atlas-desktop", "actor_id": "atlas-main",
                "runtime_session_id": "s-1", "task_id": None,
                "project_id": None, "environment_id": "windows",
                "model_deployment_id": None}
        base.update(overrides)
        return base


# ------------------------------------------------------------------ 单元

@pytest.mark.unit
def test_focus_context_commit_requires_task_and_authority_revision():
    """权威边界：commit 必须绑定 task_id 且携带 authority_revision（调用方
    传入；focus 是投影不是第二执行器）。"""
    fake = FakeFocusClient()
    focus = FocusContext(facade=FakeFacade(fake))

    async def scenario():
        with pytest.raises(FocusContextError):
            await focus.commit_focus(task_id="  ", snapshot={"goal": "g"},
                                     authority_revision=1)
        with pytest.raises(FocusContextError):
            await focus.commit_focus(task_id="t1", snapshot={"goal": "g"},
                                     authority_revision=None)

    asyncio.run(scenario())
    assert fake.update_focus_calls == []


@pytest.mark.unit
def test_focus_context_commit_maps_authoritative_snapshot():
    """commit/begin 形状映射：authority_revision / task_status 原样转发；
    snapshot 的 None 值不进请求。"""
    fake = FakeFocusClient()
    focus = FocusContext(facade=FakeFacade(fake))
    import asyncio

    async def scenario():
        await focus.begin_task_focus(task_id="t1", goal="写报告",
                                     constraints=["不得删文件"],
                                     authority_revision=7)
        await focus.commit_focus(
            task_id="t1", snapshot={
                "goal": "写报告", "steps": [{"ref": "episode:e1"}],
                "pending": None}, authority_revision=8,
            task_status="RUNNING")

    asyncio.run(scenario())
    first, second = fake.update_focus_calls
    assert first["task_id"] == "t1" and first["authority_revision"] == 7
    assert first["goal"] == "写报告" and first["task_status"] == "RUNNING"
    assert first["constraints"] == ["不得删文件"]
    assert second["authority_revision"] == 8
    assert second["task_status"] == "RUNNING"
    assert "pending" not in second                     # None 值不进请求
    assert second["steps"] == [{"ref": "episode:e1"}]


@pytest.mark.unit
def test_focus_context_attend_disabled_empty_and_purpose_gate():
    """disabled → attend 空装配不编造；本地 purpose 门；observe 透传。"""
    fake = FakeFocusClient(enabled=False)
    focus = FocusContext(facade=FakeFacade(fake))
    import asyncio

    async def scenario():
        attend = await focus.attend_for_purpose(task_id="t1")
        assert attend["enabled"] is False and attend["found"] is False
        assert attend["goal"] is None and attend["context_items"] == []
        assert "不编造" in attend["note"]
        with pytest.raises(FocusContextError):
            await focus.attend_for_purpose(task_id="t1", purpose="AUDIT")
        with pytest.raises(Exception):
            await focus.commit_focus(task_id="t1", snapshot={"goal": "g"},
                                     authority_revision=1)
        assert fake.update_focus_calls == []           # 未发 HTTP

    asyncio.run(scenario())
    # purpose 门在 attend 调用前拦截：没有 attend 网络调用发生
    assert fake.attend_calls == []


@pytest.mark.unit
def test_focus_context_attend_passes_purpose_subject():
    fake = FakeFocusClient()
    fake.attend_response = {"found": True, "goal": "装配结果"}
    focus = FocusContext(facade=FakeFacade(fake))
    import asyncio

    async def scenario():
        return await focus.attend_for_purpose(
            task_id="t9", purpose="PLAN",
            context={"memory_subject_id": SUBJECT})

    result = asyncio.run(scenario())
    assert result["enabled"] is True and result["goal"] == "装配结果"
    assert fake.attend_calls == [{"task_id": "t9", "purpose": "PLAN",
                                  "subject": SUBJECT, "max_records": None}]


@pytest.mark.unit
def test_compress_context_keeps_focus_and_original_evidence():
    """压缩不变量 1+2+4：focus 整块保留；全部原始证据 refs 保留可回溯。"""
    focus = {
        "found": True, "focus_ref": "focus:fcs-1", "focus_id": "fcs-1",
        "task_id": f"task-{UID}-c1", "goal": "修复并验证",
        "constraints": [{"item": "不得重跑有副作用的工具"}],
        "steps": [{"ref": "episode:e1", "evidence_refs": ["episode:e1"]}],
        "pending": [{"item": "等待验证"}],
        "memory_refs": [{"ref": "memory:m1", "revision": 3}],
        "external_receipts": [{"ref": "episode:r1", "status": "UNKNOWN"}],
        "status": "ACTIVE", "authority_revision": 5,
    }
    items = [
        {"record_ref": "memory:m1", "revision": 3, "facet": "STATE",
         "content": {}},
        {"record_ref": "episode:e9", "revision": 1, "facet": "EPISODE",
         "content": {}},                                   # 会被预算裁掉
        {"record_ref": "episode:s1", "revision": 1, "facet": "SUMMARY",
         "content": {}},
    ]
    out = compress_context(items, focus, max_items=1, current_message="继续任务")
    assert out["focus"]["goal"] == "修复并验证"           # 不变量 1：整块保留
    assert out["focus"]["steps"][0]["evidence_refs"] == ["episode:e1"]
    refs = {entry["record_ref"] for entry in out["evidence_refs"]}
    assert {"memory:m1", "episode:e9", "episode:s1",
            "episode:e1"} <= refs                        # 不变量 2：refs 全保留
    assert [i["facet"] for i in out["items"]].count("STATE") == 1
    assert out["current_message_first"] is True
    kept_refs = {i["record_ref"] for i in out["items"] if i.get("record_ref")}
    dropped = {entry["record_ref"] for entry in out["dropped_refs"]}
    # 被预算裁掉的条目（e9）与 focus 内 refs（e1）不丢定位，留 dropped_refs
    assert "episode:e9" in dropped and "episode:e1" in dropped
    assert dropped == refs - kept_refs


@pytest.mark.unit
def test_compress_context_summary_cannot_replace_task_state():
    """压缩不变量 3：预算内 SUMMARY 只作补充，不得顶替任务状态条目。"""
    items = [
        {"record_ref": "episode:s1", "facet": "SUMMARY", "content": {}},
        {"record_ref": "memory:g1", "revision": 1, "facet": "GOAL",
         "content": {}},
    ]
    out = compress_context(items, None, max_items=1)
    assert [i["record_ref"] for i in out["items"]] == ["memory:g1"]
    assert out["summaries_kept"] == 0
    # 预算有富余时 SUMMARY 才作为补充保留
    out2 = compress_context(items, None, max_items=2)
    assert [i["record_ref"] for i in out2["items"]] == ["memory:g1",
                                                        "episode:s1"]
    assert out2["summaries_kept"] == 1


# ------------------------------------------------------------------ 集成

@pytest.mark.integration
def test_focus_context_real_dual_service_loop(um: UMHarness):
    """FocusContext commit → observe → attend 闭环经真双服务。"""
    client = UnifiedMemoryClient(
        service_url=um.memoryos_url, internal_token=TEST_INTERNAL_TOKEN,
        timeout=10.0)
    focus = FocusContext(client=client)
    task = f"task-{UID}-real"
    # client-only 构造没有 facade 配置可绑定 context 骨架 → 显式传入 TEST 上下文
    ctx = {**um.default_context(), "runtime_session_id": f"focus-real-{UID}"}

    async def scenario():
        committed = await focus.begin_task_focus(
            task_id=task, goal=f"真实双服务焦点闭环（{UID}）",
            constraints=[{"item": "不得重复副作用"}],
            steps=[{"ref": "episode:seed-ref", "evidence_refs":
                    ["episode:seed-ref"]}],
            authority_revision=1, context=ctx)
        assert committed["found"] is True
        observed = await focus.observe(
            focus_id=committed["focus_id"],
            event={"kind": "TOOL_RESULT", "note": "工具已返回", "ref":
                   "episode:seed-ref"}, context=ctx)
        assert observed["event_id"].startswith("obs-")
        attend = await focus.attend_for_purpose(task_id=task,
                                                purpose="CONTINUE_TASK")
        return committed, attend

    committed, attend = asyncio.run(scenario())
    assert attend["enabled"] is True and attend["found"] is True
    assert attend["goal"] == f"真实双服务焦点闭环（{UID}）"
    assert attend["steps"][0]["evidence_refs"] == ["episode:seed-ref"]
    assert attend["observed"], "CONTINUE_TASK 装配应含近期注意事件"
    # 权威边界经真服务：服务端不推断完成
    assert attend["status"] != "COMPLETED"


@pytest.mark.integration
def test_focus_is_task_scoped_via_atlas_proxy(um: UMHarness):
    """任务书判据语义原样（经 Atlas 代理 /api/unified-memory/focus）：
    不同 task_id 的 attend 不串 —— 多任务焦点隔离。"""
    task_a, task_b = f"task-{UID}-pa", f"task-{UID}-pb"
    for task, goal in ((task_a, f"任务A：写报告（{UID}）"),
                       (task_b, f"任务B：修 bug（{UID}）")):
        r = um.api("POST", "/api/unified-memory/focus", json={
            "context": {**um.default_context(), "task_id": task},
            "task_id": task, "goal": goal,
            "steps": [{"ref": f"episode:{task}-1"}],
            "pending": [{"item": f"{task} 的待解决项"}],
            "memory_refs": [{"ref": f"memory:{task}-m"}],
            "authority_revision": 1,
        })
        # Atlas 代理语义（T01.3 既定偏差）：上游 2xx 统一 200（201 新提交 → 200）
        assert r.status_code == 200, r.text
        focus_id = r.json()["focus_id"]

        # 注意事件经代理 observe 入工作集
        obs = um.api("POST", f"/api/unified-memory/focus/{focus_id}/observe",
                          json={"context": um.default_context(),
                                "kind": "TOOL_RESULT", "note": f"{task} 观察"})
        assert obs.status_code == 200, obs.text  # 代理 2xx→200（T01.3）

    ra = um.api("GET", f"/api/unified-memory/focus/{task_a}",
                     params={"purpose": "CONTINUE_TASK"})
    assert ra.status_code == 200, ra.text
    attend_a = ra.json()
    assert attend_a["goal"].startswith("任务A")
    assert attend_a["observed"], "代理 observe 的注意事件应进入装配"
    # 判据语义：装配面的 context_items 全部属于 task-a（永不出现 task-b）
    assert all(x["content"].get("task_id") == task_a
               for x in attend_a["context_items"])
    assert all(x["content"].get("task_id") != task_b
               for x in attend_a["context_items"])
    assert attend_a["pending"] == [{"item": f"{task_a} 的待解决项"}]

    rb = um.api("GET", f"/api/unified-memory/focus/{task_b}",
                     params={"purpose": "PLAN"})
    assert rb.status_code == 200, rb.text
    attend_b = rb.json()
    assert attend_b["goal"].startswith("任务B")
    assert attend_b["observed"] == []                  # PLAN 不含 transient 环
    assert all(x["content"].get("task_id") == task_b
               for x in attend_b["context_items"])


@pytest.mark.integration
def test_focus_stale_revision_conflict_via_proxy(um: UMHarness):
    """旧运行版本经代理覆盖 → 409 同码透传（Atlas 侧 RevisionConflict 映射）。"""
    task = f"task-{UID}-conflict"
    r = um.api("POST", "/api/unified-memory/focus", json={
        "context": {**um.default_context(), "task_id": task},
        "task_id": task, "goal": "v5", "authority_revision": 5})
    assert r.status_code == 200, r.text  # 代理 2xx→200（T01.3；上游 201 新提交）
    stale = um.api("POST", "/api/unified-memory/focus", json={
        "context": {**um.default_context(), "task_id": task},
        "task_id": task, "goal": "旧版本回写", "authority_revision": 4})
    assert stale.status_code == 409, stale.text
    body = stale.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("error") == "FOCUS_REVISION_CONFLICT"
