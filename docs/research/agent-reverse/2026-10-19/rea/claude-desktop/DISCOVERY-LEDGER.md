# 主动发现总账 · Claude Desktop / Cowork 2.42304.0

编号 `CLAUDE_DESKTOP-001` … `CLAUDE_DESKTOP-118`，共 **118 条**。

**证据级别**（依 `tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`）：
`S` = 源码/符号直接可见 · `R` = 运行时实测 · `D` = 官方文档 · `I` = 推断（已标注推理依据） · `U` = 不可得

**收录标准**：只要是一条此前不知道、且能落到具体文件偏移或运行时观测的事实，就收。
「Electron 应用有主进程」这种通用常识不收。

---

## A. 发行与打包（001–012）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 001 | MSIX 为**单 x64 包**，`Identity Name="Claude"` `Version="2.42304.0.0"`，发布者 Anthropic PBC；`TargetDeviceFamily Windows.Desktop MinVersion 10.0.18362.0` | S | `AppxManifest.xml` |
| 002 | 应用代码是**嵌套双容器**：`app.asar`（49,338,428 B，506 文件 / 548 条目，含 6 个 unpacked）+ `app.asar.unpacked/`（27.1 MB） | S | `app/resources/` |
| 003 | 另有**完全独立的前端树** `ion-dist/`：190.3 MB、4,224 文件，`assets/v1/` 下 4,026 个资源——与 asar 主进程是两套代码 | S | `app/resources/ion-dist/` |
| 004 | 6 个 Agent Skill 随包分发（docx / frontend-design / pdf / pdf-reading / pptx / xlsx），`manifest.json` 里 `agentSkillsRef:"1792020044"`，全部 `tier:"always"` | S | `app/resources/bundled-skills/manifest.json` |
| 005 | 三个 artifact 渲染库随包内置：`chart.js` / `gridjs` / `mermaid`——产物预览不依赖网络 | S | `app/resources/artifact-libs/` |
| 006 | 一个 37,748,736 B 的 **Hyper-V 基础磁盘镜像** `smol-bin.x64.vhdx` 随包分发，首次启动复制到 bundle 目录 | S | `app/resources/smol-bin.x64.vhdx` |
| 007 | Office 365 MCP 服务随包内置，含独立的 `pdfExtractorProcess.mjs` 子进程 | S | `app/resources/office365-mcp/` |
| 008 | ~60 个 locale JSON 随包，产品 UI 完全本地化（实测中文系统下窗口标题按钮显示「最小化/最大化/关闭」） | S+R | `app/resources/*.json` |
| 009 | 托盘图标按**主题×状态**预置多份（非运行时绘制） | S | `app/resources/` 图标文件 |
| 010 | MSIX 对**注册表写入做虚拟化排除**：`ExcludedKeys` 列了 Chrome / Brave / Edge / Prisma / Island / Chromium / Arc / Vivaldi / Opera 的 native-messaging host 注册表键，键名统一 `com.anthropic.claude_browser_extension` | S | `AppxManifest.xml` |
| 011 | `startupTask` 名为 `ClaudeStartup`，**默认 `Enabled="false"`**——装完不自启，要用户主动开 | S | `AppxManifest.xml` |
| 012 | 注册自定义协议 `claude://`，并暴露三个执行别名 `claude-desktop.exe` / `claude-ssh-askpass.exe` / `claude-ssh-proxy.exe`；同时给 `Claude.exe` 与 `cowork-svc.exe` 各写防火墙规则 | S | `AppxManifest.xml` |

---

