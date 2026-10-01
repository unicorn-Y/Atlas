# 专题 5：多 Agent 编排与多模型（2026-09-30）

> 上一轮调研（`../2026-09-agent-harness-landscape.md` 第三节第 6 条）已经整理过 20 多家的子 Agent 做法，本专题只补 7–9 月的新变化和多模型这一块。

## 一、7–9 月的新变化

### 1. 协调者只管派活，不干活——Cursor Projects（9-10）
- 协调者 Agent **自己不写代码**：负责规划、派给执行 Agent、收回结果交给你检查。因为不自己跑构建和测试，**随时能回你的消息**。
- 跑在云上的独立机器里，合上笔记本也不停；能并行的子 Agent 比本机多；需要你电脑上的东西时，再临时在本机起一个 Agent。
- **项目共享上下文**：一组在所有机器之间同步的文件，Agent 把调研、产物、对代码库的了解、你的偏好都写进去。一个 Agent 摸清了怎么测试某个服务，以后所有 Agent 都能用。项目越做越顺手。
- 可以让它盯一个 Slack 频道、按计划跑、跟进你所有的 PR，看到信号就自己动手。

### 2. 按需加载能力——Manus Cascade（9-28）
- 项目一开始保持轻量，**用到哪项能力才加载对应的子工具和模块**，不把所有东西带进每个任务。
- 在一个测试配置里：token 少用 23.2%，耗时少 28.2%，成本低 32%。

### 3. 大规模并行
- Kimi K2.6：最多 300 个子 Agent、单任务 4000+ 次工具调用，比单 Agent 串行快 4.5 倍。
- Manus / Genspark 的 Wide Research：100+ 个子 Agent 并行调研。
- Cursor：子 Agent 各自跑在自己的虚拟机里；Cline v4.1.20：同一步里的子 Agent 并行。
- 豆包工作（9-02）：多 Agent 并行。
- Antigravity 2.0：Agent Manager 调度台，可以自定义子 Agent 流程。

### 4. 多模型分工
- **Perplexity Computer**：把目标拆成子任务，每个子任务交给最合适的模型（19–20 个模型：Claude 负责编排和写代码，Gemini 负责调研和图像，GPT 负责长上下文和搜索，Grok 负责要快的任务）；子 Agent 同时跑；能连续跑几天。**7-28 出了 Windows 桌面版（Personal Computer）**；6 月加了本地和云端推理的自动分流。
- **GitHub Copilot（9 月）**：自动选模型分「省钱 / 平衡 / 最强」三档，由用户选权衡方向；CLI 有自适应多模型编排。
- **Microsoft 365 Copilot**：按任务复杂度、延迟和成本在 Claude、GPT、Gemini、Phi 之间自动路由。
- **Hermes**：Mixture of Agents 2.0，多个模型并行作答再汇总，包装成一个「虚拟模型」。
- **Genspark**：用多个模型交叉核对事实。
- 行业判断：2026 下半年起，「自动选模型」会成为各家的标配。

### 5. 仍然成立的提醒
- 多 Agent 不是免费的并行：每个子 Agent 都要单独推理，有依赖的任务拆开反而更差（上一轮调研已记）。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| 子 Agent / 并行 Worker | ✅ `delegate_task / delegate_parallel`，最多 8 个，各用独立 worktree | 第六波第 1 节：类型、定义文件、验收、后台、引导、配方当 Worker |
| 协调者不干活、随时能对话 | ❌ 主 Agent 派活后要等 | Cursor Projects |
| 项目共享上下文（越做越顺） | 🟡 有项目、项目资料；Agent 不会主动往里写经验 | Cursor Projects |
| 按需加载能力 | ❌ 所有工具每轮都发 | Manus Cascade、Cursor、Claude Code ToolSearch |
| 多模型分工 / 自动选模型 | ❌ 每次运行用一个模型；第六波加了 `strong_model` 给 oracle 用 | Perplexity、Copilot |
| 本地模型和云端模型分流 | ❌（可以手动选 Ollama / LM Studio） | Perplexity |
| 云上 / 常驻跑 | ❌ | 可以用主机当常驻节点 |

## 三、Atlas 要超过它们该做的

1. **第六波第 1 节保留**（类型、定义文件、验收、后台委派和引导、配方当 Worker），但把「后台委派」往前推一步，做成 **Cursor Projects 式的协调者**：主 Agent 派完活立刻回到对话，用户随时能问进度、改方向。
2. **项目记事本**：每个项目一个共享的 Markdown 目录，子 Agent 完成任务时把「学到的」（怎么测试、怎么构建、用户偏好）写进去，下次任务自动读取。和专题 4 的「透明记忆」可以是同一套机制。
3. **自动选模型**：在设置里配置「便宜 / 平衡 / 最强」几档模型；按任务类型路由：简单任务用便宜的；子 Agent 按类型选（explore 用快的，oracle 用最强的）；用户可以选偏向哪一档。先做规则路由，不要一开始就上学习型路由。
4. **多模型会诊（可选）**：重要结论让两三个模型各答一次再汇总，或者让另一个模型核对事实。
5. **本机 + 主机分工**：长任务派到主机上跑（已有 SSH 基础），笔记本关机也不影响；本地模型处理简单、隐私敏感的子任务。

## 资料

- [Cursor Projects 评测](https://www.eesel.ai/blog/cursor-projects-review)、[Cursor Projects 上线报道](https://runtimewire.com/article/cursor-projects-persistent-coordinator-coding-agents)、[Cursor 更新日志](https://cursor.com/changelog)
- [Manus 2.0 与 Cascade（Pandaily）](https://pandaily.com/manus-2-0-cascade-agent-harness-cue-personal-agents)、[Cascade 架构](https://cryptobriefing.com/manus-2-ai-agent-cascade-architecture/)
- [Perplexity Computer 多模型指南](https://www.digitalapplied.com/blog/perplexity-computer-multi-model-ai-agent-guide)、[Perplexity Windows 桌面版（2026-07-28）](https://www.techtimes.com/articles/321882/20260728/perplexity-brings-ai-desktop-agent-windows-routing-tasks-across-20-models.htm)
- [GitHub Copilot 2026-09 更新](https://github.blog/changelog/month/09-2026/)、[自动选模型模式](https://www.agentpatterns.ai/patterns/agent-design/auto-model-selection/)
- [Microsoft 365 Copilot 自动路由（2026-09）](https://robquickenden.blog/2026/09/microsoft-365-copilot-new-models-auto-routing)
- [多模型编排：路由、兜底与选择策略](https://zylos.ai/research/2026-06-27-multi-model-agent-orchestration-routing-fallback-selection/)
- [Kimi K2.6](https://www.pingwest.com/a/313078)
