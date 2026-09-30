# Atlas 对标表（Parity Matrix）

基线：`main@e7d13b7`，2026-09-30。来源：《主流 Agent 产品、桌面功能与 Harness 调研清单》（2026-09-30）的 F001–F210 统一功能目录。

这张表是 Atlas 的路线图。每次加功能、每期竞品情报，都回来改这里的状态。

## 0. 怎么读

| 状态 | 含义 |
| --- | --- |
| ✅ | 已有，用户能在界面里用到 |
| 🟡 | 部分：后端/Agent 工具有了但界面没有入口，或只做了一半 |
| ❌ | 缺失 |
| ➖ | 暂不做：与 Atlas 定位（通用桌面 Agent）无关，如 IDE 插件、云托管 |
| ⚖️ | 需要你拍板：和现有设计决定冲突（如 FULL_ACCESS 默认） |

**标杆**（开源桌面端，可以读源码）：

- **Hermes** — Hermes Agent / Hermes Desktop（Python，和 Atlas 后端最近；队列、批注、窗格生命周期最细）
- **goose** — aaif-goose/goose（桌面 + Recipes + MCP 扩展 + 交互式工具 UI）
- **Cline** — cline/cline（Desktop Beta、Plan/Act、checkpoint、Kanban + worktree）
- **OpenCode** — opencode V2（权限、compaction、snapshot/undo、多表面）

闭源的 Claude Code、Codex、ZCode 只当交互参考，写成「参考：xx」。

判定方法：读代码（`core/atlas/**`、`frontend/src/renderer/**`、`backend-adapter/src/client.ts`），不是跑起来逐项点。标 🟡 的多数是「后端有接口，前端 adapter 或页面没接」。

## 1. 关键发现

1. **后端宽，前端窄。** 后端有 checkpoint（影子 git）、自动 compaction、Goals、外部 Agent 后端（Claude/Codex/Hermes/Pi/ZCode）、子任务委派、hooks、定时任务、知识库，但前端 adapter 里连 `goals`、`checkpoint`、`schedules`、`backends` 都没有。**最便宜的提升是把已有后端能力接到界面上**，不用新写核心逻辑。
2. **运行中交互是最大短板。** 运行时输入框写着「补充说明，或者换个方向…」，但 `sendMessage` 实际是**另起一个新 run 并发执行**，不是 steer 也不是排队。这是所有标杆都有的基础体验（F068–F073）。
3. **没有「看结果」的工作区。** 没有文件树、diff、终端面板、浏览器/预览面板。Agent 能改文件、跑命令、开浏览器，但用户只能在步骤列表里看文字。这是和 Hermes / Claude Code / ZCode 差距最大的一块（F038–F042、F109–F117、F130–F133、F143）。
4. **记忆投入过重。** `memory/__init__.py` 3900+ 行、P9/P10 共 40 多个任务都在做记忆和「自主知识」治理，已经超过所有标杆的记忆能力；而上面几条基础体验还缺。建议记忆冻结，精力转到 2、3。
5. **会话管理只有新建和列表。** 改名、删除后端都有，但界面没入口；没有置顶、归档、导出、分叉、编辑重发。

## 2. 优先级 Top 20

排序依据：日常使用频率 × 实现成本（后端已有的优先）。