## B. 进程与启动（013–028）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 013 | 打包器是 **Electron 8.0.0-alpha.10 + Electron Forge + Vite**，入口 `main` 指向 `.vite/build/index.pre.js` | S | `package.json`（asar 内） |
| 014 | 构建元数据**内联在引导脚本里**：`commitHash e7f60e658f15cfece9efa384a78a39aec3c12845`、`commitTimestamp 2026-10-15T05:54:05.000Z`、`buildType prod`、`isNestBuild false` | S | `.vite/build/index.pre.js` |
| 015 | 启动即把 `Error.stackTraceLimit` 设为 **20**（默认 10），为崩溃归类保留更深栈 | S | `index.pre.js` |
| 016 | 启动即设 `process.env.NoDefaultCurrentDirectoryInExePath = "1"`，防止从 CWD 加载 DLL——Windows 特有的 DLL 劫持缓解 | S | `index.pre.js` |
| 017 | **16 个禁用命令行开关**硬编码，含 `remote-debugging-port`、`remote-debugging-pipe`、`disable-web-security`、`ssl-key-log-file`、`host-resolver-rules`、`browser-subprocess-path`、`gpu-launcher`、`renderer-cmd-prefix`、`zygote-cmd-prefix` 等 | S | `index.pre.js` |
| 018 | 开关规范化函数 `JZ(e) = e.replace(/^(?:--|-|\/)/,"").toLowerCase().split("=",1)[0]`——同时兼容 `--x` / `-x` / `/x` 三种写法，且只取 `=` 前部分 | S | `index.pre.js` |
| 019 | 命中即**拒绝启动**，文案：`Claude: refusing to start — a debugging or network-override switch is present on the command line.` | S+R | `index.pre.js`；实测 `--remote-debugging-port=9333` → `exit 1` |
| 020 | 合法调试需 `CLAUDE_CDP_AUTH` + `CLAUDE_USER_DATA_DIR` 双环境变量，令牌三段 `base64(userDataPath).sig` | S | `index.pre.js` |
| 021 | 令牌是对 `"${ts}.${payload}"` 的 **Ed25519 签名**，公钥 SPKI 硬编码 `MCowBQYDK2VwAyEAxONNYxuoQ4/PkjI7rdBmfpsWn1Ohfuqx9VMIsLwlTQY=`，时效窗口 **0–300,000 ms** | S | `index.pre.js` |
| 022 | **私钥不在客户端**——这不是「还没逆向出来」，是密码学上不可得。所以 CDP 授权无法伪造 | S+I | `index.pre.js`（只有验签路径，无签名路径） |
| 023 | 打包态且无合法令牌时，**主动删除三个环境变量**：`CLAUDE_USER_DATA_DIR`、`SSLKEYLOGFILE`、`sslkeylogfile`（大小写各删一次，防绕过） | S | `index.pre.js` |
| 024 | 被删的原值不丢弃，存进 `globalThis.ignoredUserDataDirEnv` 供后续诊断读取 | S | `index.pre.js` |
| 025 | 启动加 `--enable-features=IsolatesPriorityUseProcessPriority`——把渲染进程优先级策略隔离 | S | `index.pre.js` |
| 026 | 启动加 `--dnsPrefetchingEnabled=false`——关掉 DNS 预取，减少可观测的外泄面 | S | `index.pre.js` |
| 027 | 启动加 `--disable-features=ConnectionAllowlists`——主动关闭 Chromium 的连接白名单机制 | S | `index.pre.js` |
| 028 | arm64 分支额外走 `L0` 逻辑禁用 GPU | S | `index.pre.js` |

---

## C. 窗口与外壳（029–038）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 029 | **9 种窗口角色**枚举 `MZ`：`claude.ai-web` / `find-in-page` / `about` / `main-window` / `quick-entry-window` / `custom3p-setup` / `custom3p-device-code` / `in-app-browser` | S | `index.pre.js` |
| 030 | 每个角色对应独立 HTML 入口，`main_window` / `quick_window` / `about_window` / `buddy_window` / `find_in_page` / `local_exec_consent` 各有一套渲染层 | S | `.vite/renderer/` |
| 031 | `in-app-browser` 是**一等窗口角色**，不是 iframe——侧栏浏览器有自己的窗口生命周期 | S | `MZ` 枚举 + `frame-connect.html` |
| 032 | `custom3p-setup` 与 `custom3p-device-code` 是两阶段：先配置，再走 device-code 认证 | S | `MZ` 枚举 + `Custom3pSetup` 41 方法 |
| 033 | `quick-entry-window` 是独立常驻窗口，配合 `quickEntry*` 系列 flag 与 `nativeQuickEntry` | S | `MZ` + `feature-flags.json` |
| 034 | 原生窗口框架链：`Chrome_WidgetWin_1` → `RootView` → `NonClientView` → `WinFrameView` → `WinCaptionButtonContainer` → `WinCaptionButton` ×3 | R | UIA 树，`uia-region-gate-full.json` |
| 035 | 另有 `Intermediate D3D Window` 节点，说明合成走 D3D 中间层（非纯 GDI） | R | 同上 |
| 036 | 文档根节点 `automationId="RootWebArea"`，`ControlType=Document`，标题 `App unavailable in region \| Claude by Anthropic` | R | 同上 |
| 037 | UIA 默认只暴露 **15** 个元素；加 `--force-renderer-accessibility` 后 **248** 个（弹层展开后 254）——Chromium 默认惰性构建无障碍树 | R | `uia-region-gate.json` vs `uia-region-gate-full.json` |
| 038 | 原生菜单按钮名 `Toggle menu`，**不支持 `InvokePattern`**（`uia-invoke.ps1` 报「不支持的模式」），需合成鼠标点击 | R | `uia-invoke.ps1` 实测失败 |

