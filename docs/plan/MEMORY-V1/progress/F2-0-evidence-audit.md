# F2-0 证据与工作区只读审计

日期：2026-10-09。审计范围：Atlas 指定的 F1-D 评测证据、F1-B/dispatch 进度记录、scenario judge 汇总，以及 MemoryOS 全部 tracked 未提交 diff 和未跟踪文件来源。除本报告外，本审计没有写产品代码、历史文件、CURRENT、生产数据或生产配置，也没有提交。

## 结论

F1-D 文件把真实基准成绩和准备性证据分开：9 份 JSON 与相邻 9 份 `.raw.log` 状态一致，分别是 `ESTIMATE_ONLY`、`READY_DRY_RUN`、`PASSED`（仅 LongMemEval 来源校验）和 `TOKEN_BOUND_ONLY`。没有真实 LongMemEval 题目结果、模型请求成功数或 benchmark pass；dry-run 指向的计划 run root 不存在。不得把来源校验、预算估算、dry-run 或单测结果写成 F1-D 效果通过。

有两项 Atlas 记录提交前要更正/确认：`progress/F1-D.md` 只记录 NumPy import 失败，没有记录 `F1-dispatch.md` 后续写明的真实 observe HTTP 403；它将真实限 1 题写成等待重跑，时间线已过时。`eval/scenario_judge_report.json` 的 30 条与摘要内部一致，是一组 19 PASS / 11 FAIL 的单次结果，不含 3 次试验；E1–E4/E6 为 14/21（66.67%），E5/E7/E8 为 5/9（55.56%），均未达门槛。它不能替代正式 30×3 结果，提交前须补来源/运行标识或明确标成历史单次结果。

总控源码审查发现 `eval_scenarios.py` / `scenario_actions.py` 原先以 scenario ID 分支控制 S27/S29/S30 能力。已按 runtime capability 和场景声明文件改造，保留原 manifest hash；定向验证见文末。该改动不改变这里记录的基准证据状态。

## Atlas 逐文件审读

### `eval/F1-D-*.json` 与同名 `.raw.log`

每对文件的 JSON `status` 与原始日志中的 status 相同；日志未见 `Traceback`、`FAILED`、`ERROR`、`ModuleNotFoundError` 或 `APITimeoutError` 字样（历史失败根因仅在进度文档与 D:\Temp 失败记录中）。文件清单与判定如下：

| 文件（每行 JSON + `.raw.log`） | 内容/实际状态 | 建议 |
|---|---|---|
| `F1-D-cost-smoke.json`、`F1-D-cost-full.json` | 12 / 120 题 `ESTIMATE_ONLY`；以 DeepSeek-v4.1-flash 的 F1-B usage 校准，非 Gemini 账单。 | 可作为明确标注为历史估算的档案；不得作为本轮预算或真实费用。 |
| `F1-D-cost-smoke-retry-upper.json`、`F1-D-cost-full-retry-upper.json` | 同上，包含每批一次重试上界；DeepSeek 直供上界分别 USD 3.2524 / 32.6939，代理 all-in 费用未知。 | 必须保留历史/过时边界标签；120 题上界不可用于声称已获费用证明。 |
| `F1-D-token-bounds-smoke.json` | 12 题、572 batch、1,144 次 Observer 调用上界、12,786,518 Observer token；Gemini、proxy 价格 unknown、USD 未估算。 | 可提交为 token-only estimate，非模型效果/实耗。 |
| `F1-D-token-bounds-full.json` | 120 题、5,780 batch、11,560 次 Observer 调用上界、128,654,616 Observer token；USD 未估算。逐题输入/输出合计与总计一致。 | 可提交为 token-only estimate，不能作为 120 题费用批准或成绩。 |
| `F1-D-runner-dry-run.json` | `READY_DRY_RUN`，12 个固定题、598 sessions、5,811 turns；答案不进入 Observer/chat 输入。 | 仅 runner preflight。 |
| `F1-D-runner-dry-run-gemini.json` | 同为 `READY_DRY_RUN`，模型路由元数据指向 Gemini；不是 Gemini 模型请求。计划 run root `D:\Temp\F1-D-real-20261009-gemini12` 实测不存在。 | 仅 dry-run；不得声称已启动服务或调用模型。 |
| `F1-D-source-validation.json` | `PASSED`：完整 LongMemEval_S 与 subset、canonical ID/类别来源和固定 evaluator source 校验。 | 可作为来源校验；不是效果成绩。 |

旧 cost 文件的模型字段均为 `deepseek-v4.1-flash` 且 `provider_reported_cost_present=false`；新 token-bound 文件模型为 `gemini-3.8-flash`、代理价格 unknown。`F1-D.md` 明确说明两者边界，不能把旧 DeepSeek USD 数字移作 Gemini 网关费用。

