# UI and Workflows — 主机、组件、操作与事件

本文件将 **D：官方行为说明**、**S-Server：上游源码协议**、**U：Desktop 前端未经解包/运行** 严格分栏。不得因为 Server 有 widget resourceUri 就虚构某个视觉组件的存在。

| 用户任务/界面入口 | 可查到的运行链条 | 反馈/状态及重要未知 | 证据 |
|---|---|---|---|
| Windows 打开项目/切换本机执行环境 | 官方文档叙述原生 Windows PowerShell / WSL、worktree | WSL 切换可能需应用重启；MSIX 实际环境菜单、启动子进程 U | D：Windows app docs；U |
| 创建/打开/分叉对话 | thread/start→thread/read/resume/fork | Thread 分开持有历史和订阅；actual conversation UI 结构 U | S-Server common.rs:552-564,858; U |
| 后台多个线程与切换 | read state 与 thread/status/changed | 已读收据只有 eligible durable local threads；应显示未读和运行两个状态；Desktop 位置 U | S-Server + README; U |
| 在执行过程中继续提问/改排后续任务 | turn, thread/queue/* experimental | add/list/reorder/start 状态变更与 listener 有序通知；Desktop 有无队列管理 UI U | S-Server common.rs:630-660; U |
| 工具调用和终端 | item/commandExecution/outputDelta, terminalInteraction, command/exec | 标准输出增量/命令控制输入/进程终止不能等同 Markdown；Desktop 是否带内嵌终端 U | S-Server common.rs:1377-1435,1975+; U |
| 查看代码改动、审查 | turn/diff/updated, item/fileChange/patchUpdated | patch 和 turn diff 是事件并非文本；真实 Windows file diff view U | S-Server common.rs:1975-2008; U |
| 批准写入/执行/额外权限 | server→client approval request→response | approval 必须回到挂起请求；错误/超时恢复要按接口测；桌面卡片 U | S-Server common.rs:1795-1827; U |
| 第三方 MCP 资源/Apps 交互 UI | mcpToolCall.mcpAppUi.resourceUri，preferredModelDisplayMode inline/fullscreen | 元数据可保留历史，是否弹 iframe、何种消息动作、sandbox 边界与实际控件 U | S-Server README; U |
| 插件/Skills 安装和更新 | plugin/list, plugin/install 等；app/list, mcpServer/tool/call | Server 拆分多个对象域；商店/列表/实际扩展 UI 未确认 | S-Server common.rs:924-1057; U |
| 文件目录/搜索 | fs/*，fuzzyFileSearch session APIs | watch 事件不同于客户端本地 UI 自动刷新；浏览器文件面板 U | S-Server; U |
| 计划任务和收件箱 | 定时任务执行和结果收件箱 | 官方宣称，需确认 Desktop build 的本地状态同步和线程恢复 | D：official automations docs; U |
| 多模态实时对话 | thread/realtime/* experimental | 协议存在不能保证 Windows Desktop 提供语音窗口 | S-Server; U |
| 版本更新/辅助命令 runner | MSIX 主 EXE 与 codex-command-runner.exe | 哪个负责更新、何时拉起、通过什么本地通信全部 U | S-collection/U |

## 对动态消息的专门假设检验

不要“ChatGPT 网页的 DIL/ChatKit 组件列表”直接当 Codex Windows App 的组件总表。要从真实 MSIX 的 JavaScript/HTML/CSS/ASAR 找：
1. 消息类型 discriminant、事件协议映射表、组件注册表、lazy imports、webview/iframe renderers、host action dispatch。
2. 输入类型：button、select、form、rating、文件预览、diff hunk、terminal buffer、task card、MCP tool UI、链接/本地文件/action menu 等；只记**真实匹配组件和事件 handler**。
3. 生命周期：stream chunk → message finalized → historical rehydrate；切换会话、重启、断线、编辑消息、批准任务后组件是否仍可交互，谁持有状态。
4. 宿主权限：renderer 发什么消息给 main/runner、外部链接怎样打开、工作目录怎样决定、URI 如何解析、用户 action 如何回传，而非只搜字符串。
5. 反向扫描：找所有 IPC/RPC handler、注册命令、feature-gates，再向上反查哪些 UI/menu/component 使用；找不到使用者标潜在/死代码。
以上字段为**取证指引**，不是当前确认的功能。

## Atlas 主窗口的实证交互（便于逐条对照）

Atlas main 的 Chat 行渲染是 ConversationMessage.tsx 的 Markdown/GFM/Mermaid；timeline.ts 的固定 union 在 ConversationActivity.tsx 转特定卡（approval、plan、review、foreground、handoff、checks、artifact）。ReviewFindingsCard.tsx 把建议通过 store.sendMessage 转成文本修复任务。ChangesPanel.tsx 可展开 unified diff、逐行写评论，再拼成文本发给 Atlas；TerminalPanel.tsx 用 xterm/WebSocket 且后台进程输出轮询。ForkTree.tsx 从会话 branch API 提供跳转。**这些 UI 确有源代码，不能说 Atlas 没有；是否同等稳定必须测试，尚未测。**
