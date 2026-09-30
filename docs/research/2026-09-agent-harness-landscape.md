# 主流 Agent 与 Harness 调研（2026-09）

目的：Atlas 往「全能」方向走，每个设计都要对标**当前**主流做法，而不是凭印象。本文按 harness 的 7 个子系统逐项对照 Atlas，给出差距和行动项。所有结论都来自文末列出的资料（2026 年发布或更新）。

> harness：Agent 里「模型之外的一切」——循环、模型接入、工具、记忆与上下文、安全权限、编排、扩展。2026 年 7 月的源码研究《Harness Engineering》把它定义为这 7 个子系统，并逐一拆解了 11 个系统：Claude Code、Codex CLI、Gemini CLI、Mistral Vibe、OpenHands、Aider、Mini-SWE-Agent、Hermes、Pi、OpenCode、OpenClaw，外加 Databricks 的 Omnigent（第一个「元 harness」）。

## 一、覆盖了哪些产品

| 类别 | 产品 |
| --- | --- |
| 大厂自家 CLI | Claude Code（Anthropic）、Codex CLI（OpenAI）、Gemini CLI（Google）、Mistral Vibe、GitHub Copilot（VS Code / CLI / 云端） |
| 开源编程 Agent | OpenCode（开源里星标最多之一）、DeepSeek Harness（2026-08-13 开源，两周星标登顶）、OpenHands、Aider、Mini-SWE-Agent、goose、Pi、Cline / Roo Code / Kilo Code |
| 通用/个人 Agent | Hermes Agent（Nous）、OpenClaw、Manus、Genspark |
| IDE / 平台 | Cursor 3.x、Devin Desktop（原 Windsurf）、Kiro（AWS）、Amp（Sourcegraph）、Factory（Droid / Missions） |
| 国内 | 字节 Trae、阿里 Qoder / Qwen Code、腾讯 CodeBuddy、Kimi Code（K2.6） |
| 元层 | Databricks Omnigent（把各家 harness 当可互换组件）、DeepSeek Harness 的 subagent provider（可把活派给 Claude Code / Codex / 任意 ACP Agent） |

## 二、两份研究给出的总体结论（直接影响 Atlas 架构）

来自源码研究（11 个系统）：

1. **没有一个主流运行时引入通用 Agent 框架**（LangChain、LangGraph、AutoGen 等都没有；Gemini CLI 连 Google 自家框架都没用），全是自己写的异步循环。Atlas 目前基于 LangGraph——不必马上重写，但新能力不要再往框架里加深耦合，循环控制点（停止条件、钩子、子 Agent）应掌握在自己代码里。
2. **没有一个用向量检索找代码**，全靠确定性检索（ripgrep、tree-sitter、glob）。Atlas 的代码检索应该同样以 ripgrep/AST 为主。
3. **Skills（SKILL.md）的采用已经超过 MCP**（11 个里 9 个对 8 个），并出现了注册表、信任分级和「Agent 自己写的技能」。
4. **ACP 有了第三种用途：托管别家 harness**（OpenHands 可以把 Claude Code、Codex、Gemini CLI 当可互换后端）。
5. **钩子和插件格式在向 Claude Code 收敛**：Codex 原样采用了 Claude Code 的钩子词汇并提供导入器；OpenHands 能读 Claude Code 的插件格式。
6. **行为策略从提示词挪到配置里**（权限、钩子、Agent 定义都变成文件）。

来自实证研究（176 组对照，SWE-Bench Verified / Terminal-Bench）：

7. **上下文管理主要防的是超长溢出**；**先按规则删减、再用模型总结**最省。
8. **规划从「提高准确率」变成了「省钱」**：它主要改变任务在哪里停下。
9. **工具形态要看模型**：shell 能力弱的模型用结构化工具更好；shell 能力强的模型只给 bash 反而更便宜、效果更好。

## 三、7 个子系统逐项对照

