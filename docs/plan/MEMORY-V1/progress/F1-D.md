# F1-D 进度

## F2-0 接管补记（2026-10-09）

本文件以下记录保留为 F1 历史准备状态。后续真实限 1 题还曾发生 observe HTTP 403（每题 MemoryOS 主体与旧 `atlas-fixture` 绑定不一致），隔离辅助配置未调用而超时，以及 Gemini 输出 `facet=QUESTION` 导致整批校验失败；详见 `F1-dispatch.md` 和 `05_收尾包F2.md`。主体绑定与每题 Hermes 配置调用的修补已落入运行器；NumPy 2.5.3 仅在 `D:/Temp/F1-D-official-numpy-2.5.3-py314` 的隔离 target，未安装到产品或提交源码。

截至接管审读，没有一题真实 LongMemEval 成功完成的可验收证据。来源校验、token 上界、dry-run 和运行器单测都不计为效果。`eval/scenario_judge_report.json` 是历史单次 19/30（核心 14/21、E5/E7/E8 5/9），不是 F2 的三次结果。

本轮规模以 F2 为准：只跑每类一题的 6 题冒烟和每类五题的 30 题；不运行旧文中 12/120 的执行命令。旧成本文件仅作为标明模型和时代边界的历史档案保留，不是 Gemini 实际费用。F2 的后续执行和缺口记录在 `progress/F2.md`。

状态：LongMemEval 完整 S 来源已重验；Runner、隔离 Gemini ModelRouter、逐题 checkpoint/resume、token 上界估算和 dry-run 已就绪。总控的首次真实限 1 题尝试在 evaluator import preflight 阶段失败，未启动 MemoryOS、未采集历史、未调用真实模型；缺失依赖已在 D:\Temp 隔离修复并通过纯 import/prompt 探针。真实限 1 题需用新的 run root 重跑；真实 12 题等待总控审阅及限 1 题通过，120 题只能在 12 题通过后开始。30 场景归 F1-A，未在本报告计为通过。未提交、未推送、未触碰 `CURRENT`。

## 来源和固定题单

- 完整 LongMemEval_S：`D:\Temp\F1-D-longmemeval-data-2ec2a55\longmemeval_s`，278,025,796 bytes，SHA256 `08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894`，500 条。
- 固定题单：`docs/plan/MEMORY-V1/eval/longmemeval_subset.json`，120 个唯一 ID，六类各 20 题，SHA256 `77e64a914eb3358e2e605c0b8306bc99f2dfd36f5e68cd0efd3f3d6922332bc4`。题单的 gold、原问题和类别与完整 S 匹配；运行器按 ID 绑定 canonical S 整行，使用完整 `haystack_sessions`，不使用 Oracle 缩短历史。Oracle 日期 120/120、answer session IDs 22/120 与 canonical S 不同。
- 官方 evaluator checkout：`D:\Temp\F1-D-official-longmemeval-9e0b455`，origin `https://github.com/xiaowu0162/LongMemEval.git`，HEAD `9e0b455f4ef0e2ab8f2e582289761153549043fc`，`src/evaluation/evaluate_qa.py` blob `4732f3772b04a2b9069121ade304e6320494abc2`。
- 完整 S：6,066 sessions、59,588 turns、58,765,462 chars。固定 12 题 smoke：598 sessions、5,811 turns。source validator 会在 run preflight 重查 S/subset hash、官方 remote/commit/blob 和工作树。

校验报告及原始日志：`docs/plan/MEMORY-V1/eval/F1-D-source-validation.json`、`.raw.log`。最近一次 source validation 状态为 `PASSED`。

## 官方 evaluator import preflight

总控于 `D:\Temp\F1-D-root-limit1-20261009-75b19c` 首次启动限 1 题时，Atlas ModelManager 初始化后，在载入固定 official `evaluate_qa.py` 阶段失败：`ModuleNotFoundError: No module named 'numpy'`。控制器日志为 `D:\Temp\F1-D-root-limit1-20261009-75b19c.controller.log`。失败发生在 MemoryOS 服务启动、Capture/Observer 历史导入和模型请求之前；此结果不是一次完成或失败的 benchmark 问题，旧 attempt root 保留且不复用。

