# 产品名单与最新动态（截至 2026-09-30）

用途：确定这轮对标覆盖哪些产品，以及每家**最近三个月**的关键变化。和用户最早给的 GPT 清单（43 个产品，P01–P43）相比，标 🆕 的是清单里没有的，标 ⚠️ 的是清单里的信息已经过时。

## 一、这三个月行业发生的大事（直接影响 Atlas 的方向）

1. **「聊天」和「干活」合并成一个入口。** OpenAI 7 月 9 日发布 ChatGPT Work，Codex 桌面端并入统一的 ChatGPT 桌面端；Anthropic 9 月 16 日把 Cowork 并进 Claude，不再区分聊天模式和 Cowork 模式，由 Claude 自己判断。两家都是：一个输入框，问问题和交任务都行。
2. **任务搬到云上跑、设备之间同步。** Claude Cowork 会话可以远程运行、定时任务在服务端跑（设备不用开机）；Codex 9 月 29 日加了跨设备复用的云端开发环境；Manus 2.0 有专属云电脑；Cursor 子 Agent 可以在各自的虚拟机里跑。
3. **协调者 Agent 不写代码、只管派活。** Cursor Projects（9 月 10 日）；Perplexity Computer 把子任务分给 19 个模型中最合适的那个；Manus 2.0 换了自研 harness「Cascade」。
4. **事件触发的自动化。** Manus Automations（新邮件、日历、Slack、Notion 变化时自动开工）；ChatGPT Work 的定时任务、事件触发、持续监控；Google Search 的 Information Agents 持续盯网页和社交媒体。
5. **产出从文字变成可交付物。** ChatGPT Work 直接交表格、幻灯片、文档、网页应用，还有 Sites 可以发布成实时更新的网页；Claude Docs / Slides（9 月 beta）；Manus Studio 有视频剪辑和游戏开发。
6. **国内办公 Agent 9 月集中更新。** 豆包工作：多 Agent 并行、操作电脑、本地 Office 编辑、浏览器录制与回放、本地和云电脑自由切换、进群聊接任务；千问办公：多人协作网页应用；腾讯 WorkBuddy：开放平台和硬件接入。
7. **个人 Agent 开源项目规模很大。** OpenClaw 约 39 万星，2.0 版支持自动发现本机已有的订阅、密钥和模型，还有共享会话、后台记忆整理、自动把经验沉淀成技能；Hermes Agent 约 25 万星，9 月发了多个版本，桌面端能渲染沙箱产物，并有插件 SDK。
8. **浏览器 Agent 洗牌。** ChatGPT Atlas 浏览器 8 月 9 日停服，能力并入 ChatGPT 内置浏览器和 Chrome 扩展；Comet 全平台免费；Gemini in Chrome 上线 Auto Browse。
9. **模型格局。** Claude Opus 5.5（9 月 22 日）、Fable 5.1；OpenAI GPT-6 Astra / Sol；国内：阶跃 Step 5 Preview、小米 MiMo（9 月开源）。编程 Agent 在独立评测里 Claude Code 第一、Codex 第二，Codex 更便宜更快。

## 二、产品名单（按类别）

### A. 大厂通用桌面 Agent（「一个入口什么都能干」）

| 产品 | 最近动态 | 状态 |
| --- | --- | --- |
| ChatGPT Work / ChatGPT 桌面端（含 Codex） | 7-09 发布；1400+ 插件、@ 调用应用上下文、Plan 模式、定时和事件触发、Sites 发布网页、自动审查敏感操作；9-24 手机端语音办公 Agent；9-29 DevDay：云端开发环境、CLI 语音、代码审查、安全扫描 | ⚠️ 清单里是「Codex／ChatGPT 桌面 Work」，需按新版重查 |
| Claude（Cowork 已合并） | 9-16 聊天和 Cowork 合并、自动判断；Docs / Slides beta；会话可远程跑、定时任务服务端跑、跨设备同步 | ⚠️ |
| Claude Code（桌面端 / CLI / 网页） | Opus 5.5 默认 | ✅ 清单 P03 |
| Google Antigravity 2.0 | 5-19 I/O 发布；Agent Manager 多 Agent 调度台、自定义子 Agent 流程、后台定时任务、语音；桌面端 + CLI + SDK + 托管 Agent | ⚠️ 清单 P08 是 1.x |
| Perplexity Computer / Personal Computer | 2-25 发布；19–20 个模型编排、子 Agent 并行、可以连续跑几天几个月；6 月加了本地和云端推理自动分流；**7-28 出了 Windows 桌面版**；企业版进 Slack | ⚠️ 清单 P42 |
| Manus 2.0 / Cue | 9-28 发布：Cascade harness、云电脑、事件触发自动化、Studio（视频、游戏）；Cue 个人 Agent 有独立邮箱、电话、钱包 | ⚠️ 清单 P30 是旧版 |
| Genspark | 2026 定位成「AI 员工」：Super Agent + AI Slides/Sheets/Docs，多模型交叉核对事实；Genspark Claw / Workspace 4.0 可以通过 WhatsApp、Telegram 派活；9-18 起每周免费额度 | ⚠️ 清单 P31 |
| Microsoft Copilot（Windows） | Copilot Actions：在和用户会话隔离的「Agent 工作区」里操作桌面和网页应用（整理照片、下载文件夹、转换文件、读 PDF）；Copilot Studio 电脑操作 5 月正式上线，带内置凭据、多 Agent 复用登录；6 月 Windows 365 for Agents MCP（云电脑完全控制、语义化界面检查） | 🆕 |
| Meta Muse 个人 Agent | 9-28：退订、退款、日常事务 | 🆕（不开源，参考即可） |

