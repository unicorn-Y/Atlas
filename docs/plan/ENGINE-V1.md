# Atlas 自有引擎 ENGINE-V1 计划书（2026-10-10，一次性施工）

> 依据：`Atlas_自有引擎_全景源码合成_复核定稿V3_2026-10-10.md`（网页调研，来源已抽查属实）+ Atlas `memory-v1` 实际代码。
> 用户要求：**一次做完；不写一堆测试**——用户自己用，问题靠日志查。所以日志是本计划的第一项，不是附属品。

## 0. 目标与铁律

把 Atlas 的「大脑」从 Hermes 的 `AIAgent` 同步循环换成 **Atlas 自己的异步 Python 内核**（`core/atlas/kernel/`），各部件按下表从最强的那家移植。以后看到别家更好的部件，直接替换对应模块。

1. **只有一个内核**。不做多引擎切换；`agents/backends/`（Claude/Codex/ZCode 外部适配）保持原样，不接进内核。
2. **不重写已有能力**：模型路由 `models/`、记忆（MemOS，`memory/`）、工具实现（Hermes `tools/*` 与 Atlas 工具）、LSP、Computer Use、前端、API/WebSocket 事件格式全部复用。内核只换「循环 + 调度 + 上下文 + 恢复」。
3. **一个事实来源**：会话仍存 SessionDB（`engine/session_sync.py`），不新建第二个库。
4. **每个移植文件写来源头**（组件追新系统靠它跟踪上游更新）：
   `# Ported from owner/repo@<完整sha>: path/to/file (License)`，多来源写多行。同时追加到 `THIRD_PARTY_NOTICES.md`。
5. **旧路径保留为开关**：`config/atlas.toml` 新增 `[engine] kernel = "atlas"`（默认）/ `"hermes"`。新内核出问题用户可切回，不用回滚代码。
6. **测试**：不新增测试矩阵、E2E 场景表、跑分。只做两件事：现有后端测试最后跑一遍，被本次改动弄坏的修好（过时的就删掉）；纯函数模块（输出裁剪、工具调度排序）各顺手 1–2 个单测即可。

## 1. 部件 → 来源 → 落点

| # | 部件 | 抄谁（固定提交） | 落到 Atlas | 要点 |
|---|---|---|---|---|
| L | **运行日志**（先做） | — | `core/atlas/logs.py`、`frontend/src/main/backendProcess.ts` | 见 §2 |
| 1 | 主循环 | Mistral Vibe `vibe/core/agent_loop/_loop.py` @`4ae5c5955da8`（Apache-2.0，Python 直接改）；DeepSeek Harness `packages/core/agent-loop/src/agent.ts` @`d74326738864`（MIT）的 turn/step 边界；Pi `packages/agent/src/agent-loop.ts` @`42a3497d03ad` 的极简形态 | `kernel/loop.py`、`kernel/state.py` | `async run(request) -> AsyncIterator[event]`：组提示词→流式调模型→调度工具→写 SessionDB→下一步/结束。状态：`preparing/streaming/tools/compacting/done/failed/interrupted`。插话复用 `engine/steer_dispatch.py`，取消用 `cancel_event`。事件转成现有 `run_turn` 输出的 dict 格式（chunk/tool_call/tool_result/…），上层 `agent/__init__.py`、`api/run_drive.py` 不用改 |
| 2 | 模型调用与重试 | Codex `codex-rs/core/src/responses_retry.rs` @`806d9732c974`（Apache-2.0）的分层；DSH `packages/llm/llm-retry/src/index.ts` | `kernel/model_call.py` | 经 Atlas `models/router.py` 解析路由后调用 Hermes 现有 provider 适配器（`agent/anthropic_adapter.py` 等，不重写）。429/529/超时/断流按类别退避；**断流时保留已收到的部分输出和半截工具调用**；provider 切换复用 `agent/fallback_cooldown.py` |
| 3 | 工具调度 | DSH `packages/core/agent-loop/src/tool-calls.ts`；ZCode `apps/zcode-cli/packages/core/src/tool/scheduler.ts` @`29628c9acdb8`（Apache-2.0） | `kernel/tools.py` | 只读/无副作用工具并行（有上限），写文件/shell/桌面操作是独占屏障；**结果按模型给出的顺序写回**；每次调用产出 `ToolReceipt{id,name,state,duration_ms,output_ref}`。工具本体经 `engine/tool_registry.py` 现有分发调用，权限走 `engine/tool_permissions.py` |
| 4 | 中断与恢复 | DSH `packages/core/session/src/repair.ts` | `kernel/repair.py` | 中断/崩溃/重启后，未配对的工具调用补结果：`not_started`（没开始，可重试）/`unknown`（可能已执行，**不自动重试**，告诉模型先检查现状）。保证历史永远是合法的「调用-结果」对，杜绝 provider 因孤儿 tool_call 报错 |
| 5 | 上下文与压缩 | OpenHands SDK `openhands-sdk/openhands/sdk/context/condenser/pipeline_condenser.py` @`1cfba2117e92`（MIT，Python）；Vibe `vibe/core/compaction/manager.py`；DSH `packages/compaction/compaction-tool-result-pruner/src/index.ts`；Pi `packages/coding-agent/src/core/cache-warmer.ts` 的成本门槛思路 | `kernel/context.py` | 管道：①无模型裁剪旧工具输出（保留头尾+存全文引用）→②超预算才 LLM 摘要。摘要在副本上做，**成功才替换**，失败保持原样。**预算 = min(模型窗口×比例, 绝对上限)**，默认绝对上限 `[engine] context_budget_tokens = 120000`——今天一次运行吃了约 890 万 token（每次请求约 18 万）就是没有绝对上限。保留不可丢的任务状态（目标、计划、已改文件、未完成工具）。稳定前缀继续用 `agent/prompt_cache_boundary.py` |
| 6 | 防打转 | OpenHands `openhands-sdk/openhands/sdk/conversation/stuck_detector.py`（MIT，Python 直接改） | `kernel/stuck.py` | 看最近事件：重复相同调用+相同结果、连续报错、只说话不干活、两步交替循环。触发时先注入一次纠偏提示，再犯就结束本轮并说明原因。替代 Hermes repetition guard 在新内核里的角色 |
| 7 | 提示词 | Pi `packages/coding-agent/src/core/system-prompt.ts`；OpenCode `packages/opencode/src/session/instruction.ts` @`055d95bb7e27`（MIT） | `kernel/prompt.py` | 顺序固定：身份→工具策略→工作区规则(AGENTS.md/CLAUDE.md)→当前目标→按需技能→MemOS 召回（只放相关条目）→历史。前缀不变部分不随轮次改，保证缓存命中。现有 `_model_family_guidance`、记忆注入逻辑搬过来复用 |
| 8 | 文件编辑（可选格式） | Oh My OpenAgent `packages/hashline-core/src/{hash-computation,validation,edit-operations}.ts` @`99d1d0ee2c74`（MIT） | `tools/hashline.py` + 注册为工具 | `read_file` 可返回 `行号#哈希|内容`；`hashline_edit` 按行号+哈希改，内容变了就拒绝让模型重读。保留现有 `patch`/精确替换；配置 `[engine] hashline_edit = true` 默认开 |
| 9 | 子 Agent | DSH `packages/subagent/subagent/src/manager.ts`；ZCode `apps/zcode-cli/packages/core/src/subagent/runner.ts` | `kernel/subagents.py` | 子 Agent 也跑同一个 `kernel.loop`，独立会话/上下文，结果以回执交回父任务（含改了哪些文件、成败、token）。worktree 继续用 `agent/subagent_worktree.py`；委派入口沿用现有 delegate 工具 |

