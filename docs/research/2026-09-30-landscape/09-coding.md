# 专题 9：编程专项（2026-09-30）

Atlas 的对标表原本就以编程 Agent 为主，这块已经做得比较全（170 个 ✅ 大多在这里）。本专题只补 9 月的新东西。

## 一、9 月的新东西

1. **代码审查成为独立功能**
   - **Codex（9-29 DevDay）**：桌面端新增代码审查视图：读摘要、看 diff、问 Codex 哪里有风险，再把意见发到 GitHub PR 或 GitLab MR。
   - **GitHub Copilot（9 月）**：审查时能用 shell 跑命令验证改动；后续审查自动关闭已经处理的意见；应用建议时自动写提交信息。
2. **安全扫描**
   - **Codex Security Cloud**：按需或定时扫描整个 GitHub 仓库，检查新提交，合并重复发现，并准备好修复。
   - **Devin**：定时扫描；新增「清理扫描」，找死代码和可以清理的地方；`/scan` 命令。
3. **可复用的云端开发环境**：Codex 保存项目配置，每个新任务都从装好依赖的环境开始，跨设备、团队共享。
4. **Agent 用量面板**：Codex `/usage`。
5. **Cursor**：Projects 协调者（专题 5）；子 Agent 在虚拟机里跑。
6. **Factory Droid**：记录「谁从哪个工具发起了 Droid 会话」的审计事件；可以选生成图片用的模型。
7. **Kiro**：会话级工具批准、环境继承控制。

## 二、Atlas 现状与差距

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| diff、改动面板、逐行评论发给 Atlas | ✅ | |
| PR 创建、CI 状态、检查日志 | ✅ | |
| 让审查员检查 | ✅ 完成后一键让「审查员」角色审查 | 没有独立的审查视图，不能审别人的 PR，不能把意见发回 PR |
| lint / 类型 / 测试结构化结果 | ✅ `run_checks` | |
| 安全扫描 | ❌ | Codex Security Cloud、Devin |
| 定时扫描仓库 | 🟡 调度器能定时跑任务，没有现成的扫描配方 | |
| worktree 并行 | ✅ | |
| 远程 / 云端环境 | 🟡 SSH 远程目录 | Codex 云环境 |

## 三、Atlas 该做的

1. **PR 审查**：打开任意 PR（自己的或别人的），Atlas 给摘要、风险点，逐行评论可以编辑后发回 GitHub。复用现有的 diff 面板和逐行评论。
2. **扫描配方**：「安全扫描」「死代码清理」做成内置配方 + 定时触发（专题 2 的触发器），结果列成待办，一键让 Atlas 修。
3. **主机当开发环境**：SSH 远程目录已有；加「环境配置」（装依赖的脚本），新任务从配好的环境开始。

## 资料

- [Codex DevDay 2026：云端环境、代码审查、安全扫描（SiliconANGLE）](https://siliconangle.com/2026/09/29/openais-codex-gets-reusable-cloud-environments-that-follow-developers-across-devices/)、[The Decoder](https://the-decoder.com/openai-expands-codex-and-its-api-at-devday-with-security-scans-a-decisions-api-and-ultrafast/)、[代码审查收件箱](https://nerdschalk.com/codex-cloud-code-review-security-cloud/)
- [GitHub Copilot 2026-09 更新](https://github.blog/changelog/month/09-2026/)
- [Devin Desktop 更新日志](https://docs.devin.ai/desktop/changelog)
- [Factory 更新日志](https://docs.factory.ai/changelog/release-notes)、[Kiro 更新日志](https://kiro.dev/changelog/)
- [Cursor 更新日志](https://cursor.com/changelog)
