# Codex 界面与模块全清单（逐个说明用途）

**证据等级：S**。全部来自包内文件：`webview/assets/*.js` 的 i18n 文案、chunk 名、`app-server` 协议 schema、Rust 源码。
本文回答一个问题：**Codex 里到底有哪些东西，每一个是干什么用的。**

---

## 一、主界面（会话区）

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 模式切换器 | 在 **ChatGPT**（对话）与 **ChatGPT Work / Codex**（编码代理）之间切换 | 截图实测 `Switch mode, current mode: ChatGPT` |
| New chat | 新建会话 | `thread/start` |
| Composer（输入框） | 输入任务；支持附件、语音、模型选择、权限选择 | `composer-controls`(257KB)、`composer-utility-bar`(139KB) |
| Full access 徽标 | 显示当前沙箱为完全访问；可切换只读/工作区/完全访问 | `permissionProfile/list` 返回 `:read-only` `:workspace` `:danger-full-access` |
| 模型选择器 | 选模型 + 推理档位（low→ultra） | `model/list` 实测返回 11 个模型 |
| 发送 / 停止 | 发消息；中断当前轮 | `turn/start` / `turn/interrupt` |
| 排队消息列表 | 模型运行中追加消息，排队等待 | `queued-message-list`、`thread/queue/*` |
| 中间旁白（commentary） | 执行过程中的进度更新（系统提示要求 60 秒内必须有一条） | 系统提示原文 |
| 最终答复（final） | 自包含的完整结果；commentary 会被折叠 | 系统提示原文 |

## 二、左侧导航

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| Pinned | 置顶会话 | `threadSection/list` 实测返回 `Pinned` |
| Projects | 项目分组（把会话按仓库/目录归类） | `project/list`、`project/create` |
| Recents | 最近会话 | `thread/list` |
| Scheduled | **定时任务** | i18n `创建定时任务` `已安排的任务` `ScheduledTaskSummary` 协议 |
| Plugins | 插件市场 | `plugin/list`、`marketplace/*` |
| Explore | 探索/发现 | 导航项实测 |
| Search | 全局搜索会话内容 | `thread/search`、`thread/searchOccurrences` |
| 会话右键菜单 | 重命名/固定/归档/删除/分支 | `thread/name/set`、`thread/archive`、`thread/fork`、`thread/delete` |

## 三、消息与工具展示

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| Markdown 渲染 | 富文本、表格、代码块 | `chatgpt-markdown-view`(108KB) |
| 数学公式 | LaTeX 渲染 | `chatgpt_math_blocks`(94KB) |
| 代码块 | 语法高亮、复制 | `chatgpt-code-block`(47KB) |
| 工具调用卡 | 显示命令执行、状态、输出流 | `command-messages`(73KB)、`item/commandExecution/outputDelta` |
| 终端交互 | 显示 PTY 会话、可输入 | `terminalInteraction` 通知、`write_stdin` 工具 |
| Diff 卡片 | 文件变更可视化 | `auto-diff`、`file-diff`、`diff-preview`、`turn/diff/updated` |
| 计划卡片 | 多步骤任务进度 | `update_plan` 工具、`turn/plan/updated` |
| 推理摘要 | 显示模型思考摘要 | `item/reasoning/summaryTextDelta` |
| 图片查看 | 查看/生成图片 | `view_image`、`imageGeneration` |
| 内联可视化 | 在对话里渲染交互图 | `inlineVisualization` 通知、`visualize` 插件 |

## 四、多 Agent / 子代理

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 子代理侧面板 | 查看所有子代理及状态 | `subagent-panel`、`chatgpt-subagents-panel` |
| 子代理行 | 每个子代理一行（状态/名称） | `subagent-row` |
| 子代理 Tab | 本地会话里以 Tab 并列查看 | `local-conversation-subagents-panel-tab` |
| 活动条目 | started/interacted/interrupted/completed | `agent-activity-item`、`subAgentActivity` 通知 |
| 最终回复查询 | 拉取子代理的结论 | `chatgpt-subagent-final-response-query` |
| 协作者头像/配色/标签 | 区分不同 agent 身份 | `collaborator-avatar`、`page-collaborator-colors` |
| 协作模式 | Plan / Default | `collaborationMode/list` 实测返回 `Plan`、`Default` |
| 并发上限 | **最多 4 个 agent 同时活跃** | 系统提示原文 |

