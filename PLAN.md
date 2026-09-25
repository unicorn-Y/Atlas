# Atlas 开发计划书 (Master Plan)

> **最后更新**：2026-09-24
> **项目路径**：`D:\Atlas`
> **状态**：骨架已搭建，准备进入功能开发

---

## ⚠️  使用说明

**这份计划书是 Atlas 项目的唯一权威文档。** 任何 agent / session 接手工作前：
1. 先读完整个 PLAN.md
2. 找到自己要做的任务编号
3. 检查前置依赖
4. 读相关源码文件
5. 实现 → 验证 → 提交

不懂就问，不要猜。改完必须能跑。

---

## 0. 项目概述

**Atlas** 是一个全能型 AI 私人助理，纯本地 Windows 11 部署，一个人用。

核心理念：不重复造轮子，整合市面上最好的开源项目和工具，做成统一入口。

### 已确定的技术选型

| 层 | 选型 | 备注 |
|----|------|------|
| 桌面框架 | **Electron** + React + TypeScript | 前端代码以后可迁移 Tauri |
| UI 风格 | **暖白简洁**（Claude 风） | 米白底 #faf8f5，暖色点缀 #c47a2a |
| Agent 核心 | **Python** + LangGraph | 状态机编排，支持循环/分支/human-in-the-loop |
| 模型管理 | **手动选择**（不自动路由） + LiteLLM | 用户自己在 UI 选模型 |
| API 网关 | **monkeyapi.net** + 各家直连备选 | 环境变量 ATLAS_API_KEY / ATLAS_API_BASE |
| 记忆系统 | **SQLite + FTS5**（先简单，接口预留） | 后续升级更强的记忆系统 |
| 工具集成 | **MCP 协议**为主 + Composio 补充 | 标准化，不搞私有协议 |
| 技能库 | 从 **Hermes** 筛选迁移 | ~100个 SKILL.md |
| 后台进程 | **PM2** + APScheduler | ecosystem.config.js 已配好 |
| 通知 | Windows Toast + Telegram Bot | |
| 第二阶段 | 语音(LiveKit/Whisper) + 屏幕(ScreenPipe) | 接口预留 |

### 关键设计原则

1. 模块化：每个能力独立模块，可单独替换
2. MCP 标准化：工具接入统一走 MCP
3. Model-agnostic：不绑死任何一家模型
4. 本地优先：数据留本地
5. 渐进式：先跑通再加功能
6. 接口预留：记忆、语音、屏幕识别都留好接口

---

## 1. 当前项目结构 (已完成)

```
D:\Atlas\
├── package.json                  # monorepo 根，workspaces: ["frontend"]
├── README.md                     # 项目说明 + 结构
├── ecosystem.config.js           # PM2 进程管理配置
├── .gitignore
│
├── core/                         # ===== Python 后端 =====
│   ├── pyproject.toml            # 依赖：fastapi, langgraph, litellm, aiosqlite, etc.
│   ├── tests/
│   │   └── __init__.py
│   └── atlas/
│       ├── __init__.py           # 版本号 0.1.0
│       ├── server.py             # FastAPI + WebSocket 主服务
│       │                         #   GET  /api/health
│       │                         #   GET  /api/models
│       │                         #   POST /api/models/select
│       │                         #   GET  /api/conversations
│       │                         #   WS   /ws/chat
│       ├── cli.py                # Click CLI：atlas serve / atlas chat / atlas version
│       │                         #   CLI 内支持 /model <id> 切换，/models 列表
│       ├── agent/
│       │   ├── __init__.py       # AgentOrchestrator（当前是简单 LiteLLM 流式调用）
│       │   └── orchestrator.py   # re-export
│       ├── memory/
│       │   ├── __init__.py       # MemoryStore（SQLite + FTS5）
│       │   │                     #   表：conversations, messages, messages_fts, facts
│       │   │                     #   方法：save_message, search, set_fact, get_fact...
│       │   └── store.py          # re-export
│       ├── models/
│       │   ├── __init__.py       # ModelManager（7个预配模型，手动选择，LiteLLM 代理）
│       │   │                     #   预配：opus-4, sonnet-4, gpt-4o, gpt-4o-mini,
│       │   │                     #         haiku-3.5, deepseek-v3, deepseek-r1
│       │   └── manager.py        # re-export
│       └── tools/
│           └── __init__.py       # 空，待填充 MCP 工具管理
│
├── config/
│   └── atlas.example.toml        # 配置模板（server, models, memory, scheduler, tools, logging）
│
├── skills/                       # 技能库（待迁移）
│   └── .gitkeep
│
├── data/                         # 运行时数据（SQLite DB）
│   └── .gitkeep
│
└── frontend/                     # ===== Electron + React 前端（待创建）=====
    （尚未创建）
```

