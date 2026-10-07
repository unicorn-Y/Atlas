# 总控移交记录（2026-10-07 深夜，Hermes AI计划 接手）

## 0. 为什么换总控

上一任总控（商店版 Codex，controller 线程 `01a1165a-54e1-7c83-9…`，cwd `D:\Atlas`，模型 gpt-6.1-sol）
与其 3 个 luna-xhigh 子智能体（`01a1165f`/`01a11660-8afe`/`01a11660-28b4`）在 **22:35–22:36 全部撞 ChatGPT 额度墙**：

```
You've hit your usage limit. Upgrade to Pro ... or try again at Oct 8th, 2026 1:37 AM.
codexErrorInfo = usageLimitExceeded
```

四条线程 `status=failed`，无可用额度至 Oct 8 01:37。Codex 线当晚不可续。
用户指令：**「接着 codex 现在的会话的那个任务继续，严格按照任务要求来」** → 总控移交 Hermes AI计划。
本机 Codex CLI 未登录（`codex login status` → Not logged in），且额度墙与登录无关，不依赖它。

任务权威规范：`docs/plan/MEMORY-V1/00_任务书.md`；交接纪律：`03_交接给Codex.md`。
本记录 = 新总控的现场复核 + 施工续接基线，后续以本文件与各 `progress/packages/*.md` 为准。

## 1. 现场基线（动手前）

- Atlas HEAD `75c9709c`（branch `memory-v1`，已提交：remove scripted harness answers + expose memory model setting）。
- MemoryOS HEAD `ba8613403f56429333fe5adfdca6f291bd4b41f1`（已提交推送：S0 冻结子包）。
- 两仓均有**大量未提交改动**，属 A/B/C 三通道施工中产物（非本轮新总控产生）。
  Atlas 未跟踪新文件：`core/atlas/memory/{observer,observer_drain,observer_prompt,service_lifecycle}.py`、
  `core/atlas/capabilities/durable/dbos_compat.py`、`core/tests/test_memory_*.py`、
  `core/tests/unified_memory/test_cutover_fixture.py`、`scripts/memory_v1/smoke_observer.py`、
  `docs/plan/MEMORY-V1/progress/packages/{C,C_vendored}.md`、`.construction-pack/`。
- **红线遵守**：未触碰 `D:\MemoryOSData`、`D:\Atlas\data`、`user-settings.json`、生产配置；测试全部用隔离数据根。

## 2. 独立复跑（新总控亲自跑，不采信汇报）

| 复跑对象 | 结果 |
|---|---|
| Atlas `tests/test_bootstrap_memory_v1_config.py` | 14 passed |
| Atlas `tests/test_memoryos_service_lifecycle.py` + `test_memory_v1_observer.py` + `test_memory_observer_drain.py` + `test_unified_memory_v1_reads.py` | 39 passed |
| MemoryOS `tests/unified_memory/test_v1_freeze.py` + `test_legacy_import.py` + `test_associative_recall.py` + `test_transfer_gate.py` | 25 passed |
| Atlas 全库 `pytest`（放开 `-m unit`，2296 passed / 19 failed，7:29） | 见 §3 |
| MemoryOS 全库 `pytest tests` | 收集错误（缺 PYTHONPATH 含 `service/`），跑法待修，见 §4 |

代码抽查（读 diff，非采信）确认已按总控打回意见返工：
- `service_lifecycle.py` health probe 已改为 probe `/`（identity `service=="MemoryOS Service"`）+ `/v1/health`（status∈{ok,healthy}），不再只看一个端点。
- `outbox.py` Observer 预算已改为单事务 `BEGIN IMMEDIATE` 的 reserve/commit/release，跨会话与进程重启持久。
- `memory/__init__.py` 已实现 `_list_unified_records`（分页读、**绝不回落本地 facts**）、`_unified_recall_context`、`_fact_from_unified_record`。
- `run_phases.py` 已在 `_phase_context`/`_phase_goal_knowledge`/`_phase_plan`/`_phase_finalize` 接入 `_unified_reads_enabled` 分支。

## 3. Atlas 全库 19 个失败分类（关键）

判定方法：`git worktree add --detach ... 75c9709c`（基线 HEAD）跑同一批测试对比。