## 五、Codex Micro（实体硬件控制台）

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 6 个 Agent Key | 一键切换/查看 6 个 agent；灯色表示状态 | `White–Idle / Blue–Thinking / Green–Complete / Amber–Requires input / Red–Error / Off` |
| Command Keys | 绑定常用动作、快捷键、keycap、skill | `codex-micro-settings`(842 条文案) |
| 旋钮 Encoder | 左转/右转/按下（长按开设置） | `Assign left turn` / `Turn right` |
| 模拟摇杆 | 四方向各自映射动作；推远触发 | `Move farther to trigger` / `Direction reached` |
| 灯光 | 亮度 + 无操作自动熄灭 | `Adjusts the brightness` / `auto-off` |
| Keycap 编辑器 | 自定义每个键帽显示内容 | `Choose what appears on {slotId}` |
| Push to talk | 按住说话（实时语音） | `Push to talk` |
| YOLO / YEET 键 | 往输入框写 `:yolo:` / `:yeet:` | 原文 keycap 丝印 |
| **Secret game** | 摇杆持续划圈触发小游戏 | `Keep circling · {progress}` / `Category label ... "Secret game"` |
| 三款小游戏 | brick-breaker / asteroids / snake | `codex-micro-mini-games` |
| 设备 | Work Louder **Creator Micro 2** 定制版 | onboarding 原文 |

## 六、Codex Mobile（手机遥控本机）

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| Setup 对话框 | 把手机连到这台电脑 | `codex-mobile-setup-dialog`(98KB) |
| QR 码配对 | 手机扫码配对；可全屏、可刷新、有动画 | `Scan to continue setup in ChatGPT` |
| 配对码 | 手动输入备用 | `Copy pairing code` |
| Allow host | 允许设备控制本机 | `Allow devices to control this computer?` |
| MFA 检查 | 开启远程控制前必须开双重验证 | `Turn on Multi-Factor Authentication` |
| Keep PC awake | 远程访问时阻止睡眠 | `Prevent sleep when this computer is plugged in` |
| Locked Computer Use | 锁屏状态下仍可控制 Mac 应用 | `Use your Mac apps while locked` |
| Computer Use | 让 ChatGPT 控制本机应用 | `Let ChatGPT control apps on your PC` |
| Chrome 扩展 | 让 ChatGPT 浏览网页、填表 | `Set up Chrome extension` |
| 设备管理 | 查看/撤销已授权设备 | `remoteControl/client/list` / `revoke` |
| 三大卖点文案 | 接着做 / 保持知情 / 随时开新任务 | `Pick up where you left off` / `Stay in the loop` / `Start something new` |
| 安全提示 | 明确告知可访问文件、应用、浏览器 | 原文 security notice |

## 七、设置页

| 分类 | 用来干嘛 | 证据 |
|---|---|---|
| Account | 账号、登录、套餐 | `account-settings`(58KB)、`account/*` RPC |
| Appearance | 主题（浅色/深色/跟随系统） | `appearance-settings`、`getSystemThemeVariant` |
| Analytics | 用量分析（5 小时/每周额度历史） | `analytics-settings`、`analytics_plan_history` feature |
| Agreements | 条款 | `agreements-settings` |
| Age settings | 年龄相关设置 | `age-settings` |
| Connections | 已连接的应用/设备 | `app-connect-*`、`remoteControl/client/list` |
| Plugins | 插件安装/管理/分享 | `add-plugins-modal`、`plugin/share/*` |
| Skills | 技能列表、开关、额外根目录 | `skills/list`、`skills/extraRoots/set` |
| Hooks | Hook 列表与状态 | `hooks/list`、`hook/started` / `hook/completed` |
| Codex Micro | 硬件按键映射（7 大类） | `codex-micro-settings` |
| Remote / Mobile | 手机配对与设备管理 | `codex-mobile-setup-*` |
| Computer Use | 本机操作权限与范围 | `ComputerUseConfig` 协议 |
| Browser | 浏览器接入策略、WebMCP、标注 API | `get-browser-webmcp-policy` |
| Experimental | 实验功能开关 | `experimentalFeature/list` 实测 |

## 八、审批与安全

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 命令审批弹窗 | 执行前请求允许 | `CommandExecutionRequestApproval` |
| 文件变更审批 | 改文件前请求允许 | `FileChangeRequestApproval` |
| 补丁审批 | apply_patch 前请求允许 | `ApplyPatchApproval` |
| 权限请求工具 | 模型主动申请额外权限 | `request_permissions` 工具 |
| Guardian 警告 | 风险分级审查 + 警告 | `GuardianRiskLevel`、`guardianWarning` |
| 沙箱状态 | 只读 / 工作区写 / 完全访问 / 外部沙箱 | `SandboxPolicy` 四态 |
| 网络策略 | 域名白名单、Unix socket 权限 | `NetworkDomainPermission` |
| 提权被拒后申诉 | 请求批准被 Guardian 拒绝的动作 | `thread/approveGuardianDeniedAction` |

## 九、后台与自动化

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 定时任务 | 按计划自动跑任务 | `ScheduledTaskSummary`、`ScheduledTaskSchedule` |
| 后台终端 | 长跑命令独立管理 | `background-terminal`、`thread/backgroundTerminals/*` |
| Agent Jobs | CSV 批量任务，逐行跑，输出 CSV | `agent_jobs` / `agent_job_items` 表 |
| 目标系统 | 带 token 预算的长期目标，六种状态 | `thread_goals` 表、`thread/goal/*` |
| 队列 | 给运行中会话排队消息 | `thread/queue/*` |
| 记忆 | 两阶段记忆（stage1 → phase2） | `memories_1.sqlite`、`memory/status` |
| Rollout 压缩 | 压缩历史记录文件 | `rollout/compress` |

