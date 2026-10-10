# Atlas 自有引擎 ENGINE-V1 计划书（2026-10-10 修订，一次性施工）

> 依据：网页调研 `Atlas_自有引擎_全景源码合成_复核定稿V3_2026-10-10.md`（来源已抽查属实）+ Atlas `memory-v1` 实际代码。
> 用户要求：**抄一流的——Codex、Claude Code、ZCode 为主**；一次做完；不写一堆测试，用户自己用、问题靠日志查。

## 0. 目标与铁律

把 Atlas 的「大脑」从 Hermes 的 `AIAgent` 同步循环换成 **Atlas 自己的异步 Python 内核**（`core/atlas/kernel/`），每个部件照一流产品的做法实现。以后看到更好的部件，直接替换对应模块。

1. **来源优先级**：① **Codex**（`openai/codex`，Apache-2.0，Rust → 逐段翻成 Python）② **ZCode**（`zai-org/ZCode`，Apache-2.0，TS → Python）③ **Claude Code**（闭源，只照官方文档/changelog 描述的**行为**重做，不碰其打包代码）。其他项目（DeepSeek Harness、OpenHands、OpenCode、Pi、Oh My OpenAgent）**只补这三家没有的东西**，表里已注明。语言不同不是不抄的理由。
2. **只有一个内核**。不做多引擎切换；`agents/backends/`（外部 Claude/Codex/ZCode 适配）保持原样，不接进内核。
3. **不重写已有能力**：模型路由 `models/`、记忆（MemOS，`memory/`）、工具本体（Hermes `tools/*` 与 Atlas 工具）、LSP、Computer Use、前端、API/WebSocket 事件格式全部复用。内核只换「循环 + 调度 + 执行 + 上下文 + 恢复 + 子 Agent」。
4. **一个事实来源**：会话仍存 SessionDB（`engine/session_sync.py`），不建第二个库。
5. **每个移植文件写来源头**（组件追新靠它跟踪上游更新）：`# Ported from owner/repo@<完整sha>: path (License)`，多来源多行；闭源行为写 `# Behavior from Claude Code <版本> docs: <链接>`。同时追加 `THIRD_PARTY_NOTICES.md`。
6. **旧路径保留为开关**：`config/atlas.toml` 新增 `[engine] kernel = "atlas"`（默认）/ `"hermes"`，新内核出问题可切回。
7. **不写任何新测试，不跑测试套件**（用户明确要求：浪费时间和 token，他自己用、靠日志查问题）。只做：后端能启动、前端 build 通过、真实模型跑通一条消息。旧测试因本次改动失效的不用管。

固定提交：Codex `806d9732c974`（rust-v0.162.1 之后）、ZCode `29628c9acdb8`（v3.14.3）、Claude Code 行为以 v2.1.296（10-09）文档为准；DeepSeek Harness `d74326738864`、OpenHands SDK `1cfba2117e92`、Oh My OpenAgent `99d1d0ee2c74`。

## 1. 部件 → 来源 → 落点

