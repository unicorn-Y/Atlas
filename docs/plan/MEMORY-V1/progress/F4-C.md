# F4-C 接线进度

状态：施工中，未验收、未提交。仅 Atlas 源码/隔离测试；本轮没有触发真实模型调用。

## 当前 ownership 与接口

- C owned：`core/atlas/time_context.py`、`core/atlas/agent/run_phases.py`、`core/atlas/api/run_drive.py`、`core/atlas/server.py`、`core/atlas/memory/observer.py`、必要的 `core/atlas/memory/reflector.py`、`scripts/memory_v1/eval_scenarios.py` 与其 runner 测试、`core/tests/unified_memory/test_test_clock_gate.py` / 新时间测试、本文档；经 root 明确授权，`core/atlas/memory/capture.py` 只增真实用户源 Observation metadata。
- B owned：reminders、IntentBridge、ObserverDrain、tool_node、Automation/场景动作测试及 MemoryOS repository projection。未编辑 B 文件。
- 唯一时钟入口：`test_clock_context(value, config=None, *, event_class=None)` 用 ContextVar 设置并在退出/异常时 reset；TEST+隔离根双闸通过后生效。`resolve_gated_test_clock` 将 naive 时间解释为用户本地墙钟、返回 aware 本地时间；`now_utc()` 与 `now_local(config)` 读取同一 instant。生产/无效 scope 显式屏蔽继承 clock。
- 后台源时间入口：`resolve_source_event_test_clock(events, config)` 只接受来源完整、唯一、全部 TEST 且时间/时区有效的源事件集合，选择 UTC instant 最新来源时间；混合、缺失或冲突时回到真实钟。
- 工具关联约定：Atlas真实用户源 `payload.observation.metadata.request_run_id`，由 `RunRequest.run_id or source_run_id` 真实值生成；Observer队列保留为 `entry.metadata.request_run_id`。没有真实run id时不写字段。绝不伪造 SessionDB `message_uid`。

## 已完成

- `time_context.py` 增 gated ContextVar clock、用户本地 naive 归一、有效来源事件选择；DST gap 被拒为无效 clock，不中止 run。
- `execute_run` 在请求 scope 执行；`_build_messages` 加当前用户本地时间及 IANA 时区。`run_drive` 入口规范化 test clock，`run.started.effective_test_clock` 只在双闸通过时回显。
- `_hermes_turn` 在调用 Hermes 前取得 SessionDB 中既有 USER `message_uid` 集合；turn结束捕获只接受前界之后唯一新增、正文精确等于本轮输入的用户消息。历史同文、仅有异文、边界读取失败或有多个新同文均不捕获；不再按 latest / 历史正文回溯，避免把真实run id贴到旧/无关来源。
- `_capture_run_user_message` 使用同一规范化本地 instant 与 `source_timezone`；生产忽略请求 test clock并以本轮真实 SessionDB `created_at` 捕获。CaptureService只将真实run id存入顶层 `metadata.request_run_id`，不改原文/UID。
- Observer source queue 保留 Observation metadata；batch system prompt 与日预算日期只在本批所有来源均为 TEST、隔离根有效时使用最新源事件时钟，否则走真实墙钟。
- Reflector 读取 record 的 `metadata.source_events`。完整且全 TEST 时用 UTC instant 最新的真实源事件覆盖 prompt 与 receipt 的时钟；缺失/空/混合/无效 provenance 会显式遮蔽外层时钟，回真实墙钟。源事件时间必须 aware；不会把历史naive值按当前用户时区重解释，也不使用模型 `valid_from`。
- RunDrive 回归真实调用 `_handle_run_start` → `_execute_run` WebSocket 事件路径，Hermes executor 被隔离替身替代且不发模型请求；TEST+隔离时 `run.started` 含归一化 `effective_test_clock`，PRODUCTION 时省略。
- `execute_run` 额外覆盖 task cancellation reset、跨任务并发不同 clock 隔离；异步生成器 `aclose()`、之前已创建任务和嵌套 production mask 已有回归。
- 新增独立测试覆盖 naive/aware 同 instant、嵌套 production masking、DST gap、安全 reset、async generator close、先于请求创建的并行任务不受污染、真实 execute_run prompt/production ignore、source capture metadata、Observer source metadata与批次时钟。

## 当前验证

命令（PowerShell，唯一隔离根位于 C 盘 `%TEMP%`，每次新 GUID）：

```powershell
$testRoot = Join-Path $env:TEMP ('atlas-f4-c-observer1-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$env:ATLAS_DATA_DIR = Join-Path $testRoot 'data'
$env:ATLAS_UNIFIED_EVENT_CLASS = 'TEST'
& .\core\.venv\Scripts\python.exe -m pytest -q -o addopts= -p no:cacheprovider --basetemp (Join-Path $testRoot 'pytest') core/tests/unified_memory/test_test_clock_gate.py
```