### 已有的 UI 参考文件

- `C:\Users\25011\AppData\Local\hermes\atlas-ui-mockup.html` — 暖白风格完整 mockup
  - 配色变量都在 CSS :root 里（--bg: #faf8f5, --accent: #c47a2a 等）
  - 包含：侧栏（会话列表+新建按钮+设置/技能）、顶栏（标题+模型选择器）、
    对话区（用户消息、AI消息、tool card、代码块）、输入区（附件/代码/工具/语音按钮+发送）
  - 前端开发时直接参考这个 HTML 的结构和样式

### 已有的架构文档

- `C:\Users\25011\AppData\Local\hermes\Atlas架构方案.md` — 完整架构方案

---

## 2. 开发任务清单

### 任务编号规则
- P = Phase, T = Task
- 标记 ✅ = 已完成, 🔲 = 待做, 🏗️ = 进行中
- `[Codex]` = 适合交给 Codex/低深思考 agent
- `[Human]` = 需要人工决策或操作
- `[Claude]` = 需要深思考/架构设计

---

### Phase 1: 后端跑通 (Week 1)

#### P1-T01: 安装 Python 依赖并验证后端启动 `[Codex]`
```
操作：
1. cd D:\Atlas\core
2. pip install -e ".[dev]" --break-system-packages
3. 运行 python -m uvicorn atlas.server:app --port 8765
4. 验证 http://localhost:8765/api/health 返回 {"status": "ok"}
5. 如有依赖冲突，修复 pyproject.toml 中的版本约束

验收：服务启动无报错，health endpoint 返回 200
```

#### P1-T02: 验证 CLI chat 模式 `[Codex]`
```
操作：
1. cd D:\Atlas\core
2. python -m atlas.cli chat --model claude-sonnet-4
3. 发一条消息测试流式输出
4. 测试 /models 和 /model <id> 命令
5. 如果 LiteLLM 调用失败，检查环境变量 ATLAS_API_KEY 和 ATLAS_API_BASE

前置：P1-T01 完成
验收：能正常对话，流式输出，模型切换正常
```

#### P1-T03: 配置加载系统 `[Codex]`
```
操作：
1. 新建 D:\Atlas\core\atlas\config.py
2. 用 pydantic-settings 或 tomli 读取 config/atlas.toml
3. 把 server.py / ModelManager / MemoryStore 里的硬编码参数替换为配置读取
4. 如果 atlas.toml 不存在，复制 atlas.example.toml

需要实现的配置项：
- server.host, server.port
- models.default, models.gateway.base_url, models.gateway.api_key
- memory.db_path
- logging.level

验收：改 atlas.toml 中的端口号，服务跟着变
```

#### P1-T04: 补全 REST API `[Codex]`
```
在 server.py 中添加：

1. GET /api/conversations/{id}/messages — 获取某会话的消息列表
2. DELETE /api/conversations/{id} — 删除会话
3. PUT /api/conversations/{id} — 更新会话标题
4. GET /api/search?q=xxx — 全文搜索消息
5. GET /api/facts — 列出所有事实记忆
6. POST /api/facts — 添加/更新事实

验收：用 curl 或 httpie 测试每个 endpoint，返回正确 JSON
```

#### P1-T05: 写基础测试 `[Codex]`
```
在 core/tests/ 下新建：

1. test_memory.py — 测试 MemoryStore 的增删查搜（用临时 SQLite）
2. test_models.py — 测试 ModelManager 的选择/列表/收藏（不需要真实 API）
3. test_server.py — 用 httpx + FastAPI TestClient 测试 REST API

运行：cd D:\Atlas\core && python -m pytest tests/ -v

验收：全部 pass
```

#### P1-T06: Git 初始化 `[Codex]`
```
操作：
1. cd D:\Atlas
2. git init
3. git add .
4. git commit -m "feat: Atlas v0.1.0 project skeleton"

验收：git log 有第一个 commit
```

---

### Phase 2: Electron 前端 (Week 1-2)

#### P2-T01: 初始化 Electron + React + TypeScript 项目 `[Codex]`
```
操作：
1. cd D:\Atlas
2. mkdir frontend && cd frontend
3. 用 electron-vite 或 create-electron-app 初始化：
   npm create @electron-vite/create@latest . -- --template react-ts
   （或手动配置：Vite + React + TypeScript + Electron Builder）
4. 确保 package.json 的 name 是 "atlas-frontend"
5. npm install
6. npm run dev 能打开空白 Electron 窗口

目录结构目标：
frontend/
├── package.json
├── electron.vite.config.ts
├── src/
│   ├── main/              # Electron 主进程
│   │   └── index.ts       # createWindow, tray, globalShortcut
│   ├── preload/
│   │   └── index.ts       # contextBridge 暴露 API
│   ├── renderer/          # React 渲染进程
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── main.tsx
│   │   │   ├── index.css
│   │   │   ├── components/
│   │   │   ├── hooks/
│   │   │   ├── stores/
│   │   │   └── types/
│   │   └── index.html
│   └── shared/            # 主进程和渲染进程共享的类型
│       └── types.ts

验收：npm run dev 打开 Electron 窗口显示 "Hello Atlas"
```

