# F4-B Checkpoint — 2026-10-09

**状态：IN_PROGRESS。** 本检查点记录已开始的可审 diff，不代表 F4-B 验收通过。未提交、未推送。

## 范围与协作

B 当前唯一写入的 Atlas 产品范围：`automation/store.py`、`automation/reminders.py`、`memory/intent_bridge.py`、`memory/observer_drain.py`、`agent/tool_node.py`，以及本报告点名的测试和 `scenario_actions.py`。C 另行拥有 `time_context.py`、run phases/drive、observer/reflector/server、`eval_scenarios.py` 和对应测试；不会回退或覆盖其并行改动。

Root 已批准 MemoryOS 一处最薄 source provenance 读投影，限 `D:\MemoryOS\service\unified\repository.py` 及对应测试。MemoryOS evidence API 只给文本片段、hash 与 locator，不返回 observation metadata，因此采用唯一权威路线：record.source_refs → 同主体 evidence event → `observation.derived_from` 递归 → 真实 `ATLAS_USER_MESSAGE`/`USER` Observation。只投影实际 USER source 的 `request_run_id`（唯一时）及 `metadata.source_events` 的 `{source_event_id,event_class,occurred_at,source_timezone}`；派生 metadata 不作为依据，不读取/输出源文本。

## 已完成的检查点

- 补了 AutomationStore source binding 往返测试，恢复原 `test_roundtrip_put_get_list_delete` 原有 delete 覆盖，没有把旧断言移入新测试。
- 补了同一 source run 下轻微措辞变化、不同动作/不同 run 分离、取消后重放不可复活、改期保留 Automation ID 和记录数的红测。
- 补了工具创建 + Observer 投影复用同一 Automation 的服务 harness 测试；目前仍是手工构造投影记录，不等同真实 `tool_node` + `observer_drain` 完整路径。
- 补了 E8 新审计测试：pipeline 可以创建并取消提醒，不要求模型必须调用提醒工具。旧生产判词仍要求 turn 1/2 有工具证据；新测试当前 RED。尚无真实模型运行结果，旧/新审计的实际 scenario judgment 均待真实 smoke。
- MemoryOS 新增 repository provenance 投影及 3 个测试：直接/派生 USER 来源、多个 source run 歧义、派生 metadata 伪造 run ID。隔离专项 `tests/unified_memory/test_f4b_source_provenance.py`：**3 passed**。总控独立 MemoryOS 全集尚未复跑。

## 红测与验证证据

- Atlas store/reminder RED（隔离 C 盘根，`core` cwd）：**4 failed, 2 warnings**，失败分别对应 source_binding roundtrip、同 source 去重、取消重放、防改期新建；测试文件 `core/tests/test_automation_store.py` 与 `core/tests/unified_memory/test_reminder_automation.py`。
- 新 E8 审计 RED（隔离 C 盘根，repo cwd）：`scripts/memory_v1/test_scenario_actions.py::test_reminder_audit_accepts_observer_created_and_cancelled_automation_without_tool`：**1 failed**，当前审计仍要求工具证据。
- MemoryOS RED→GREEN：`tests/unified_memory/test_f4b_source_provenance.py`：**3 passed in 1.75s**；基线 RED 为 3 failed（record 无 metadata）。
- 每个测试 invocation 均将 `TEMP/TMP/TMPDIR`、MemoryOS service/db root（适用时）和 pytest basetemp 指向 `C:\Users\25011\Documents\Codex\f4b-*`。未读生产数据/配置/凭据，未操作进程。

## 当前自有改动清单

Atlas：

- `core/tests/test_automation_store.py`
- `core/tests/unified_memory/test_reminder_automation.py`
- `scripts/memory_v1/test_scenario_actions.py`
- `docs/plan/MEMORY-V1/progress/F4-B.md`

MemoryOS：

- `service/unified/repository.py`
- `tests/unified_memory/test_f4b_source_provenance.py`

以上是 F4-B 当前新增/修改文件；C 与其它历史 dirty 不属于本 lane，不得显式纳入 B 提交。

## 剩余工作

1. 实现并红绿验证 `source_binding` 持久化、source-run + 同 due + 唯一 action 的双路幂等；模糊匹配不得跨 source/run，也不得合并不同动作。
2. 完成模型 `automation_manage` 的真实 tool dispatch 接线；取消与改时同步更新对应 MemoryOS intent，改时复用相同 Automation ID，旧 due 不触发，终态 intent replay 不复活；触发回写从 `source_binding.intent_id` 查当前 intent。
3. 将 MemoryObserverDrain 的来源 metadata/projection 接到真实记录，补工具 dispatch + drain 同源一条/两任务两条的端到端隔离服务测试；复用 C 的真实 run/source 关联合同，不从文本推导 ID。
4. 修改 E8 `scenario_actions` 判词：允许 pipeline 证据，仍严格验证 active/cancelled state、store delta、运行史；运行并同时报告旧判词与新判词结果。
5. 跑 B 专项与 Atlas `tests/unified_memory` 全集，另跑 MemoryOS `tests/unified_memory` 全集；逐一报告失败。随后在隔离 service/model 环境按 root 安排跑真实 chat/service 与已登记模型 smoke；单位测试不作为效果证据。
6. 更新本报告并交 root 独立审 diff/复跑；B 不提交、不推送。
