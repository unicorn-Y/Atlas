# ZCode · GLM-5.3-Flash 任务书｜官方 DSH 基准更新与 Atlas 第一批验收

> 全量执行从[官方 DSH 与 Atlas 全量任务书](2026-11-18-zcode-glm-full-dsh-atlas.md)开始。本文件提供基准差异盘点与尝试生命周期验收的具体命令。

> 请在 ZCode 使用 **GLM-5.3-Flash** 执行本任务书。工作区是 `D:\Atlas`。直接按步骤取证并交付文件。已有 Atlas 工作继续归原作者，当前批次由你负责版本对账、验收和定位缺口。

## 目标

总目标是让 Atlas 覆盖最新版官方 DeepSeek Harness 的全部可确认能力，并验证 Atlas 的额外能力和同场景优势。本批交付两个结果：一份可复现的官方版本与变更清单，以及一份流式取消、重试、重开会话的前后端验收结果。两个结果分别交付，真实运行条件缺失时保留已取得的证据，并继续另一条工作。

主计划位于 `D:\Atlas\docs\glm-hammer\plans\2026-11-17-atlas-dsh-atomic-parity-and-superiority.md`，本批只执行对应 Task 1 的版本差异盘点，以及 Task 2 的指定验收路径。按需读主计划这两节。

## 文件与工作边界

