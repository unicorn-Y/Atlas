# W2 — Agent 内核与执行可靠性审查

Review date: 2026-10-17  
Reviewed baseline: `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`  
Review worktree: detached `D:\atlas-luna-w2-20261017`, created from that exact commit.  
Host status: `D:\Atlas` was `ui-redesign` at the same commit with tracked modifications and untracked files. No host changes were made. The specified host-side `expert_harness.py` and `research/` additions were read-only inputs. Whether the running process uses this worktree or the host overlay remains unverified by W2.

## 审查范围与证据边界

W2 的源码根判断更新：主执行者确认运行进程的源码根目录是 `D:\Atlas`；但该进程实际加载的字节是否对应 `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f`、还是加载了主目录 tracked dirty/untracked 覆盖，仍未能确认。因此下文将“源码根已确认”和“运行字节未确认”分开陈述。

Static review covered the kernel run loop and state machine, streaming/tool result de-duplication, cancellation and pause paths, child agent delegation and worktree isolation, durable workflow scheduling, persistent scheduler and automation entry points, heartbeat/evolution state, review/rewind lifecycle modules, persistent agent profile storage, and the host-only expert/deep-research additions. No user data under `D:\Atlas\data` was read. No tests, application process, scheduler dispatch, model request, or real-data operation was run. Findings below are code-confirmed behaviors; no local runtime reproduction is claimed.

## 结论摘要

基线内核确认两项代码缺口：运行中的工具批次没有受 run cancel event 监督，Stop 可能要等长工具返回才生效（W2-001，P1）；编辑文件后模型可以直接结束，而当前默认 AtlasKernel 未连接现存的 edit-before-stop 验证提醒（W2-002，P2）。独有 `codex/desktop-repair-20261013` 分支没有修复这两项，并且移除了工具结果去重和流式准备进度，另有一项候选集成回归风险（W2-003，P2）。`p11b-worker-leftover` 是空提交。

所有判定来自源码链；没有现场复现。主执行者确认进程源码根为 `D:\Atlas`，但实际加载的 Git/dirty 字节仍未知，因此不能把基线或任一候选分支直接认定为运行版本。

## 问题

### W2-001 — run cancel event 未监督正在执行的内核工具批次

- 优先级：P1
- 领域：运行取消 / 长时工具
- 症状：工具运行期间用户请求停止时，kernel 仍等待整个工具批次。如果工具没有继续发事件，也不自行轮询取消信号，API 要等工具返回后才能观察到停止。长等待、deep research 或卡住的扩展调用因此可能在 Stop 后仍让 run 保持运行。
- 运行影响：主执行者确认源码根是 `D:\Atlas`；实际进程加载的 commit/dirty overlay 字节未知。若加载 `ui-redesign` 基线，该代码路径受影响。
- 证据：
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/kernel/loop.py:1496-1505`, `AtlasKernel.run`: starts `tool_task`, then waits only for `{tool_task, queue_get}`. The model-stream path at `1178-1181` separately includes `cancel_waiter`, showing cancellation is supervised during model requests but not tool batches.
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/kernel/loop.py:2394-2423`, `_dispatch`: delegates to `agent._execute_tools_node`; the active tool await is owned by that task.
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/agent/tool_node.py:261-267`, `execute_tools_node`: checks cancellation before starting a tool and waits on pause, but the shown guard does not race the running tool await against cancellation.
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/api/run_drive.py:166`, stop command sets `run.cancel_event`; `2268-2278` defines cooperative cancellation checking; `2707-2710` invokes it only after the orchestrator yields an event.
  - Host-only dirty overlay `D:\Atlas\core\atlas\agent\tool_node.py:1240-1253` dispatches `deep_research` and awaits `run_deep_research_tool`; `D:\Atlas\core\atlas\research\tool.py:57-80` does not accept/pass a cancel event, and its tool description says it can take 1–5 minutes. This is an example of a long call exposed by the dirty overlay, not part of the reviewed commit.