### 1. Agent 循环

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| 最简：一个 while 循环 + bash（Mini-SWE-Agent）；最强：事件溯源（OpenHands，所有动作写进持久事件日志，支持并行动作批次）；DeepSeek Harness 把循环本身做成可替换插件，所有消息、工具调用、推理、token、子 Agent 派发写进统一的追加式轨迹日志 | LangGraph 状态机；运行事件有序号、可重放（第一波） | 中期：把运行事件日志升级为「事件溯源」——恢复、分叉、审计都从日志重建。**停止前校验**（见安全节）要放在循环里 |

### 2. 模型接入

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| Hermes：5 种自有传输、29 个服务商配置；Codex：服务端下发模型目录；Hermes「Mixture of Agents 2.0」把多模型并行作答 + 汇总做成虚拟模型 | litellm + OpenAI 兼容网关，模型列表可加 | 加「强模型」配置（给深度分析 Worker 用，已写进第六波）；后续可做 MoA 式「多模型会诊」预设 |

### 3. 工具与动作

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| Claude Code：43 个类型化工具 + **延迟加载**（工具多时只发工具清单，模型用 ToolSearch 按需加载，约 1.5 万 token）；Codex：工具调用以代码形式在 V8 里执行；Pi：默认只有 read / write / edit / bash 四个工具，其余靠扩展 | 工具全部每轮都发；有 CodeAct（execute_code）；技能索引 | **工具延迟加载**（MCP 工具多时尤其需要）；按模型能力提供「精简工具」模式（强模型只给 bash + 文件读写） |

### 4. 记忆与上下文

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| Codex：Agent 自己维护的跨会话记忆流水线；Gemini CLI：基于图的上下文蒸馏；Claude Code：谱系压缩；OpenClaw：每次回复前先跑一个「主动记忆」子 Agent 取相关记忆；Amp：「Handoff」——把当前对话总结成新对话的开场，可编辑后开新线程；Pi：会话是树，可以开支线修问题，回主线时自动总结支线 | 自动压缩；手动压缩；分叉可带总结（相当于 Handoff）；会话树视图；记忆系统**冻结** | 压缩改成「先规则删减（旧工具输出、重复内容）再模型总结」；Pi 式「支线结束后把结论总结回主线」；记忆系统解冻时参考 OpenClaw 主动记忆 |

### 5. 安全与权限

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| Codex：策略规则 + **LLM 审批员**（auto-review 子 Agent 自动批准低风险操作）+ 三平台系统级沙箱；Gemini CLI 也做了跨平台沙箱；Claude Code：**Stop 钩子**作为确定性关卡，检查不过不许结束（连续拦 8 次后放行）；研究记录了「按命令语法做权限判断」 | 三档权限（完全访问 / 改前问我 / 只读）；Hooks；Docker 沙箱；目录限制；OriginGuard | **停止前校验关卡**（钩子能拦下「结束」）；「改前问我」加可选的 **LLM 审批员**，低风险自动过、高风险才问人；命令按语法拆解后判断（`rm -rf`、管道、重定向） |

### 6. 编排（子 Agent / 多 Agent）——本次重点