| # | 编号 | 做什么 | 现状 | 参考实现 |
| --- | --- | --- | --- | --- |
| 1 | F068–F071 | 运行中 steer + 消息队列（可编辑/删除待发条目） | ❌ 现在是并发新 run | Hermes 队列；Pi steering；Codex App-server `turn/steer` |
| 2 | F025/F028/F026/F027 | 会话改名、删除、置顶、归档 | 🟡 改名/删除后端已有 | Codex、ZCode |
| 3 | F092/F094/F097 | Checkpoint 列表 + 一键撤销本轮改动 | 🟡 `ShadowGitCheckpointStore` 已有 | OpenCode snapshots/undo；Cline checkpoint |
| 4 | F115/F103/F110 | 本轮改动 diff 面板 + 改动行数 | ❌ | Claude Code diff；ZCode 变更过滤 |
| 5 | F042/F123/F124 | 终端面板：看 Agent 命令输出、后台进程、可手动敲命令 | 🟡 后端有进程生命周期 | Hermes（hide/close 语义）；Claude Code |
| 6 | F041/F143/F130–F131 | 浏览器/预览面板（地址栏、刷新、打开本地服务） | ❌ | ZCode；Hermes Desktop；Claude Code |
| 7 | F173/F174 | 读取项目规则文件（AGENTS.md / CLAUDE.md） | ❌ | OpenCode、Junie、Cursor；标准格式直接兼容 |
| 8 | F047/F049/F050/F051 | @ 文件、任意文件附件、拖放、粘贴截图 | 🟡 只支持图片按钮 | Claude Code；Hermes |
| 9 | F082–F084 | Goal 界面：设定/暂停/替换目标 + 按轮进度 | 🟡 `/api/goals` + trace 已有 | ZCode `/goal`；Codex Goal |
| 10 | F077 | 只读 Plan 模式（先讨论再改） | ❌ 现在是自动规划 | Cline Plan/Act；Claude Code Plan |
| 11 | F059/F063 | `/` 命令菜单 + 自定义 prompt 模板 | ❌ | Pi templates；Claude Code |
| 12 | F104/F102 | 系统原生通知 + 未读标记 | 🟡 只有 apprise 外部推送 | Devin Desktop；ZCode |
| 13 | F108/F168 | Token/上下文占用显示 + 手动压缩 | 🟡 自动压缩已有 | Aider、Crush；Gemini CLI `/compress` |
| 14 | F045/F187 | 子任务/后台任务面板 | 🟡 `delegate_task` 已有 | Claude Code Tasks；Hermes |
| 15 | F065/F008 | 在界面里选执行 Agent（Atlas 自己 / Claude / Codex / Hermes…） | 🟡 后端 backends 已有 | Zed ACP；OpenHands Agent Canvas |
| 16 | F064/F184 | Recipes：把一次成功任务存成可参数化复跑的配方 | ❌ | goose Recipes/Subrecipes |
| 17 | F088/F091 | 从回复分叉、编辑最后一条消息重发 | ❌ | ZCode；Pi 会话树 |
| 18 | F087 | 辅助聊天（side chat，不打断主任务） | ❌ | ZCode `/side`；Claude Code |
| 19 | F133/F136/F137 | 页面元素点选/框选批注，成批发给 Agent | ❌（依赖 #6） | Hermes Annotate；ZCode 元素选择 |
| 20 | F154–F159 | 权限模式切换 | ⚖️ 现在默认 FULL_ACCESS 且不加逐工具审批 | OpenCode permissions；Claude Code 模式 |

第 20 项和现有决定冲突（`tasks/CURRENT.md`：「FULL_ACCESS remains the default. Do not add per-tool approval prompts.」）。建议保留 FULL_ACCESS 为默认，只加一个可选的「计划/只读」和「改文件前确认」模式，不做逐工具弹窗。需要你决定。

## 3. 全表 F001–F210

### 01 入口、安装与连接

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F001 | 账号/订阅登录 | ➖ | 只用 API Key，无需账号体系 | |
| F002 | 模型提供商连接 | ✅ | OpenAI 兼容 base+key、自定义模型、测试连接 | OpenCode `/connect` |
| F003 | 首次配置向导 | 🟡 | 有依赖检查面板，没有引导式向导 | Mistral Vibe |
| F004 | IDE 内嵌入口 | ➖ | | |
| F005 | 独立桌面入口 | ✅ | Electron | |
| F006 | Web/CLI 入口 | 🟡 | 有 `cli.py`，无 Web | Hermes 桌面/TUI 共享状态 |
| F007 | 远程配对/连接 | ❌ | | Codex Remote |
| F008 | ACP 外部 Agent | 🟡 | `agents/backends`（claude/codex/hermes/pi/zcode），界面无入口 | Zed、OpenHands |
| F009 | 统一命令/Agent 输入 | ❌ | | Warp |

### 02 项目、工作区与执行环境

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F010 | 选择本地目录 | 🟡 | 项目可填 `workspace_path`，但新会话不能直接选目录 | Claude Code |
| F011 | 多个目录 | ❌ | | Codex |
| F012 | 项目 Sources | 🟡 | 项目有 current_goal 和历史 recall，无文件/指令来源 | Codex Projects |
| F013 | 工作区分组 | ✅ | 项目 ↔ 会话 | |
| F014 | 起始分支 | ❌ | | Codex |
| F015 | Git worktree | ❌ | | Cline Kanban、Kilo |
| F016 | SSH | ❌ | | ZCode |
| F017 | 容器/沙箱 | ❌ | FULL_ACCESS 本机执行 | OpenHands |
| F018 | Cloud session | ➖ | | |
| F019 | Local/Cloud 移交 | ➖ | | |
| F020 | Profile | ❌ | | Hermes profile |
| F021 | 执行环境标记 | ❌ | 目前只有本机，做了 F016/F017 再补 | |