**A. 基线既有失败（8 个，与本次改动无关，不阻塞本计划）**
`test_lint_gate::test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows`、
`test_model_router::test_ast_no_acompletion_outside_router`、
`test_plugins::test_git_source_update_available`、
`test_route_snapshot::test_routes_match_frozen_snapshot`、
`test_subprocess_encoding::test_text_mode_subprocess_calls_declare_an_encoding`、
`test_repair_baseline::{test_r00_b_0026_is_construction_not_foreign,test_r00_b_dirty_counts_match_known_baseline,test_manifest_artifact_written}`。

**B. 本次未提交改动引入（11 个，必须修，S0 闸门）**
1. `test_agent_run_phases.py` 6 项：`test_context_phase_closes_unexpected_memories_coroutine`、
   `test_cancel_event_ends_run_promptly_without_polling`、`test_cancel_watcher_is_cleaned_up_after_done`、
   `test_terminal_failed_turn_yields_error_and_never_done`、`test_failed_turn_without_error_detail_still_fails`、
   `test_interrupted_turn_is_not_reported_as_failure`、`test_successful_turn_still_ends_in_done`
2. `test_c4_hooks.py::test_agent_userpromptsubmit_context_enriches_the_round`
3. `unified_memory/test_composition.py::test_proxy_transport_failure_maps_503`（assert 200 == 503）
4. `unified_memory/test_legacy_migration.py::TestUnifiedDelegation::test_audit_correction_stays_local_per_authority_map`（`FakeUnifiedFacade` 缺 `list_records`）
5. `unified_memory/test_windows_activity.py::{test_receipt_capture_media_asset_idempotent_and_passive_watermark,test_receipt_capture_after_stop_active_continues_no_passive}`

**根因（已定位到行）**：`run_phases._phase_context` 里
`unified_enabled = bool(getattr(agent._memory, "_unified_reads_enabled", lambda: False)())`。
测试用 `AsyncMock` 作 `agent._memory` → `getattr(...)` 取到 AsyncMock 属性，调用返回**协程对象**，
`bool(协程)` 恒为 True → 误入统一分支 → `state.context` 变成协程 → `trace.get(...)` 抛
`'coroutine' object has no attribute 'get'` → 被 `_phase_context` 的 except 捕获 → 整轮 yield `error`。
生产路径 `MemoryStore._unified_reads_enabled` 返回真 `bool`，**不受影响**；这是测试替身未同步。
另 4 项同类：新 `_list_unified_records` 调 `facade.list_records`，测试 `FakeUnifiedFacade` 未实现；
composition/windows_activity 的期望值未跟随统一读分支更新。

**判定**：11 项全部为**测试替身/期望未同步**类，不是生产逻辑缺陷；但按任务书第 6 节「不得靠改测试掩盖」，
必须**既修探针健壮性、又补齐夹具**，并证明修完全库回到基线既有失败数（8）为止，不得多。

## 4. MemoryOS 全库跑法（待固化）

`D:/MemoryOS` 无 `pytest.ini`/`pyproject`/`conftest.py`；`tests/test_graph_conservative.py` 用
`from graph_conservative import ...`，模块在 `service/` 下。全库跑法需 `PYTHONPATH` 含 `service/`
（或 `cd service` 后 `pytest ../tests`）。服务 venv 无 pytest，用
`C:/Users/25011/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pytest` 或服务 venv 装 pytest，
在 progress 写明用的是哪个。

## 5. 续接派工（本轮，3 通道并行，遵 CURRENT.json 的 max_subagents=3 授权）

- **A 通道（续 B，S1）**：修 §3.B 的 11 项回归 → 全库回绿 → 完成 S1（`run_phases` 五条真实模型冒烟：
  remember / 新会话 / 服务离线 / 重启自动拉起）。独占 `run_phases.py`、`memory/__init__.py`、`capture.py`、`outbox.py`、`observer*.py`。
- **D 通道（S2 MemoryOS 侧）**：无 key 记忆形成路径 + `consolidation:apply` 整理接口。独占 `formation.py`、`consolidation.py`、`api.py`、新迁移。
- **E 通道（S3+S4）**：召回装配（画像块/相关记忆块/意图闸门/出处标记）+ 衰减与强化排序、HIGH 下限。独占 `retrieval.py`、Atlas 新 `recall_context.py`。

真实模型：Atlas `cnapi.pleasure.cc.cd` 的 `deepseek-v4.1-flash`（`D:\Atlas\config\atlas.toml`）。
子智能体不得把模型 id/用量漏记；真实冒烟必须打真网关，不得用 fake 冒充。