- 分类：源码确认；未作隔离运行复现；实际运行影响待核实。
- 最小处理：让 kernel 工具批次等待 run cancel event。取消时通知可取消的子操作、停止启动新调用、等待并记录已结束结果、保留部分输出，再以 cancelled/interrupted 结束。不得自动重跑已取消且有副作用的调用。
- 复用：模型流现有 `cancel_waiter` 路径和 workflow 工具取消 watcher（`core/atlas/kernel/workflow_tool.py:185-225`）。
- 复杂度：M。
- Worker：W2。

### W2-002 — 当前 kernel 路径漏接现有 edit-before-stop 验证提醒

- 优先级：P2
- 领域：如实结束 / 编辑后验证
- 症状：代码修改工具成功后，模型可以直接给最终回答结束，而没有机械提醒它运行相关检查。是否验证依赖模型自行记住，因此未验证的修改也可能以正常 completed 结束。
- 运行影响：若当前进程加载 `ui-redesign` kernel 路径则受影响；实际加载字节待核实。
- 证据：
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/engine/hermes_runtime.py:864-867,967,985`, `run_turn`: validates Atlas inputs, creates `AtlasKernel`, and forwards its events; line 522 states the old Hermes AIAgent path was removed.
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/kernel/loop.py:1593-1604`, `AtlasKernel.run`: transitions to `DONE`, records `run_end status="completed"`, and emits the result after the model reaches its stop condition. No changed-path/verification gate is referenced in `core/atlas/kernel/`.
  - `ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f` — `core/atlas/agent/run_phases.py:929-949`, `_phase_finalize`, contains the existing soft `run_verify_nudge` behavior, while `agent/tool_node.py:1340-1359` tracks changed paths and verification for that legacy path. The current `HermesRuntime.run_turn` path above uses `AtlasKernel` instead.
  - Historical clue requalified against current code: `tasks/reviews/ATLAS-C1-HERMES-CORE.review.md` records the earlier Hermes stop-gate integration; that evidence does not establish the gate is connected to the current kernel entry point.
- 分类：当前 kernel 代码缺口确认；未运行时复现误报完成。
- 最小处理：将已有 changed-path 与成功检查证据接入 kernel finalize；代码改动仍未验证时发出相同的有界提醒。除非产品契约另行定义目标成功，否则保留 `run.completed` 仅表示本轮终止。
- 复用：`agent/verification_stop.py`、`agent/tool_node.py` 的路径变更跟踪、旧 `run_phases._phase_finalize` 提醒。
- 复杂度：S–M。
- Worker：W2。

## 覆盖矩阵

状态说明：以下均为静态入口/调用链核查；没有启动 Atlas、调用真实模型、触发真实工具、调度任务或访问真实数据。`D:\Atlas` 的主进程源码根由主执行者确认，进程加载字节未知。