#### P2-T02: 实现暖白主题 CSS 基础 `[Codex]`
```
参考文件：C:\Users\25011\AppData\Local\hermes\atlas-ui-mockup.html

操作：
1. 把 mockup 的 CSS 变量搬到 frontend/src/renderer/src/index.css
2. 重点变量：
   --bg: #faf8f5
   --bg-card: #ffffff
   --bg-sidebar: #f5f2ed
   --bg-hover: #f0ede8
   --text-primary: #1a1a1a
   --text-secondary: #6b6560
   --accent: #c47a2a
   --accent-light: #f5ead8
   --border: #e8e4de
   --radius-sm: 8px
   --radius-md: 12px
3. 设置全局字体：-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif
4. 设置全局滚动条样式（6px 宽，var(--border) 色）

验收：打开看到暖白底色，不是白闪闪的默认白
```

#### P2-T03: 实现应用布局框架 `[Codex]`
```
参考 mockup 的 HTML 结构，实现以下 React 组件：

1. Layout.tsx — 最外层：左侧 Sidebar + 右侧 Main
2. Sidebar.tsx — 260px 宽，包含：
   - SidebarHeader（Logo "A" + "Atlas" + "Personal Assistant"）
   - NewChatButton
   - ChatList（按日期分组的会话列表）
   - SidebarFooter（Settings + Skills 按钮）
3. TopBar.tsx — 52px 高，包含：
   - 左：对话标题 + tools active badge
   - 右：ModelSelector 下拉 + 搜索按钮 + 任务按钮
4. ChatArea.tsx — 主对话区，flex-1，overflow scroll
5. InputArea.tsx — 底部输入框，max-width 720px 居中

暂时都用静态数据/placeholder，不需要连后端。

验收：布局和 mockup 一致，侧栏、顶栏、对话区、输入区都在正确位置
```

#### P2-T04: 实现消息组件 `[Codex]`
```
组件：
1. Message.tsx — 单条消息，props: role, name, content, time, avatar
   - 头像圆形 28px（AI 用渐变 accent 色，用户用 bg-active）
   - 内容区 padding-left: 38px
   - 支持 markdown 渲染（用 react-markdown）
2. CodeBlock.tsx — 代码块，深色背景 #1e1e1e，带语言标签和 Copy 按钮
   - 用 react-syntax-highlighter 或 prism
3. ToolCard.tsx — 工具调用卡片
   - 白底带 border，icon + tool name + detail + status checkmark

验收：能渲染示例对话（和 mockup 一致），代码高亮正常，copy 按钮可用
```

#### P2-T05: 实现 ModelSelector 组件 `[Codex]`
```
组件：
1. ModelSelector.tsx — 顶栏右侧的模型选择下拉
   - 默认显示当前模型名 + 绿色小圆点 + 下拉箭头
   - 点击展开下拉列表，显示所有可用模型
   - 收藏模型排前面，带星标
   - 选中模型后发 POST /api/models/select
   - 下拉用 headlessui 或手写

验收：能展开、选择、切换模型，UI 更新
```

#### P2-T06: WebSocket 连接和流式对话 `[Codex]`
```
实现：
1. hooks/useChat.ts — 自定义 hook
   - connect() 连接 ws://localhost:8765/ws/chat
   - sendMessage(content, conversationId, model?) 发送消息
   - 监听 chunk → 追加到当前 AI 消息
   - 监听 tool_call / tool_result → 渲染 ToolCard
   - 监听 done → 标记消息完成
   - 监听 error → 显示错误提示
   - 自动重连逻辑
2. 把 ChatArea 和 InputArea 连上 useChat

验收：在 Electron 中能和后端对话，流式显示 AI 回复
```

#### P2-T07: 会话管理 `[Codex]`
```
实现：
1. stores/conversations.ts — zustand 或 jotai 状态管理
   - 从 GET /api/conversations 加载会话列表
   - 创建新会话
   - 切换会话 → 加载该会话的消息
   - 删除会话
   - 重命名会话
2. 连接 Sidebar 的 ChatList
3. 连接 NewChatButton

验收：侧栏显示真实会话列表，点击切换，新建对话正常
```