### B. 国内办公 / 通用 Agent 🆕（清单只收了编程类的 TRAE、Qoder、CodeBuddy）

| 产品 | 最近动态 |
| --- | --- |
| 豆包工作（字节） | 9-02 多 Agent 并行 + 操作电脑；9 月中旬本地 Office 编辑、浏览器录制与回放、本地和云电脑切换；9-15 进飞书群聊接任务 |
| 千问办公（阿里） | 9-07 多人工作台：一句话生成可以百人在线协作的网页应用 |
| WorkBuddy（腾讯） | 9-02 开放平台，接入眼镜、录音卡片、耳机等硬件 |
| 阶跃 AI 桌面版 | 内置 Step 模型，扫码即用，支持建多个 Agent |
| Kimi（OK Computer / Agent Swarm） | K2.6（4 月开源）最多 300 个子 Agent 并行、单任务超过 4000 次工具调用；K3（7 月，2.8T 开源、原生视觉、1M 上下文）加 Goal 模式 |
| 智谱 AutoClaw / AutoGLM、扣子空间、MiniMax Agent（M3） | 都是通用办公 Agent：网页开发、音视频创作、文档分析；细节后面按能力逐项查 |

### C. 编程 Agent（清单主要覆盖的部分，需要更新版本）

| 产品 | 最近动态 |
| --- | --- |
| Cursor | 9-10 Projects（协调者 Agent 只规划和派活）；9-23 子 Agent 各自跑在虚拟机里、运行中引导不打断当前工具、token 成本降 7%（动态加载工具、压缩文件读取、提高缓存复用） |
| Codex CLI | v0.158：提权命令默认要确认、语音默认开、/usage 用量面板、默认使用 worktree |
| OpenCode | 9-11 发布 V2（2.0.14），约 21 万星 |
| goose | v1.51（9-17）：回合结束或等审批时响铃、中断的无头任务返回失败；CLI 去掉了规划模式和创建配方命令 |
| Cline | v4.1.20（9-22）：同一步里的子 Agent 并行、修复压缩 |
| Kilo Code | v7.7.7（9-22）；Kilo CLI 是 OpenCode 的分支 |
| GitHub Copilot | 9 月：自动选模型分「省钱 / 平衡 / 最强」三档；代码审查能用 shell 验证改动、自动关闭已处理的意见；Copilot 应用接 Jira、Sentry；本地沙箱（预览）；CLI v1.0.89 的自适应多模型编排 |
| Devin、Kiro、Amp、Factory、Zed、Warp、Junie、Augment、Tabnine、Amazon Q | 清单里有，按能力专题再查 |

### D. 开源个人 Agent / 常驻助手

| 产品 | 最近动态 |
| --- | --- |
| OpenClaw 2.0 | 约 39 万星；自动发现本机已有的订阅、密钥和本地模型；浏览器界面重做成主界面；多人共享云会话；后台记忆整理，经验自动沉淀成技能；可撤销的只读分享链接；会议记录库 |
| Hermes Agent | v0.21.5（9-24）；约 25 万星；新增 6 家服务商；桌面端沙箱实时预览产物；插件 SDK，看板是第一个插件 |
| OpenHuman 🆕 | 5 月发布，GPL-3.0；118+ 服务一键授权；「10 亿 token」的个人记忆、可编辑的记忆库（类似 Obsidian）；能以语音头像代你开会；上下文压缩号称省 70–80% |

### E. 电脑操作（GUI Agent）🆕

