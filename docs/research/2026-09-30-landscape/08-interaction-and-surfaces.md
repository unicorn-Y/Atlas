# 专题 8：交互体验——入口、语音、跨设备、协作（2026-09-30）

## 一、当前最强做法

### 1. 一个入口，自动判断是聊天还是干活
- **Claude（9-16）**：不再区分聊天模式和 Cowork 模式，Claude 自己判断是简单回答还是交给 Agent 干；聊天、任务、项目、连接器、技能全部通用。
- **ChatGPT（7-09）**：Work、Codex 并进同一个桌面端，Codex 只是一个可选的默认视图。
- 结论：**用户不该选模式**。

### 2. 语音驱动 Agent
- **ChatGPT 桌面端语音（7-23，macOS 和 Windows）**：基于全双工语音模型 GPT-Live，直接接到 Codex 和 Work：说一句话，几个 Agent 同时开工、调查、回报，你可以边说边插话、打断、追加指令。编程语音 Agent 排名第一。
- **Codex CLI**：语音对话默认开启（v0.158）。
- **Antigravity 2.0**：原生语音命令。
- **Claude Code**：`/voice`，按住空格说话，松开转成文字。
- **OpenAI（9-24）**：手机端语音办公 Agent（处理文档、邮件、总结 Slack）。

### 3. 跨设备：电脑上跑，手机上管
- **Claude Code Remote Control（9-28 正式版）**：会话一直在你自己的电脑上跑（文件、MCP、工具都在本地），手机和网页只是一个窗口；终端、浏览器、手机可以交替发消息，保持同步。9 月起，开着 Remote Control 的电脑在手机 App 里显示成一张**设备卡片**：点它、选目录，就在那台电脑上开一个新会话。
- **Claude Cowork**：会话和文件同步到账号，跨设备继续；定时任务服务端跑。
- **Codex（9-29）**：云端环境跨设备复用。
- **豆包工作**：在一台电脑上给其他已登录设备下指令（专题 1）。
- **Genspark Claw、OpenClaw、Hermes**：WhatsApp、Telegram 等 20+ 个聊天渠道派活。

### 4. 多人协作
- **OpenClaw 2.0**：多人加入同一个 Agent 会话、共享上下文；可撤销的只读分享链接。
- **豆包工作伙伴（9-15，和飞书）**：Agent 进群聊，接不同成员交来的任务。
- **ChatGPT**：群聊；团队共享的定时任务。
- **千问办公**：多人工作台（专题 3）。
- 这块 Atlas 用户是自己用，**优先级低**，只取「分享链接」和「进群聊接任务」两点。

### 5. 编程产品的界面细节（9 月更新）
- **Devin**：会话侧栏按 PR 状态或仓库分组、按模式筛选。
- **Kiro**：推理和工具活动的时间线可折叠；会话级工具批准；图片太大自动缩放、被拒自动重试。
- **goose**：回合结束或等审批时响铃。
- **Cursor**：运行中引导不打断当前工具调用，等下一次工具调用时再生效。

## 二、Atlas 现状

| 能力 | Atlas | 差距 |
| --- | --- | --- |
| 统一入口 | ✅ 基本是一个输入框；有 Plan / Act、角色、执行者等选项 | 选项偏多，可以更自动 |
| 语音 | 🟡 语音通话界面 + 本机朗读；识别用浏览器的 `SpeechRecognition` | ⚠️ **在 Electron 里很可能用不了**（需要实测）；不是全双工，不能边说边打断 |
| 手机远程 | 🟡 Telegram（没在真机上验证过）；第六波第 3 节做局域网网页版 | Claude 的 Remote Control 体验最好：手机就是这台电脑上会话的一个窗口 |
| 设备卡片（手机上选电脑、开会话） | ❌ | 两台电脑正好用得上 |
| 运行中引导 | ✅ 插话、排队 | |
| 分享 | ❌（第六波导出 HTML） | |
| 提示音 / 通知 | ✅ 系统通知 | 可以加提示音 |
| 看板 | ✅ | |

## 三、Atlas 要超过它们该做的

1. **修好语音，再做全双工**：先实测现在的语音能不能用；识别换成本地 Whisper（或 faster-whisper / SenseVoice，中文更好）或者云端识别；然后做「边说边干」：语音指令直接派任务，Agent 边做边用语音汇报，可以打断。**语音驱动多个 Agent 目前只有 ChatGPT 做到**，开源里没有。
2. **手机当窗口**：第六波第 3 节的局域网网页版保留，定位改成「Remote Control」：手机上看到的就是电脑上正在跑的会话，能发消息、批准、停止；再加**设备卡片**：主机和笔记本都在列表里，点哪台就在哪台上开会话。Telegram 作为不在局域网时的备用通道。
3. **自动判断模式**：Plan / Act 由 Atlas 根据请求自己判断（大改动先出计划，小问题直接答），用户可以覆盖。
4. **分享链接**：见专题 3。

## 资料

- [Claude Cowork 与聊天合并（2026-09）](https://www.explainx.ai/blog/claude-cowork-chat-merge-docs-slides-design-september-2026)
- [ChatGPT Work 发布解读](https://www.digitalapplied.com/blog/chatgpt-work-openai-agent-launch-2026)
- [ChatGPT 语音上桌面并能驱动 Codex（2026-07）](https://www.digitalapplied.com/blog/chatgpt-voice-desktop-codex-hands-free-agentic-coding)、[2026 最佳语音编程 Agent](https://omidsaffari.com/blog/best-voice-controlled-ai-coding-agents-2026)
- [Claude Code 手机端（官方文档）](https://code.claude.com/docs/en/mobile)、[Remote Control 设置指南](https://claudefa.st/blog/guide/development/remote-control-guide)、[手机上启动会话](https://aicatchup.com/news/claude-code-remote-control-phone-start)
- [Codex DevDay 2026 更新](https://endue.ai/blog/codex-devday-2026-updates/)
- [OpenClaw 2.0（InfoQ）](https://www.infoq.com/news/2026/09/openclaw-2-release/)
- [AI 办公三强实测（36 氪）](https://www.36kr.com/p/3989030731700105)
- [Devin Desktop 更新日志](https://docs.devin.ai/desktop/changelog)、[Kiro 更新日志](https://kiro.dev/changelog/)
- [goose 与 OpenCode 对比（2026-09）](https://www.morphllm.com/comparisons/opencode-vs-goose)、[Cursor 更新日志](https://cursor.com/changelog)