#### P2-T08: 系统托盘 + 全局快捷键 `[Codex]`
```
在 Electron 主进程 (src/main/index.ts) 实现：

1. 创建 Tray icon（先用文字图标或简单 PNG）
2. 托盘右键菜单：Show/Hide、New Chat、Quit
3. 全局快捷键 Ctrl+Shift+A（或用户可配置）唤出/隐藏窗口
4. 关闭窗口时 hide 而不是 quit（最小化到托盘）
5. 窗口标题 "Atlas"

验收：关闭窗口后托盘还在，快捷键能唤出
```

#### P2-T09: 输入区功能完善 `[Codex]`
```
实现：
1. 可伸缩文本框（Shift+Enter 换行，Enter 发送）
2. 附件按钮：点击打开文件选择器，选择后显示文件名 chip
3. 快捷发送：Ctrl+Enter 也能发送
4. 发送按钮在有内容时变为 accent 色，空时灰色
5. 停止生成按钮：AI 回复中显示 Stop 按钮，点击发送 cancel

验收：输入体验流畅，附件可选择，停止按钮可用
```

---

### Phase 3: 工具集成 (Week 2-3)

#### P3-T01: MCP 客户端实现 `[Claude]`
```
设计和实现 D:\Atlas\core\atlas\tools\mcp_client.py：

1. 定义 MCPClient 类，能启动和连接 MCP server 进程
2. 支持 stdio 和 SSE 两种 transport
3. 支持 tool listing、tool calling
4. 管理多个 MCP server 的生命周期
5. 从 config/atlas.toml 的 [tools] 部分读取要启动哪些 server

这是核心架构代码，需要仔细设计接口，给 AgentOrchestrator 用。

验收：能启动 filesystem MCP server，列出 tools，调用 read_file
```

#### P3-T02: Agent Orchestrator 升级为 LangGraph `[Claude]`
```
当前 AgentOrchestrator 只是简单的 LiteLLM 调用。
升级为 LangGraph 状态机：

1. 定义 AgentState：messages, tool_calls, current_step, etc.
2. 定义 nodes：
   - think: 调用 LLM 生成回复或 tool call
   - execute_tool: 通过 MCP 执行工具调用
   - verify: 检查工具结果，决定是否继续
   - respond: 生成最终回复
3. 定义 edges：think→(有tool_call)→execute_tool→think / think→(无tool_call)→respond
4. 保持流式输出（chunk events）
5. 支持 human-in-the-loop（需要确认时暂停）

这是核心架构代码，需要深思考。

验收：agent 能自动决定是否调用工具，调用后继续推理
```

#### P3-T03: 接入 filesystem MCP server `[Codex]`
```
1. pip install mcp-server-filesystem（或 npm install @modelcontextprotocol/server-filesystem）
2. 在 config/atlas.toml 的 tools.auto_start 中配置
3. 测试：让 Atlas 读一个本地文件，应该能通过 tool call 完成

验收："帮我看看 D:\Atlas\README.md 的内容" 能正确返回文件内容
```

#### P3-T04: 接入 brave-search MCP server `[Codex]`
```
1. npm install @anthropic/mcp-server-brave-search（或 pip 等效包）
2. 配置 Brave API key
3. 测试搜索功能

验收："搜索一下最新的 LangGraph 教程" 能返回搜索结果
```

#### P3-T05: 接入 git MCP server `[Codex]`
```
1. 安装 git MCP server
2. 配置
3. 测试：让 Atlas 查看 D:\Atlas 的 git status / log

验收：能读取 git 信息
```

#### P3-T06: 工具调用 UI 展示 `[Codex]`
```
在前端实现：
1. 收到 tool_call event 时显示 ToolCard（loading 状态）
2. 收到 tool_result event 时更新 ToolCard（完成状态 + 结果摘要）
3. ToolCard 可展开查看完整结果
4. 多个 tool call 依次显示

验收：工具调用过程可视化，和 mockup 的 tool card 样式一致
```

---

### Phase 4: 技能迁移 + 定时任务 (Week 3-4)

#### P4-T01: 设计技能系统格式 `[Claude]`
```
基于 Hermes 的 SKILL.md 格式，设计 Atlas 的技能格式：

1. frontmatter 字段：name, description, triggers, dependencies (需要哪些 MCP tools)
2. 正文：具体的 system prompt / 指令
3. 自动激活逻辑：根据 triggers 匹配用户意图
4. 手动激活：/skill <name> 命令

输出：D:\Atlas\skills\SKILL-FORMAT.md 格式规范文档
```