| 产品 | 最近动态 |
| --- | --- |
| Simular Sai / Agent S（开源） | Sai 8 月 OSWorld 2.0 得分 73%，超过 GPT 和 Opus；Agent S3 是第一个在 OSWorld 上超过人类的（72.6%） |
| OpenCUA | 开源模型里 OSWorld-Verified 最好（45%） |
| UI-TARS Desktop（字节） | 纯视觉操作；浏览器可以选视觉、DOM 或混合方式；内核基于 MCP；远程电脑、远程浏览器操作 |
| Stagehand v3.7 / browser-use | Stagehand：AI 生成的操作可以预览、缓存，重放时不调用模型，网站变了再让 AI 接手 |

### F. 浏览器 Agent

| 产品 | 最近动态 |
| --- | --- |
| ChatGPT Atlas | ⚠️ 8-09 停服，能力并入 ChatGPT 内置浏览器和 Chrome 扩展 |
| Perplexity Comet | Mac、Windows、iOS、Android 全平台免费，可以自主浏览、填表、下单 |
| Gemini in Chrome | Auto Browse 面向付费用户上线 |
| Claude in Chrome | 8-26 正式版：用你已登录的 Chrome 自主浏览、填表；页面加载前先用探针扫描恶意指令，号称注入成功率降到 0% |
| Dia、Tabbit | Tabbit 和 Comet 能执行多步任务；Dia、Edge、Brave 偏辅助 |

## 资料

- [Genspark 2026 功能实测](https://www.lindy.ai/blog/genspark-ai-features)
- [Copilot Actions（Windows）](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/)、[Copilot Studio 电脑操作](https://learn.microsoft.com/en-us/microsoft-copilot-studio/computer-use)
- [Kimi Agent Swarm](https://www.kimi.com/zh-cn/help/agent/agent-swarm)、[Kimi K2.6](https://www.pingwest.com/a/313078)
- [GitHub Copilot 2026-09 更新](https://github.blog/changelog/month/09-2026/)
- [UI-TARS Desktop](https://github.com/bytedance/UI-TARS-desktop)、[电脑操作 Agent 汇总（Turing Post）](https://www.turingpost.com/p/computer-use-ai-agents)
- [Claude in Chrome 正式版](https://gigazine.net/gsc_news/en/20260827-claude-chrome-available/)

- [ChatGPT Work 发布解读](https://www.digitalapplied.com/blog/chatgpt-work-openai-agent-launch-2026)
- [Claude Cowork 与聊天合并（2026-09）](https://www.explainx.ai/blog/claude-cowork-chat-merge-docs-slides-design-september-2026)、[Claude 发布说明](https://support.claude.com/en/articles/12138966-release-notes)
- [Antigravity 2.0（TechCrunch）](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/)
- [Perplexity Computer 解读](https://www.buildfastwithai.com/blogs/what-is-perplexity-computer)、[本地和云端推理分流](https://www.marktechpost.com/2026/06/05/perplexity-ai-introduces-hybrid-local-server-inference-orchestrator-for-personal-computer-automatic-on-device-and-cloud-task-routing/)
- [Manus 2.0 与 Cue](https://cellcog.ai/blog/manus-2-0/)
- [Codex 云端环境（TechCrunch 2026-09-29）](https://techcrunch.com/2026/09/29/openai-gives-codex-reusable-cloud-environments-that-work-across-devices/)、[Codex 更新日志](https://developers.openai.com/codex/changelog)
- [Cursor 更新日志](https://cursor.com/changelog)
- [AI 办公三强实测（36 氪，2026-09）](https://www.36kr.com/p/3989030731700105)、[拆解 WorkBuddy、千问办公和豆包工作（新浪，2026-09-30）](https://finance.sina.com.cn/tech/roll/2026-09-30/doc-initqvci2592696.shtml)
- [国内 AI Agent 大全（火山引擎）](https://developer.volcengine.com/articles/7673072533139030067)
- [OpenClaw 2.0（InfoQ）](https://www.infoq.com/news/2026/09/openclaw-2-release/)
- [Hermes Agent 发布页](https://github.com/NousResearch/hermes-agent/releases)
- [OpenHuman](https://agentic-ai.readthedocs.io/en/latest/AgentPlatforms/openhuman/)
- [OpenCode 与 goose 对比（2026-09）](https://www.morphllm.com/comparisons/opencode-vs-goose)、[编程 Agent 排行（2026-09）](https://www.morphllm.com/best-ai-coding-agents-2026)
- [电脑操作 Agent（Simular）](https://www.simular.ai/alternatives/computer-use-agents)、[Agent S](https://github.com/simular-ai/agent-s)、[OpenCUA](https://opencua.xlang.ai/)
- [AI 浏览器对比](https://tech-insider.org/comet-vs-gemini-agent-vs-chatgpt-atlas-2026/)
- [本周 Agent 新闻（2026-09-30 当周）](https://aiagentstore.ai/ai-agent-news/this-week)