---

## D. IPC 服务面（039–052）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 039 | 通道名格式恒定：`$eipc_message$_<uuid>_$_<module>_$_<Class>_$_<method>` | S | `ipc-contract.json` |
| 040 | 服务 UUID 之一 `6010a08f-a0fa-48b4-99da-0689b9e2de7b`，承载全部 `claude.*` 业务服务 | S | `ipc-methods.json` |
| 041 | 服务 UUID 之二 `fcb91d11-972d-4fd6-b90b-72739699bff5`，只承载 `electron_window.WindowManager` 的 7 个方法 | S | 同上 |
| 042 | **总计 1,411 个 IPC 方法**（全量枚举，非抽样） | S | `ipc-methods.json` `method_count` |
| 043 | 分布在 **98 个服务类** | S | `ipc-methods.json` `class_count` |
| 044 | 最大单类 `LocalSessions` **339 个方法**——比 Atlas 全部 IPC handler（9 个）多 37 倍 | S | `by_class` |
| 045 | `LocalAgentModeSessions` 134 个方法——这是 Cowork/本地 agent 会话的主力面 | S | 同上 |
| 046 | `Launch` 111 个方法——启动路径的复杂度集中在这里 | S | 同上 |
| 047 | `Simulator` 71 个方法——iOS/Android 模拟器是一等功能，不只 flag | S | 同上 + `iosSimulator*`/`androidEmulator*` flags |
| 048 | `Custom3pSetup` 41 个方法——第三方 provider 接入（Bedrock/Vertex 类）有完整配置面 | S | 同上 |
| 049 | `CoworkSpaces` 34 个方法——Cowork 有「工作空间」这一层抽象，不仅是会话 | S | 同上 |
| 050 | `Extensions` 28 个方法——浏览器扩展桥接是主进程正式职责 | S | 同上 + `chromeExtensionInstall` flag |
| 051 | `EngineSurface` **仅 25 个方法**——引擎控制面很薄，印证「agent loop 在外部二进制」 | S | 同上 |
| 052 | `CoworkArtifacts` 25 个方法 + `coworkArtifactPopout`/`artifactsPane` flags——产物有独立的弹出窗口能力 | S | 同上 |

---