| 产品 | 做法 |
| --- | --- |
| Claude Code | 子 Agent（Markdown 定义，独立上下文，只回报告）；可递归组合；**Agent Teams**（2026-02，实验）：团队负责人 + 队友，共享任务清单（带依赖）+ 邮箱互发消息 |
| Codex CLI | 线程树：父会话派生子 Agent、路由、等待、汇总；审批转发；角色定义为 TOML（`~/.codex/agents/`、`.codex/agents/`），默认最多 6 个并发；实验性 |
| Gemini CLI | 子 Agent 有自己的提示词、工具集、独立上下文，防递归；**远程子 Agent 走 A2A 协议**（把大工具集放到远端，减少主 Agent 的「工具空间干扰」） |
| OpenCode | 主 Agent / 子 Agent 用 JSON 或 Markdown 定义，各自模型和权限；子会话的能力由父权限推导 |
| OpenHands V1 | TaskTool（每个任务独立对话和事件日志）+ DelegateTool（并发）；子 Agent 定义是 Markdown + frontmatter，字段含 name、description、model、tools、**skills、hooks、MCP 配置、权限模式、上下文压缩器**；内置 code-explorer、bash-runner、web-researcher；支持嵌套 |
| GitHub Copilot | `.agent.md`（项目 `.github/agents/`、用户 `~/.copilot/agents/`），VS Code / CLI / 云端共用；可带 MCP 服务器、覆盖模型 |
| Hermes | 默认扁平委派：子 Agent 在进程内线程池运行，全新对话、专注提示词、**只回摘要**、工具集取交集；v0.17 **看板 Swarm**（根 Agent 拆任务上看板，并行 Worker，**指派验证 Agent**）；v0.21 Agent 间通信、**运行中引导子 Agent** |
| goose | 子 Agent（一次性）与 **subrecipe**（可复用、带参数的流程文件）两种；最多 10 个并发 Worker；2026 加了后台异步委派、ACP 外部 Agent、Goosetown 编排层 |
| Cursor 3.x | 子 Agent 从同步改为**后台运行，还能再派子 Agent**（形成树）；Agents 窗口最多 8 个 Agent，各自 worktree；/multitask |
| Amp | 具名专职子 Agent：**Oracle**（换一个更强的推理模型做架构分析、调试、审查，主 Agent 在难点自动调用）、**Librarian**（基于代码搜索索引查外部库）、Painter |
| Factory Missions | 先和用户定计划（功能、里程碑、成功标准），再由 Mission Control 调度**编排者 / 执行者 / 验证者**三类 Agent |
| Kilo Code / Roo Code | 编排模式把大任务拆给不同「模式」（人设）的子任务 |
| Kiro | 自定义子 Agent + 规格驱动 + 钩子 + 执行模式（自动 / 监督） |
| Mistral Vibe | 串行子 Agent 委派 |
| Pi | 子 Agent 是扩展，「舰队」是一个包；会话树 |
| OpenClaw | 回复前的主动记忆子 Agent |
| DeepSeek Harness | 子 Agent 有 6 种 provider，包括直接把活派给 Claude Code、Codex、任意 ACP Agent |
| Manus / Genspark | Wide Research：100+ 个完整能力的通用子 Agent 并行做大规模调研 |
| Kimi Code（K2.6） | Sub-agents + Agent Swarm（官方称最多 300 个子 Agent、4000 步）；Plan 模式、Goal 模式 |
| Devin Desktop | Agent 指挥中心：看板式展示所有本地/云端会话的状态；Spaces 把会话、PR、文件、上下文归到一处 |

**共识（几乎所有家都这么做）**：独立上下文、只回摘要；工具集 = 类型白名单 ∩ 父权限；防递归或限制深度；用文件定义类型。

**差异化的强项（值得 Atlas 吸收）**：
- **验证者角色**（Factory、Hermes）：并行结果先由验证 Agent 对照成功标准检查，再交给用户。
- **后台异步 + 运行中引导**（Cursor、Hermes、goose）：派出去主 Agent 不必等着，可以随时给子 Agent 补充指令。
- **可复用流程当 Worker**（goose subrecipe）：Atlas 已有「配方」，应该能直接作为子任务执行。
- **远程子 Agent（A2A）**（Gemini CLI）。
- **团队模式**（Claude Code Agent Teams、Hermes 看板）：共享任务清单 + 互发消息。仍是实验性，放后面。
- **多模型会诊**（Hermes MoA）。

**Agent 定义文件格式**：Claude Code `.claude/agents/*.md`、OpenCode `.opencode/agent(s)/*.md`、Codex `.codex/agents/*.toml`、Copilot `.github/agents/*.agent.md`、OpenHands（Markdown + frontmatter，字段最全）。Atlas 以 Claude Code 风格 Markdown 为主格式，字段取 OpenHands 的超集，其他格式做导入。

