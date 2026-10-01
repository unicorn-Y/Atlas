# 专题 2：连接器、扩展生态与自动化触发（2026-09-30）

## 一、当前最强做法

### 1. 连接器数量和接入方式
- **ChatGPT**（最大）：7-09 把应用目录改成「插件目录」（chatgpt.com/plugins），一个插件打包「应用 + 技能 + 模板」，一次安装；目录里有 1400+ 个插件；聊天中用 **@ 某个应用**把它的上下文拉进来，Agent 还会在干活时**主动建议该接哪个应用**；9 月宣布自定义 GPT 也迁移成插件。
- **OpenHuman**：118+ 服务**一键 OAuth**；**OpenClaw 2.0** 安装时自动发现本机已有的 ChatGPT / Claude 订阅、API 密钥和本地模型。
- **连接器托管平台**（可以直接拿来用）：Composio（1000+ 集成，托管 OAuth，提供 MCP 服务，SDK 开源）、Pipedream Connect（2500+ 应用）、Arcade（约 100 个服务，按用户身份代理授权，不用机器人令牌）、Nango（开源，自托管 OAuth）。
- **Claude**：先走连接器，没有连接器才用浏览器或电脑操作（见专题 1）。

### 2. MCP 协议的新版本（2026-07-28 规范）
- **无状态核心**：每个请求自带全部信息，远程服务器可以放在普通负载均衡后面。
- **MCP Apps**：服务器可以返回**交互式 HTML 界面**，客户端在沙箱 iframe 里渲染。ChatGPT 的应用就是这个机制——界面可以内嵌、画中画或全屏显示，通过 postMessage 和宿主通信。
- **Tasks 扩展**：长任务先返回句柄，客户端用 `tasks/get / update / cancel` 跟进。
- **授权加固**：OAuth / OIDC，企业托管授权。
- **官方 MCP Registry**（预览）：公开的 MCP 服务器目录和 API，可以用来做「搜索并一键安装」。

### 3. 技能（Skills）生态
- SKILL.md 开放标准（Anthropic 2025-12 发布），40+ 平台支持。
- 市场：skills.sh（Vercel，`npx skills add owner/repo` 一条命令安装）、skills-hub.ai（每天从 90+ 官方来源同步）、SkillsMP、ClawHub；三大市场合计 49 万+ 技能（3 月数据）。
- **自动沉淀技能**：OpenClaw 2.0 自动把做事的经验整理成「待确认的技能」；豆包把浏览器演示录成技能（专题 1）。

### 4. 自动化触发
| 产品 | 定时 | 事件触发 | 在哪跑 |
| --- | --- | --- | --- |
| Manus 2.0 | ✅ | ✅ 新邮件、Slack 消息、日历事件、广告数据变化、Notion 更新 | 云电脑 |
| ChatGPT Work | ✅ | ✅ Gmail、Slack、GitHub PR；团队共享任务；**没有 Webhook / API 触发** | 云端 |
| Claude Code Routines | ✅ | ✅ Webhook、GitHub 事件 | 云端 |
| Claude Cowork | ✅ 每小时/天/周，服务端跑，设备不用开机 | ❌ 没有事件触发 | 云端 |
| Google Information Agents（9-25） | 持续 | 持续监控网页、博客、社交媒体、实时信息流 | 云端 |
| Cursor Automations、Codex、Warp、Gemini CLI | ✅ | 部分 | 云端 / 本地 |

结论：**最强的组合是 Manus 的事件触发 + Claude Code Routines 的 Webhook + Google 的持续监控**，没有一家全有。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| MCP | 🟡 只支持 stdio 和 SSE（`MCPServerAddRequest.transport`）；没有可流式 HTTP、没有 OAuth、没有 MCP Apps、没有 Tasks、没有 elicitation | 落后新规范一个大版本 |
| 连接器 | 🟡 靠用户自己配 MCP；没有「一键授权」的连接器目录 | 和 ChatGPT、OpenHuman 差距最大的一块 |
| 插件 | 🟡 只能本地安装；第六波第 5 节做兼容 Claude Code 的插件市场 | ChatGPT 插件把「应用 + 技能 + 模板」打成一个包 |
| 技能 | ✅ 注册、发现、目录联邦、信任、回滚 | 没接 skills.sh 等公共市场的「一条命令安装」；没有自动沉淀技能 |
| 定时 | ✅ /api/schedules，自动化页 | |
| 事件触发 | 🟡 任务完成/失败、文件变化 | 没有邮件、日历、IM、Webhook、GitHub、网页变化这类外部事件 |
| 设备关机也能跑 | ❌ 只在本机跑 | 可以用「主机」当常驻服务器（两台机器的现成条件） |
| 自动建议该用哪个连接器 | ❌ | ChatGPT |