- 在 `D:\Atlas\tasks\dsh-parity\zcode-glm-20261118\` 下交付 `BASELINE.md`、`UPSTREAM-DELTA.tsv`、`ATTEMPTS.md`，以及用于复验的少量脱敏证据，放在 `evidence\`。只有这个新目录归你写入。脚本、安装包和试验数据放独立临时目录，交付物记录复现命令。
- 先读 `D:\Atlas\AGENTS.md` 和 `D:\Atlas\Atlas.md`。主工作区与已有 worktree 只读检查和运行隔离测试。保留已有未提交文件。测试使用临时数据目录和空闲端口。用户配置、账号、长期记忆、现有安装和正在运行的进程按原状态保留。
- 执行前记录工作区路径、分支、完整 HEAD、影响验收的已修改及未跟踪路径。当前工作区近期在 `wave3@060071ab`，含未提交的尝试取消、恢复和审计器工作。ZCode 如果自动建工作树，先核对测试文件及实现是否在里面，结果写明跑的是哪个快照。两个快照的结果各自标注。
- 参考入口依次是 `docs/parity/DSH-GAP-LEDGER.md`、`tasks/dsh-parity/atomic/completion.json`、`tasks/dsh-parity/atomic/batches/T2-CANCELLED-STREAM-WORKER-045.md`。优先读摘要和目标行。用程序汇总变更、索引和台账，只输出相关条目和计数。`source-index.json` 约 364 MiB，避免整文件送进模型。

## A. 固定官方 DSH 基准并交付版本差异清单

- [ ] **确认版本。** 从 [官方 GitHub 发布记录](https://github.com/deepseek-ai/deepseek-harness/releases)、[npm](https://www.npmjs.com/package/@deepseek-ai/dsh?activeTab=versions) 与 [官网下载页](https://www.deepseek.com/download/) 分别查官方版本。上次观察是 GitHub `dsh-v0.2.2-rc.4`，npm `next` 为 `0.2.2-rc.4`、`latest` 为 `0.2.2-rc.1`，本机桌面 `0.2.2-rc.2`。在 `BASELINE.md` 记录实际查到的日期、Git 标签及解析后的完整 commit、npm dist-tag 与包版本、官网 Windows/macOS 下载入口和各自能查证的版本。Windows 安装包可取到时保存在临时目录，记录 SHA-256、文件版本及可读取的内置 runtime 版本。macOS 只取公开或静态证据。官网链接文件名和源码标签各有独立证据。
- [ ] **从旧基准对账到新标签。** 旧基准为 `d743267388641bc76f17c45ce8b4c231aed1d32c`，现有参考仓库是 `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`。在临时目录取官方对象，校验两个 commit 后，用 `git diff --name-status --find-renames <旧commit> <新commit>` 比较两个端点。用 `git ls-tree -r --name-only <新commit>` 汇总各顶层目录，另比较 workspace 包清单。给每个变更文件或改名对写一行。核对总行数，包括新增、修改、删除及改名。对新、改、删的产品行为写入对应行，允许多文件共用同一个功能 ID。按层统计桌面/前端、CLI、Host/Agent、API/协议、插件、原生、构建发版、测试/文档。对模型异常响应和 LiveShare 桌面分享等发行说明涉及的行为，追到具体入口和实现。LiveShare 取源码和文档证据即可。
- [ ] **映射到 Atlas。** `UPSTREAM-DELTA.tsv` 列名为 `change_type`, `old_path`, `new_path`, `surface`, `behavior_id`, `behavior_or_reason`, `dsh_evidence`, `atlas_path`, `atlas_state`, `next_check`。Atlas 状态用 `已有证据`、`部分`、`缺失`、`待核`、`仅工程变更`。每个结论有路径、符号或测试作为证据。判断缺失前查同一功能的现有工作区改动及 `wave4` 独有提交中相关路径，找到实现时标明所在工作树和集成状态。`BASELINE.md` 汇总各类别和状态的计数，列出最先值得做的三项差距、对应代码入口和可执行验收。旧 `128/135` 仅沿用为历史口径。源文件计数、候选行为计数及已验证能力计数分别记录。

**A 验收**　标签、包和安装包能分别定位，变更表项能和差异命令对齐，产品行为有 DSH 证据和 Atlas 状态。暂未查到的安装包信息或行为要注明缺少的证据。已有源码差异可先交付。

## B. 复跑流式取消、失败重试和会话恢复

- [ ] **先跑当前自动化证据。** 从 `D:\Atlas\core` 运行以下测试。保存命令、执行快照、退出码和通过/失败计数。取消用例使用真实 SDK 和 app-server 子进程，以及本机受控模型替身。核对临时片段、回滚顺序、最终历史与失败审计的断言。

  ```powershell
  $env:PYTHONDONTWRITEBYTECODE = '1'
  python -m pytest -q -p no:cacheprovider -o addopts= --tb=short tests/test_event_contract.py tests/test_kernel_recovery.py tests/test_retry_attempt_isolation.py tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_cancel_rolls_back_partial_attempt_and_persists_only_audit tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_subprocess_commits_only_new_attempt_and_reopens_audit tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_fallback_attempt_isolated_across_process_restart
  ```

  从 `D:\Atlas\frontend` 运行渲染事件与时间线投影测试。根目录依赖已存在时可运行如下命令。

  ```powershell
  & '..\node_modules\.bin\vitest.cmd' run --root . src/renderer/services/runtimeEvents.test.ts src/renderer/components/timelineProjection.test.ts
  ```

- [ ] **跑真实桌面路径。** 先查可用的 Atlas 和 DSH 构建与版本。优先使用打包桌面端，条件允许时在隔离测试工作区和测试配置中接入可控的 loopback 模型替身。重试用例里让首次请求发出 `ATLAS_OLD_ATTEMPT` 后失败，下一次请求只返回 `ATLAS_NEW_ATTEMPT`。取消用例里让响应先发出 `ATLAS_CANCELLED_ATTEMPT` 后保持流打开，从桌面点停止。记录以下观察，逐项注明是打包端、开发版、SDK、还是源码证据。

  | 场景 | Atlas 要核对的结果 |
  |---|---|
  | 用户停止流式输出 | 临时片段确实先显示。同一尝试的回滚在终止事件前到达。停止后的桌面正文无该片段，停止终态可见。 |
  | 失败后重试成功 | 首次失败片段不会与成功回答拼接。桌面最终正文和会话历史只保留成功尝试的文本。 |
  | 关闭后重开会话 | 用户可见历史与最终状态一致。失败或取消尝试的审计存在，记录和正文能区分。受控请求次数和子进程退出符合预期。 |

  在官方 DSH 上尝试同一操作，标记实际使用的版本，记录它的实际保留与恢复语义。两个产品能用同一个替身或同一个已授权的 provider/model 时才做直接对照。已有授权且能安全使用独立测试会话时，每个产品最多补一个真实模型回合，记录版本、模型名和终态。受控模型用例承担可重复的失败和竞态覆盖。
- [ ] **把证据接起来。** `ATTEMPTS.md` 逐项写 `场景 → 可见入口 → 事件顺序 → 后端终态 → 重开后的正文与审计 → 证据 → 状态`。重点沿 `core/atlas/engine/kernel/model_call.py`、`core/atlas/engine/kernel/loop.py`、`core/atlas/agent/run_phases.py`、`core/atlas/api/run_drive.py`、`frontend/src/renderer/services/runtimeEvents.ts`、`frontend/src/renderer/components/timelineProjection.ts` 追链。可以复用历史回执作索引，现场新结果单列。桌面无法启动、版本落后、provider 不可用或缺权限时，写清尝试、错误、影响和复验条件。
- [ ] **找到失败就给出具体后续任务。** 对能复现的产品缺口写最短复现、首次丢失或错误投影的代码位置、预计改动文件和应加入的回归断言。若是环境问题，区分默认环境和临时修正后的复跑。审计器默认 Windows 路径曾选中不可用的系统 Bash，单次测试进程优先使用 `C:\Program Files\Git\bin` 后曾通过。若遇到相同症状，用 `Get-Command bash` 与 `bash --version` 复核。

**B 验收**　每个场景都有实际结果，或给出可复现失败与具体阻塞证据。FakeLLM/SDK、开发版、打包端和真实模型各自单列。登记优势须固定双方版本，并具备同条件、可复验的比较证据。

## 交付给主控

- [ ] 复核三份文件相互引用，随机抽查前端、后端、发版各一条映射，检查证据链接、退出码和脱敏。确认 Atlas 生产代码无本批写入，并报告遇到的并行工作区变化。
- [ ] 最终回复列出三个文件的绝对路径，给出实际基准版本、本批测试与复现结果、阻塞项、下一批最小可执行改动。全量对齐和全量超越由总台账及后续验收裁定。