## E. Agent loop 与引擎契约（053–070）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 053 | **agent loop 不在桌面端**。桌面端是 Claude Code 引擎的 SDK 客户端，通过 stdio `stream-json` 双向通信 | S | `index.chunk-DNyequwM.js` @1131100–1134600 |
| 054 | 承接层类名 `ProcessTransport`，负责 spawn / 写 stdin / 读 stdout / 归类退出 | S | 同上 |
| 055 | 基础 argv 固定四项：`["--output-format","stream-json","--verbose","--input-format","stream-json"]` | S | 同上 |
| 056 | 在基础之上按条件追加 **30+ 个开关**：`--thinking=adaptive` / `--max-thinking-tokens` / `--thinking=disabled` / `--thinking-display` / `--effort` / `--max-turns` / `--max-budget-usd` / `--task-budget` / `--model` / `--agent` / `--betas` / `--json-schema` / `--debug-file` / `--continue` / `--resume` / `--channels` / `--allowedTools` / `--disallowedTools` / `--tools` / `--setting-sources` / `--fallback-model` / `--include-hook-events` / `--include-partial-messages` / `--add-dir` / `--await-initialize` / `--plugin-dir` / `--plugin-dir-no-mcp` / `--resume-session-at` / `--resume-drops-turn` / `--session-id` / `--no-session-persistence` / `--managed-settings` | S | 同上 |
| 057 | 设置对象里值为 **`null` 的键会展开成布尔开关** `--<key>`——一种紧凑的 flag 编码约定 | S | 同上 |
| 058 | 权限询问走 `--permission-prompt-tool=stdio`——**权限决策也在引擎侧发起**，桌面端只是应答方 | S | 同上 |
| 059 | MCP 配置以 `--mcp-config <json>` 整块传入（不是逐服务器命令行） | S | 同上 |
| 060 | 另有 `--strict-mcp-config`，用于拒绝非配置来源的 MCP 服务器 | S | 同上 |
| 061 | `--allow-dangerously-skip-permissions` 真实存在，说明 bypass 模式是设计内能力 | S | 同上 |
| 062 | `--session-mirror`：会话镜像能力，配合 `sessionMentions`/`sideSession*` 支持多端同步 | S | 同上 |
| 063 | `--fork-session` 与 `--resume-session-at`：支持在任意历史点分叉会话（不只是末点续接） | S | 同上 |
| 064 | Skills 在协议层被编码进 `--allowedTools`，形如 `Skill` 或 `Skill(<name>)` | S | 同上 |
| 065 | 强制设置 `CLAUDE_CODE_ENTRYPOINT ||= "sdk-ts"`——引擎据此区分调用来源 | S | 同上 |
| 066 | 显式 `delete l.NODE_OPTIONS`——防止父进程环境注入 Node 参数 | S | 同上 |
| 067 | 每次 spawn 打日志 `Spawning Claude Code: ${me} ${he.join(" ")}`，是抓完整命令行的最直接证据 | S | 同上 |
| 068 | 失败归类 **5 类**：`aborted` / `spawn_failed` / `process_error` / `process_exited_nonzero` / `process_killed_by_signal` | S | 同上 |
| 069 | 有专门的 `formatStderrTail()`——只保留 stderr 尾部，避免错误对象爆掉 | S | 同上 |
| 070 | 写 stdin 失败有专门路径 `[ProcessTransport] stdin write failed (child likely exited)`，即已预判子进程先死 | S | 同上 |

---

## F. 流式事件协议（071–080）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 071 | **28 个 stream 事件 subtype**：init, status, api_retry, compact_boundary, hook_started, hook_progress, hook_response, informational, local_command_output, notification, task_started, task_progress, task_updated, task_notification, background_tasks_changed, commands_changed, session_state_changed, thinking_tokens, control_request_progress, memory_recall, mirror_error, model_refusal_fallback, model_refusal_no_fallback, permission_denied, plugin_install, files_persisted, elicitation_complete, worker_shutting_down | S | `index.chunk-Bn6onBlX.js` |
| 072 | **5 个 result subtype**：success, error_during_execution, error_max_turns, error_max_budget_usd, error_max_structured_output_retries——终止原因是枚举化的，不是自由文本 | S | 同上 |
| 073 | hook 应答结构固定 `{hookSpecificOutput:{hookEventName, permissionDecision, permissionDecisionReason, updatedInput}}` | S | 同上 |
| 074 | `permissionDecision` 只有 `allow` / `deny` 两个值 | S | 同上 |
| 075 | `updatedInput` 允许 hook **改写工具参数**（不只是允许/拒绝），这是很强的扩展点 | S | 同上 |
| 076 | `init` 事件在会话开始发出，携带引擎版本、工具表、可用模型等握手信息 | S | 同上 |
| 077 | `compact_boundary` 是**压缩的边界标记**——桌面端能知道压缩发生了，但压缩算法本身在引擎内（U） | S+U | 同上 |
| 078 | `thinking_tokens` 单独成事件，说明思考预算消耗是实时上报的 | S | 同上 |
| 079 | `mirror_error` 独立事件——多端镜像失败是**可恢复事件**，不终止会话 | S | 同上 |
| 080 | `worker_shutting_down` 事件——引擎有优雅停机阶段，不是被直接 kill | S | 同上 |

---