| # | 部件 | 主来源（一流三家） | 补充 | 落到 Atlas | 要点 |
|---|---|---|---|---|---|
| L | **运行日志**（先做） | — | — | `core/atlas/logs.py`、`frontend/src/main/backendProcess.ts` | 见 §2 |
| 1 | 主循环 / 回合状态机 | ZCode `apps/zcode-cli/packages/core/src/agent/turn-machine.ts`（显式状态迁移）；Codex `codex-rs/core/src/session/turn.rs`（turn 生命周期、流式 item、自动压缩触发点） | Claude Code：运行中插话、Esc 中断保留已做部分、转后台 | `kernel/loop.py`、`kernel/state.py` | 状态：`preparing/streaming/tools/waiting_approval/compacting/done/failed/interrupted`。`async run(request) -> AsyncIterator[event]`，事件转成现有 `run_turn` 的 dict 格式（chunk/tool_call/tool_result/…），上层 `agent/__init__.py`、`api/run_drive.py` 不改。插话复用 `engine/steer_dispatch.py` |
| 2 | 模型调用与重试 | Codex `codex-rs/core/src/responses_retry.rs`（流错误分类、续流） | Claude Code v2.1.296：529 过载重试上限可配 | `kernel/model_call.py` | 经 `models/router.py` 定路由，调用 Hermes 现有 provider 适配器（`agent/anthropic_adapter.py` 等，不重写）。429/529/超时/断流分类退避；**断流保留已收到的部分输出和半截工具调用**；切 provider 复用 `agent/fallback_cooldown.py` |
| 3 | 工具调度与审批 | Codex `codex-rs/core/src/tools/parallel.rs`（可并行判定）+ `tools/orchestrator.rs`（审批→执行→失败升级重试，单一入口）；ZCode `tool/scheduler.ts`（依赖/副作用排序） | — | `kernel/tools.py` | 只读工具并行（有上限），写文件/shell/桌面是独占屏障；**结果按模型给出的顺序写回**；每次调用产出 `ToolReceipt{id,name,state,duration_ms,output_ref}`。工具本体经 `engine/tool_registry.py` 分发，权限经 `engine/tool_permissions.py`，全部从 orchestrator 一个口子走 |
| 4 | 命令执行 / 后台进程 | Codex `codex-rs/core/src/unified_exec/process_manager.rs` + `head_tail_buffer.rs`；ZCode `tool/bash-timeout-policy.ts` | Claude Code：后台任务、`/tasks` 查看 | `kernel/exec.py`（包在现有 `tools/local_execution.py` 外面） | 统一 `start/poll/write_stdin/kill` 句柄；输出存全文文件，模型只拿头+尾+文件路径；按命令类型给超时；超时/中断标记 `unknown` 状态。Windows 继续用现有 Git Bash/PowerShell 实现 |
| 5 | 中断与恢复 | Codex `session/turn.rs` 中断时给未完成调用补 aborted 结果的做法 | DeepSeek Harness `packages/core/session/src/repair.ts`（`not_started` / `unknown` 两级，三家都没写这么细） | `kernel/repair.py` | 中断/崩溃/重启后，未配对的工具调用补结果：`not_started` 可重试；`unknown`（可能已执行）**不自动重试**，让模型先查现状。历史永远是合法的调用-结果对 |
| 6 | 上下文与压缩 | ZCode `compact/policy.ts`（窗口−输出预留−缓冲 的预算、失败熔断）+ `compact/microcompact.ts`（局部减负）；Codex `codex-rs/core/src/compact.rs`（本地压缩流程） | Claude Code：自动压缩 + `/compact` 手动带重点 + 子 Agent 各自压缩（v2.1.296 `autoCompactWindow`）；DeepSeek Harness 工具输出裁剪（保留头尾） | `kernel/context.py` | 顺序：①microcompact：无模型裁剪旧工具输出（头尾+全文引用）→②超预算才 LLM 摘要，在副本上做，**成功才替换**。**预算 = min(模型窗口×比例, 绝对上限)**，默认 `[engine] context_budget_tokens = 120000`（今天一次运行吃约 890 万 token，就是缺绝对上限）。必须保留：目标、计划、已改文件、未完成工具。稳定前缀继续用 `agent/prompt_cache_boundary.py` |
| 7 | 提示词 / 规则 / 技能 | Codex `codex-rs/core/src/agents_md.rs`（AGENTS.md 层级发现）；ZCode `context/builder.ts`（分段组装） | Claude Code：CLAUDE.md 目录继承、Skills 只放描述按需展开 | `kernel/prompt.py` | 固定顺序：身份→工具策略→工作区规则（AGENTS.md / CLAUDE.md，向上逐级）→当前目标→技能目录（只放名字+一句描述）→MemOS 召回（只放相关条目）→历史。不变部分不随轮次改，保缓存命中。复用现有 `_model_family_guidance`、记忆注入 |
| 8 | 文件编辑 | Codex `codex-rs/core/src/apply_patch.rs`（GPT 系列训练过的 patch 格式）；ZCode `tool/edit-matchers.ts`（精确→容错匹配，要求唯一命中）+ `tool/read-file-state.ts`（读过才能改、文件变了要重读） | Claude Code：Edit 工具精确替换 + 必须先 Read；Oh My OpenAgent hashline（可选，默认关） | `kernel/edit.py`，注册为 `apply_patch` / `edit` 工具 | 三种入口：`apply_patch`（GPT 类模型默认）、`edit` 精确替换（Claude 类默认）、`write`。统一：读后才能改、陈旧检测、保留原换行/BOM/编码、原子写盘、回执带 diff |
| 9 | 计划模式 | Codex `models-manager/src/collaboration_mode_presets.rs`（计划/执行各自的模型与推理强度）+ `tools/handlers/plan.rs`（更新计划工具） | Claude Code：计划模式只读、用户批准后执行 | `kernel/plan.py`，复用 `agent/planning.py`、`agent/todo_state.py` | 计划阶段只读工具；可配更强模型/更高推理强度；计划状态持久化在会话里，不另建对象 |
| 10 | 子 Agent | Codex `codex-rs/core/src/agent/control.rs`（生命周期）+ `tools/handlers/multi_agents.rs`（spawn/send/wait/close）；ZCode `subagent/runner.ts` | Claude Code：子 Agent 独立上下文、可指定模型、各自压缩、只回传结论 | `kernel/subagents.py` | 子 Agent 跑同一个 `kernel.loop`，独立会话；结果以回执交回父任务（改了哪些文件、成败、token）。worktree 用现有 `agent/subagent_worktree.py`；入口沿用现有委派工具，改成调新内核 |
| 11 | Hooks | Codex `codex-rs/core/src/hook_runtime.rs` | Claude Code 的事件名与语义：`PreToolUse/PostToolUse/UserPromptSubmit/Stop/SubagentStop/PreCompact/SessionStart` | 复用 `runtime/hooks.py`，由内核在对应时机触发 | 事件名与 Claude Code 对齐，用户现成的 Claude Code hooks 配置可直接用 |
| 12 | 防打转 | 三家无独立实现 | OpenHands `openhands-sdk/openhands/sdk/conversation/stuck_detector.py`（Python，直接改） | `kernel/stuck.py` | 重复相同调用+相同结果、连续报错、只说不做、两步交替循环；先纠偏一次，再犯就结束本轮并说明原因 |