#### P4-T02: 从 Hermes 迁移高价值技能 `[Codex]`
```
源目录：C:\Users\25011\AppData\Local\hermes\skills\
目标目录：D:\Atlas\skills\

优先迁移列表（按价值排序）：
1. github/ 下所有（PR, issue, review, auth 等）
2. creative/comfyui/ （ComfyUI 工作流）
3. productivity/ （PDF, OCR 等）
4. research/ （论文, blog-watcher 等）
5. software-development/ （计划, 验证等）
6. memory/ （对话存档, 记忆基建）

操作：
1. 遍历源目录，列出所有 SKILL.md
2. 筛选上述列表中的
3. 复制到 D:\Atlas\skills/ 对应子目录
4. 根据 P4-T01 定义的格式，调整 frontmatter（如果需要）

验收：D:\Atlas\skills/ 下有 20-30 个整理好的技能
```

#### P4-T03: 实现定时任务系统 `[Codex]`
```
在 core/atlas/ 下新建 scheduler.py：

1. 用 APScheduler 4.x 实现
2. 支持 cron 表达式 + interval + one-shot
3. 任务定义存 SQLite（新建 scheduled_tasks 表）
4. REST API：
   - GET /api/tasks — 列出所有定时任务
   - POST /api/tasks — 创建
   - PUT /api/tasks/{id} — 更新
   - DELETE /api/tasks/{id} — 删除
   - POST /api/tasks/{id}/run — 手动触发
5. 任务执行时调用 AgentOrchestrator.run()
6. 在 server.py startup 中初始化 scheduler

验收：创建一个每分钟执行的任务，能看到执行日志
```

#### P4-T04: 实现 Windows Toast 通知 `[Codex]`
```
1. pip install windows-toasts
2. 在 core/atlas/notifier.py 实现 Notifier 类
3. 支持：
   - 简单文本通知
   - 带按钮的通知（打开 Atlas / 忽略）
   - 定时任务完成通知
4. 在 AgentOrchestrator 完成长任务时触发通知

验收：后台任务完成后 Windows 右下角弹出 Toast
```

#### P4-T05: 前端设置页面 `[Codex]`
```
实现 Settings 页面（点击侧栏 Settings 打开）：

1. 通用设置：语言、快捷键
2. 模型设置：API Key、API Base、默认模型、自定义模型
3. 工具设置：MCP server 列表、启用/禁用
4. 通知设置：Toast 开关、Telegram 配置
5. 存储设置：数据目录、清空数据

验收：能修改设置并生效
```

---

### Phase 5: Web 界面 + Composio (Week 4+)

#### P5-T01: Web 界面 `[Codex]`
```
复用 Electron renderer 的 React 代码，作为独立 Web 应用：

1. Vite 配置一个 web build target
2. 后端提供 static file serving（或单独起一个 Vite dev server）
3. 去掉 Electron 特有的 API（通过环境判断）

验收：浏览器打开 localhost:5173 能正常对话
```

#### P5-T02: Composio 集成 `[Codex]`
```
1. pip install composio-core composio-langgraph
2. 在 tools/ 下新建 composio_tools.py
3. 注册需要的工具：Gmail, Google Calendar, Notion 等
4. 处理 OAuth 流程
5. 集成到 AgentOrchestrator 的工具列表中

验收：能通过 Atlas 发邮件或查日历
```

#### P5-T03: Telegram Bot 通知 `[Codex]`
```
1. pip install python-telegram-bot
2. 在 notifier.py 中添加 Telegram 通道
3. 支持发送文本、图片、文件
4. 配置项：bot_token, chat_id

验收：定时任务完成后能收到 Telegram 消息
```

---

### Phase 6: 第二阶段功能 (后续)

#### P6-T01: 语音对话 — LiveKit 集成 `[Claude]`
#### P6-T02: 本地语音备选 — Whisper + Piper `[Claude]`
#### P6-T03: 屏幕识别 — ScreenPipe 集成 `[Claude]`
#### P6-T04: 屏幕操作 — Computer Use `[Claude]`

（这些是后续规划，先不展开。）

---

## 3. 依赖关系图

```
P1-T01 (安装依赖)
  ├── P1-T02 (CLI chat)
  ├── P1-T03 (配置系统)
  ├── P1-T04 (REST API)
  ├── P1-T05 (测试)
  └── P1-T06 (Git init)

P2-T01 (Electron 初始化)
  ├── P2-T02 (CSS 主题)
  │   └── P2-T03 (布局框架)
  │       ├── P2-T04 (消息组件)
  │       ├── P2-T05 (模型选择器)
  │       └── P2-T09 (输入区)
  ├── P2-T06 (WebSocket 连接) ← 依赖 P1-T01
  │   └── P2-T07 (会话管理) ← 依赖 P1-T04
  └── P2-T08 (系统托盘)

P3-T01 (MCP 客户端) ← 依赖 P1-T01
  └── P3-T02 (LangGraph 升级)
      ├── P3-T03 (filesystem)
      ├── P3-T04 (brave-search)
      ├── P3-T05 (git)
      └── P3-T06 (工具 UI) ← 依赖 P2-T04

P4-T01 (技能格式) → P4-T02 (技能迁移)
P4-T03 (定时任务) ← 依赖 P1-T01
P4-T04 (Toast 通知) ← 依赖 P1-T01
P4-T05 (设置页面) ← 依赖 P2-T03

P5-T01 (Web) ← 依赖 P2-T03
P5-T02 (Composio) ← 依赖 P3-T02
P5-T03 (Telegram) ← 依赖 P4-T04
```