## G. Cowork VM 运行时（081–099）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 081 | `cowork-svc.exe` 是 **Go 二进制**（13,761,360 B），不是 C++/Rust | S | Go 符号表 |
| 082 | Go module 路径 `github.com/anthropics/cowork-win32-service`——内部项目名确认 | S | `cowork-svc-go-symbols.json` |
| 083 | 以 `desktop6:Extension Category="windows.service"` 注册为 Windows 服务（不是普通子进程） | S | `AppxManifest.xml` |
| 084 | 自有函数 **871 个**，分布在 **6 个包**；另有 4,412 个标准库函数（只登记不解释） | S | `cowork-svc-go-symbols.json` |
| 085 | 最大包 `vm` **531 个函数**——VM 生命周期是绝对主体 | S | `go_packages` |
| 086 | 次大包 `pipe` **244 个函数**——hvsock/命名管道通信层很重 | S | 同上 |
| 087 | `edrgate` **42 个函数**——端点检测响应门禁，说明有安全软件交互逻辑 | S | 同上 |
| 088 | `edrpolicy` **29 个函数**——EDR 策略独立成包（策略与执行分离） | S | 同上 |
| 089 | `logsink` **17 个函数**——日志汇聚独立成包 | S | 同上 |
| 090 | `win-httpproxy` **8 个函数**——VM 出网走自建代理 | S | 同上 |
| 091 | `startVM` 完整链路：等 **5 秒** → 与网络 **5 秒**竞速 → 复制 `smol-bin.<arch>.vhdx` 到 bundle → `g.configure()` → `g.startVM(i,_,v,"gvisor",probeTarget,y,b,void 0)` | S | `index.chunk-lzaSYO3Q.js` @4319128–4341310 |
| 092 | VHDX 复制遇 `EBUSY` / `EACCES` / `EPERM` **跳过而非失败**——已预期文件被占用（上次 VM 还在跑） | S | 同上 |
| 093 | 隔离层参数是字符串 **`"gvisor"`**——在 VM 内再叠一层用户态内核（runsc），是双层隔离 | S | 同上 |
| 094 | HCS 能力探测函数 `Pxr()` 返回 `{available, missingServices}`——先查服务再启动，失败可定位到具体缺失组件 | S | 同上 |
| 095 | VM 不可用原因 **5 种枚举**：`kvm_permission_denied`、`vhost_vsock_module_missing`、`vhost_vsock_kernel_unsupported`、`not_enabled`、`os_version_too_new`（注意最后一项：系统**太新**也不行） | S | 同上 |
| 096 | 遥测事件名 `lam_vm_shutdown_failed`——VM 关不掉是被单独监控的故障类型 | S | 同上 |
| 097 | 常量 `s2r="vm_bundles"`、`c2r="claudevm.bundle"`——bundle 目录结构与命名 | S | 同上 |
| 098 | 临时/标记文件后缀 `l2r=".wvm-tmp-"`、`u2r=".partial"`、`p2r=".cowork-adopted"`、`m2r="efivars.fd"`——UEFI 变量单独落盘，说明是真实固件启动而非轻量沙箱 | S | 同上 |
| 099 | 两个专用错误类 `VMDownloadError`、`VMConnectionTimeoutError{guestReady}`——后者带 `guestReady` 标志，用于区分「VM 起来了但 guest 没就绪」 | S | 同上 |

---

## H. 权限与安全（100–110）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 100 | 权限决策值 `once` / `always` / `scheduled` / `deny` / `default`；`default` 兜底为 `{behavior:"deny", message:"Unknown decision"}`——**未知即拒绝** | S | `index.chunk-lzaSYO3Q.js` |
| 101 | 权限结果带三重分类：`decisionClassification` ∈ {`user_reject`,`user_temporary`,`user_permanent`}、`approvalSurface:"host_dialog"`、`updatedPermissions` | S | 同上 |
| 102 | `updatedPermissions` 结构 `[{type:"setMode", mode, destination:"session"}]`——用户的一次授权可以**升级为会话级模式** | S | 同上 |
| 103 | 拒绝文案模板化且带工具名：`` `User rejected ${t.$f(s.toolName)} ${e}` `` 与 `"User rejected the directory access request"` | S | 同上 |
| 104 | 权限模式分布实测：`default` 24 处、`auto` 21、`ask` 18、`bypassPermissions` 4、`acceptEdits` 2、`plan` 2——`auto` 用得比 `default` 还多 | S | 全量 grep 计数 |
| 105 | 有 `delegatedAsk` / `turnIsDelegated` / `turnDelegation` 三个协作机制，配 flag `desktop_ccd_delegated_ask_allowed`——支持把权限询问**委托给子代理** | S | 同上 |
| 106 | 授权生命周期钩子齐全：`notePlanAnswered`、`rememberSshHostToolGrant`、`onWriteScopeGranted`、`renewArchiveConsent`、`voidArchiveConsent`、`accumulateSessionPermissionUpdates` | S | 同上 |
| 107 | 有「先审后自动」的提示文案 `"Review the first dynamic workflow before auto-approving."`——动态工作流首跑强制人工过目 | S | 同上 |
| 108 | `contextBridge` 暴露 **19 个桥节点**；`cowork` 桥含 `callMcpTool` / `askClaude` / `runScheduledTask` / `navigateHost` / `openExternalUrl` / `setEditableFocused` | S | preload 产物 |
| 109 | 其中 `callMcpTool` / `askClaude` / `runScheduledTask` 三个**额外受 `navigator.userActivation.isActive` 门控**——必须由真实用户手势触发，防自动化滥用 | S | 同上 |
| 110 | 启动拒绝原因分类含 `managed_sideload_disabled`、`managed_settings_refused`、`gateway_signin_required`、`gateway_access_denied`、`remote_settings_required_unavailable`、`sandbox_required_unavailable`——企业策略可在启动前拦截 | S | `index.pre.js` |