**这次不做**：ZCode dynamic-workflow / DAG 编排器、DeepSeek Harness durable inbox / goal 驱动、检查点与回退重做（现有 `agent/checkpoints.py` 先用）、Repo Map、MemOS 改动、前端改版。以后用出问题再照同样方式抄。

## 2. 运行日志（排查全靠它，先做）

1. **后端日志文件** `data/logs/backend.log`：按天轮转保留 14 天，沿用 `[logging]` 的 level/format（文件里 JSON 行）；uvicorn 访问日志降到 WARNING。
2. **Electron 收集后端 stdout/stderr**：`frontend/src/main/backendProcess.ts` 追加写 `data/logs/backend-stdio.log`（崩溃 traceback 不丢）。
3. **每次 run 一个事件文件** `data/logs/runs/YYYY-MM-DD/<run_id>.jsonl`，每步一行：`run_start`（模型、会话、工作区、内核）/`model_request`（输入/输出/缓存 token、耗时）/`model_error`（类别、第几次重试）/`tool_start`/`tool_end`（耗时、成败、输出长度）/`compaction`（前后 token、方式）/`stuck`/`repair`/`run_end`（结果、总 token、总耗时、失败原因）。只记长度和摘要，不记完整输出和密钥。
4. `run.failed` 事件带上该 jsonl 路径，用户可直接把文件交给 Claude 查。

## 3. 施工方式

- 主机新建工作树：`git -C D:\Atlas worktree add D:\atlas-engine -b engine-v1 origin/memory-v1`，**不要改 `D:\Atlas`**（用户在用；更新器遇脏工作树会拒绝更新）。Python 环境用 `D:\Atlas\core\.venv` 的副本或设 `PYTHONPATH` 指向工作树。
- 移植方法：每个部件**先读上表的上游源文件**，按其数据结构和分支逐段翻成 Python，保留关键常量与边界处理，不要凭印象重写。
- 并行分工（按文件归属，互不碰）：
  A 日志（§2）；
  B `kernel/state.py`+`loop.py`+`model_call.py`+`repair.py`（先定事件/状态类型，其余照它写）；
  C `kernel/tools.py`+`exec.py`+`stuck.py`；
  D `kernel/context.py`+`prompt.py`+`plan.py`；
  E `kernel/edit.py`+`subagents.py`+ hooks 触发 + 接线（`engine/hermes_runtime.py` 按 `[engine] kernel` 分流到新内核）。
- 做完：后端能正常启动；`npm --prefix frontend run build` 通过；用真实模型发一条「列出当前目录并读一个文件」确认能跑通、日志文件正常生成。**到此为止，不写测试、不跑测试套件。**
- 提交到 `engine-v1` 并推送 origin，**不要推 memory-v1**（由 Claude 合并后推）。结果写 `tasks/results/ATLAS-ENGINE-V1.result.md`：做了什么、每个文件的来源、没做完的、最终 SHA。