| 要求域 | 当前基线入口与调用链（完整相对路径:行） | 审查判定与边界 |
|---|---|---|
| 生命周期：取消、暂停、恢复 | `core/atlas/api/run_drive.py:166,2268-2278,2707-2710` → `core/atlas/engine/hermes_runtime.py:864-867,967,985` → `core/atlas/kernel/loop.py:219-244,1178-1181,1496-1505` → `core/atlas/agent/tool_node.py:261-267` | 安全点会响应 pause/cancel；模型流请求有 cancel waiter；正在执行的通用工具批次没有 race cancel waiter，见 W2-001。实际长任务延迟未现场测量。 |
| 流式消息与工具调用去重 | `core/atlas/kernel/loop.py:472-525,1070-1120,1483-1516` → `core/atlas/agent/tool_node.py:203-257,315-364,1409-1419` | 基线按 call id 记录已转发 tool result，避免队列事件和批次聚合重复输出；未发现基线确定性重复。desktop-repair 分支删掉该去重路径，风险见“独有分支复核”。 |
| 长任务 / 后台进程 | `core/atlas/kernel/loop.py:1496-1505` → `core/atlas/kernel/exec.py:90-161,341-350` → `core/atlas/agent/tool_node.py:261-267`；主目录 overlay：`D:\Atlas\core\atlas\agent\tool_node.py:1240-1253` → `D:\Atlas\core\atlas\research\tool.py:57-80` → `D:\Atlas\core\atlas\research\deep.py:229-254,256-281,317-363,442-502` | 进程管理器跟踪 watcher，并在非 detached 执行的 shutdown 路径清理；kernel 通用工具等待仍受 W2-001 影响。untracked deep_research 会做模型请求及 web 搜索/抓取，代码未见对研究结果作持久化写入；其调用不接收 run cancel event，因此 Stop 可能只在研究调用结束后生效。未执行该工具，未访问其任何真实数据。 |
| 并行子代理与隔离 | `core/atlas/agent/tool_catalog.py:302-415` → `core/atlas/agent/tool_node.py:725-960` → `core/atlas/agent/enrichment.py:830-900,960-1000` → `core/atlas/agent/subagent_worktree.py:237-336`；workflow：`core/atlas/kernel/workflow_tool.py:46-160` → `core/atlas/kernel/subagents.py:154-329` | delegate_parallel 支持有界并行，Git worker 在满足条件时建隔离 worktree，并在脏/未证明安全时保留 worktree。该隔离仅能确认于特定 Git worker 路径；单个 delegate/backend 和非 Git workspace 不保证 worktree 隔离。未实际创建子代理。 |
| scheduler / 常驻 Agent | `core/atlas/scheduler/__init__.py:354-378,459-479,548-556`；`core/atlas/automation/engine.py:566-610,627-669`；`core/atlas/persistent_agents/store.py:55-80,91-220`；`core/atlas/groups/store.py:120-194` | lease/heartbeat 生命周期、automation 取消暂停恢复与持久配置入口存在。文件触发会创建无句柄后台 dispatch task（`scheduler/__init__.py:548-556`）；静态审查不足以证明泄漏或丢任务，未编号为问题。没有实际等待心跳或触发调度。 |
| 资源泄漏与关闭 | `core/atlas/kernel/exec.py:90-161,341-350` → `core/atlas/kernel/loop.py:1650-1664`；workflow watcher：`core/atlas/kernel/workflow_tool.py:185-225`；scheduler lifespan：`core/atlas/scheduler/__init__.py:354-378` | 可见拥有者/关闭入口；工具批次取消延迟可能导致资源生命周期延长（W2-001），但没有观测到实际泄漏。后台调度 callback 的任务句柄生命周期未运行验证。 |
| 终态与真实完成 | `core/atlas/kernel/state.py:15-68` → `core/atlas/kernel/loop.py:1593-1604` → `core/atlas/api/run_drive.py:2908-2942`；旧 nudge：`core/atlas/agent/run_phases.py:929-949`、`core/atlas/agent/tool_node.py:1340-1359` | 状态机区分完成/失败/取消，kernel 的 completed 表示模型轮次结束，不能视作用户目标已验证。当前 kernel 没连接旧路径的 edit-before-stop verification nudge，见 W2-002。 |
| heartbeat、evolution、review、rewind | `core/atlas/evolution/watcher.py:511-602`；`core/atlas/review/engine.py:443-558`；`core/atlas/rewind/__init__.py:156-164,303+` | watcher 在回填不完整时保留 checkpoint/status；review 有只读 Git allowlist；rewind 提供恢复路径。未对真实 repo 执行 review/rewind，也未观测 heartbeat 的现场效果。 |
| 主目录 dirty/untracked 实际覆盖 | `D:\Atlas\core\atlas\expert_harness.py:122-204`；`D:\Atlas\core\atlas\agent\tool_node.py:1240-1253`；`D:\Atlas\core\atlas\research\tool.py:57-80`；`D:\Atlas\core\atlas\research\deep.py:229-254,256-281,317-363,442-502` | `expert_harness.py` 是 prompt/agent harness 指引，不单独构成工具副作用。deep research 会调用模型 router、网页搜索/抓取；源码所示研究成果以返回值为主，没有发现持久化到长期记忆/会话目录的写操作；网络访问和模型费用是实际外部副作用。该路径是主目录 untracked overlay，不属于审查 commit。 |

## 独有分支复核