### 03 会话与任务导航

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F022 | 新建任务 | ✅ | | |
| F023 | 历史列表 | ✅ | 侧栏 | |
| F024 | 全文搜索 | 🟡 | 后端 `/api/search`、项目内搜索；命令面板只按标题过滤 | Hermes |
| F025 | 改名 | 🟡 | 后端+adapter 有，只用于自动起标题 | |
| F026 | 置顶 | ❌ | | Codex |
| F027 | 归档/恢复 | ❌ | | ZCode |
| F028 | 删除 | 🟡 | 后端+adapter 有，界面无入口 | |
| F029 | 分组颜色/排序 | ❌ | | ZCode |
| F030 | 状态筛选 | ❌ | | Devin Desktop |
| F031 | 时间线导航 | ❌ | | Hermes |
| F032 | 恢复阅读位置 | ❌ | | Hermes |
| F033 | JSON 导出 | ❌ | | Hermes |
| F034 | 分享线程 | ❌ | | OpenCode |
| F035 | 会话多 Tabs | ❌ | | |

### 04 布局与面板

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F036 | 侧栏任务导航 | ✅ | | |
| F037 | 三栏布局 | 🟡 | 侧栏 + 对话 + Inspector（产物/步骤/能力） | ZCode |
| F038 | 分屏窗格 | ❌ | | Claude Code |
| F039 | 可拖拽布局 | ❌ | | Claude Code |
| F040 | 文件面板 | ❌ | | |
| F041 | 浏览器面板 | ❌ | | Hermes、ZCode |
| F042 | 终端面板 | ❌ | | Hermes |
| F043 | 产物面板 | 🟡 | Inspector 产物列表，不能预览内容 | Codex |
| F044 | Kanban 指挥中心 | ❌ | | Cline Kanban |
| F045 | Tasks/子任务面板 | 🟡 | Inspector 有步骤，无子 Agent/后台命令视图 | Claude Code |

### 05 输入与上下文组合

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F046 | 自然语言任务 | ✅ | | |
| F047 | @ 文件/目录 | ❌ | | Claude Code |
| F048 | # 引用历史会话 | ❌ | | ZCode |
| F049 | 附件按钮 | 🟡 | 仅图片，≤8 MiB | |
| F050 | 拖放附件 | ❌ | | Hermes |
| F051 | 截图粘贴 | ❌ | | |
| F052 | Figma 输入 | ➖ | 可走 Figma MCP | |
| F053 | 选区上下文 | ➖ | IDE 场景 | |
| F054 | 终端/Problems 上下文 | ❌ | 做了终端面板后可「把这段输出发给 Agent」 | |
| F055 | 大段粘贴折叠 | ❌ | | ZCode |
| F056 | 语音转文字 | ✅ | 语音输入 + 语音通话 + 朗读 | |
| F057 | Web/知识材料 | ✅ | web 工具 + 知识库 | |
| F058 | 跨标签引用 | ➖ | | |

### 06 命令、技能与快捷操作

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F059 | Slash 菜单 | ❌ | | Claude Code、Pi |
| F060 | 技能快捷调用 | ✅ | 激活技能 | |
| F061 | 命令中心 | ✅ | 命令面板 | |
| F062 | 内联聊天快捷键 | ➖ | | |
| F063 | 自定义 Prompt 模板 | ❌ | | Pi |
| F064 | Recipes/Workflows | ❌ | | goose |
| F065 | 自定义 Agent 选择 | ❌ | | Roo Modes |
| F066 | 命令直通 | ❌ | 输入 `!cmd` 直接跑 | Aider |