---

## 4. 现有源码详细规格

> 下面按文件逐一说明已有代码的结构、公开接口、已知问题。
> 改任何文件之前必须先读这一节对应的描述。

### 4.1 `core/atlas/server.py` — FastAPI + WebSocket 主服务

**依赖**: ModelManager, MemoryStore, AgentOrchestrator

**全局单例**（startup 时创建）:
- `model_mgr: ModelManager`
- `memory: MemoryStore`
- `orchestrator: AgentOrchestrator`

**已有 REST 端点**:
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 返回 `{"status":"ok","version":"0.1.0"}` |
| GET | `/api/models` | 返回 `{models: [...], current: "..."}` |
| POST | `/api/models/select` | body: `{"model":"claude-sonnet-4"}` 切换模型 |
| GET | `/api/conversations` | 返回会话列表 |

**缺失的端点**（P1-T04 要补）:
- `GET /api/conversations/{id}/messages`
- `DELETE /api/conversations/{id}`
- `PUT /api/conversations/{id}` (改标题)
- `GET /api/search?q=xxx`
- `GET /api/facts` / `POST /api/facts`

**WebSocket `/ws/chat`**:
- 客户端 → 服务器消息格式:
  ```json
  {"type": "message", "content": "...", "conversation_id": "...", "model": "..."}
  {"type": "cancel"}
  ```
- 服务器 → 客户端事件:
  ```json
  {"type": "chunk", "content": "..."}
  {"type": "tool_call", "name": "...", ...}
  {"type": "tool_result", "name": "...", ...}
  {"type": "done", "message_id": "...", "model": "..."}
  {"type": "error", "detail": "..."}
  {"type": "cancelled"}
  ```

**已知问题**:
- `@app.on_event("startup")` 已 deprecated，应迁移到 lifespan
- cancel 功能是 TODO，未实现
- CORS 全开（`allow_origins=["*"]`），开发阶段可以，上线要收紧

---

### 4.2 `core/atlas/agent/__init__.py` — AgentOrchestrator

**当前状态**: 简单的 LiteLLM 流式调用，**不是** LangGraph 状态机

**类接口**:
```python
class AgentOrchestrator:
    def __init__(self, model_mgr: ModelManager, memory: MemoryStore) -> None
    async def run(self, message: str, conversation_id: str, model: str | None = None) -> AsyncIterator[dict[str, Any]]
```

**run() 流程**:
1. 解析模型 → `model_mgr.current_litellm_model`
2. 从 memory 加载最近 50 条消息
3. 构造 messages 列表（system prompt + history）
4. 调用 `litellm.acompletion(stream=True)`
5. yield chunk events
6. 完成后 save_message 到 memory
7. yield done event

**System Prompt**: 硬编码在文件顶部 `SYSTEM_PROMPT` 常量

**升级计划**（P3-T02）:
- 改为 LangGraph StateGraph
- 添加 tool_call / tool_result 节点
- 添加 human-in-the-loop 中断点
- 保持相同的 yield 事件接口

---

### 4.3 `core/atlas/memory/__init__.py` — MemoryStore

**SQLite 表结构**:
```sql
conversations (id TEXT PK, title, created_at, updated_at, metadata)
messages (id TEXT PK, conversation_id FK, role, content, metadata, created_at)
messages_fts (FTS5 虚表，自动同步 messages.content)
facts (key TEXT PK, value, category, created_at, updated_at)
```

**公开方法**:
```python
async def init() -> None                    # 建库建表
async def create_conversation(title) -> str  # 返回 conv_id
async def list_conversations(limit=50) -> list[dict]
async def get_conversation_messages(conv_id, limit=100) -> list[dict]
async def save_message(conv_id, role, content, metadata=None) -> str  # 返回 msg_id，自动建会话
async def search(query, limit=20) -> list[dict]  # FTS5 全文搜索
async def set_fact(key, value, category="general") -> None  # UPSERT
async def get_fact(key) -> str | None
async def list_facts(category=None) -> list[dict]
async def close() -> None
```