- `codex/desktop-repair-20261013@b177a6a94a7f1a9adb2891955a37cd4d4490054d` 相对基线有 36 个相关/全局变更文件（代码差异统计：568 insertions/65 deletions；内核/执行相关有 16 个文件）。分支仍默认 `engine.kernel=atlas` 并创建 `AtlasKernel`：`core/atlas/engine/hermes_runtime.py:1097-1107`；另保留可选 Hermes 路径。它**没有修复 W2-001**：`core/atlas/kernel/loop.py:1435-1442` 的工具批次只 wait `{tool_task, queue_get}`，没有 `cancel_event` waiter；API 的取消入口仍仅在事件消费/安全点被处理：`core/atlas/api/run_drive.py:2329,2772`。它**也没有把 verification nudge 接到默认 AtlasKernel 路径**：nudge 仍在 `core/atlas/agent/run_phases.py:1467-1474` 的旧 finalize；API 有 `run_verify_nudge` 映射 `api/run_drive.py:2867`，但默认 kernel 的结束路径未调用此 finalize。
- 该分支把 AtlasKernel 的取消响应实现为对 task cancellation 的收敛与 settle（`kernel/loop.py:1447-1469`），但仅在 `tool_task` 自身被 cancel 时执行；`run.cancel_event` 并未触发这个分支，因此不算修复用户 Stop。
- desktop-repair 的 kernel loop 移除了基线的 `forwarded_results` 去重逻辑与 tool result 转发标记（基线 `core/atlas/kernel/loop.py:519-524,1483-1516`；分支对应区域 `core/atlas/kernel/loop.py:1410-1452`）。tool_node 仍把结果放入事件队列（`core/atlas/agent/tool_node.py:203-208,315-319,1409-1419`），而 kernel 在 batch 聚合结束后又从 `consume_tool_results` 发 tool_result；这形成重复 tool_result wire event 的代码路径。分支还删去 `tool_preparing` 增量进度事件（基线 `kernel/loop.py:1115-1120`；分支模型流事件处理 `kernel/loop.py:1050-1080`），长 write_file 参数流期间会失去该进度提示。按**候选集成回归风险**记录，未经真实 UI 实测。
- desktop-repair 将 kernel `memory_search` schema/dispatch 从 `kernel/tools.py` 与 `kernel/loop.py` 移除（分支 diff；当前基线入口在 `kernel/tools.py:75-90` 及 `kernel/loop.py:1945-1980`）。这是可见的能力回退；W2 不对记忆功能整体完成状态作判断，转交 W5/W7 评估是否为有意迁移。
- `p11b-worker-leftover@9379d6b499a8d1dd316ff7f8af274cf5285a8654` 是空提交：其 tree 与 parent `9f02a68cb2a52a9c4bcd9836c57d2fb715f50085` 同为 `794e6f5cd1e43b5cca2f125974a8a9126d507814`；不产生内核代码差异，不视作修复或集成候选。

## 已核对的 W7 LEDGER 能力入口（供总账复用）