### 07 运行中干预与消息队列

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F067 | 停止当前动作 | ✅ | `run.cancel` + 停止按钮；另有暂停/继续 | |
| F068 | 中途指导 steer | ❌ | 运行中发消息会并发起新 run | Pi、Codex App-server |
| F069 | 后续消息排队 | ❌ | | Hermes |
| F070 | 队列条目编辑 | ❌ | | Hermes、ZCode |
| F071 | 删除队列条目 | ❌ | | Hermes |
| F072 | 队列暂停/恢复 | ❌ | | Hermes |
| F073 | 立即推进队列 | ❌ | | |
| F074 | 草稿恢复 | ❌ | | Hermes |
| F075 | 运行中澄清问题 | 🟡 | 有审批卡片，没有 ask_user 工具 | Claude Code |
| F076 | 运行错误重试 | 🟡 | 后端有错误恢复（P7G），界面无 Retry | OpenClaw |

### 08 规划、目标和长期执行

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F077 | 只读 Plan 模式 | ❌ | 现在是 `requires_plan` 自动规划，不是只读模式 | Cline Plan/Act |
| F078 | 可执行计划 | 🟡 | 自动生成并校验计划，用户不能先确认 | Replit |
| F079 | Todo/任务清单 | 🟡 | 运行头部显示计划步骤进度 | Hermes Tasks |
| F080 | Specs | ❌ | | Kiro |
| F081 | Quest | ➖ | | |
| F082 | Goal | 🟡 | `/api/goals`、run、trace；adapter/界面没有 | ZCode |
| F083 | Goal 编辑/替换 | ❌ | | ZCode |
| F084 | 迭代摘要 | 🟡 | goal trace 有数据，无界面 | ZCode |
| F085 | Missions | ➖ | | |
| F086 | 后台长期运行 | 🟡 | Hub 任务 + DBOS durable | |

### 09 分叉、辅助聊天与恢复

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F087 | 辅助聊天 side chat | ❌ | | ZCode |
| F088 | 从回复分叉 | ❌ | | Pi、ZCode |
| F089 | Duplicate 会话 | ❌ | | |
| F090 | 会话树 | ❌ | | Pi |
| F091 | 编辑最后用户消息 | ❌ | | ZCode |
| F092 | Checkpoint | 🟡 | 影子 git 快照，Agent 工具可调，界面无 | OpenCode、Cline |
| F093 | 对话+文件重置 | ❌ | | ZCode |
| F094 | Undo/重新应用 | 🟡 | 能 restore，无 redo、无界面 | ZCode |
| F095 | Resume | ✅ | `resume` + `after_sequence` 断线续传 | |
| F096 | 分支摘要 | ❌ | | Pi |
| F097 | Restore checkpoint | 🟡 | 同 F092 | |

### 10 过程展示与任务状态

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F098 | 流式文本 | ✅ | | |
| F099 | 工具调用卡片 | ✅ | `timeline.ts` 白话步骤 | |
| F100 | 工具输入/输出 | ✅ | 可展开详情 + 原始事件 | |
| F101 | 运行/等待/失败标记 | ✅ | | |
| F102 | 未读提示 | ❌ | | ZCode |
| F103 | 更改行数 | ❌ | | ZCode |
| F104 | 原生通知 | 🟡 | apprise 外部推送；无系统通知 | Devin Desktop |
| F105 | 进度/Todo | 🟡 | 同 F079 | |
| F106 | 连接/重连状态 | ✅ | | |
| F107 | 错误原位恢复 | 🟡 | 错误提示条，无原位 Retry | OpenClaw |
| F108 | Token/成本状态 | ❌ | | Aider |

### 11 文件、编辑与 Git

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F109 | 文件树 | ❌ | | ZCode |
| F110 | 只看变更文件 | ❌ | | ZCode |
| F111 | Git 状态 | ❌ | | |
| F112 | 文件预览 | ❌ | | |
| F113 | 外部编辑器打开 | ❌ | 用 `shell.openPath` 即可 | |
| F114 | 多文件修改 | ✅ | Agent 文件系统工具 | |
| F115 | Diff 查看 | ❌ | | Claude Code |
| F116 | 逐行评论 | ❌ | | Claude Code |
| F117 | Accept/Reject | ⚖️ | 与 FULL_ACCESS 冲突，可做成事后撤销代替 | |
| F118 | Agent 自检/Review | 🟡 | TrajectoryReviewer + code-review 技能 | |
| F119 | Git commit | ✅ | Agent 用 git | |
| F120 | 创建/跟踪 PR | 🟡 | github-pr-workflow 技能 | |
| F121 | CI 自动修复 | ❌ | | |