固定 checkout 的 `requirements-lite.txt` 为 evaluator 依赖列出 `openai==1.35.1`、`tqdm==4.66.4`、`backoff==2.2.1` 和 `numpy==1.26.3`。本机 Atlas runner 使用 Python 3.14.7；NumPy 1.26.3 官方支持 Python 3.9–3.12，[1.26.3 release notes](https://numpy.org/doc/2.0/release/1.26.3-notes.html)，不支持当前解释器。NumPy 官方说明 2.4 及以上支持 Python 3.14，[NumPy 2.4 release notes](https://numpy.org/doc/stable/release/2.4.0-notes.html)。因此只把 `numpy==2.5.3` wheel 安装到 `D:\Temp\F1-D-official-numpy-2.5.3-py314`，并使用 `--no-deps`：这样 `PYTHONPATH` 只增加 NumPy，不会覆盖 Atlas venv 的 OpenAI/httpx/pydantic 依赖。其余顶层 imports 已存在于 Atlas venv（openai 2.26.0、backoff 2.2.1、tqdm 4.70.1）。固定 evaluator 源码不变；F1-D 只调用它的 `get_anscheck_prompt`，不执行该文件中独立的 API scoring main。

纯 import 探针以固定 checkout 的 evaluator 调用 `_load_official_module`，并生成一条 Judge prompt；结果 `PASSED`，NumPy 2.5.3、OpenAI 2.26.0、backoff 2.2.1、tqdm 4.70.1 均成功导入，prompt callable，0 model requests。探针脚本与原始输出：`D:\Temp\F1-D-official-evaluator-import-probe-20261009.py`、`D:\Temp\F1-D-official-evaluator-import-probe-20261009.raw.log`。隔离包目录没有其它 evaluator/Atlas 依赖副本。

## Runner 和模型路由

真实问答使用原始 user/assistant 历史 turn，经隔离 `CaptureService` → HTTP ACK → Atlas `MemoryObserver` → MemoryOS `/observe`；所有历史排队并且 semantic worker `READY`、pending=0 后，问题才进入 Atlas `run_phases` 的真实召回/回答入口。官方 `get_anscheck_prompt` 只在回答之后进行独立判分。答案、criteria、gold 不进入观察、记忆、检索或回答输入。

问题原文不变；canonical `question_date` 只作为单独的日期参考 skill 元信息。回答模型的 tools 禁用，避免通过文件读取绕过 Atlas 检索。每题有独立 runtime root、Atlas data/DB、Observer outbox、MemoryOS data/DB、Hermes home 和固定 subject；开跑时会检查解析后的实际存储路径在题目隔离根内。

所有答案、判分、观察和反思路由固定 `gemini-3.8-flash`，走 Atlas 用户配置的 custom ModelRouter/Antigravity endpoint。只复制 `custom_models`、`providers.custom`、`memory_model` 的安全 allowlist 到临时设置；继承的 gateway 凭据被清理，custom credential 只由 Atlas ModelManager 从 Windows Credential Manager 解析。证据只记录 model/provider/endpoint host 和 `credential_present`，不记录 key、provider secret 或敏感 URL 路径。Atlas 生产 `config.toml` 与用户设置只读。

Observer 的生产默认日预算为 50,000 tokens；隔离评测覆盖为 6,000,000，满足完整长历史输入。覆盖只写隔离内存配置，每题仍执行 durable reserve/commit/release、retry 预算和超预算保护。单题最大模型无关预算上界为 12 smoke 的 1,183,770 tokens、120 题的 1,296,512 tokens。

## 调用量和成本边界

依据完整来源字符上界和当前 Observer 单次 prompt/output 限制，严格估算每个 Observer batch 最多发生一次语言重试：

| 集合 | 题数 | Observer batches 上界 | Observer calls 上界（含一次重试） | 输入 tokens 上界 | 输出 tokens 上界 | 合计 Observer tokens 上界 |
|---|---:|---:|---:|---:|---:|---:|
| 分层 smoke | 12 | 572 | 1,144 | 8,210,518 | 4,576,000 | 12,786,518 |
| 固定全集 | 120 | 5,780 | 11,560 | 82,414,616 | 46,240,000 | 128,654,616 |

每题另有一次 answer 和一次 official judge 调用；reflector 是否及何时触发遵从 production 阈值/idle 规则，不按题目强制触发。上表仅是 Observer token 上界，答案、判分、反思实际 usage 按每次 provider 返回值记录。当前 Antigravity proxy 单价未知，因此 estimated USD 明确为 `null`，不以 `$0` 代替未知价格。用户已明确解除旧的 `$20` 阻断；旧 DeepSeek 校准和旧成本停止线标记为 `SUPERSEDED_BY_USER20261009`，不得作为当前模型或成本依据。

新 token-only 估算与原始输出：

- `docs/plan/MEMORY-V1/eval/F1-D-token-bounds-smoke.json`、`.raw.log`
- `docs/plan/MEMORY-V1/eval/F1-D-token-bounds-full.json`、`.raw.log`

此前 `F1-D-cost-*` / `F1-D-cost-*-retry-upper` DeepSeek 金额文件仅保留历史，不代表 Gemini 网关账单或本轮授权边界。

当前没有真实 Gemini 请求，因此无法给出有证据的 wall-clock 预测。120 题预计至少要处理 6,066 个历史 session、5,780 个 Observer batch，严格重试上界为 11,560 个 Observer 模型调用，再加 240 个 answer/judge 调用及真实触发的 reflector 调用。第一次获准的 12 题会记录总耗时、每阶段耗时、单次模型延迟和每题吞吐，再据此给 120 的带假设估算；不会把未测时长写成事实。

## Checkpoint 和失败恢复

- 每题成功后先原子写 `question-<id>/result.json`，再 flush + fsync 根目录 `raw_output.jsonl`。恢复时检查两份记录一致；有 checkpoint 但 journal 尚未写入时会补写 journal，不会重新导入该题历史。
- 某题失败时保留其 runtime 根、题目级 `failure.json`（若该根已创建）、根级 `failures.jsonl` 和 `summary.json`；状态为 `FAILED_ATTEMPT` / `FAILED_QUESTION`，保留脱敏后的异常类型和根因。失败题不会计入完成/通过。
- 恢复必须指定一个全新的 `--run-root` 和旧根 `--resume-from`。只将旧根内完成且校验一致的结果 checkpoint 带入新 attempt；unfinished、失败 journal 或不完整题根会被标为 retry 并在新题目隔离根重跑。旧根不改写，失败题不会在同一 root 重复导入。resume 会核对题单、完整来源、官方 evaluator、模型、配置 hash、预算、服务端口和解释器身份；不一致就拒绝导入。
- 当前 resume 走代码单测覆盖；真实断网/服务中止后的恢复证据要由 12 题运行生成。不能删除失败题、静默重试或将缺结果题计为 PASS。

## 可复跑命令和验证

Python：`D:\Atlas\core\.venv\Scripts\python.exe`。

来源验证：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\validate_longmemeval_f1.py' --source 'D:\Temp\F1-D-longmemeval-data-2ec2a55\longmemeval_s' --subset 'D:\Atlas\docs\plan\MEMORY-V1\eval\longmemeval_subset.json' --output 'D:\Atlas\docs\plan\MEMORY-V1\eval\F1-D-source-validation.json'
```

当前 12 题 dry-run（不会创建 run root、不会启动服务或调用模型）：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\run_longmemeval_f1.py' --source 'D:\Temp\F1-D-longmemeval-data-2ec2a55\longmemeval_s' --subset 'D:\Atlas\docs\plan\MEMORY-V1\eval\longmemeval_subset.json' --validation 'D:\Atlas\docs\plan\MEMORY-V1\eval\F1-D-source-validation.json' --official-root 'D:\Temp\F1-D-official-longmemeval-9e0b455' --limit 12 --observer-daily-token-budget 6000000 --run-root 'D:\Temp\F1-D-real-20261009-gemini12'
```

本轮 dry-run 状态 `READY_DRY_RUN`；六类各 2 题，598 sessions、5,811 turns；S hash、固定题单 hash、官方 commit/blob 均匹配；每题隔离路径和 gold 边界已进入报告。原始输出：`F1-D-runner-dry-run-gemini.raw.log`；结构化输出：`F1-D-runner-dry-run-gemini.json`。计划根尚未创建。

真实 12 题命令模板（等待总控给服务端口和启动信号）：

```powershell
& 'D:\Atlas\core\.venv\Scripts\python.exe' 'D:\Atlas\scripts\memory_v1\run_longmemeval_f1.py' --source 'D:\Temp\F1-D-longmemeval-data-2ec2a55\longmemeval_s' --subset 'D:\Atlas\docs\plan\MEMORY-V1\eval\longmemeval_subset.json' --validation 'D:\Atlas\docs\plan\MEMORY-V1\eval\F1-D-source-validation.json' --official-root 'D:\Temp\F1-D-official-longmemeval-9e0b455' --limit 12 --run-real --service-port <总控协调端口> --service-python 'D:\Temp\F1-A-cuda-20261008-174500\venv\Scripts\python.exe' --observer-daily-token-budget 6000000 --run-root 'D:\Temp\F1-D-real-20261009-gemini12'
```

12 题通过后启动 120 题时，使用 `--limit 120 --full-evaluation`、新的唯一 `D:\Temp\F1-D-*` 根和总控协调端口。若失败则从失败根调用 `--resume-from <旧根>` 并新建唯一 attempt 根；每题结果按原 ID checkpoint，不重复成功题的导入/观察。

已运行验证：`python -m unittest test_longmemeval_f1_runner test_longmemeval_cost_estimate test_f1_gemini_runtime test_real_memory_process_lifecycle -v`，27 passed；对 runner、Gemini helper、RealMemoryService、估算器和相关测试运行 `py_compile`，通过。独立 Gemini helper 测试 8 passed，不再 import Long runner。

本轮 D 所有权文件：`scripts/memory_v1/run_longmemeval_f1.py`、`scripts/memory_v1/gemini_runtime.py`、`scripts/memory_v1/real_memory.py`、`scripts/memory_v1/estimate_longmemeval_f1_cost.py`、`scripts/memory_v1/test_longmemeval_f1_runner.py`、`scripts/memory_v1/test_f1_gemini_runtime.py`、`scripts/memory_v1/test_real_memory_process_lifecycle.py`、`scripts/memory_v1/test_longmemeval_cost_estimate.py`、本报告及上述 `F1-D-*` source/token-bound/dry-run 产物。`eval_scenarios.py`、F1-A 报告、F1-B 语言文件/报告和既有 `scenario_judge_report.json` 不在本 lane 修改范围。
