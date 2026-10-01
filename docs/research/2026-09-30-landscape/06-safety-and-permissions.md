# 专题 6：安全与权限（2026-09-30）

用户已定：FULL_ACCESS 是默认，不做逐工具弹窗。本专题的目标不是加弹窗，而是**在不打扰用户的前提下，挡住真正危险的操作**——这正是今年各家的方向。

## 一、当前最强做法

### 1. 用「审查员」代替人工确认
- **Claude Code 自动模式**（8-14 起成为默认）：每个动作执行前，交给一个独立的分类模型审查。
  - **分类模型只看用户消息和工具调用，看不到 Claude 自己的话和工具返回的内容**——文件和网页里的恶意指令影响不到它。
  - 两段式：先用一个 token 快速判断放行还是标记；被标记了，再做完整推理给出结论。
  - 拦截：超出你请求范围的操作、针对它认不出是你的基础设施的操作、看起来是被读到的恶意内容驱使的操作；会话开始前就存在的文件的不可逆删除；`git reset --hard`、`git clean -fd`、强推、批量删除云资源。
  - 规则优先：`deny` 规则直接拒绝且不能被覆盖；`ask` 规则强制问人，分类模型不能自动放行。
- **Codex Auto-review**：主 Agent 在只读或「只能写工作区」的沙箱里干活；要越过沙箱边界时，审批请求交给独立的审查 Agent（guardian）而不是人；审查通过就继续，被拒绝则主 Agent 必须找更安全的办法或者停下来问人。约 99% 的请求被自动通过。**审查员只是换了审批的人，不扩大权限**：不增加可写目录、不打开网络、不放宽受保护路径。
- **ChatGPT Work**：敏感操作（涉及已连接系统的）先经过自动审查再执行；管理员可以集中配置哪些操作要人确认。

### 2. 隔离
- **Copilot Actions**：远程桌面子会话 + 专用低权限账户（专题 1）。
- **Codex**：三平台系统级沙箱；v0.158 起提权命令默认要确认。
- **GitHub Copilot 应用**：本地沙箱（9 月公测）。
- **Nvidia（9-30）**：开源沙箱运行时 OpenShell + 硬件级看门狗。

### 3. 防提示注入
- Claude in Chrome：页面加载前先用探针扫描恶意指令（专题 1）。
- Claude Code 分类模型看不到工具返回内容（上面第 1 条）。
- OpenClaw：网络来源的内容标为不可信，不进长期记忆（专题 4）。

### 4. 凭据
- Copilot Studio：内置凭据库，多个 Agent 复用登录。
- Manus Cue：给每个 Agent 独立的邮箱、电话、钱包，在预算内付款。
- Mastercard / Alchemy AgentCard、Google 的 Universal Commerce Protocol（9-24）：Agent 在用户授权下付款的开放标准。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| 权限模式 | ✅ 完全访问（默认）/ 改前问我 / 只读 | 完全访问下没有任何兜底 |
| 规则 | ✅ Hooks：工具调用前退出码 2 可以拦下 | 需要用户自己写命令 |
| 审查员 | ❌（上一轮调研已列为第七波候选） | Claude Code、Codex 都已是默认 |
| 危险命令识别 | ❌ 没有按命令语法拆解判断 | Claude Code 自动模式有明确清单 |
| 沙箱 | ✅ Docker 沙箱（可选）；目录限制 | |
| 提示注入防护 | ❌ | |
| 检查点 / 撤销 | ✅ 影子 git 检查点，一键撤销本轮改动 | 这是 Atlas 的兜底优势 |
| 本机接口防护 | ✅ OriginGuard、token 注入、沙箱 CSP | |

## 三、Atlas 要超过它们该做的

1. **在完全访问模式下加一个隐形审查员**（不改变「默认不弹窗」的决定）：
   - 第一层：确定性规则——危险命令清单（按命令语法拆解，识别管道、重定向、`rm -rf`、强推、格式化、注册表、批量删除），命中才进第二层；其余直接放行，零延迟。
   - 第二层：小模型审查，**只给它用户的原始请求和这次工具调用**，不给工具返回的内容（学 Claude Code，防注入）。
   - 结果：放行 / 拦下并让 Agent 换办法 / 真的拿不准才问用户。
   - 兜底：所有操作前自动建检查点（已有），出事一键撤销。
   这样对用户来说体验仍然是「不打扰」，但比 Claude Code 多一层检查点兜底。
2. **会话开始前就存在的文件，删除前自动备份**（Atlas 已有检查点，扩展到工作区以外的路径）。
3. **提示注入扫描**（专题 1 第 5 条）+ **记忆来源标记**（专题 4）。
4. **后台操作隔离**（专题 1 第 1 条）。
5. **凭据库**：网站登录保存在系统凭据库（Atlas 已经用它存 Telegram 密钥），浏览器 Agent 需要登录时从这里取，不经过模型。

## 资料

- [Claude Code 自动模式成为默认](https://triedandtyped.com/2026/08/30/claude-code-auto-mode-default/)、[分类模型工作原理](https://claudcod.com/blog/claude-code-auto-mode/)、[自动模式详解](https://www.developersdigest.tech/blog/claude-code-auto-mode-explained)
- [Codex Auto-review（官方文档）](https://developers.openai.com/codex/concepts/sandboxing/auto-review)、[OpenAI 对齐博客：无人同步监督下的自动审查](https://alignment.openai.com/auto-review/)、[Guardian 审批的失败模式](https://codex.danielvaughan.com/2026/04/20/when-guardian-approval-goes-wrong-failure-modes-escalation-patterns/)
- [Codex 审批与安全](https://developers.openai.com/codex/agent-approvals-security)、[Codex 更新日志](https://developers.openai.com/codex/changelog)
- [ChatGPT Work 发布解读](https://www.digitalapplied.com/blog/chatgpt-work-openai-agent-launch-2026)
- [Copilot Actions 与 Agent 工作区](https://www.bleepingcomputer.com/news/microsoft/microsoft-debuts-copilot-actions-for-agentic-ai-driven-windows-tasks/)
- [本周 Agent 新闻（Nvidia OpenShell、AgentCard、UCP）](https://aiagentstore.ai/ai-agent-news/this-week)
