# F1-C 测试诚实化进度

> **状态（2026-10-08 22:56，AI计划 接替）：门禁全绿。** Atlas 三连 `271 passed, 2 skipped` ×3（0 flake）；MemoryOS 全量 `421 passed`；T12 真 HTTP/WS 纠正 smoke `1 passed`；frozen skip = 2。剩余仅「双仓提交+推送」需持有推送权的角色执行。证据 `D:\Temp\F1-C-gate-20261008\`。

## 范围与所有权

- Atlas 既有统一记忆测试和 `conftest.py`：`core/tests/unified_memory/`。
- 本轮实际 harness 路径已核实：`core/tests/unified_memory/harness.py`。
- 进度与失败分类：`docs/plan/MEMORY-V1/progress/F1-C.md`、`KNOWN_FAILURES.md`。
- 经总控明确授权的真实纠错接线：`frontend/src/renderer/components/memory/CorrectionDialog.tsx`、`core/atlas/api/unified_memory_router.py`（仅 corrections 请求）。
- 不拥有 MemoryOS 产品文件、A/B 专属测试、`CURRENT`；不提交、不推送。

## 环境隔离

所有服务测试使用独立 `ATLAS_DATA_DIR`、`MEMORYOS_DATA_ROOT`、`MEMORYOS_DB_PATH` 和动态端口。运行时落在 `D:\Temp\F1-C-20261008\...`。未使用 `D:\Atlas\data`、`D:\MemoryOSData` 或生产 user-settings.json。Harness 对普通契约服务显式禁用语义模型 worker；这只隔离非语义服务，不构成真实模型效果证据。

测试 fake provider 明确标注 `fake_provider`，只验证合约、代理/请求装配与 fixture 行为，不报告为模型效果。F1-C 唯一冻结项为多模态理解与被动屏幕/媒体采集，当前对应两个 `frozen_v1` skip；有效文本导入、capture 生命周期、服务代理与真实 Atlas chat 路径仍保留。

## 基线与当前进展

| 项目 | 结果 | 说明 |
|---|---:|---|
| Atlas 首轮有效完整基线 | 253 passed / 11 failed / 2 errors / 0 skipped | 2026-10-08；日志 `C:\Users\25011\AppData\Local\Temp\atlas-f1c-atlas-run2-20261008\pytest.log`。run1 使用共享 pytest 临时目录，不计有效结果 |
| 修复后的 focused 组 | 8 passed / 1 failed / 2 skipped | 日志 `C:\Users\25011\AppData\Local\Temp\atlas-f1c-focus2-20261008\pytest.log`；唯一失败是当时旧版 T12 observe-helper 测试没有把 replacement 装入新 chat provider context。该用例后来被真实 old→corrections→new-chat 流程替换；它不是 correction5 的 title 根因 |
| Legacy roundtrip 严格复验 | 1 passed | A 修复 legacy raw content hash 污染后，Atlas 导入/导出 hash 与重复回放验证通过；日志 `D:\Temp\F1-C-20261008\focus5-legacy\pytest.log` |
| A 修复后 C-owned focused 组 | 8 passed / 2 failed / 2 skipped | 日志 `D:\Temp\F1-C-20261008\focus6-after-a\pytest.log`。legacy、capture、import、proxy、source idempotency 与两个明确冻结项按预期；T12真实 recall 仍将不可变原始事件投影 episode 当成活动 context，旧值回流；另一个 R00 manifest 比较因同一测试运行中 B 正修改 `scripts/memory_v1/run_longmemeval_f1.py`、前后 SHA 不同而失败，是共享源变动竞态，须固定源后由总控复测 |
| T12 episode-filter focused 复验 | 1 failed / 1 passed | 日志 `D:\Temp\F1-C-20261008\focus8-after-a-episode-fix\pytest.log`。A 过滤 CURRENT 原始 episode 后旧值不再回流；但 recall items 变为空，活动 profile 有新值而自然 query 取不到对应偏好。复现 query `我偏好采用什么回复格式？`、新旧 value 通过真实 correction body 发入，均未注入用户 query/provider的预期答案。A 正修活动 text 投影时保留原本语义描述，source evidence 与审计历史继续不变 |
| T12 语义描述 focused 复验 | 1 failed / 1 passed | 日志 `D:\Temp\F1-C-20261008\focus9-after-a-text-preserve\pytest.log`。活动偏好现可按自然query召回且value/title/summary/text为new；但recall `context_items[].content`把persisted audit字段 `corrected.prev_value=old`也送入模型可见内容。活动record audit与source evidence检查均通过；A 正在只过滤 recall 投影审计字段、保留DB审计及AS_OF/source history |
| CorrectionDialog Vitest | 11 passed | `frontend/src/renderer/components/memory/CorrectionDialog.test.tsx`；C 修正合法 replacement body 后通过 |
| Frontend build | exit 0 | `npm run build` 通过；只有既有 bundle chunk size warning。日志 `D:\Temp\F1-C-20261008\frontend-build.log` |
| Router Python 编译 | exit 0 | `core/atlas/api/unified_memory_router.py` `py_compile` |
| T12 真 HTTP/WS 纠正 smoke | **通过** | `test_release_composition.py::test_desktop_correction_is_visible_in_new_chat` = `1 passed in 15.44s`（2026-10-08 22:56，AI计划 接替复跑）。真实隔离 Atlas+MemoryOS HTTP 服务、真实 corrections API、真实 Atlas WebSocket chat；唯一 fake 为 provider，仅证明链路/数据装配。日志/证据 `D:\Temp\F1-C-gate-20261008\t12-smoke\` |
| 三次连续 Atlas 全量门禁 | **通过** | 口径 `-o addopts= core/tests/unified_memory`，2026-10-08 由 AI计划 接替总控职责亲跑。run1 `271 passed, 2 skipped` 291.70s exit0；run2 同上 293.70s exit0；run3 同上 282.98s exit0。各独立 basetemp + JUnit XML + summary log，落 `D:\Temp\F1-C-gate-20261008\`。零 flake |
| MemoryOS 全量门禁 | **通过** | `tests/unified_memory` = `421 passed` 120.38s exit0（2026-10-08 22:11，AI计划 亲跑）。gate1 的 3 个 hybrid 语义通道失败（`DISABLED`/`LOCAL_DETERMINISTIC` vs 期望 `OK`/`NOT_WIRED`/`RAW_OR_FTS`）经 A 修复前置后全绿 |

run2 基线的 11 项失败逐项定性及当前状态见同目录 `KNOWN_FAILURES.md` 的 F1-C 专节。run2 另有两个 teardown error：harness 已改为终止本轮服务的进程树并验证绑定端口释放；focus2 teardown 已无错误。冻结 skip：单文件组为 2，全量三连亦为 2（`271 passed, 2 skipped`）。

## Correction 真实路径约束

T12 用例先通过 Atlas `/observe` 持久化旧回复格式偏好，取实际 `record_ref` 和 revision，核对真实 profile/recall，然后经 Atlas `/api/unified-memory/corrections` 以合法 `replacement: {value}` 和 `expected_revision` 发起纠正。缺省 context 只由该 corrections route 从配置后的 `UnifiedMemoryFacade.default_context()` 构造，复用权威 subject；UI保留 409 冲突保护。随后用 GET record、profile、recall 检查活动新值，最后经新 Atlas WebSocket chat 发送不包含 expected replacement 的自然查询。

当前失败揭示 MemoryOS 活动 title 投影未随 replacement.value 更新。活动字段 `value/title/summary` 与 recall/model-visible `context_items` 不得残留旧值；`corrected.prev_value` 更正审计和不可变原始 source/evidence 应继续保留，不得为了断言清除原文。T12 provider 是 fake，所以只证明真实 Atlas/MemoryOS HTTP 与 Atlas WebSocket 的链路和 prompt 装配，不证明真实模型遵循偏好。A 修复后，C 将复跑上述接口链并确认旧值不在活动记录/真实 profile/recall/chat context，同时审计 history/source 仍在。

## 可复跑的真实 Atlas HTTP/WS smoke 命令

在 PowerShell、`D:\Atlas` 仓库根目录执行；每轮把下列 `correction-smoke` 替换成独立目录名，日志和 pytest basetemp 留在 D 盘：

```powershell
$env:ATLAS_DATA_DIR = 'D:\Temp\F1-C-20261008\correction-smoke\atlas-data'
$env:MEMORYOS_DATA_ROOT = 'D:\Temp\F1-C-20261008\correction-smoke\memoryos-data'
$env:MEMORYOS_DB_PATH = 'D:\Temp\F1-C-20261008\correction-smoke\memoryos-data\db\memoryos.sqlite3'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -v -p no:cacheprovider -o addopts= `
  --basetemp 'D:\Temp\F1-C-20261008\correction-smoke\basetemp' `
  --junitxml 'D:\Temp\F1-C-20261008\correction-smoke\junit.xml' `
  'core/tests/unified_memory/test_release_composition.py::test_desktop_correction_is_visible_in_new_chat' `
  *> 'D:\Temp\F1-C-20261008\correction-smoke\pytest.log'
