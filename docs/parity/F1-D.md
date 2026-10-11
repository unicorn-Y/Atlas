# FEATURE-F2 D 区：工具功能统一账本

盘点基线：2026-10-11，实施前。原 F1-D 114 行逐项复核，并合入 F1-unassigned 中 D 负责的 Browser Review pane、本地/Worktree handoff 与清理、PR 状态、跨会话 Agent 工具缺口；另从四大Agent功能矩阵 V5 增补 15 个独立 callable 类别。各类按本表一行计数，不把既有类别中的参数/API 子项重复计入。状态仅使用「已做 / 部分 / 没做 / 原有」；部分和没做都在说明中列明当前缺口。

实施前基线：129 项；已做 67，部分 44，没做 16，原有 2。

| 功能 | 哪家有 | 出处 | 状态 | 说明 |
|---|---|---|---|---|
| 文件读取（路径、范围、编码/大文件保护） | Claude、ZCode、OpenCode | Claude [tools reference](https://code.claude.com/docs/en/tools-reference)；ZCode `apps/zcode-cli/packages/core/src/tool/handlers/read.ts`；OpenCode `packages/core/src/tool/plugin/read.ts`；Codex core handler index 未列独立 text Read handler | 部分 | 缺按行范围/字节范围读取及大文件硬上限；当前一次读完整文件。 |
| 文件写入 | Claude、ZCode、OpenCode | Claude tools reference；ZCode `handlers/write.ts`；OpenCode `plugin/write.ts`；Codex core handler index 未列独立 Write handler | 部分 | 缺工作区路径限制与越界拒绝；当前 local_file 可写本机任意路径。 |
| 文件编辑、批量编辑 | Claude（Edit；旧 MultiEdit 已移除）、ZCode、OpenCode | Claude tools reference + [changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)；ZCode `handlers/edit.ts`；OpenCode `plugin/edit.ts`；Codex 通过 `apply_patch`/shell 组合 | 部分 | edit 仅单文件，多文件 patch 不具事务性；缺批量校验及原子回执。 |
| Patch / apply patch | Codex、ZCode、OpenCode | Codex `handlers/apply_patch.rs`（freeform）；ZCode `handlers/patch.ts`；OpenCode `plugin/patch.ts` | 已做 | 已有 Codex freeform apply_patch 兼容与统一结果。 |
| 文件 glob | Claude、ZCode、OpenCode | Claude tools reference；ZCode `handlers/glob.ts`；OpenCode `plugin/glob.ts`（MIT，固定 HEAD 见来源清点） | 已做 | 已有 workspace-scoped glob，路径/隐藏文件/limit 参数及常见依赖目录排除。 |
| 内容搜索 / Grep | Claude、ZCode、OpenCode | Claude tools reference（含文件名/计数/递归参数）；ZCode `handlers/grep.ts`；OpenCode `plugin/grep.ts`（准确输入见附录 VIII-H） | 已做 | 已有 workspace-scoped grep，正则/字面、大小写、文件过滤与硬上限。 |
| 符号/LSP 查询 | Claude、Codex 周边能力 | Claude tools reference (`LSP`)；Codex handler registry `codex-rs/core/src/tools/` | 已做 | 已有只读 LSP diagnostics/hover/definition/references/document symbols；不可用状态明确返回。 |
| Notebook 编辑 | Claude | [tools reference](https://code.claude.com/docs/en/tools-reference#notebookedit-tool-behavior) | 已做 | 已有 workspace-relative notebook_edit，含原子替换与版本检查。 |
| Bash / shell 命令 | Codex、Claude、ZCode、OpenCode | Codex `handlers/exec_command.rs`；Claude tools reference；ZCode `handlers/bash.ts`；OpenCode `plugin/shell.ts` | 原有 | Atlas 原有可调用能力：有：`local_shell`、`local_exec`。 |
| PowerShell 命令 | Claude | [tools reference](https://code.claude.com/docs/en/tools-reference) | 已做 | 已有 PowerShell callable，固定路由到受管 PowerShell shell，非 Windows 明确拒绝。 |
| 后台进程启动、等待、输入、输出、停止 | Codex、Claude、ZCode、OpenCode | Codex `handlers/exec_command.rs`, `write_stdin.rs`；Claude TaskOutput/TaskStop（TaskOutput 有文档弃用冲突）；ZCode `handlers/{bash,task_output,task_stop}.ts`；OpenCode `plugin/shell.ts` | 部分 | 缺 Claude TaskOutput/TaskStop 兼容 callable 名称与运行映射。 |
| 任务清单 CRUD | Claude、ZCode | Claude TaskCreate/Get/List/Update、TodoWrite；ZCode TodoRead/TodoWrite | 已做 | 已有 TaskCreate/Get/List/Update 与 TodoWrite，共享 run-scoped TodoStore。 |
| 计划模式入口/退出 | Claude、ZCode、Codex `update_plan` | Claude EnterPlanMode/ExitPlanMode；ZCode 同名工具；Codex `update_plan.rs` | 部分 | 有 update_plan，但缺显式 EnterPlanMode/ExitPlanMode 工具与状态转换。 |
| 询问用户 / 结构化问题 | Claude、ZCode、OpenCode | Claude AskUserQuestion；ZCode AskUserQuestion；OpenCode `plugin/question.ts` | 部分 | 仅返回字符串；缺标题、选项描述、多选结果的结构化传递。 |
| Codex 异步向用户发送消息 | Codex | `codex-rs/core/src/tools/handlers/send_message_to_user_async.rs`（固定 HEAD 见来源清点） | 已做 | 已有 send_message_to_user_async，经当前运行 assistant chunk 发往界面。 |
| 代理创建和委派 | Codex、Claude、ZCode、OpenCode | Codex `handlers/multi_agent.rs`、TUI task tools；Claude Agent；ZCode Agent/Task；OpenCode `plugin/subagent.ts` | 部分 | 委派参数缺调用级模型、reasoning effort 与最大深度控制。 |
| 子代理消息、恢复、等待、中断、关闭 | Codex、Claude、ZCode | Codex multi-agent v1/v2 handlers；Claude SendMessage/Agent teams；ZCode SendMessage/RespondToCoordinator/submit_result/escalate/ReplyToChannel/TaskStop | 部分 | 缺模型侧等待/取消/恢复/关闭/结果升级，以及跨会话 Agent registry、消息路由与权限校验（合入 F1-unassigned）。 |
| 会话上下文读取/工具历史 | ZCode、Codex | ZCode `ReadSessionContext` handler；Codex `get_context_remaining` / `new_context` | 部分 | 缺当前运行工具历史读取；new_context 依赖 Hermes handoff callback。 |
| 等待工作区路径可用 | Codex | `codex-rs/core/src/tools/handlers/wait_for_environment.rs` | 已做 | 已有 wait_for_environment，最多等待 60 秒并返回状态/路径/时长。 |
| 当前时间与延时 | Codex | `clock.curr_time`、`clock.sleep` 在 Codex runtime tool registry | 已做 | 已有 UTC 当前时间与有界异步 sleep。 |
| Web 搜索 | Codex、Claude、ZCode、OpenCode | Codex `web_search` handler + [web search docs](https://learn.chatgpt.com/docs/web-search)；Claude WebSearch；ZCode `handlers/web-search.ts`；OpenCode `plugin/websearch.ts` | 部分 | mode 不改变检索；当前仅 DDG，缺 cached/live/provider 能力控制及不支持模式的显式结果。 |
| Web 抓取 | Claude、ZCode、OpenCode | Claude WebFetch；ZCode `handlers/web-fetch.ts`；OpenCode `plugin/webfetch.ts` | 部分 | 缺重定向跳数/响应大小限制和 TTL 缓存。 |
| 图片查看/输入 | Codex、Claude、ZCode、OpenCode | Codex `handlers/view_image.rs`, CLI image input docs；Claude Read；ZCode tool handlers；OpenCode `plugin/read.ts` | 已做 | 已有本地图片 MIME/尺寸校验与模型上下文图像输入。 |
| 图片生成/编辑 | Codex skill `$imagegen`、Hermes、OpenClaw | [Codex image generation](https://learn.chatgpt.com/docs/image-generation)；Hermes `tools/image_gen.py`；OpenClaw `extensions/*` media tools | 已做 | 已有需审批 image_generate/image_edit，缺凭据时明确失败。 |
| X/Twitter 搜索 | Hermes、OpenClaw | Hermes `tools/x_search.py`；OpenClaw `extensions/xai/x-search.ts` | 已做 | 已有 x_search，调用 xAI Responses API 并返回引用。 |
| 视频 URL/文件分析 | Hermes | Hermes `tools/video_analyze.py` | 已做 | 已有受限 YouTube/工作区视频分析 callable。 |
| 视频生成、编辑和延长 | Hermes、OpenClaw | Hermes `tools/video_generate.py`, `tools/xai_video.py`；OpenClaw media provider extensions | 已做 | 已有 xAI 异步 video generate/edit/extend/job status。 |
| 文本转语音/音乐生成 | Hermes、OpenClaw | Hermes `tools/tts.py`；OpenClaw media overview / provider extensions | 已做 | 已有 Atlas/OpenAI-compatible 或 ElevenLabs TTS 与 ElevenLabs music generation。 |
| Computer Use | Codex、Claude、ZCode | Codex [computer use docs](https://learn.chatgpt.com/docs/computer-use)；Claude [computer use](https://code.claude.com/docs/en/computer-use)；ZCode `packages/zcode-cua` / `packages/zcode-cua-plugin` | 部分 | 当前只有聚合动作；缺 request_access、stop control 等低层 Computer Use callable。 |
| Browser 标签页/预览/导航 | OpenCode browser 插件 | `packages/plugin-browser/src/rpc.ts`, `tools.ts` | 部分 | BrowserPanel 已有预览/停止按钮，但 browser.panel.sync 无前端消费者，browser_use 缺 tab.stop 与 pane handoff；缺 F1-unassigned Review pane/local preview 后端接线。 |
| Browser 文档/DOM 操作 | OpenCode browser 插件 | `packages/plugin-browser/src/rpc.ts` | 部分 | 缺 fill_form、selectOption 与 locator press 等 DOM 操作。 |
| Browser 文件交互 | OpenCode browser 插件 | `packages/plugin-browser/src/rpc.ts` | 没做 | 缺 Browser 上传/下载/拖放及受授权文件句柄 API。 |
| Browser console/network/trace/CPU/heap/Lighthouse | OpenCode browser 插件 | `packages/plugin-browser/src/rpc.ts` | 部分 | 只有 console；缺 network、trace、CPU/heap profiler 与 Lighthouse 内置操作。 |
| MCP 动态工具调用 | Claude、ZCode、OpenCode、Codex | Claude MCP docs；ZCode `handlers/mcp.ts`, `tool/registry.ts`；OpenCode `plugin/mcp*`；Codex MCP client/tool registry | 原有 | Atlas 原有可调用能力：有：动态 MCP tools、调用、审批。 |
| MCP Streamable HTTP 与认证 | Codex、OpenCode、Claude | [Codex MCP docs](https://learn.chatgpt.com/docs/extend/mcp)；OpenCode `packages/core/src/tool/plugin/mcp-resource.ts`；Claude MCP docs | 部分 | 有 Streamable HTTP/headers，缺 OAuth 授权、PKCE、令牌持久化和刷新。 |
| MCP server instructions | Codex MCP docs | [Codex MCP docs](https://learn.chatgpt.com/docs/extend/mcp) | 已做 | MCP server instructions 随工具描述传递并作为不可信内容处理。 |
| MCP resource 列表/读取 | Codex、Claude、OpenCode | Codex MCP tool handlers；Claude ListMcpResourcesTool/ReadMcpResourceTool；OpenCode `packages/core/src/tool/plugin/mcp-resource.ts` | 已做 | 已有资源/template 列出与 URI 资源读取，支持游标及 text/blob/MIME。 |
| MCP 工具延迟发现/搜索 | Claude、Codex、ZCode plugin tools | Claude ToolSearch；Codex `tool_search`/plugin extension registry；ZCode `registry.ts` | 部分 | tool_search 只返回名称/描述；缺按需 schema 注入，工具仍在运行启动时枚举。 |
| 插件/skill 工具 | Claude、Codex、ZCode、OpenCode | Claude Skill/Mods；Codex plugins docs；ZCode `registry.ts`, `packages/core/src/tool/handlers/skill.ts`, `UI_PLUGIN.md`；OpenCode `plugin/skill.ts` | 部分 | 缺将已安装插件的 skills/commands 暴露为统一模型侧可调用/可搜索工具。 |
| 插件安装/发现请求 | Codex | Codex `list_plugins`, `request_plugin_install` tool handlers；[plugins docs](https://learn.chatgpt.com/docs/plugins) | 部分 | 可请求安装，但模型侧目录未涵盖完整已安装插件运行状态；缺统一 discover/list/catalog 返回。 |
| 工具权限请求 | Codex、Claude、ZCode、OpenCode | Codex `request_permissions`；Claude permission docs；ZCode `PermissionDialog.tsx`；OpenCode `session-permission-dock.tsx` | 已做 | 已有 request_permissions callable，将请求交给现有审批回调，不自动批准。 |
| 工具审批范围/理由 | Claude、ZCode、OpenCode | Claude permissions docs；ZCode `packages/ui/src/PermissionDialog.tsx`, `lib/permissionRequest.ts`；OpenCode `packages/app/src/session/requests/` | 部分 | 审批事件未统一携带显式 scope/resource 与 reason；部分 PreToolUse 分支丢失理由。 |
| Tool registry 和兼容名称 | 四家都有 | Codex `codex-rs/core/src/tools/registry.rs`; ZCode `packages/core/src/tool/registry.ts`; OpenCode `packages/core/src/plugin/internal.ts`; Claude tools reference | 部分 | Kernel schema 与 executor dispatch 分开维护；缺单一 registry 驱动注册。 |
| Workflow 动态编排 | Claude、ZCode、OpenCode CodeMode | Claude Workflow；ZCode workflow tools；OpenCode CodeMode `packages/core/src/codemode` | 部分 | 缺持久化、可复用的命名 workflow 定义注册表与 save/list/get 生命周期。 |
| OpenCode 工作流运行管理 | OpenCode | `packages/core/src/tool/plugin/opencode.ts` | 已做 | 已有 workflow_run_manage，可列出/恢复 Atlas workflow runs 并明确报告不支持操作。 |
| OpenCode session rename/move 与 worktree 生命周期 | OpenCode | `packages/core/src/tool/plugin/opencode.ts` | 部分 | 缺跨 workspace 活动会话 handoff；worktree 自动清理/回收流程不足（合入 F1-unassigned）。 |
| OpenCode model/provider 发现 | OpenCode | `packages/core/src/tool/plugin/opencode.ts` | 部分 | 仅查 Atlas 配置与静态 provider catalog；缺完整 provider/model 动态发现和过滤分页。 |
| 应用生成生命周期 | Goose | `crates/goose/src/agents/platform_extensions/apps.rs` | 部分 | 只管理 HTML 文件，没有独立 app/window 创建、运行和关闭生命周期。 |
| 交互式数据可视化 | Goose | `crates/goose-mcp/src/autovisualiser/mod.rs` | 部分 | 仅支持 bar/line/donut/radar，无其他矩阵图类和界面内交互展示器。 |
| Goose focused code analysis | Goose | `crates/goose/src/agents/platform_extensions/analyze/mod.rs` | 已做 | 已有 focused_call_graph，使用配置语言服务器 call hierarchy 并限制深度；不支持时明确返回不可用。 |
| Goose 文件树摘要 | Goose | `crates/goose/src/agents/platform_extensions/summarize.rs` | 已做 | 已有 workspace_summarize，受 Git workspace、ignore、路径、敏感文件及大小上限约束。 |
| 无头/SDK/app-server 调用 | Codex、Claude Code、ZCode ACP、Codex app-server | Codex `codex exec` / app-server 官方文档；Claude Code `claude -p` CLI 文档；[ACP v1 session setup](https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx)；Codex app-server 文档 | 部分 | ACP 只支持文本 session；缺按 session 注入 MCP、loadSession 和 free-text elicitation。 |
| Git 平台 PR 创建与评论 | GitHub、OpenCode GitHub/MCP 工具 | GitHub CLI `gh pr create` / `gh pr comment` 官方文档；Atlas `api/workspace_router.py` 现有 PR 创建 API | 部分 | 已有 PR 创建/评论 callable，缺可信 PR 状态查询/徽章数据工具（合入 F1-unassigned）。 |
| Android 环境预检 | ZCode Android 插件 | [`android-emulator-plugin/src/mcp/server.ts`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/android-emulator-plugin/src/mcp/server.ts) | 已做 | Android preflight 可探测本机 SDK/adb/Java/Gradle，按平台注册并报告环境状态。 |
| Android 项目发现 | ZCode Android 插件 | 同上：`android_discover_project` | 已做 | 已有 Android Gradle 项目/模块/变体/applicationId/APK 发现。 |
| Android 创建应用 | ZCode Android 插件 | 同上：`android_create_app`；准确参数见矩阵 VIII-K2 | 部分 | Android scaffold 缺 compileSdk、overwrite 参数及覆盖前确认/冲突策略。 |
| Android 构建应用 | ZCode Android 插件 | 同上：`android_build_app`；共享 `build` schema 见 VIII-K2 | 已做 | 已有 Android Gradle build，支持目标设备、模块、变体与 applicationId。 |
| Android 构建并运行 | ZCode Android 插件 | 同上：`android_build_and_run`；共享 `build` schema 见 VIII-K2 | 已做 | 已有 Android build/install/launch；按目标或 AVD 等待设备就绪。 |
| Android 设备列表 | ZCode Android 插件 | 同上：`android_list_devices` | 已做 | 已有 Android adb 设备列表。 |
| Android AVD 列表 | ZCode Android 插件 | 同上：`android_list_avds` | 已做 | 已有 Android AVD 列表。 |
| Android 启动模拟器 | ZCode Android 插件 | 同上：`android_start_emulator`；`emulator` schema 见 VIII-K2 | 已做 | 已有显式图形 Android 模拟器启动并复用 ready device。 |
| Android 停止模拟器 | ZCode Android 插件 | 同上：`android_stop_emulator` | 已做 | 已有按 serial 停止 Android 模拟器。 |
| Android 创建 AVD | ZCode Android 插件 | 同上：`android_create_avd` | 已做 | 已有 Android AVD 创建。 |
| Android 安装 APK | ZCode Android 插件 | 同上：`android_install_app`；共享 `target` schema 见 VIII-K2 | 已做 | 已有 Android APK 安装及 target 选择。 |
| Android 启动应用 | ZCode Android 插件 | 同上：`android_launch_app` | 已做 | 已有 Android applicationId/activity 启动。 |
| Android 停止应用 | ZCode Android 插件 | 同上：`android_terminate_app` | 已做 | 已有 Android 应用强制停止。 |
| Android 打开 URL | ZCode Android 插件 | 同上：`android_open_url` | 已做 | 已有在 Android 设备浏览器打开 URL。 |
| Android 截屏 | ZCode Android 插件 | 同上：`android_screenshot` | 已做 | 已有 Android 截屏及 MCP 图像回传。 |
| Android 日志 | ZCode Android 插件 | 同上：`android_logs` | 已做 | 已有 Android logcat 查询和过滤。 |
| Android UI Automator 状态 | ZCode Android 插件 | 同上：`android_ui_status` | 已做 | 已有 Android UI Automator backend 状态查询。 |
| Android UI 描述 | ZCode Android 插件 | 同上：`android_ui_describe`；共享 `target` schema 见 VIII-K2 | 已做 | 已有 Android UI 组件树描述。 |
| Android UI 元素解析 | ZCode Android 插件 | 同上：`android_ui_resolve` | 已做 | 已有 Android UI 按文本/content-description/resource-id/class 解析元素坐标。 |
| Android UI 点击 | ZCode Android 插件 | 同上：`android_ui_tap` | 已做 | 已有 Android UI 点击。 |
| Android UI 滑动 | ZCode Android 插件 | 同上：`android_ui_swipe` | 已做 | 已有 Android UI 滑动。 |
| Android UI 输入文本 | ZCode Android 插件 | 同上：`android_ui_type_text` | 已做 | 已有 Android UI 输入文本。 |
| Android UI 按键 | ZCode Android 插件 | 同上：`android_ui_keyevent` | 已做 | 已有受限 Android UI 按键操作。 |
| iOS 环境预检 | ZCode iOS 插件 | [`ios-simulator-plugin/src/mcp/server.ts`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/ios-simulator-plugin/src/mcp/server.ts) | 已做 | 已有 macOS-gated iOS preflight，探测 Xcode/Simulator 与可选 idb。 |
| iOS 模拟器列表 | ZCode iOS 插件 | 同上：`ios_list_simulators` | 已做 | 已有 iOS Simulator 列表并过滤 watchOS/tvOS。 |
| iOS 启动模拟器 | ZCode iOS 插件 | 同上：`ios_boot_simulator`；共享 `target` schema 见 VIII-K3 | 已做 | 已有指定设备/runtime 启动 iOS Simulator。 |
| iOS 显示模拟器 | ZCode iOS 插件 | 同上：`ios_show_simulator` | 已做 | 已有 iOS Simulator 窗口显示。 |
| iOS 项目发现 | ZCode iOS 插件 | 同上：`ios_discover_project` | 已做 | 已有 Xcode project/workspace/scheme/bundle ID 发现。 |
| iOS 创建应用 | ZCode iOS 插件 | 同上：`ios_create_app`；准确参数见 VIII-K3 | 部分 | iOS scaffold 缺 overwrite 参数及覆盖前确认/冲突策略。 |
| iOS 构建应用 | ZCode iOS 插件 | 同上：`ios_build_app`；共享 `build` schema 见 VIII-K3 | 已做 | 已有 iOS xcodebuild callable 与 project/workspace/scheme/configuration 等参数。 |
| iOS 构建并运行 | ZCode iOS 插件 | 同上：`ios_build_and_run` | 已做 | 已有 iOS build/install/launch/show simulator。 |
| iOS 安装应用 | ZCode iOS 插件 | 同上：`ios_install_app`；共享 `target` schema 见 VIII-K3 | 已做 | 已有 iOS .app 安装及 target 参数。 |
| iOS 启动应用 | ZCode iOS 插件 | 同上：`ios_launch_app` | 已做 | 已有 iOS bundleId/launchArgs 启动。 |
| iOS 停止应用 | ZCode iOS 插件 | 同上：`ios_terminate_app` | 已做 | 已有 iOS 应用停止。 |
| iOS 打开 URL | ZCode iOS 插件 | 同上：`ios_open_url` | 已做 | 已有 iOS Simulator 打开 URL。 |
| iOS 截屏 | ZCode iOS 插件 | 同上：`ios_screenshot` | 已做 | 已有 iOS 截屏并回传图像。 |
| iOS 日志 | ZCode iOS 插件 | 同上：`ios_logs` | 已做 | 已有 iOS 日志查询。 |
| iOS UI 自动化状态 | ZCode iOS 插件 | 同上：`ios_ui_status` | 已做 | 已有 iOS idb backend 预检。 |
| iOS UI 点击 | ZCode iOS 插件 | 同上：`ios_ui_tap` | 已做 | 已有 iOS 坐标点击。 |
| iOS UI 滑动 | ZCode iOS 插件 | 同上：`ios_ui_swipe` | 已做 | 已有 iOS 坐标滑动。 |
| iOS UI 输入文本 | ZCode iOS 插件 | 同上：`ios_ui_type_text` | 已做 | 已有 iOS 文本输入。 |
| iOS 设备按钮 | ZCode iOS 插件 | 同上：`ios_ui_button` | 已做 | 已有 iOS 设备按钮操作。 |
| iOS UI 描述 | ZCode iOS 插件 | 同上：`ios_ui_describe`；共享 `target` schema 见 VIII-K3 | 已做 | 已有 iOS 屏幕辅助功能描述。 |
| ZCode Browser Use runtime 选择 | ZCode Browser Use | [`browser-use-plugin/docs/overview.md`](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/apps/zcode-cli/packages/browser-use-plugin/docs/overview.md) | 部分 | 只有 X2 单一 runtime；runtime select 不可持久化且不支持 provider 切换。 |
| Browser tabs 生命周期与用户 tab claim | ZCode Browser Use | 同上；`agent.browsers`, `browser.tabs`, `browser.user` | 部分 | 缺 desktop user tab ownership registry、claim/finalize 生命周期。 |
| Browser 页面导航/信息 | ZCode Browser Use | 同上：`tab.goto/back/forward/reload/close/url/title` | 已做 | 已有 goto/back/forward/reload/close/URL/title 操作及 DOMContentLoaded 等待。 |
| Browser DOM snapshot 与 locator | ZCode Browser Use | 同上：`playwright.domSnapshot`, `getBy*/locator` | 部分 | locator 未覆盖完整 press/select/fill_form 行为；返回的 Atlas snapshot/ref 不等同 upstream ARIA evidence。 |
| Browser frame/JS/wait | ZCode Browser Use | 同上：`frameLocator/evaluate/waitForURL/waitForLoadState` | 部分 | frame/evaluate/wait 依赖 Hermes/CDP supervisor；缺完整可用状态与策略受限行为一致性。 |
| Browser 坐标 CUA | ZCode Browser Use | 同上：`tab.cua.{click,double_click,move,scroll,drag,keypress,type}` | 已做 | 已有带审批的当前 browser tab 坐标 click/double-click/move/scroll/drag/key/type。 |
| Browser DOM CUA | ZCode Browser Use | 同上：`tab.dom_cua.{click,double_click,scroll,keypress}` | 已做 | 已有基于 Atlas snapshot/ref 的 DOM click/keypress/type/double-click/scroll。 |
| Browser 截图与视口 | ZCode Browser Use | 同上：`tab.screenshot`, `setViewportSize`, `viewportSize` | 部分 | 截图返回 cache path/data URL，未形成可供界面访问的 workspace artifact。 |
| Browser 原生 JS dialog | ZCode Browser Use | 同上：`tab.getJsDialog` | 部分 | 原生 JS dialog 仅在活动 CDP supervisor 下可用，缺统一 pane/runtime 管理。 |
| Browser deliverable/handoff | ZCode Browser Use | 同上：`markDeliverable`, `markHandoff` | 部分 | handoff 可用；markDeliverable/finalize 缺 pane 所有权与交付 registry。 |
| Browser recording | ZCode Browser Use | 同上：`tab.recording.{start,status,cancel}` | 部分 | 能录制步骤并保存 skill，但缺 WebM 视频产物和通用流程回放交付。 |
| Browser panel visibility/headless | ZCode Browser Use | 同上：`browser.capabilities.get("visibility").set`, `--browser-use=headless` | 部分 | 缺 browser pane visibility 控制及 headless launch 模式。 |
| ZCode Android/iOS plugin MCP tools | ZCode | Android `packages/android-emulator-plugin/src/mcp/server.ts`（23）；iOS `packages/ios-simulator-plugin/src/mcp/server.ts`（20）；[plugin docs](https://zcode.z.ai/cn/docs/plugin) | 已做 | 已有 43 个 Android/iOS MCP-compatible callables，并按平台/SDK/设备状态注册或返回错误。 |
| ZCode image-search 插件 | ZCode | `packages/image-search-plugin/.zcode-plugin/plugin.json`（远程 HTTP MCP；工具 schema 在远端不可见） | 部分 | 无内置 image_search callable；外部 MCP 可配置不等于提供该服务/schema，远端 schema 仍需官方接口/凭据。 |
| ZCode documents/pdf/presentations/spreadsheets 插件 skills | ZCode | `packages/{documents,pdf,presentations,spreadsheets}-plugin/.zcode-plugin/plugin.json` | 部分 | 已有 office create/read 能力，但缺 documents/presentations/spreadsheets 对应 skill/payload 工作流。 |
| Codex App Computer Use | Codex Desktop | [Computer Use 官方插件发布说明](https://help.openai.com/en/articles/11391654)；[computer use docs](https://learn.chatgpt.com/docs/computer-use) | 部分 | 缺 Computer Use request/stop 低层动作与授权生命周期；后台窗口控制受 Atlas host 能力限制。 |
| Codex Record & Replay | Codex Desktop/ChatGPT Work | [Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay) | 部分 | 缺将一般桌面录制整理为可参数化并可调用的 skill lifecycle；现有仅 browser steps→skill。 |
| Codex Security plugin scan | Codex Desktop 插件 | [Security plugin](https://learn.chatgpt.com/docs/security/plugin) | 部分 | 已有本地 bounded security_scan；缺 repo/branch 选择与 findings/report/repository 生命周期工具。 |
| 本地定时任务管理 | ZCode、Claude | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/cron.ts`；Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 CronCreate/List/Update/Delete 模型工具及 Atlas 可持久化调度 CRUD；现有前端 Automation 不提供同等 callable。 |
| 离峰任务管理 | ZCode | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/off-peak.ts` | 没做 | 缺 OffPeakCreate/List callable 与独立离峰队列/生命周期语义。 |
| 远程 Routine 触发 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 RemoteTrigger callable 与已授权 routine 触发桥接。 |
| 会话唤醒调度 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 ScheduleWakeup callable；普通 clock.sleep 不提供持久化的会话唤醒。 |
| Node REPL / JavaScript 工具 | ZCode | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/node-repl.ts` | 没做 | 缺有状态 JavaScript REPL callable；浏览器 API 行不等于 Node REPL。 |
| 回复外部频道 | ZCode | ZCode `apps/zcode-cli/packages/core/src/tool/handlers/reply-to-channel.ts` | 没做 | 缺带 channel/message target 与送达回执的 reply_to_channel callable。 |
| 托管 Artifact 发布 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺将 HTML/Markdown 交互内容发布到受管 Artifact 并返回可访问引用的 callable。 |
| 结束会话 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺结束当前 Agent 会话的显式模型工具与用户可见结束原因。 |
| 事件流监视 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺对后台命令输出/异步事件/WebSocket 的订阅与增量回传工具。 |
| 推送通知 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺经用户授权的桌面/移动推送通知 callable 与送达状态。 |
| 结构化审查发现 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 ReportFindings 的结构化 finding/severity/location/evidence 接收与持久化 callable。 |
| 用户反馈草稿 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺可审核的 SendFeedback 草稿创建 callable 与状态回执。 |
| 向客户端发送文件 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺受授权的本地文件传至客户端 callable 与成功/失败回执。 |
| 分享入门指南 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 ShareOnboardingGuide callable 及指南选择/分享结果。 |
| 等待 MCP 服务就绪 | Claude | Claude [tools reference](https://code.claude.com/docs/en/tools-reference) | 没做 | 缺 WaitForMcpServers callable 与服务启动/超时状态查询。 |

## 完整来源清点与边界

### ZCode

- HEAD `zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f`（Apache-2.0）。主注册表 `apps/zcode-cli/packages/core/src/tool/handlers/index.ts` 中 `builtInTools` / `registerBuiltInTools()` 有 42 canonical entries，`Task` 为 `providerVisible:false`（最多 41 项向模型公告）。工具按精确 handler 文件为 Read `handlers/read.ts`、Write `write.ts`、Edit `edit.ts`、Bash `bash.ts`、Glob `glob.ts`、Grep `grep.ts`、WebFetch `webfetch.ts`、WebSearch `websearch.ts`、TodoRead/TodoWrite `todo.ts`、EnterPlanMode/ExitPlanMode `plan-mode.ts`、AskUserQuestion `ask-user-question.ts`、Agent/兼容 Task `agent.ts`、TaskOutput `task-output.ts`、TaskStop `task-stop.ts`、ReadSessionContext `read-session-context.ts`、Skill `skill.ts`、js `node-repl.ts`；协作类 SendMessage `send-message.ts`、RespondToCoordinator `respond-to-coordinator.ts`、submit_result `submit-result.ts`、escalate `escalate.ts`、ReplyToChannel `reply-to-channel.ts`；工作流 11 项分别位于 `create-workflow.ts`, `amend-workflow.ts`, `save-workflow.ts`, `eval-workflow-snippet.ts`, `list-workflow-runs.ts`, `get-workflow-run.ts`, `resume-workflow-run.ts`, `resolve-workflow-question.ts`, `fill-workflow-hole.ts`, `list-saved-workflows.ts`, `list-models.ts`；调度 CronCreate/List/Update/Delete 在 `cron.ts`，OffPeakCreate/List 在 `off-peak.ts`。动态 MCP 源在 `packages/core/src/mcp/index.ts`。TaskOutput/TaskStop 还接受多个旧别名；它们不是单独模型公告工具。`ApplyPatch` 与旧 `Workflow` 在当前注册清单注释掉；GoalRead 有 handler 但未注册，不列作 callable。
- Computer Use 的 14 个低层方法在 `packages/zcode-cua-plugin/scripts/computer-use-client.mjs` 的 `COMPUTER_METHOD_NAMES` 与 `docs/computer-use.md`：`list_apps`, `list_windows`, `get_app_state`, `left_click`, `left_click_drag`, `scroll`, `type`, `set_value`, `select_text`, `key`, `paste`, `perform_action`, `request_access`, `stop_computer_control`。`packages/zcode-cua` 是 fail-closed API 兼容 placeholder，当前 checkout 不含其 producer registry；14 项证据来自插件 SDK 和文档。浏览器通过 `js` 的 `agent.browsers` 暴露，不是独立固定 handler。
- UI 检查路径：`packages/ui/src/PermissionDialog.tsx`, `ToolCallBlocks/`, `settings/McpSettingsSection.tsx`, `McpServerList.tsx`, `McpServerForm.tsx`, `ComputerUseSection.tsx`, `BrowserSettingsSection.tsx`, `ShortcutSettingsSection.tsx`, `quickpick/quickPickCommands.ts`, `packages/shared/src/shortcutCommands.ts`, `packages/ui/src/i18n/locales/{en-US,zh-CN}.ts`; CUA 授权面板在 `packages/desktop/src/renderer/cua-permission-panel.html`。UI 审批、设置、命令面板、快捷键及本地化是 B/C 区域，不等同于 D 的 callable handlers。

### OpenCode

- HEAD `anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937`（MIT）。计划书的 `packages/opencode/src/tool/` 已迁移；当前 callable source 在 `packages/core/src/tool/plugin/`，注册在 `packages/core/src/plugin/internal.ts`。基础工具：edit、glob、grep、patch、question、read、shell、skill、subagent、webfetch、websearch、write；CodeMode `execute` 在 `packages/core/src/codemode/`。命名空间工具在 `plugin/opencode.ts`：session rename/move、worktree create/list/remove、models；MCP resources list/read 在 `plugin/mcp-resource.ts`；MCP 动态工具也进入同一 registry。
- `packages/plugin-browser/src/rpc.ts` 与 `tools.ts` 声明 43 个浏览器 RPC：tabs.list/open/focus/close、preview、navigate/back/forward/reload/stop、frames/snapshot/find/evaluate、click/hover/drag/fill/fill_form/select/check/press/scroll/wait/screenshot/dialog、files.upload/drop/list/get、console、network.list/get、trace.start/stop/analyze、cpu.start/stop/analyze、heap.snapshot/summary/query/object/compare、lighthouse。
- UI 穷举路径：命令 registry/palette `packages/app/src/shell/commands/command.tsx`, `palette.ts`, `dialog.tsx`；权限与 MCP `packages/app/src/session/requests/`, `packages/app/src/providers/connect/mcp-dialog.tsx`；设置 `packages/app/src/settings/`; shortcut definitions/editing `packages/app/src/settings/keybinds/`; TUI palette/keybind/MCP `packages/tui/src/component/command-palette.tsx`, `config/keybind.ts`, `component/dialog-mcp.tsx`; tool renderers `packages/session-ui/src/tools/tool-renderer.tsx`, `components/basic-tool.tsx`; app/UI i18n 在 `packages/app/src/runtime/i18n/{en,zh,zht}.ts`, `packages/ui/src/i18n/`。UI 审批/卡片/设置属于 B/C；D 本次只实现后端 handlers。

### Codex

- 开源 HEAD `openai/codex@de8fab6d7adfcef8b4ce6f02f3b5c8be4092015a`（Apache-2.0；通过 `git ls-remote` 确认当日 `main` HEAD）。选择/注册/路由在 `codex-rs/core/src/tools/{spec_plan,registry,router}.rs`；可注册 handlers 索引在 [`handlers/mod.rs`](https://github.com/openai/codex/blob/de8fab6d7adfcef8b4ce6f02f3b5c8be4092015a/codex-rs/core/src/tools/handlers/mod.rs)。core callable：`exec_command`, `write_stdin`, `apply_patch`, `update_plan`, `request_permissions`, `get_context_remaining`, `new_context`, `clock.curr_time`, `clock.sleep`, `wait_for_environment`, `view_image`, `request_user_input`, `request_user_input_async`, `send_message_to_user_async`, `list_available_plugins_to_install`, `request_plugin_install`, `test_sync_tool`, `tool_search`, `list_mcp_resources`, `list_mcp_resource_templates`, `read_mcp_resource`；dynamic families 另含 MCP functions、extension tools、multi-agent v1/v2；CodeMode `exec`/`wait`，Hosted `web_search`。TUI/app-server 动态 tools 另含 `codex_tui` 的 thread lifecycle 与 `codex_worktrees` 的 create/status/list worktree；它们依赖 host，不是 core handlers。
- Codex `de8fab6` 的变化未新增本清单中的模型工具名；该提交迁移 MCP SDK client/server config 类型并修复 transport EOF/取消时的连接清理。CLI/TUI 私有 app-server 操作须按 Atlas session/workspace API 重做，不直接拷协议。
- 官方文档入口在 [Codex Learn](https://learn.chatgpt.com/docs)：CLI、CLI ref、IDE、desktop、Linux/Windows desktop、commands/slash commands/settings、config basic/advanced/reference、AGENTS/subagents/rules/speed、MCP、permissions/sandbox/auto-review/approvals、browser/computer use、web search、plugins、image generation/inputs、appshots/browser extension、hooks/skills、worktrees/app-server/non-interactive。页面没有公布发布时间，按访问日记录。近三个月版本变化已纳入本表：0.146.0（7/29）、0.150.0（8/26）、0.155（9/17）、0.160（10/5）、0.161（10/7）；MCP Streamable HTTP、Windows stdio 环境及 `/mcp login` 是相关行为变化。
- 通用浏览器、Appshots、图片输入、hooks、权限/沙箱配置、桌面设置均按宿主 UI/扩展能力登记，不冒充固定 CLI handler。

### Claude Code

- 官方 [llms.txt](https://code.claude.com/docs/llms.txt) 列有 185 个页面；D 相关逐页范围包括 tools reference、permissions/modes、commands、settings/reference、hooks/guide、checkpointing、subagents/agents/teams/workflows、MCP/quickstart、skills/plugins/mods、desktop/Chrome/computer-use/artifacts/scheduled-tasks。工具页当前列 46 项：Agent、Artifact、AskUserQuestion、Bash、CronCreate/Delete/List、Edit、EndConversation、EnterPlanMode、EnterWorktree、ExitPlanMode、ExitWorktree、Glob、Grep、ListAgents、ListMcpResourcesTool、LSP、Monitor、NotebookEdit、PowerShell、PushNotification、Read、ReadMcpResourceTool、RemoteTrigger、ReportFindings、ScheduleWakeup、SendFeedback、SendMessage、SendUserFile、ShareOnboardingGuide、Skill、SubagentHandback、TaskCreate/Get/List/Output/Stop/Update、TodoWrite、ToolSearch、WaitForMcpServers、WebFetch、WebSearch、Workflow、Write。
- 最新工具参考没有 MultiEdit、BashOutput、KillShell；Task APIs 已取代 TodoWrite 为默认接口，但 changelog 与工具参考对 TaskOutput 是否移除有冲突（清单按当前工具页保留 deprecated 项）。Mods API 可直接注册 callable 工具；MCP resources 有 list/read；Chrome/computer use 是集成级 callable surface，公共页不列具体 schema。Checkpointing 是自动 snapshot + `/rewind` UI，不列为工具。
- 三个月 changelog：官方 [CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) 与 [releases](https://github.com/anthropics/claude-code/releases)，日期窗口 2026-07-11 至 2026-10-11；重点包括权限 parser/plan-mode 修复、restricted mode、Task APIs 默认启用、WebFetch disable switch、MCP OAuth/scopes、Agent effort、Mods `isDeferred`、Grep flags、大文件 Read 与非 UTF-8 写入保护。

### Hermes / OpenClaw / Pi / Cline / Goose 补充

Supplement 版本记录：Hermes `66605471e9f0b0832abbefaf625ce08e948ca540`（MIT）；OpenClaw `07a870b2eaabc277315583e8a05d9060f175266f`（MIT）；Pi `e37cdc420669e48b4df4bbce0fb2617fc3c71328`；Cline `c3a40572765b76873c597247941118c1778d02c8`；Goose `3bd852002903e016ff30947e973f76e2fcfcf90f`（Apache-2.0）。Pi/Cline 没有在四家之外提供唯一 callable capability。按任务书只纳入唯一候选：Goose analyze/summarize/apps/Auto Visualiser；Hermes/OpenClaw image/video/TTS/music generation、Hermes video analysis、xAI X search 与视频编辑。具体来源分别是 Hermes 官方 tool reference、OpenClaw media overview / `extensions/xai/`、Goose `platform_extensions/{analyze,summarize,apps}.rs` 与 `goose-mcp/src/autovisualiser/`。

## 不属于 D 的已发现功能

- ZCode 的 Approval Dialog、tool-call cards、MCP/ComputerUse/Browser 设置、快捷键编辑、命令面板和 i18n 文案属于 B/C；相关源码路径见上文。D 仅保证后端工具含完整 approval request 数据。
- OpenCode 命令面板、session tool cards、MCP 设置 dialog、Auto-approve 设置、keybind 编辑属于 B/C；权限 dock 的 allow once/always/deny 操作属于 B，MCP 与插件设置属于 C。
- Codex image-input、Appshots、浏览器扩展 tab context、hook callbacks、沙箱/审批设置是 desktop/runtime surfaces，不是固定模型 callable handler；配置 UI 属于 C，对话/审批 UI 属于 B。
- Claude `/commands`、settings、hooks、checkpoint rewind、MCP prompts-as-slash-commands、plugin marketplace/settings 属于 B/C 或运行时；只把真正 callable handler 放在 D 表内。