---

## I. MCP / Skills / 配置 / 遥测（111–118）

| ID | 发现 | 级 | 位置 |
|---|---|---|---|
| 111 | MCP 服务器类型枚举含 `ws-ide`，且 `["http","streamable-http"]` 被 `transform(()=>"http")` **归一化**——对外两个名字，内部一个实现 | S | MCP schema |
| 112 | MCP 配置字段：headers / headersHelper / oauth / timeout / request_timeout_ms / tools / alwaysLoad / bareElicitationCapability / discoveryCache / role / toolPermissions | S | 同上 |
| 113 | **130 个 feature flag**，其中 **24 个是未发布代号**：`grandPrix` / `violinBow` / `copperLarkA\|B\|C` / `yukonSilver*` / `humbleSky` / `quietPenguin` / `louderPenguin` / `rubberDuck` / `chillingSloth*`(5) / `sableOtter` / `epitaxyMcpApps` | S | `feature-flags.json` |
| 114 | **58 个偏好项 schema**，按域分组：`security` 31、`other` 15、`internal_state` 10、`ui_state` 2——安全类偏好占一半以上 | S | 同上 |
| 115 | `sableOtter` 配置里按键名是 **macOS 风格**（`right-control+right-shift`、`right-option`），证明这是跨平台共享代码，Windows 版只是其中一个编译目标 | S+I | 同上 |
| 116 | **26 个遥测维度**：product_surface / desktop_variant / deployment_mode / config_source / config_source_remote / inference_provider / inference_host_kind / app_version / commit_hash / platform / arch / os_version / os_release / os_build / linux_distro_id / linux_distro_version_id / linux_session_type / linux_desktop_environment / cpu_model / app_session_id / organization_id / vm_network_mode / error_code / error_kind / backend_error_code / nest_local_user | S | 遥测代码 |
| 117 | 托管配置 `surfaceGrants` 按模式给默认：`standard:{chat,fileAnalysis,cowork}`、`simple:{cowork:false}`、`no-vm`、`off`；并有保护 `"At least one surface must remain enabled; ${x} has been re-enabled."`——**不允许全关** | S | 托管配置代码 |
| 118 | 托管来源四通道：`MDM profile` / `GPO registry policy` / `/etc/claude-desktop/managed-settings.json` / `managed configuration`；`disableEssentialTelemetry` 走 JSON 前缀 `desktop-managed-config=`（偏移 25） | S | 同上 |

---

## 附：与 Atlas 的对照结论（详见 `ATLAS-GAP.md`）

三条已经**逐项比对完**、有可复现脚本的结论：

1. **33 个 hook 事件完全一致**。`scripts/diff_hooks.py` 复现：Atlas `core/atlas/runtime/hooks.py` 的 `CLAUDE_HOOK_EVENTS` 与桌面端枚举，双向差集均为 `none`。
2. **IPC 规模差 157 倍**。桌面端 1,411 个 eipc 方法 / 98 类；Atlas 9 个 `ipcMain` handler，主能力走 35 个 HTTP router。
3. **隔离层代差**。桌面端 Hyper-V + gvisor 双层 + hvsock + Plan9 共享 + EDR 门禁；Atlas `core/atlas/sandbox.py` 是 `DockerSandboxManager`（单层容器）。

这三条都不是「谁更好」的判断，是**架构选择差异**，在 `ATLAS-GAP.md` 里逐项给了取舍分析。