```

该单测启动真实隔离 Atlas 与 MemoryOS HTTP 服务、实际 corrections API 和 Atlas WebSocket chat；唯一 fake 的部分是 provider，故只能作为链路/数据装配证据。

## 隔离缺陷修复（本会话，2026-10-08）

- 修复 `test_client_contract.py::test_service_down_raises_and_no_local_fallback_write` 的剩余 flake：`db_snapshot` 增加 `only` 参数，Atlas 侧只认 `atlas.db`、MemoryOS 侧只认 `memoryos.sqlite3`（`runtime_manifest["memoryos_db"]`），忽略 SQLite checkpoint 的 `-wal`/`-shm` 边车。断言强度未降（主库 mtime+size 仍精确比对）。
- 单文件 20 passed；全量三连 0 flake。定性/修复详见 `KNOWN_FAILURES.md`「跨用例隔离缺陷（二）」。
- 修正了口径偏差：上一轮后半段曾把门禁误跑成整个 `core/tests`（2694 项），本轮按派单书口径 `core/tests/unified_memory` 重跑。

## 接下来

1. ~~等 A 通知 MemoryOS correction 活动 title 修复落地，复跑 smoke~~ ✅ 已复跑通过（T12 smoke `1 passed`）。
2. ~~smoke 与本批 owned focused tests 绿后通知总控~~ ✅ Atlas 三连与 MemoryOS 全量均已绿。
3. ~~每轮记录结果与 frozen_v1 skip 数~~ ✅ frozen skip = 2（贯穿全量）。
4. 提交与推送由持有双仓推送权的角色统一执行（C 不提交、不推送）；本报告已具备 ACCEPTED 所需的门禁证据。