结果：上轮 `24 passed`；本 checkpoint 最近定向集（clock/capture/reflector/WS、F1 timezone、eval runner）`75 passed`，每次都在新建的 `C:\Users\25011\AppData\Local\Temp\atlas-f4-c-sources-<GUID>` 隔离目录，未访问 Atlas/MOS 生产数据根或触发真实模型。

在补上 `aclosing(inner_scoped_generator)`、inner `finally` 清理断言，并更新两个 capture 生命周期夹具以建立真实 turn-start UID 前界后，2026-10-09 20:14 的最新窄专项为 `40 passed in 2.28s`。该轮包括 clock gate/cancel/close/concurrency、run.start TEST/PRODUCTION、更新后的 phase-order assertion 和两个真实 UID-boundary capture 测试；未触发模型。

```powershell
$testRoot = C:\Users\25011\AppData\Local\Temp\atlas-f4-c-close-boundary-9efb1baec51b468fb3fb3f001f9e2023
$env:ATLAS_DATA_DIR = Join-Path $testRoot 'atlas-data'
$env:ATLAS_UNIFIED_EVENT_CLASS = 'TEST'
.\core\.venv\Scripts\python.exe -m pytest -q -o addopts= -p no:cacheprovider --basetemp (Join-Path $testRoot 'pytest') --junitxml (Join-Path $testRoot 'pytest.junit.xml') core/tests/unified_memory/test_test_clock_gate.py core/tests/unified_memory/test_behavioral_use.py::test_pre_plan_constraint_order_in_execution_flow core/tests/unified_memory/test_capture_lifecycle.py::test_run_user_message_capture_swallows_capture_errors core/tests/unified_memory/test_capture_lifecycle.py::test_run_user_message_capture_prefers_matching_persisted_message
```

stdout 与 JUnit：`C:\Users\25011\AppData\Local\Temp\atlas-f4-c-close-boundary-9efb1baec51b468fb3fb3f001f9e2023\pytest.stdout.log`、`C:\Users\25011\AppData\Local\Temp\atlas-f4-c-close-boundary-9efb1baec51b468fb3fb3f001f9e2023\pytest.junit.xml`。

总控之后独立复跑 clock gate + capture lifecycle + behavioral ordering + eval runner 专项，回报 `90 passed in 33.25s`。随后按审阅意见将 runner temp guard 改为 `longmemeval_observation_cache.checked_temp_child`（它只接受校验过的 `D:\Temp` 或当前 C 盘 profile temp 的严格子路径并保留 production root 阻断），新增 TEMP 指向 `D:\Atlas\data` 和 root 本身拒绝回归。runner 完整专项在 `C:\Users\25011\AppData\Local\Temp\atlas-f4-c-eval-guard-886dae8883574904a0f499d321763ee9` 独立通过 `27 passed in 0.38s`；stdout/JUnit 分别为该目录下 `pytest.stdout.log`、`pytest.junit.xml`。这次 guard 改动只重跑 runner 专项，未重复 clock/capture 用例。

首次完整 `core/tests/unified_memory` 运行结果 `371 passed, 2 skipped, 6 failed in 331.54s` 的原始 pytest stdout/JUnit 未落盘，运行后保留的脱敏失败摘要在 [F4-C-first-full-unified-20261009-200425.log](D:\Atlas\docs\plan\MEMORY-V1\progress\F4-C-first-full-unified-20261009-200425.log)。摘要明确了确切 nodeids、受影响断言和限制，不冒充原始日志。三个 C-owned 旧测试夹具/源码检查失败已由最新窄专项验证通过；另外三项为 B-owned reminder/automation 测试，已将 nodeid 和断言结果交给 B，等待其收口后由总控保存独立的完整全集 stdout/JUnit。

## 未完成闭环

- RunDrive/isolated Outbox 的 eval 证据仅在同 run `run.started.effective_test_clock`、ACKED 且无错误的 Observer source USER event、真实 `request_run_id`、事件时间/时区一致、observer settlement ready 全部满足时将 `occurred_at_used_by_ws=True`；control / blocked / pending / mismatch 等路径保持 false。runner tests 已覆盖判据。root审出的任意 `TEMP` 环境变量授权问题已修：评估读取/写入只用 vetted helper，不再把 `tempfile.gettempdir()` 当作授权依据。
- MemoryOS 边界已核实并报告总控：Atlas recall request 只传 `cue_context.current_timezone`，不传 `as_of`；MOS `retrieval.retrieve` 的 `now_iso()` 与 `temporal.utc_now()` 锚定当前窗口、有效期过滤和 recency。因此 TEST clock 不影响 MOS 相对时间召回。按总控裁定本 C 不新增 `as_of`/MOS clock 接线；若正式 D 场景因此失败，应按真实服务根因另做最薄契约修复，不绕过产品路径。
- `server.py` 背景生命周期只创建独立 drain task 和 reflector idle loop；Observer 在每批中用原始 source provenance重建时钟，Reflector在最终records中用source_events重建；请求 ContextVar 不依赖跨后台 task 传播。还要最终核验所有权 diff、跑专项与完整 `-o addopts= core/tests/unified_memory`、ruff/diff 检查，向总控交付。