**注意**：多家都标注「实验性」，且有研究指出多 Agent 不是免费的并行——每个子 Agent 都要单独推理，有依赖的任务拆开反而更差。

### 7. 扩展

| 主流做法 | Atlas 现状 | 行动 |
| --- | --- | --- |
| Pi：一切皆扩展，扩展/技能/提示模板/主题打包成 npm 或 git 包；Codex：插件市场分发；DeepSeek Harness：一切皆插件（含循环）；钩子/插件格式向 Claude Code 收敛 | Skills、MCP、本地插件；Hooks（自有事件名）；第六波做插件市场（兼容 Claude Code 格式） | **钩子事件名兼容 Claude Code**（PreToolUse、PostToolUse、Stop、SubagentStop 等），能导入 Claude Code 的 hooks 配置；插件市场同时认 Claude Code 格式 |

## 四、按优先级的行动清单

**并入第六波（Codex 尚未开工）**
1. Agent 定义：主格式 Claude Code 风格 Markdown，字段取 OpenHands 超集（name、description、tools、model、skills、hooks、mcp、permission_mode）；导入 OpenCode、Codex TOML、Copilot `.agent.md`。
2. 内置类型扩为：explore、plan、general、oracle（强模型分析）、**verifier**（对照成功标准验收）、**researcher**（网页调研，参考 OpenHands web-researcher / Amp Librarian）。
3. 并行组可选「验收」：全部完成后由 verifier 对照目标检查，不合格的项自动再派一次（最多一次）。
4. **后台异步委派 + 运行中引导**：`delegate_task` 可 `background: true` 立即返回句柄，主 Agent 继续；新工具 `subtask_status` / `subtask_message` 查看和给子 Agent 补充指令；用户也能在界面里给子任务发话。
5. **配方可以当 Worker**（goose subrecipe）：`delegate_task` 接受 `recipe` + 参数。

**第七波候选**
6. 停止前校验关卡（Stop 钩子，确定性拦截「结束」）。
7. 「改前问我」的 LLM 审批员（低风险自动过）+ 命令语法级权限判断。
8. 工具延迟加载（ToolSearch）+ 按模型的精简工具模式。
9. 上下文压缩改为「规则删减优先」；支线结论回写主线。
10. 钩子事件名兼容 Claude Code 并可导入其配置。
11. Agent 团队模式（共享任务看板 + 消息），接到现有「看板」页。
12. 远程子 Agent（A2A）；多模型会诊预设。

## 资料

