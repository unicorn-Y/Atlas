# ATLAS-U1：全局 Latest-Best Refresh（已完成 C1–C6 也重新对标）

> U0 同步最新 Hermes 后执行。
> 目标不是重做 C1–C6，而是用 2026-10 当前最新一代 Agent 重新扫描 Atlas 已有能力。
> **最新情报 + 当前最强实现**，不是“哪个版本号最大就照抄”。

## 对标对象（每次开工重新取最新）

至少：
- NousResearch Hermes Agent current main
- Claude Code current release/changelog
- OpenAI Codex current stable + main（预发布只取明显成熟且源码稳定的能力）
- OpenCode current release/main
- Pi current release/main
- ZCode 当前可公开验证的桌面交互/功能
- Factory / Cline / Kiro / Roo / goose 等 Atlas 已经用过的来源，如它们对应能力仍更强

记录精确：
- version/tag/commit
- date
- repo/file 或官方 release note

## 核心规则

逐项看 C1–C6，不因为“已经 PASS”就跳过。

每个能力只做三种结论：
1. **KEEP**：Atlas 当前已经是最新/更强；
2. **UPGRADE**：有新的更强实现，直接搬或兼容；
3. **REPLACE**：Atlas 旧实现已被上游/别家成熟实现超越，删旧代码，保留薄 adapter。

禁止为了“新”而换差的实现。

例：Pi 0.15 把 built-in subagent 移除，不代表 Atlas 也要删；Atlas 只吸收 Pi 当前更强的 session/UI/extension 能力。

## C1–C6 全部重扫

### A. Agent loop / recovery / context
对比：
- Hermes latest recovery/guardrails/compaction
- Claude Code latest resume/recovery/auto mode
- Codex latest interrupt/context/session
- Pi latest compaction/session lazy loading
- OpenCode latest session/runtime

检查 Atlas：
- tool loop
- retries / 429 / 500 / timeout / truncation / overflow
- repetition/stop gates
- stable prompt/cache
- compaction
- new-context handoff
- token/cost/context stats

### B. Files / patch / terminal / diagnostics
对比最新：
- Hermes file tools
- Codex apply_patch/V4A
- OpenCode edit/LSP
- Pi snapshots/revert
- Claude Code Bash/edit diff behavior

检查：
- read/search/write/patch
- CRLF/BOM
- overwrite guards
- V4A
- LSP
- terminal/background/PTY
- tool output storage

### C. Sessions / interaction / permissions
对比：
- Claude Code latest fullscreen/queue/send-now/remote/background
- Codex latest command center/thread/history
- Pi latest session tree/snapshots
- OpenCode permission/session

检查：
- steer/queue
- fork/tree
- rewind/checkpoint
- plan
- permission modes
- status/composer/history

### D. Subagents / orchestration
重点看：
- Hermes latest delegation nested orchestrator + worktree isolation
- Claude Code latest subagent/side-agent behavior
- Factory patterns
- Pi extensions current approach

检查：
- dynamic max concurrency
- worktree
- verifier
- nested delegation
- structured child results
- child resume/cancel/timeout
- no shared-workspace collisions

### E. Extensions
重点看 Claude Code current release：
- hooks
- plugins
- Claude Mods
- plugin configure/eval
- skills
- agents
- MCP
- prompt audit

Atlas C4 要决定：
- 哪些直接兼容
- 哪些要升级格式
- 哪些新 Claude feature 值得直接复刻

### F. Models
对比最新 provider/runtime：
- Hermes current provider architecture
- Pi ModelRuntime
- Codex/Claude current reasoning/cache/provider routing

检查：
- catalog
- multi-key
- cooldown/rotation
- reasoning stages
- cache diagnostics
- context windows
- local providers
- alias normalization

### G. Coding UX
对比最新：
- Codex current fullscreen / command center / parallel work
- Claude Code current fullscreen/plugin/skills UX
- OpenCode desktop
- Pi current TUI improvements

检查：
- /init
- /review
- findings navigation
- long sessions
- virtualized UI
- palette
- status
- errors/retry
- terminal/diff/files/settings

## “别家最新”当前已知必须重新核的例子

- Claude Code current changelog includes Claude Mods + built-in side agent (“You should know”), plugin configure/eval, prompt audit, AGENTS.md fallback, improved remote/background session behavior.
- Codex current stable/main includes new fullscreen/command-center/history/parallel-work UX.
- Hermes current upstream has Browser Use CLI 3.x, Skills Hub, Bot Mode, worktree isolation and many gateway/delegation changes.
- Pi current has newer ModelRuntime, snapshot/revert/session loading and extension architecture; built-in subagent removal仅作为架构信息，不机械复制。
- OpenCode current release/main重新核 edit/LSP/permissions/session。

## 输出

先写：
`docs/research/2026-10-03-latest-best-refresh.md`

表格：
能力 | Atlas 当前 | 最新最强来源 | version/commit | repo/file | KEEP/UPGRADE/REPLACE | 施工文件 | 是否阻塞日常使用

然后直接施工所有标记为：
- 会影响日常强度
- 明显落后
- 成本低/中且能直接搬

不急着施工纯企业治理/云管理/用户完全不用的边角功能，记录到后续。

## 验证

每块 focused tests。
整合结束：
- backend full pytest 最多一次
- frontend 四项一次
- fake-model 主链一次

## 交付

`tasks/results/ATLAS-U1-LATEST-BEST-REFRESH.result.md`

结果必须有：
- KEEP/UPGRADE/REPLACE 总表
- 实际升级清单
- 删除的重复旧实现
- 仍然不如某家的真实差距
- test summary

完成后再进入 X2。
