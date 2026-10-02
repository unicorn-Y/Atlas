# ATLAS-C3R-FINISH：C3 两项最小补做

> **当前正式任务。主控：GPT-6.1 Sol / reasoning=medium；施工子代理：GPT-6 Luna / reasoning=high。**
> 这是 C3 的最小 repair，不是重做 C3。
> C3 review: `tasks/reviews/ATLAS-C3-SESSION-INTERACTION.review.md`

工作目录：`D:\Atlas`。Hermes fork：`D:\hermes-agent`。

## 只做两件事

### 1. I3：Automation Goal 统一到 Hermes GoalManager

现状：
- 对话内 `/goal` 已走 Hermes GoalManager；
- Automation / GoalsPanel 仍走 Atlas Scheduler 自己的 goal store / evaluation / continuation loop。

目标：
- **Scheduler 只负责“什么时候触发”**；
- goal 的定义、状态、progress、pause/resume/replace/clear、evaluation、continuation、completed/blocked 等运行语义统一使用 Hermes GoalManager；
- Automation 页和聊天 `/goal` 看到的是同一套 Goal backend / lifecycle；
- 不保留第二套独立 goal 状态机或第二份真相源。

允许：
- Scheduler 保存 trigger/cron/interval 元数据；
- 为 Automation 做很薄的 adapter，把 trigger 触发转成对 Hermes GoalManager 的推进调用。

不要：
- 重写 Hermes GoalManager；
- 再建新的 goal DB；
- 顺手改 Automation 其它功能。

完成标准：
- 从 Automation 创建一个 goal 后，Hermes GoalManager 能读到并推进同一个 goal；
- pause/resume/replace/clear 对两边一致；
- 一次假模型推进能更新同一份 progress/evaluation 状态；
- chat 与 Automation 不再各自维护一份 goal lifecycle。

### 2. A4：子 Agent 启停 + 默认模型设置

只补任务书遗漏的两项 UI：
- 子 Agent：启用 / 禁用
- 默认子 Agent 模型

要求：
- 优先接现有 child/subagent 配置和 ModelManager；
- 设置立即用于后续新建的 child Agent；
- 不影响已经运行中的 child Agent；
- 不新建第二套 settings store；
- 如果后端已有字段，只接 UI；缺字段时只加最小 API/配置。

## 不要碰

已经通过验收的 C3 项不要重构：
- immediate redirect
- session tree / summaries
- checkpoint / undo-redo
- permissions
- plan mode
- slash commands
- status/context
- background tasks
- worker acceptance

不要开始 C4。
不要碰 ZCode 的 `zcode/c5-models-parallel` 并行施工线。

## 最小验证

禁止重新跑整轮 C3。

只做：
1. Goal backend：2–3 个 focused tests，覆盖 Automation → Hermes GoalManager 同源、pause/resume/replace/clear、一次推进；
2. Subagent settings：1 个后端 focused test（若后端有改动）；
3. 前端：1 个 Vitest 覆盖启停 + 默认模型设置；
4. renderer TypeScript、Electron TypeScript、Vitest、Vite build 各一次；
5. **不重跑 backend full pytest**，除非 repair 意外触碰了广泛共享基础设施。

不用真实模型/外部服务。

## 交付

完成后：
- 更新 `docs/plan/CORE-PARITY.md`：I3、A4 改成 ✔；
- 写 `tasks/results/ATLAS-C3R-FINISH.result.md`；
- `tasks/CURRENT.md` 改为 `AWAITING_REVIEW`；
- push main，核验 remote HEAD；
- 停止，通知上游验收；
- **不要自行开始 C4。**
