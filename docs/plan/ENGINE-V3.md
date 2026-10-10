# Atlas 自有引擎 ENGINE-V3 计划书：逐部件对照上游补齐（2026-10-11）

> V1/V2 已把内核和模块做出来并接通（memory-v1 `74588c1`），但移植是精简版：上游 Codex `session/turn.rs` 128KB+ZCode → Atlas `loop.py` 55KB；压缩 47KB → 12KB；进程管理 74KB → 13KB。本批**逐个部件对照上游源码，把漏掉的处理逻辑补齐**，让每个部件达到上游的完整度。
> 用户要求：一次做完；**不写测试、不跑测试套件**，补齐后用户自己用，问题看日志。

## 0. 铁律

1. 工作树：`git -C D:\Atlas fetch origin` → `git -C D:\Atlas worktree add D:\atlas-engine4 -b engine-v3 origin/track-upstream`。**不要改 `D:\Atlas`**（用户在用），也不要碰 `D:\atlas-engine*` 旧工作树。
2. **上游用最新**：开工时取 Codex、ZCode 默认分支的当前 HEAD，固定下来写进 `docs/engine/GAPS.md` 开头；所有移植文件的来源头改成新提交号。其他来源（DeepSeek Harness、OpenHands、OpenCode、Aider）同样取最新 HEAD。
3. **方法**：每个部件先通读上游对应目录（不只是计划书点名的文件，包括它调用的同目录辅助文件），逐个分支、逐个边界情况对照 Atlas 现有实现，列出差异，然后照上游补上。**行为以上游为准**，不凭印象改写；Atlas 已有的更好的做法保留并在 GAPS 里注明。
4. 不重写模型路由、MemOS、工具本体、前端、API 事件格式；对外接口（`AtlasKernel`、`KernelRequest`、事件 dict、`[engine]` 配置）保持兼容，新增配置项给默认值。
5. 来源头格式不变：`# Ported from owner/repo@<sha>: path (License)`；闭源写 `# Behavior from Claude Code <版本> docs: <链接>`。`THIRD_PARTY_NOTICES.md` 只追加/更新提交号。
6. **不写任何测试，不跑测试套件。**

## 1. 对照清单（每行一个子 agent，按文件归属，互不改同一文件）

| # | Atlas 文件 | 对照的上游（读整个相关目录） | 重点检查（不限于） |
|---|---|---|---|
| 1 | `kernel/loop.py`、`kernel/state.py` | Codex `codex-rs/core/src/session/`（turn.rs 及其调用的同目录文件）；ZCode `agent/turn-machine.ts`、`agent/turn-state.ts` 及 `agent/` 下相关文件 | 每个状态迁移及其失败分支；流式 item 的完整处理（推理/文本/工具调用分片、部分输出）；插话/排队/中断的时机与保留内容；回合结束判定；自动压缩触发点；回合内的 token 计量 |
| 2 | `kernel/model_call.py` | Codex `responses_retry.rs`、`client.rs`、`client_common.rs`、`model_request.rs`；Claude Code v2.1.296 529/过载重试行为 | 错误分类全集（429/5xx/529/超时/断流/上下文超限/内容过滤/认证）；退避与 Retry-After；续流；超限时转压缩；每次重试写日志 |
| 3 | `kernel/tools.py` | Codex `tools/`（parallel.rs、orchestrator.rs、router 及 handlers 共用部分）；ZCode `tool/scheduler.ts`、`tool/executor.ts` | 并行判定规则全集；审批→执行→失败升级重试；工具输出截断与超长处理；取消时已启动/未启动调用的结果；未知工具/参数解析失败的回包 |
| 4 | `kernel/exec.py` | Codex `codex-rs/core/src/unified_exec/` 整个目录；ZCode `tool/bash-timeout-policy.ts` 及 bash 工具相关文件 | 进程句柄生命周期、write_stdin、轮询、进程树结束、输出环形缓冲与头尾保留、超时与后台化、Windows 下 Git Bash/PowerShell 差异、编码 |
| 5 | `kernel/context.py` | Codex `compact.rs`、`compact_remote*.rs`、`compact_token_budget.rs`、`context_manager/`；ZCode `compact/` 整个目录 | 预算公式（窗口−输出预留−缓冲）与按模型取值；microcompact 规则全集；摘要提示词与保留内容（目标/计划/文件/未完成工具）；压缩失败熔断与回退；压缩后缓存前缀稳定 |
| 6 | `kernel/prompt.py` | Codex `agents_md.rs` 及其调用处；ZCode `context/builder.ts`、`context/dynamic-sections.ts` 及 `context/` 目录；Claude Code memory/skills 文档 | AGENTS.md/CLAUDE.md 发现规则（向上查找、大小上限、合并顺序）；动态段的位置与缓存边界；环境信息内容 |
| 7 | `kernel/edit.py` | Codex `codex-rs/apply-patch/` 整个 crate；ZCode `tool/edit-matchers.ts`、`tool/read-file-state.ts`、`tool/diff.ts` 及 edit/write 工具 | patch 语法全集（Add/Delete/Update/Move、上下文行、EOF 标记）；模糊匹配的各级退化与唯一性；先读后改与陈旧检测；换行/BOM/编码保持；失败信息让模型能自我纠正 |
| 8 | `kernel/plan.py` | Codex `tools/handlers/plan.rs`、`models-manager/src/collaboration_mode_presets.rs`；Claude Code 计划模式文档 | 计划模式下的工具限制、批准流程、计划/执行分别的模型与推理强度 |
| 9 | `kernel/subagents.py`、`kernel/workflow_tool.py`、`workflow/` | Codex `codex-rs/core/src/agent/` 整个目录 + `tools/handlers/multi_agents.rs`；ZCode `subagent/`、`workflow/` 整个目录 | 子 agent 生命周期（spawn/send/wait/close/中断）、并发上限与排队、结果回传与失败传播、上下文隔离、DAG 节点重试/暂停/恢复与 journal |
| 10 | `kernel/repair.py`、`kernel/stuck.py`、Hooks 触发点 | DeepSeek Harness `packages/core/session/src/`；OpenHands `conversation/stuck_detector.py`；Codex `hook_runtime.rs`；Claude Code hooks 文档 | 未配对调用修复全集；卡住模式全集与阈值；Hook 事件全集与阻断/改写语义 |
| 11 | `rewind/`、`repomap/` | OpenCode `snapshot/`、`session/revert.ts`；Aider `repomap.py` 及其 queries | 对照最新版补齐，检查 V2-A 移植遗漏 |

总控负责：开工前定好各上游最新 SHA；汇总各子 agent 的差异清单成 `docs/engine/GAPS.md`（每个部件：上游有、Atlas 原来缺、本次已补 / 有意不补及原因）；最后解决接口衔接。

## 2. 交付

- 只做最小确认：后端能启动（验证用的后端要设 `ATLAS_UPSTREAM_AUTO=0`，免得它自己跑追新）；`npm --prefix frontend run build` 通过；真实模型跑通一条普通消息。**到此为止。**
- 提交到 `engine-v3`，`git push origin engine-v3`。不要推 memory-v1 / track-upstream。
- 结果写 `tasks/results/ATLAS-ENGINE-V3.result.md`：各部件补了什么（指向 GAPS.md）、新的上游提交号、有意没补的、最终 SHA。