- [Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents — A Source-Code Study of Eleven Systems（arXiv 2609.00006）](https://arxiv.org/html/2609.00006v1)
- [An Empirical Study of Harness Design for Coding Agents（arXiv 2609.20804）](https://arxiv.org/pdf/2609.20804)
- [Harness Engineering for Agentic AI Coding Tools: An Exploratory Study（arXiv 2602.14690）](https://arxiv.org/pdf/2602.14690)
- [Claude Code Agent Teams 官方文档](https://code.claude.com/docs/en/agent-teams)
- [Claude Code Agent Teams 指南（MorphLLM）](https://www.morphllm.com/claude-code-agent-teams)
- [Tool Search 延迟加载解析](https://oldeucryptoboi.substack.com/p/tool-search-deep-dive)
- [Codex 多 Agent 官方文档](https://developers.openai.com/codex/multi-agent)
- [Codex CLI 自定义 Agent（TOML）](https://codex.danielvaughan.com/2026/04/27/codex-cli-custom-agent-definitions-toml-specialised-subagents/)
- [The Illusion of Multi-Agent Advantage](https://codex.danielvaughan.com/2026/07/03/illusion-multi-agent-advantage-codex-cli-subagent-decision-framework-single-agent-cot-sc/)
- [Codex CLI 2026 评述](https://codemyspec.com/blog/codex-cli-review-2026)
- [Gemini CLI 子 Agent 文档](https://geminicli.com/docs/core/subagents/)
- [Gemini CLI 远程 Agent（A2A）PR](https://github.com/google-gemini/gemini-cli/pull/16013)
- [OpenHands 用任意 Agent（ACP）](https://openhands.dev/blog/use-any-coding-agent-in-openhands-with-acp)
- [OpenHands Software Agent SDK（arXiv 2511.03690）](https://arxiv.org/pdf/2511.03690)
- [GitHub Copilot 自定义 Agent 与子 Agent 编排](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents)
- [Hermes Agent v0.21 Pantheon](https://aiweekly.co/alerts/nous-research-ships-hermes-agent-v021-pantheon-with-bots-mode-agent-to-agent)
- [Hermes v0.17 看板 Swarm](https://medium.com/@sannyvanjara1/hermes-v0-17-turns-one-agent-into-a-persistent-multi-agent-kanban-team-01dcf0a84d51)
- [Hermes Mixture of Agents 2.0](https://noqta.tn/en/news/nous-hermes-mixture-of-agents-2-virtual-models-2026)
- [OpenClaw Active Memory](https://www.skool.com/build-and-automate-2188/openclaw-2026412-ships-active-memory-plugin)
- [goose：子 Agent 与 subrecipe](https://goose-docs.ai/blog/2025/09/26/subagents-vs-subrecipes)
- [goose as conductor（2026）](https://goose-docs.ai/blog/2026/05/05/goose-as-conductor/)
- [Pi 会话树与扩展（Armin Ronacher）](https://lucumr.pocoo.org/2026/1/31/pi/)
- [Cursor 3.2 作为 Agent 运行时](https://futurumgroup.com/insights/cursor-3-2-reframes-the-ide-as-an-agent-execution-runtime/)
- [Cursor 后台 Agent 与子 Agent](https://tutorials.technology/tutorials/cursor-ai-v3-complete-guide-2026.html)
- [Amp 模式与子 Agent](https://ampcode.com/docs/models-and-subagents)
- [Amp 多仓库编排](https://codex.danielvaughan.com/2026/04/07/sourcegraph-amp-multi-repo-orchestrator/)
- [Factory Missions](https://docs.factory.ai/missions/overview)
- [Kilo Code vs Cline](https://www.morphllm.com/comparisons/kilo-code-vs-cline)
- [Kiro 子 Agent](https://kiro.dev/docs/custom-agents/subagents/)
- [Devin Desktop（原 Windsurf）](https://apidog.com/blog/whats-new-in-devin-2026/)
- [DeepSeek Harness 开源（InfoQ）](https://www.infoq.com/news/2026/08/deep-seek-harness/)
- [DeepSeek Harness：一切皆插件（The New Stack）](https://thenewstack.io/deepseek-harness-open-source-plugins/)
- [Databricks Omnigent](https://www.opensourceforu.com/2026/06/databricks-launched-omnigent-an-open-source-meta-harness-for-ai-agents/)
- [Manus Wide Research](https://alternativeto.net/news/2025/7/manus-unveils-new-wide-research-mode-enabling-100-parallel-ai-agents-for-scalable-tasks/)
- [Kimi K2.6 开发者指南](https://www.verdent.ai/guides/kimi-k2-6-developers)
- [2026 国产 AI 编程 Agent 横评](https://www.hlxxi.com/ai-agent-tech/china-ai-coding-agent-comparison-selection-2026/)
- [TRAE、Kimi Code、Qoder 实测](https://www.csdn.net/article/2026-08-24/164033550)
- [Best Open Source CLI Coding Agents in 2026](https://pinggy.io/blog/best_open_source_cli_coding_agents/)
- [9 Open-Source Agent Orchestrators (2026)](https://www.augmentcode.com/tools/open-source-agent-orchestrators)
