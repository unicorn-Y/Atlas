# ATLAS-U0：Hermes 最新上游同步

> 这是 X2/X4/X5 和全局“最新最强”刷新前的强制前置。
> 当前 Atlas 的 Hermes fork 明显落后 upstream；先把底座同步，再做任何基于 Hermes 的搬运。
> 目标不是“重做 Atlas”，而是把 NousResearch/hermes-agent 当前 main 的成熟更新吃进 fork，同时保住 Atlas 自己的增强。

## 目标

1. 把 `NousResearch/hermes-agent:main` 当前最新 HEAD 合进 `unicorn-Y/hermes-agent:atlas`。
2. 保留 Atlas fork 自己的增强和 Windows 修复。
3. 识别 upstream 新增能力里已经覆盖 Atlas 旧自研/旧搬运的部分，后续 U1/X2/X4/X5 直接复用，不再重复造。
4. 更新 Atlas 中所有记录的 Hermes 基线 commit/source map。

## 开工先记录

- upstream HEAD + date
- atlas branch HEAD
- merge-base
- ahead/behind
- upstream 自上次基线以来的主要能力增量

至少分类：
- agent loop / recovery / context
- files / patch / terminal
- delegation / worktree
- browser / computer
- skills hub / skill learning / curator
- gateway / bot mode / cron / messaging
- desktop / CLI
- provider/model
- Windows fixes

## 合并原则

- 以 upstream 最新实现为底；
- Atlas 自己的 8 个左右增强按语义重放，不允许简单 ours/theirs；
- upstream 已经实现得更强的 Atlas 自研补丁，优先删掉 Atlas 重复实现，改成薄 adapter；
- Atlas 独有且 upstream 没有的功能继续保留；
- 不回退 C1–C6 已验收行为。

重点保留 Atlas fork 已知增强：
- context handoff / fixed summary sections
- OpenCode-style variable-size anchored fuzzy edit
- Windows/MCP orphan fixes
- Atlas read/write baseline guards
- multimodal tool result guardrail compatibility
- Atlas-specific toolset hooks

## 特别核查 upstream 新能力

至少确认当前 upstream 是否已有并记录精确文件：
- Browser Use CLI 3.x / browser providers
- Skills Hub
- Bot Mode
- delegation worktree isolation / nested orchestration
- latest cron/gateway
- latest desktop/session/remote control
- latest Windows fixes

## 验证

不要做无意义大矩阵。

最低：
- upstream 自带受冲突文件相关 tests
- Atlas fork 自己新增/修改文件的 focused tests
- file/patch/context/delegation/browser/skills/gateway 的直接相关 smoke
- Windows 相关 focused tests

若 full upstream suite 很快可跑，可跑一次；若明显很重，不要求。

## 交付

写：
`tasks/results/ATLAS-U0-HERMES-UPSTREAM-SYNC.result.md`

必须列：
- before/after HEAD
- ahead/behind 变为多少
- 冲突文件及选择
- upstream 新能力清单
- Atlas 重复实现可删除/可改 adapter 清单
- tests
- fork 新 HEAD

推送 `unicorn-Y/hermes-agent:atlas`。

然后只更新 Atlas main 的 Hermes 基线记录/任务状态，不开始 U1。