**不做**：ZCode DAG 工作流编排器、DSH durable inbox / goal-round-driver、Vibe checkpoint/rewind 重做（现有 `agent/checkpoints.py` 先用着）、Repo Map、新的权限/Hook 框架、MemOS 改动、前端改版。以后用出问题再按同样方式抄。

## 2. 运行日志（排查全靠它，必须先做好）

1. **后端日志文件**：`data/logs/backend.log`，按天轮转保留 14 天，`[logging]` 现有 level/format 生效（文件里用 JSON 行）。uvicorn 访问日志降到 WARNING。
2. **Electron 收集后端 stdout/stderr**：`frontend/src/main/backendProcess.ts` 把子进程输出追加到 `data/logs/backend-stdio.log`（崩溃前的 traceback 不会丢）。
3. **每次 run 一个事件文件**：`data/logs/runs/YYYY-MM-DD/<run_id>.jsonl`，内核每一步写一行：`run_start`（模型、会话、工作区）/`model_request`（输入 token、是否命中缓存、耗时）/`model_error`（类别、重试次数）/`tool_start`/`tool_end`（耗时、成败、输出长度）/`compaction`（前后 token、方式）/`stuck`/`repair`/`run_end`（结果、总 token、总耗时、失败原因）。只记长度和摘要，不记完整工具输出和密钥。
4. 失败时 `run.failed` 事件里带上该 jsonl 路径，方便用户直接把文件给 Claude 看。

## 3. 施工方式

- 主机新建工作树：`git -C D:\Atlas worktree add D:\atlas-engine -b engine-v1 origin/memory-v1`，**不要改 `D:\Atlas`**（用户在用，更新器遇到脏工作树会拒绝更新）。环境用 `D:\Atlas\core\.venv`（`pip install -e D:\atlas-engine\core --no-deps` 到一个副本 venv，或直接设 `PYTHONPATH`）。
- 并行分工（按文件归属，互不碰）：A 日志（§2）；B `kernel/loop.py`+`state.py`+`model_call.py`+`repair.py`；C `kernel/tools.py`+`stuck.py`+`tools/hashline.py`；D `kernel/context.py`+`prompt.py`；E `kernel/subagents.py` + 接线（`engine/hermes_runtime.py` 里按 `[engine] kernel` 分流到新内核）。B 先定 `kernel/state.py` 里的事件/状态类型，其余人照它写。
- 做完：跑一遍现有后端测试（`core` 下 `pytest -q -n auto --timeout 300`；Codex 终端会杀长命令就分批跑或后台跑写日志），修好改坏的；前端 `npm --prefix frontend run build` 通过；用真实模型发一条「列出当前目录并读一个文件」确认能跑通、日志文件正常生成。
- 提交到 `engine-v1` 并推送 origin，**不要推 memory-v1**（由 Claude 合并后推）。结果写 `tasks/results/ATLAS-ENGINE-V1.result.md`：做了什么、每个文件的来源、未完成项、最终 SHA。