- **D011 已做**：`kernel/tools.py:194-210` 注册 `write_stdin`、TaskOutput、TaskStop → `kernel/loop.py:2247-2268` 映射至 `local_process` read/write/poll/cancel → `kernel/exec.py:90-161,341-350` 管理进程。工具级别的启停/输入/输出链存在；通用 Run Stop 无法打断当前未返回的工具等待另见 W2-001。
- **D013 已做**：`kernel/tools.py:99-116` 注册 `update_plan`、EnterPlanMode、ExitPlanMode → `kernel/loop.py:1863-1930` 更新可见计划、进入只读 plan mode，并在已有 plan 且用户批准后退出。审批前置是预期约束，不是缺少显式入口。
- **D014 部分**：`kernel/tools.py:245-258` 注册 AskUserQuestion 别名 → `kernel/loop.py:2126-2164` 建立 user input wait/request 事件与回调。存在可调用结构化入口；用户多选/描述字段端到端传递未在此处证实。
- **D016 已做（本条 ledger 描述的调用级控制）**：`agent/tool_catalog.py:302-365` 注册 delegate_task/delegate_parallel 及 model、reasoning effort、depth 参数 → `agent/tool_node.py:725-801,885-950` 校验并传给 `_delegation` → `agent/enrichment.py:437-505,742-783` 执行。不能据此推断跨会话 registry 已做。
- **D017 部分**：`agent/tool_catalog.py:375-415` 注册子任务 wait/resume/cancel/escalate/close 操作 → `agent/tool_node.py:845-882` 转给对应 delegation backend。跨会话 registry、消息路由、权限和恢复完整性未由此调用链证明。
- **D018 已做**：`kernel/tools.py:114-117` 暴露 `read_tool_history`/`new_context` → `kernel/loop.py:503,2065-2108` 从本轮 messages 返回工具调用/结果，并由 `prepare_compaction(force=True)` 准备新的上下文窗口。此状态限于当前 kernel 本轮工具历史及 compaction/handoff，不表示任意跨会话历史读取。
- **D042 部分**：kernel approval event/wait 在 `kernel/loop.py:590-608,1960-1990,2105-2130,2270-2330`，tool-node permission event 在 `agent/tool_node.py:475-526`。审批调用链存在；不同权限分支的 scope/resource/reason 是否统一保留需逐项核验。
- **D043 部分**：kernel schemas 从 `kernel/tools.py:41-258` 汇总工具；`kernel/loop.py:1011-1030` 注入模型请求；执行仍由 `_dispatch` 中分散的 name 分支（`kernel/loop.py:1773-1791,1863-1980,2045-2365`）与多个 executor 分别实现。存在注册/执行接线，但不是单一 registry 驱动。
- **D044 部分**：`kernel/tools.py:239-240` 暴露 workflow schema → `kernel/loop.py:2357-2365` dispatch → `kernel/workflow_tool.py:46-160` → `workflow/scheduler.py:21-200` 持久运行/暂停恢复。动态执行入口存在；命名定义的 save/list/get registry 生命周期未在此调用链出现。
- **D045 已做**：`tools/workspace_workflows.py:60-70,347-480,1041-1067` 注册 `workflow_run_manage` 并提供 list/get/status/resume；`kernel/loop.py:1772-1791` dispatch。schema 会把 `save` 标为 discovery-only，executor明确报告不支持；该项声称的 run 管理链已接通。
- **D046 部分**：`agent/enrichment.py:830-900,960-1000` → `agent/subagent_worktree.py:237-336` 创建/收尾 Git worker worktree，并对 dirty/unproven 情况保留现场。仅证明此委派场景；跨 workspace 活动会话 handoff 与普遍 worktree 自动回收未证实。

## 当前基线中已复核、未另立问题的路径

- Pause/resume and run state: `kernel/loop.py:219-244` races pause and cancellation at safe points; `kernel/state.py:15-68` restricts legal terminal transitions. API run state is persisted and exposes distinct terminal statuses. The unresponsive in-flight tool case is W2-001.
- Stream and tool-result de-duplication: `kernel/loop.py:519-524,1483-1516` tracks forwarded results by call ID and avoids emitting a second result event for a call already forwarded from the event queue. The reviewed path does not show a duplicate `tool.completed` emission defect.
- Workflow lifecycle: `kernel/workflow_tool.py:46-160,185-225` binds planning, journal, pause/cancel; `workflow/scheduler.py:21-135,179-200` bounds parallelism, persists transitions, waits for active nodes before pausing, and reconciles active nodes on resume. Cancellation of active workflow children is supervised separately from the generic kernel tool-batch gap.
- Child isolation: `agent/enrichment.py:873-884,990-1000` creates/finalizes delegated worker worktrees when a Git workspace is available. `agent/subagent_worktree.py:237-336` uses a bounded git environment and preserves unproven/dirty worktrees. This covers the `delegate_parallel` path; it is not a general isolated worktree guarantee for all external backends.
- Long-running process manager: `kernel/exec.py:90-161,341-350` owns watcher tasks and shuts down non-detached executions on shutdown. Kernel shutdown is reached on failed/interrupted phases at `kernel/loop.py:1650-1664`; cancellation delayed during a live tool call is covered by W2-001.
- Persistent scheduling/automation: `scheduler/__init__.py:354-378,459-479` starts/stops and heartbeats the lease task; `automation/engine.py:566-610,627-669` provides cancel/pause/resume and records outcomes. File-trigger callbacks at `scheduler/__init__.py:548-556` create dispatch tasks without retaining a task handle; no failure was reproduced, so this remains a static follow-up point, not a numbered finding.
- Persistent agents and groups: `persistent_agents/store.py:55-80,91-220` validates durable profile and heartbeat settings; `groups/store.py:120-194` validates membership and round caps. These are configuration/state stores, not evidence of a live heartbeat agent run.
- Evolution watcher: `evolution/watcher.py:511-602` retains checkpoints when backfill limits prevent reaching history; status differentiates current from incomplete backfill. This preserves the “not caught up” condition rather than advancing the checkpoint.
- Review/rewind: `review/engine.py:443-558` restricts the review Git command set to read-only operations; `rewind/__init__.py:156-164,303+` computes checkpoint diffs and applies restoration. Neither was run against a real workspace in this read-only review.
- Dirty expert/research overlay: `D:\Atlas\core\atlas\expert_harness.py:122-204` alters prompt guidance only; `D:\Atlas\core\atlas\research\deep.py:229-254,256-281,317-363,442-502` bounds breadth/depth and uses gathered research branches. Model/tool cancellation is not propagated in `research/tool.py`, as cross-referenced in W2-001. These files are untracked on the host and are not in the reviewed commit.