**DB 路径**: `D:\Atlas\data\atlas.db`（硬编码，P1-T03 要改为从配置读取）

**缺失功能**:
- 删除会话
- 删除消息
- 更新会话标题
- 按会话 ID 获取单个会话详情

---

### 4.4 `core/atlas/models/__init__.py` — ModelManager

**预配模型** (7个):
| ID | LiteLLM Model | Category |
|----|---------------|----------|
| claude-opus-4 | anthropic/claude-opus-4-20250514 | flagship |
| claude-sonnet-4 | anthropic/claude-sonnet-4-20250514 | balanced |
| gpt-4o | openai/gpt-4o | balanced |
| gpt-4o-mini | openai/gpt-4o-mini | fast |
| claude-haiku-3.5 | anthropic/claude-3-5-haiku-20241022 | fast |
| deepseek-v3 | deepseek/deepseek-chat | balanced |
| deepseek-r1 | deepseek/deepseek-reasoner | reasoning |

**默认模型**: `claude-sonnet-4`
**默认收藏**: opus-4, sonnet-4, gpt-4o

**API Key 配置方式**:
- 环境变量 `ATLAS_API_BASE`（默认 `https://api.monkeyapi.net`）
- 环境变量 `ATLAS_API_KEY`
- 所有 provider 都通过 monkeyapi 统一代理

**公开方法**:
```python
def select(model_id: str) -> None          # 切换模型，无效 ID 抛 ValueError
def list_models() -> list[dict]             # 返回带 favorite/selected 标记
def add_favorite(model_id) / remove_favorite(model_id)
def add_model(model: dict) -> None          # 注册自定义模型
@property current_model -> str              # 当前模型 ID
@property current_litellm_model -> str      # 当前模型的 LiteLLM 字符串
```

---

### 4.5 `core/atlas/cli.py` — CLI 入口

**命令**:
- `atlas serve [--port 8765] [--reload]` — 启动 uvicorn
- `atlas chat [--model claude-sonnet-4]` — 终端交互，支持 `/model <id>`, `/models`, `quit`
- `atlas version` — 输出版本号

**依赖**: Click + Rich

---

### 4.6 `core/pyproject.toml` — Python 依赖

**核心依赖**: fastapi, uvicorn, websockets, litellm, langgraph, langchain-core, pydantic, pydantic-settings, aiosqlite, apscheduler (4.x alpha), httpx, click, rich, tomli, structlog

**开发依赖**: pytest, pytest-asyncio, ruff

**构建**: hatchling

**CLI 入口点**: `atlas = atlas.cli:main`

---

### 4.7 `config/atlas.example.toml` — 配置模板

分区：general, server, models, models.gateway, memory, scheduler, notifications, tools, logging

注意：当前代码并未读取此配置文件。P1-T03 要实现 `config.py` 来加载它。

---

### 4.8 `package.json` — Monorepo 根

**npm scripts**:
- `dev` — 同时启动 backend + frontend
- `dev:backend` — uvicorn --reload
- `dev:frontend` — frontend npm dev
- `build` — frontend build
- `start` / `stop` — PM2

**workspaces**: `["frontend"]`（frontend 目录尚未创建）

---

### 4.9 `ecosystem.config.js` — PM2 配置

配置了 `atlas-backend` 进程，指向 `core/` 目录运行 uvicorn。

---

### 4.10 其他文件

- `core/atlas/__init__.py` — 只有 `__version__ = "0.1.0"`
- `core/atlas/agent/orchestrator.py` — re-export from `__init__`
- `core/atlas/memory/store.py` — re-export from `__init__`
- `core/atlas/models/manager.py` — re-export from `__init__`
- `core/atlas/tools/__init__.py` — 空的，只有 docstring
- `core/tests/__init__.py` — 空
- `skills/.gitkeep`, `data/.gitkeep` — 占位
- `.gitignore` — 标准 Python + Node 忽略规则
- `README.md` — 项目说明

---

## 5. 开源项目参考清单

> 开发过程中遇到实现困难时，优先参考以下项目的源码。

| 功能 | 项目 | GitHub | 重点看 |
|------|------|--------|--------|
| Electron + AI Chat | **LobeChat** | lobehub/lobe-chat | 前端组件、流式渲染、会话管理 |
| Agent 编排 | **LangGraph** | langchain-ai/langgraph | StateGraph、节点定义、流式输出 |
| 本地 Agent | **Open Interpreter** | OpenInterpreter/open-interpreter | CLI 交互、工具调用 |
| 模型代理 | **LiteLLM** | BerriAI/litellm | provider 适配、streaming |
| SaaS 集成 | **Composio** | ComposioHQ/composio | OAuth、工具注册 |
| 屏幕识别 | **ScreenPipe** | mediar-ai/screenpipe | 截屏、OCR、搜索 |
| IDE Agent | **OpenHands** | All-Hands-AI/OpenHands | 沙箱执行、工具设计 |
| 代码 Agent | **Aider** | paul-gauthier/aider | git 集成、diff 编辑 |
| 本地 AI 助手 | **Khoj** | khoj-ai/khoj | 记忆、搜索、自动化 |
| 桌面 AI | **Jan.ai** | janhq/jan | Electron + 本地模型 |
| 多 Agent | **CrewAI** | joaomdmoura/crewAI | 角色定义、任务分配 |

