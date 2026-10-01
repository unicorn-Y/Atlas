# Atlas 全景对标（2026-09-30）

**目标**（用户原话整理，见记忆 `atlas-goal`）：全能 Agent、主要自己用；不是「有这个功能」就行，而是**每个细节都比最强的那家好**；要能持续跟上各家的更新。

本目录取代 `../2026-09-agent-harness-landscape.md` 作为路线依据（那份只深挖了子 Agent 编排，仍可参考）。和用户最早给的 GPT 清单（43 个产品、F001–F210）相比：补了大厂通用 Agent 的 7–9 月新版本、国内办公 Agent、电脑操作、浏览器 Agent 和开源个人 Agent，并且每个能力都写了「谁最强、怎么做的」。

| 文件 | 内容 |
| --- | --- |
| [00-roster.md](00-roster.md) | 产品名单、每家最近三个月的动态、行业九件大事 |
| [01-computer-and-browser.md](01-computer-and-browser.md) | 电脑操作与浏览器 |
| [02-connectors-extensions-automation.md](02-connectors-extensions-automation.md) | 连接器、MCP 新规范、技能市场、事件触发 |
| [03-deliverables.md](03-deliverables.md) | 文档、表格、演示、网页、分享 |
| [04-memory-and-self-learning.md](04-memory-and-self-learning.md) | 记忆和自我学习（Atlas 记忆冻结中） |
| [05-orchestration-and-models.md](05-orchestration-and-models.md) | 多 Agent 编排、多模型 |
| [06-safety-and-permissions.md](06-safety-and-permissions.md) | 审查员、隔离、防注入 |
| [07-context-and-cost.md](07-context-and-cost.md) | 提示缓存、按需加载、压缩 |
| [08-interaction-and-surfaces.md](08-interaction-and-surfaces.md) | 统一入口、语音、手机、协作 |
| [09-coding.md](09-coding.md) | 编程专项（PR 审查、安全扫描） |
| [10-tracking-sources.md](10-tracking-sources.md) | 持续跟踪的信息源 |

## 一、总判断

1. **Atlas 的强项是编程工作台**（diff、检查点、worktree、终端、浏览器面板、逐行评论），这部分已经和 Claude Code、Codex 桌面端同一水平。
2. **作为「全能」Agent，最大的缺口在「连接外部世界」和「自己干活」**：连接器、MCP 新规范、事件触发、常驻运行——这些正是 ChatGPT Work、Claude Cowork、Manus 2.0 这三个月的主攻方向。
3. **有几项便宜但每天都在吃亏**：没开提示缓存（成本和速度）、语音在 Electron 里可能用不了、完全访问模式下没有任何兜底审查。
4. **Atlas 可以做到领先的地方**（别家没做好，或者开源里没人做）：
   - Windows 上的**后台电脑操作**（开源里没人做，只有微软自己做了）；
   - **国内服务的连接器**（ChatGPT、Claude 的空白）；
   - **事件触发做全**（没有一家同时有 Webhook、邮件、IM、网页监控）；
   - **两台电脑协同**：主机常驻跑任务、手机当窗口、设备之间切换（你的现成条件）；
   - **审查员 + 检查点双保险**（别家只有审查员）。

## 二、路线和执行计划

本调研之后，用户纠正了方向：**全部功能都要，而且有现成开源代码就拿来改**，并选择了「移植」路线（保留 Atlas 后端，从 Hermes Agent 等项目逐块搬代码）。路线和任务书不再写在这里，见：

- `docs/plan/00-MASTER-PLAN.md`：总计划（W06–W12）
- `docs/plan/SOURCE-MAP.md`：每个能力从哪个仓库的哪个文件拿代码
- `tasks/taskbooks/ATLAS-W06…W12-*.md`：各波任务书