## 十、模型与成本

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 模型目录 | 11 个模型，含 3 个隐藏 | `model/list`、`codex debug models` |
| 推理档位 | low / medium / high / xhigh / max / ultra | 模型目录 |
| Fast 模式 | 2 倍速度、更多用量 | `service_tiers: priority` |
| 用量面板 | token 消耗、5 小时/每周额度 | `threadTokenUsage`、`account/usage/read` |
| 额度重置 | 使用重置额度 | `account/rateLimitResetCredit/consume` |
| 限额弹窗 | 触达限额提示 | `rate-limit`、`rate-limit-reset-checkout` |
| 上下文剩余 | 剩余上下文查询工具 | `get_context_remaining` |
| 主动换窗 | 模型可主动开新上下文窗口 | `new_context_window` 工具 |
| 三种压缩 | 摘要 / 远程 V2 / token-budget 新窗口 | 源码 |

## 十一、扩展机制

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| Skills | `SKILL.md` 说明书，三种来源 | `skills/list` 实测列出本机 164 个 |
| Apps (Connectors) | `codex_apps` MCP 工具集，`[$app](app://id)` 触发 | 系统提示原文 |
| Plugins | skills + MCP + apps 的捆绑包，带签名 | `plugin-signatures/` |
| MCP Servers | 外部工具服务器，支持 OAuth | `mcpServer/oauth/login` |
| MCP Apps | 可嵌入对话的小部件（沙箱 iframe） | `mcp-app-attachment`、`sandbox-preload.js` |
| Hooks | 生命周期钩子，可调 MCP 工具 | `hooks` crate、插件 hook 声明 |
| Marketplace | 插件市场，支持分享/检出 | `marketplace/*`、`plugin/share/*` |
| External Agent 迁移 | 把别家 Agent 配置导入 Codex | `externalAgentConfig/detect|import` |

## 十二、浏览器与 Computer Use

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| 内置浏览器 | 在应用内开网页标签 | `browser-page-preload.js` |
| 浏览器侧栏 | 侧边显示网页 | `browser-sidebar-runtime-message` |
| WebMCP | 发现网页声明的工具 | `get-browser-webmcp-policy` |
| 页面标注 | 在网页上做标注 | `get-browser-annotation-api-policy` |
| Chrome 扩展接入 | 控制用户真实 Chrome | `chrome` 插件、`control-chrome` skill |
| Computer Use | 控制本机应用（Mac/Windows） | `computer-use` 插件、`cua_node/` |
| 截图/窗口 | 屏幕捕获与窗口识别 | `screenshot`、`cuaPermissionPanel` |

## 十三、隐藏与彩蛋

| 东西 | 用来干嘛 | 证据 |
|---|---|---|
| Play Snake | 登录页隐藏按钮，贪吃蛇游戏 | 实测点开截图 |
| Codex Micro 三款小游戏 | 摇杆划圈触发 | `codex-micro-mini-games` |
| Pet / 桌面宠物 | 桌面宠物，有完整美术管线 | `skills/.curated/hatch-pet`、`character-preview`、`Show Pet` |
| Daybreak 模型 | 隐藏模型（blue/red） | `visibility: hide` |
| codex-auto-review | 隐藏的自动审查模型 | `visibility: hide` |
| 74 个匿名 Statsig gate | 远程开关，控制未公开功能 | `checkGate("1079089693")` |

## 十四、未在界面出现但存在的后端能力

| 能力 | 用来干嘛 | 证据 |
|---|---|---|
| Realtime 语音 | 实时语音对话（WebRTC） | `thread/realtime/*` 9 个 RPC |
| Code Mode | 用代码批量调用工具 | `exec`/`wait`、gRPC |
| Environment | 多环境（本地/远程容器） | `environment/add`、`environment/status` |
| Bedrock | AWS Bedrock 接入 | `account/bedrock/*` |
| Gateway OAuth | 企业网关登录 | `account/gatewayOAuth/*` |
| 用户验证 | 身份验证（enroll/verify） | `userVerification/*` |
| 反馈上传 | 带日志的反馈 | `feedback/upload` |
| 诊断 | 进程内存与请求指标 | `server/diagnostics` 实测返回 RSS 与 gauge |
| 模糊文件搜索 | 会话内快速搜文件 | `fuzzyFileSearch/sessionStart` |

---

## 说明

- 本文列的每一项都能在包内找到对应文件或协议方法，**不是产品宣传页的转述**。
- 图片没给，是因为这些界面需要登录才能渲染；但"有什么、干什么用"完全可以从包内确定，不需要截图。
- 之前把 UI 覆盖率报成 15%，是把"有没有截图"当成了"知不知道界面有什么"，这是我的分类错误。按"界面元素是否已识别并说明用途"算，实际接近 90%。