### 进度与 scenario judge 文件

- `progress/F1-D.md`：对完整 S、固定题单、官方 evaluator、隔离边界、预算上界、checkpoint 设计及 dry-run 的描述，与相应 source-validation/token-bound/dry-run 文件一致；其真实尝试时间线缺少后续 403，必须更新后再提交。当前没有一题成功的真实 LongMemEval 结果。
- `progress/F1-D-actions.md`：17 个 adapter 单测的声明清楚限定为 fake/contract coverage，报告真实隔离 action 验收仍未完成；没有将单测写成真实效果。`S29` 端点能力限制也被保留为失败条件。
- `progress/F1-D-scenarios-runner.md`：明确没有正式 30×3 或 Judge 验收；两次 S27 canonical 运行均非正式验收，第二次记录目标缺少前置原始输入、删除 action 失败、Gemini 回答当前无家庭/孩子事实，不能算通过。诊断数据写在 D:\Temp 隔离 root。
- `progress/F1-B.md`：把旧 DeepSeek 结果标为历史，Gemini 部分记录 30 个成功样本/31 条中文 Observation，并保留另一次真实超时和未落盘 usage 的限制；费用为未知。另补充首组 Hermes 根未隔离的边界和后续脚本修正，没有声称旧调用已具备完整 Hermes 隔离。
- `progress/F1-dispatch.md`：记录真实限 1 题 NumPy 缺失及后续 403，二者都是失败尝试、正式 12/120 未启动；但其中“B 正修 runner”需在后续修复后更新状态。
- `eval/scenario_judge_report.json`：30 条 verdict 与 summary 一致：19/11；分组 14/21 与 5/9，`threshold_met=false`。比较 HEAD 后只有四条 verdict 改动（19、23、29 由 PASS 转 FAIL；21 由 FAIL 转 PASS）。它没有重复试验或 F2-B run ID；保留为单次历史数据，禁止作为 F1-D 完成证据。

### 来源、隔离与敏感内容检查

`F1-D` 证据引用 LongMemEval_S 公开基准来源、固定题目 ID/hash、官方 evaluator commit/blob、session/turn/token 汇总；没有 Atlas/MemoryOS 生产数据库或生产对话 payload。目标文件上扫描常见 OpenAI/Google/GitHub key、Bearer token、API secret 赋值及 `D:\MemoryOSData` / Atlas 生产 DB 路径模式均无匹配；扫描是格式模式检查，不等于对所有可能密钥格式的数学证明。F1-D JSON/raw log 内容未发现实际 API key 或私人生产输入。

`D:\Temp\F1-D-official-numpy-2.5.3-py314` 是 CPython 3.14 Windows wheel 的临时 target（METADATA 为 NumPy 2.5.3，`cp314-cp314-win_amd64`），版本/来源元数据指向 NumPy/PyPI。仓库中没有此目录、wheel、NumPy vendor 文件，也没有把该 Temp 路径写进 Atlas source；它只用于固定 LongMemEval evaluator 的隔离 import probe。D:\Temp 的探针脚本和 wheel 均不属于提交路径。

对 `D:\Temp\F1-D-gemini-prep-20261009\memory_v1` 快照与当前 Atlas 源码按 SHA-256 对比：`real_memory.py` 相同；`run_longmemeval_f1.py` 与 `eval_scenarios.py` 不同。旧 runner 快照固定 `atlas-fixture`，当前 Atlas runner 使用 `_question_subject_id(qid) = f1d-{qid}`，并将同一值用于 MemoryOS root 和 capture binding，修复 subject mismatch 的代码已落入 Atlas；但真实修复后成功运行证据仍缺失。旧 runner/env 只有隔离 `HERMES_HOME`，当前 `run_longmemeval_f1.py` 增加每题 config 写入与 readback，设置无 fallback、`memory_observe`/`memory_reflect` 120 秒；`eval_scenarios.py` 也增加 `_write_isolated_hermes_config()` 并在真实场景启动前调用。相关配置修补已在 Atlas 源码，只有隔离 runner 生效，不改变产品配置。F1-B 的 `scripts/f1_language_smoke.py` 另有独立 HERMES_HOME 根隔离修正。NumPy 包本身没有落入 Atlas 源码/生产环境。

## MemoryOS 未提交内容逐文件/来源清单

审计快照：6 个 tracked modified 文件，3,318 个 untracked files。tracked diff 全部属于其他 MEMORY-V1/P1/P2B 历史工作或独立 plan 状态，没有 MemoryOS F2 必需改动；MemoryOS 本轮无允许提交路径。

Tracked diff：