## Relevant LEDGER call-chain evidence for W7

- D016 的调用级模型/reasoning/depth 控制已接线；D017 子代理等待/恢复/取消等控制为部分接线。逐项状态与路径见新增 `W2-FEATURE-SUPPLEMENT.json`。
- Workflow graph execution is callable: `kernel/loop.py:2357-2365` → `kernel/workflow_tool.py:46-160` → `workflow/scheduler.py:21-200` → `kernel/subagents.py:154-329`.
- D115, D118, and D122 are no longer accurately described as absent in the baseline: `kernel/tools.py` exposes Cron CRUD, `ScheduleWakeup`, and `EndConversation` schemas; `kernel/loop.py:1684-1685` routes lifecycle calls through `dispatch_lifecycle_tool`; `kernel/lifecycle_tools.py:16-124` implements automation creation/update/deletion, wakeup, and end-conversation cancellation. W7 should reclassify from current source and API registration rather than carry the old ledger status.
- Run terminal events: `kernel/loop.py:1593-1604` emits model-turn completion; `run_drive.py:2707` maps streamed events and later `run.completed`/`run.failed`/`run.cancelled` are distinct at `2908-2942`. This is a run-status contract, not proof the user's goal was independently verified.

## 其他分支对比

- `origin/absorb-all@8d7b01d829f1332e9305fe8ee56758a6294139f7` differs from the baseline in the reviewed kernel/agent/runtime/scheduler scope only at `core/atlas/agent/__init__.py` and `core/atlas/runtime/hooks.py`; neither adds an alternate kernel lifecycle implementation.
- `origin/engine-v1@cbd1dc2d487e324844a60da29280c8782ef3133a`, `origin/engine-v2@3c5e6ac5142331c7b7e6c5bd38459a7e17a3b67d`, `origin/engine-v2b@9a1d0feeef4ee49d2fb4b37f67f35ed227d023d8`, and `origin/engine-v3@140eece4cd8765b88604b75876795214889a5744` have no unique files in the reviewed kernel, agent, engine, runtime, scheduler, persistent-agent, or workflow scopes relative to the baseline (they are not evidence of current divergence there).
- `origin/wip/kernel-deep-research-20261015@7f0ee93293786f8d884cdf45650f1fb8aa7e29c4` has unique changes only in `core/atlas/kernel/loop.py` and `core/atlas/kernel/tools.py`; the baseline already contains these changes. They do not alter the tool-batch cancellation wait. Host-side untracked deep research implementation is a separate dirty overlay noted above.

## 未观测项与剩余边界

- 主执行者已确认运行进程的源码根目录为 `D:\Atlas`；W2 未能确认进程实际加载的 commit 与 dirty overlay 字节，故运行行为归属待核实。
- 未执行现场取消/暂停、scheduler heartbeat、automation trigger、subagent worktree、后台进程、review、rewind 或 deep-research；不声称运行验收通过。
- 未打开 `D:\Atlas\data` 中任何文件，未修改源码。W2 只新增审查文档、问题 JSON 与 Ledger evidence supplement。