### 12 终端、进程与诊断

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F122 | Agent 执行命令 | ✅ | PowerShell/cmd/argv | |
| F123 | 终端输出查看 | 🟡 | 只在步骤详情里 | |
| F124 | 后台命令 | 🟡 | 后端支持 background/detached，界面不能管理 | |
| F125 | 手动终端 | ❌ | | Hermes |
| F126 | 终端隐藏 | ❌ | | Hermes |
| F127 | 终端关闭 | ❌ | | Hermes |
| F128 | 诊断/linter 修复 | ❌ | | |
| F129 | 测试与运行结果 | 🟡 | 只有文字输出 | |

### 13 浏览器、网页与电脑交互

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F130 | URL 导航 | 🟡 | Agent 能开网页（browser_use / playwright MCP），用户侧没有浏览器 | |
| F131 | 前进/后退/刷新 | ❌ | | ZCode |
| F132 | 开发者工具 | ❌ | | ZCode |
| F133 | 元素选择器 | ❌ | | ZCode |
| F134 | 截图/录制结果 | 🟡 | playwright 截图 | |
| F135 | DOM 定位上下文 | ❌ | | ZCode |
| F136 | 区域框选批注 | ❌ | | Hermes |
| F137 | 成批发送批注 | ❌ | | Hermes |
| F138 | Agent 点击/填表 | ✅ | | |
| F139 | 浏览器接管 | ❌ | | Manus |
| F140 | 复用用户浏览器 | 🟡 | chrome-devtools MCP 已接，未做成用户可选项 | Manus Operator |
| F141 | Computer use | ✅ | UIA/CUA 真实鼠标（P18B），领先多数标杆 | |
| F142 | Node 设备能力 | ➖ | | |

### 14 预览、产物与可视编辑

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F143 | HTML/应用预览 | ❌ | | ZCode |
| F144 | PDF 预览 | ❌ | | ZCode |
| F145 | Mermaid 预览 | ❌ | | ZCode |
| F146 | 文档/表格/幻灯片产物 | 🟡 | pdf 技能、图像生成；无 docx/xlsx/pptx | Cowork |
| F147 | 代码与预览切换 | ❌ | | |
| F148 | 可视化修改 | ➖ | 网页构建器场景 | |
| F149 | Preview toolbar | ❌ | | |
| F150 | 设计系统选择 | ➖ | | |
| F151 | 产物版本历史 | ❌ | | |
| F152 | 发布/部署 | ➖ | | |
| F153 | 网页/视频一键摘要 | ❌ | | Comet |

### 15 权限、批准与边界

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F154 | 工具前批准 | ⚖️ | 审批卡片已有，但按决定不做逐工具弹窗 | |
| F155 | 只读模式 | 🟡 | 配置里有 `deny`，界面不能切换 | OpenCode |
| F156 | 自动接受文件修改 | ➖ | FULL_ACCESS 已涵盖 | |
| F157 | 完全访问/YOLO | ✅ | 默认 | |
| F158 | 自动批准审查 | ⚖️ | | Claude Code Auto |
| F159 | deny/ask/allow | 🟡 | 只有 full_access / deny 两档 | OpenCode |
| F160 | 工作目录限制 | ❌ | | OpenCode |
| F161 | 项目信任确认 | ❌ | 做 F173 规则文件时一起做 | Pi |
| F162 | 敏感动作确认 | ⚖️ | | |
| F163 | Sandbox 边界 | ❌ | | |

### 16 模型、上下文与记忆

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F164 | 模型选择 | ✅ | | |
| F165 | 推理档位 | ❌ | | ZCode |
| F166 | 本地模型 | 🟡 | 填 Ollama 等 OpenAI 兼容地址可用，无专门入口 | |
| F167 | 自动摘要/compaction | ✅ | `ContextMaintenance` 按消息数/字符数触发 | OpenCode |
| F168 | 手动压缩 | ❌ | | Gemini CLI |
| F169 | 大结果外置 | ❌ | 未核实，需查工具输出是否截断落盘 | Deep Agents |
| F170 | 用户记忆 | ✅ | facts + 候选审批 | |
| F171 | 项目记忆 | ✅ | 项目 recall | |
| F172 | 记忆启停/查看 | ✅ | 记忆页；已超过标杆 | |
| F173 | 规则文件 | ❌ | 不读 AGENTS.md / CLAUDE.md | OpenCode |

