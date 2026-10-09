# F2-B LongMemEval 与场景运行器

状态：`IMPLEMENTATION_READY_FOR_REVIEW`。本文件记录的只是 runner 与单测状态；尚未发起 6 题、30 题、30 场景×3 的真实模型评测，也没有 F2 验收成绩。

## 本轮实现

- `scripts/memory_v1/run_longmemeval_f2.py` 限定 6 题 smoke 与 30 题 reference 两档；固定子集元数据必须为 seed `20261007`，按 canonical category 顺序选每类前 1/5 题。既有 F1 runner 保留其自身模式，F2 入口不暴露 12/120。
- 官方 evaluator import 要求 Atlas CPython 3.14 venv；只把 `D:\Temp\F1-D-official-numpy-2.5.3-py314` 加到 NumPy import path，并验证实际 NumPy 版本/文件路径。OpenAI、tqdm、backoff 等依赖继续从 Atlas venv 解析。
- `scripts/memory_v1/longmemeval_observation_cache.py` 将逐题 Observer 结果以持久 checkpoint 和服务快照缓存至 `D:\Temp\F2-B-longmemeval-observation-cache-v1`。指纹覆盖固定来源/题目历史、Observer 与 MemoryOS 源码、Atlas model router 源码、观察模型/配置及实际 auxiliary route 参数（`memory_observe`、120 秒、适用时 `reasoning_effort=low`）；不包含答题模型或 judge 选项。gold/answer 不进入 fingerprint 的 question-history 字段、观察输入或报告正文。
- SQLite 数据库通过 SQLite backup API 生成一致副本，不复制活动 WAL/SHM sidecar；每个副本执行 `PRAGMA integrity_check`。Answer/judge 使用恢复到独立逐题 runtime 的副本，缓存源保持不变。6 与 30 共用同一 cache root；交集题命中同一 Observer 指纹时不再观察。
- 每题写出 `OBSERVING`、`OBSERVATION_COMPLETE`、`ANSWER_COMPLETE`、`JUDGE_COMPLETE` 或 `FAILED_ATTEMPT` checkpoint。完成报告仅保留 qid、category、官方 judge label、cache 证据、token/时延与 evaluator 来源；不复制问题、答案、gold 或 judge reasoning。30 题外部比较值只作为样本数不同的参考，不作为验收阈值。
- 场景 runner 在执行下一轮前同时等待：本轮 outbox source 全部 ACK、`observer_source_watermarks` 覆盖并全部 `DELIVERED`、本轮 `observer_queue` 无行、`observer_batches` 无 `PENDING`、`observer_sessions` 无活动行，以及 MemoryOS semantic `READY/pending_count=0`。缺少这些表或读取失败时不把请求推进为 settled。
- LongMemEval 的 `read_only` 与 `tool_deny=["*"]` 保持原样，避免答案路径绕过召回读取 transcripts/gold。

## 单测与执行边界

验证：

- `python -m pytest --basetemp D:/Temp/F2-B-owned-runner-tests-20261009 scripts/memory_v1/test_longmemeval_f1_runner.py scripts/memory_v1/test_eval_scenarios_runner.py -q`：`41 passed`。
- `python -m compileall -q scripts/memory_v1/run_longmemeval_f1.py scripts/memory_v1/run_longmemeval_f2.py scripts/memory_v1/longmemeval_observation_cache.py scripts/memory_v1/eval_scenarios.py`：通过。
- `git diff --check`：通过；仅有测试文件 LF→CRLF 提示。
- Atlas Python 3.14 venv 同样运行上述两个 runner 测试文件：`41 passed`。零请求 official-import probe 通过，报告 Python `3.14.7`、NumPy `2.5.3` 且来自隔离 target，`get_anscheck_prompt` 可调用。

以上只验证代码与本地隔离 fixture，不代表 Observer/HTTP/judge 的真实评测结果。尚无真实评测 token、category score、耗时或失败题数据。须先经总控 diff review、独立真实单场景抽查及 F2-A 验收信号，再启动 6 题、30 题和 30 场景×3；不运行 120 题。

## 已确认的场景边界与根因

- **S6 时间边界**：runner 保留原始用户输入，不注入 benchmark 时间，也不改写原话。`run_phases._capture_run_user_message` (`core/atlas/agent/run_phases.py:938-977`) 从 SessionDB 读持久化消息，并把 `created_at` 传给 `CaptureService.capture_user_message`；当前场景入口没有把 scenario 时间作为 message timestamp 传入。因此相对日期证据可能基于真实运行时间，结果必须如实报告，不能由评测器补时间来规避。
- **S28 pause 边界**：`PassiveCaptureController.pause` (`core/atlas/memory/windows_sources.py:1045`) 的文档及实现只暂停被动观察源，并排空在途被动观察；正常对话仍经 `run_phases._capture_run_user_message` 捕获。场景若将 pause 解读为禁止对话内容进入主动捕获，会与产品现有语义不一致；本轮不扩展 pause 语义。
- **S29 Automation 缺口**：`ENGINE_WIRING["wired"]` 在 `core/atlas/memory/intent_bridge.py:203-220` 明确为 false；`IntentBridge.create_automation_for_intent` (`:280-312`) 只返回 projection/instructions，不写 Automation store。`core/atlas/agent/tool_catalog.py` 的 model-facing tools 未提供 Automation/reminder CRUD，`core/atlas/server.py:659-665` 只初始化 AutomationEngine。虽然 `core/atlas/api/automation_router.py` 提供 HTTP API，该 API 不是模型工具。故现有模型无法通过原产品链路完成自然提醒管理；runner 不会代为创建/取消 Automation，也不自造工具调用证据。

这些是产品/场景语义限制，不得包装为评测 runner 权限限制或 partial pass。任何产品接线仍由总控单独分派；当前 B 不修改产品代码。