## 三、Atlas 要超过它们该做的

1. **MCP 升级到 2026-07-28 规范**：可流式 HTTP 远程服务器 + OAuth 登录（点「连接」→ 浏览器授权 → 完成）；支持 **MCP Apps**，在对话里渲染交互界面（Atlas 已经有沙箱 iframe 的经验）；支持 Tasks 和 elicitation（服务器向用户要信息时弹卡片）。这一步做完，ChatGPT 生态里基于 MCP 的应用 Atlas 基本都能直接用。
2. **连接器目录**：内置常用服务（邮箱、日历、网盘、飞书/钉钉/企业微信、Notion、GitHub、Slack…）的一键接入；底层可以接 Composio 或自托管 Nango，也可以从官方 MCP Registry 搜索并安装。**国内服务是 ChatGPT 和 Claude 的空白，是 Atlas 的机会。**
3. **@ 应用 + 主动建议**：输入框里 @ 连接器把它的上下文拉进来；Agent 发现需要某个没接的服务时，弹卡片建议接入。
4. **事件触发做全**：Webhook（本地起一个带 token 的接收地址）、邮件、日历、IM 消息、GitHub 事件、**网页变化监控**（Google Information Agents 那种持续盯），和现有调度器合并成一套「触发器」。这一项做全就超过所有家。
5. **常驻执行**：主机当常驻节点，笔记本关机后任务照常跑；手机端（Telegram / 局域网网页）能看结果。
6. **技能市场接入 + 自动沉淀**：支持 `skills.sh`、ClawHub 的一键安装（安装前展示脚本原文，走现有信任流程）；任务成功后建议「存成技能」（Atlas 已有配方，可以合并）。
7. **插件格式兼容**：第六波的 Claude Code 插件市场保留；插件包里同时能带连接器配置。

## 资料

- [MCP 2026-07-28 规范（官方博客）](https://blog.modelcontextprotocol.io/posts/2026-07-28/)、[变更与迁移（AAIF）](https://aaif.io/blog/mcp-2026-07-28-whats-changing-and-how-to-migrate)、[MCP Apps 构建指南](https://ecorpit.com/mcp-apps-server-rendered-ui-extension-build-guide-2026/)
- [ChatGPT 插件目录（2026）](https://www.taskade.com/blog/chatgpt-plugins)、[ChatGPT 和 Codex 里的插件（官方帮助）](https://help.openai.com/en/articles/20001256-plugins-in-codex)、[Apps SDK 工作原理](https://tollbit.com/blog/how-openai-apps-sdk-works/)
- [ChatGPT Work 发布解读](https://www.digitalapplied.com/blog/chatgpt-work-openai-agent-launch-2026)
- [定时编程 Agent 对比：Claude Code Routines、Cursor Automations、Codex、Warp、Gemini CLI](https://aicatchup.com/comparisons/claude-code-routines-vs-cursor-automations)、[Claude 能自动化什么（2026）](https://www.usecarly.com/blog/claude-automations/)
- [Manus 2.0](https://cellcog.ai/blog/manus-2-0/)
- [Google Information Agents 等（2026-09-25 当周新闻）](https://aiagentstore.ai/ai-agent-news/this-week)
- [Composio、Arcade、Pipedream Connect 对比](https://www.pkgpulse.com/guides/composio-vs-arcade-vs-pipedream-connect-ai-agent-tools-2026)、[Composio 替代品（含 Nango）](https://www.scalekit.com/blog/composio-alternatives)
- [Agent Skills 格式与采用](https://atlan.com/know/ai-agent/ai-agent-skills/what-are-agent-skills/)、[技能市场对比](https://www.agensi.io/learn/best-ai-agent-skills-marketplaces-2026)
- [OpenClaw 2.0（InfoQ）](https://www.infoq.com/news/2026/09/openclaw-2-release/)、[OpenHuman](https://agentic-ai.readthedocs.io/en/latest/AgentPlatforms/openhuman/)