### 17 扩展与自定义行为

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F174 | Rules/Instructions | ❌ | 同 F173 | |
| F175 | Skills | ✅ | 注册、发现、目录联邦、生命周期、信任、回滚；已超过标杆 | |
| F176 | MCP servers | ✅ | 增删、重启 | |
| F177 | Plugins | 🟡 | 只支持本地安装 | Claude Code 插件市场 |
| F178 | Hooks | 🟡 | 内部 `HookBus`，用户不能配置 | Kiro、Gemini CLI |
| F179 | 自定义工具 | 🟡 | 走 MCP/插件，无轻量脚本工具 | Pi |
| F180 | Agent 配置 | ❌ | | Roo Modes |
| F181 | 扩展包 | 🟡 | skill bundles | Pi Packages |
| F182 | 主题/键位 | 🟡 | 三套主题，无自定义快捷键 | |
| F183 | Powers | ➖ | | |
| F184 | Recipes | ❌ | 同 F064 | goose |
| F185 | Warp Drive | ➖ | | |

### 18 多 Agent 与并行任务

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F186 | 多会话并行 | 🟡 | 能并发多个 run，没有并行视图 | |
| F187 | 子 Agent 委派 | 🟡 | `delegate_task`（委派给外部后端），无界面 | Claude Code |
| F188 | 角色 Mode | ❌ | | Roo |
| F189 | 上下文隔离 | 🟡 | 委派天然隔离 | |
| F190 | 工作树隔离 | ❌ | | Cline Kanban |
| F191 | 协调视图 | ❌ | | Cline Kanban |
| F192 | Worker/协调者 | ❌ | | Factory Missions |
| F193 | 并行结果汇总 | ❌ | | |

### 19 自动化、跨设备与常驻工作

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F194 | 一次性/周期调度 | ✅ | 自动化页（Hub 任务）；另有 `/api/schedules` 未接前端 | Hermes Cron |
| F195 | Cron 管理 | 🟡 | 两套调度（Hub / scheduler）并存，建议合并 | Hermes |
| F196 | 自动化触发 | 🟡 | scheduler 有 TriggerType，界面只有时间触发 | |
| F197 | 关闭前台仍继续 | 🟡 | 后端独立进程 + DBOS，但随 Electron 退出 | OpenClaw |
| F198 | 手机控制电脑任务 | ❌ | | Codex Remote |
| F199 | 远程布置任务 | ❌ | | Cowork Dispatch |
| F200 | 消息平台渠道 | 🟡 | telegram-integration 技能 | OpenClaw、Hermes |
| F201 | 共享本地状态 | 🟡 | CLI 与桌面共用后端 | Hermes |
| F202 | 断线后恢复 | ✅ | 同 F095 | |

### 20 资料、连接器与团队协作

| 编号 | 功能 | 状态 | Atlas 现状 / 说明 | 参考 |
| --- | --- | --- | --- | --- |
| F203 | 文档知识库/RAG | ✅ | `/api/knowledge` | AnythingLLM |
| F204 | 组织资料连接 | 🟡 | 通过 MCP | |
| F205 | 编码平台连接 | 🟡 | github 技能 | |
| F206 | 团队 Workspaces | ➖ | | |
| F207 | 成果分享 | ❌ | | |
| F208 | 控制台/管理面板 | ✅ | 设置、集成、依赖检查、可观测性 | |
| F209 | API/SDK 驱动 | ✅ | HTTP + WebSocket 协议（docs/api-protocol-v1.2.md） | |
| F210 | Headless/CI | 🟡 | `cli.py` | |

## 4. 统计

| 状态 | 数量 |
| --- | --- |
| ✅ | 36 |
| 🟡 | 53 |
| ❌ | 99 |
| ➖ | 18 |
| ⚖️ | 4 |

## 5. 维护规则

1. 做完一项就改状态，并在「现状」写上 commit 或 PR。
2. 竞品情报（标杆 release/changelog）出现新能力时：已在目录里的，更新「参考」列；目录里没有的，追加 F211 起的新编号，标上来源和日期。
3. 标 🟡 → ✅ 的判断标准：用户不看文档、不敲命令，能在界面里用到。
4. ⚖️ 项由你决定后改成具体状态，并把决定写进 `PLAN.md`。