---

## 6. Codex Desktop 任务委派指南

> 标记 `[Codex]` 的任务适合交给 Codex Desktop (GPT6luna 模型) 通过 CDP 分配。

### 适合 Codex 的任务特征
- 有明确的输入/输出
- 不需要架构决策
- 代码量可控（单文件 < 500 行）
- 有清晰的验收标准

### 不适合 Codex 的任务
- 需要跨多个模块协调的架构设计（标 `[Claude]`）
- 需要理解整体系统来做取舍的决策
- 涉及安全敏感的配置

### 委派格式模板
```
任务：{任务编号} {任务标题}
项目路径：D:\Atlas

做什么：
{从本计划书的任务描述复制}

前置条件：
{列出需要先完成的任务}

现有代码参考：
{列出需要先读的文件路径}

验收标准：
{从任务描述的"验收"部分复制}

工作规范：
- 改代码前先读现有代码
- 所有修改都要能跑
- Python 用 type hints
- 提交用 conventional commits
```

---

## 7. 给 Codex / 其他 Agent 的工作指南

### 必读文件

接手任务之前，按需读以下文件：

| 文件 | 什么时候必须读 |
|------|---------------|
| `D:\Atlas\PLAN.md`（本文件） | 每次开始工作前 |
| `D:\Atlas\core\atlas\server.py` | 改后端 API |
| `D:\Atlas\core\atlas\agent\__init__.py` | 改 agent 逻辑 |
| `D:\Atlas\core\atlas\memory\__init__.py` | 改记忆系统 |
| `D:\Atlas\core\atlas\models\__init__.py` | 改模型管理 |
| `D:\Atlas\core\atlas\cli.py` | 改 CLI |
| `D:\Atlas\core\atlas\tools\__init__.py` | 加工具 |
| `D:\Atlas\config\atlas.example.toml` | 改配置 |
| `D:\Atlas\core\pyproject.toml` | 加 Python 依赖 |
| `D:\Atlas\package.json` | 加 npm 依赖/脚本 |
| `C:\Users\25011\AppData\Local\hermes\atlas-ui-mockup.html` | 做前端 UI |

### 环境信息
- **OS**: Windows 11 Pro
- **Python**: 系统 Python（确认版本 ≥ 3.11）
- **Node.js**: 已安装（确认版本 ≥ 18）
- **项目路径**: `D:\Atlas`
- **API 网关**: monkeyapi.net（环境变量 ATLAS_API_KEY, ATLAS_API_BASE）

### 工作规范
1. **改代码前先读现有代码**。先看懂再改，不要凭猜测写。
2. **所有修改都要能跑**。改完必须验证（运行/测试），不要提交跑不起来的代码。
3. **保持现有风格**。看看旁边的代码怎么写的，保持一致。
4. **Python 用 type hints**。所有函数签名都要有类型标注。
5. **TypeScript 严格模式**。不要用 any，不要 @ts-ignore。
6. **提交信息用 conventional commits**。feat: / fix: / refactor: / docs: / test:
7. **一个任务一个 commit**。不要把多个任务混在一起。

### 如何开始一个任务
1. 读这个计划书，找到你要做的任务编号
2. 检查前置依赖是否已完成
3. 读相关现有代码文件
4. 实现
5. 验证（运行 / 测试）
6. 提交

### 关键文件快速索引
| 你要改什么 | 看哪个文件 |
|-----------|------------|
| 后端 API | `core/atlas/server.py` |
| Agent 逻辑 | `core/atlas/agent/__init__.py` |
| 记忆系统 | `core/atlas/memory/__init__.py` |
| 模型管理 | `core/atlas/models/__init__.py` |
| CLI 命令 | `core/atlas/cli.py` |
| 工具集成 | `core/atlas/tools/__init__.py` |
| 配置模板 | `config/atlas.example.toml` |
| PM2 配置 | `ecosystem.config.js` |
| Python 依赖 | `core/pyproject.toml` |
| UI mockup | hermes 目录下 `atlas-ui-mockup.html` |
| 架构方案 | hermes 目录下 `Atlas架构方案.md` |