| 路径 | 来源/内容 | F2 分类与建议 |
|---|---|---|
| `docs/plan/MEMORY-V1/CURRENT.json` | 另一条 MemoryOS orchestration run 的 `RUNNING` reason 更新，指向其 `ORCHESTRATION_BLOCKED.md`/`DISPATCH.md`。 | 非本包允许改动；F2 收尾任务要求由总控统筹更新 CURRENT。本包只读保留此现状，交总控在 F2 收尾时核对后更新。 |
| `recovery/memory_intelligence_p2b_model_shootout/benchmark_ground_truth_audit.json` | P2B 模型 shootout benchmark case hash / expected-count audit。 | 历史 P2B，排除。 |
| `recovery/memory_intelligence_p2b_model_shootout/benchmark_v2_manifest.json` | P2B V2 已退休 benchmark manifest / 校准状态。 | 历史 P2B，排除。 |
| `recovery/memory_intelligence_p2b_two_stage/P2B_TWO_STAGE_RESULT.md` | 已提交推送的 two-stage P2B 结果收尾记录。 | 历史 P2B，排除。 |
| `recovery/memory_intelligence_p2b_two_stage_fix2/P2B_TWO_STAGE_FIX2_RESULT.md` | 已提交推送的 P2B fix2 结果及 holdout=0 说明。 | 历史 P2B，排除。 |
| `tests/evidence/HARD_ERASE_E2E_EVIDENCE.json` | 2026-09-25 的隔离 hard erase E2E 结果从 65 增到 68 checks，包含 Temp 隔离路径与合成 source/barrier ID。 | 历史证据而非 F2；含本机路径/运行细节，排除本次提交。 |

Untracked family counts: `artifacts/` 2,197; `recovery/` 158; `work/` 962; `tests/benchmark_memory_intelligence_p1a5.py` 1. These are historical/generated suite output, DB artifacts, recovery traces, benchmark results, snapshots, pytest basetemp data, temporary scripts and source snapshots; none is F2 deliverable. DBs, traces, run output and snapshots may contain test memory or private benchmark content, so exclude them. Only path/family provenance was inspected; the untracked files were not individually content-reviewed. Complete path inventory: `D:\Temp\F2-0-history-inventory.json` (3,318 paths; SHA-256 `F674DB15E7EAC73F4ABD6CBA3A8AF71FC0F335CE424D9CAAEA0EE83A4C6B851E`). No untracked MemoryOS file is recommended for F2.


## F2-0 ID 分支返工与验证

- `ScenarioSpec` 增加 `runtime_capabilities` 与 `workspace_files` 运行时声明，并在 canonical manifest serialization 中排除这两个运行时字段。场景 27 声明 `hard_erase`，场景 29 声明 `reminder_readonly_audit`，场景 30 声明 `workspace_write_tools`、`owned_process_kill` 及原任务请求的 `docs/file1.md`、`docs/file2.md`、`docs/file3.md`。运行时 setup 只按这些声明设置 hard-erase flag、提醒审计、workspace 文件与工具权限。
- `kill_process` 不再检查 scenario ID；它要求声明 `owned_process_kill`，仍限定 runner-owned workspace/lifecycle，并从声明的 workspace 文件中验证任务第一个文件确实存在。不会读取 payload 中的 PID 或 completed_steps。
- 定向测试先红（6 项新行为测试失败，原因是无 capability 声明/行为仍按 ID 选择），修改后绿：`test_eval_scenarios_runner.py` 与 `test_scenario_actions.py` 共 **33 passed**；`test_original_30_scenario_manifest_is_unchanged` 通过，manifest SHA-256 仍为 `6abdefcaaab706dd690527a2c305defd43f5d53a556315d0553988e38ea8d1fa`。`git diff --check` 通过；对两个实现文件检索 `scenario.id ==/!= 27/29/30` 与 `ctx.scenario_id ==/!= 27/29/30` 无匹配。总控另回报独立复跑 6 个脚本测试文件 **56 passed in 2.09s**，JUnit `D:/Temp/F2-0-controller-final/junit.xml`（该 JUnit 未由本审计代理独立读取）。
- 这不是正式模型评测或 30×3 证据；本包未触发真实模型调用，未启动服务，未提交。

后续 F2-B 仍须修通用 runner 路由与动作权限：当前自然聊天 run 对 S30 以外场景设 `read_only` / `tool_deny=["*"]`，因此 S29 提醒用例不能依赖真实 Automation tool；每轮固定 Gemini 也会让 S3 model-switch 无法验证跨轮当前模型。F2-B 还须在下一轮前等待真实 outbox drain/semantic worker READY。旧 `real_memory.to_observation()` 使用 `USER_ASSERTED` 的 helper 不在新版 `eval_scenarios` 调用链；本报告不把它表述为预置评测历史或有效运行路径。

