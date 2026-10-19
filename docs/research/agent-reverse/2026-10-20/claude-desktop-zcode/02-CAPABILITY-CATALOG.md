# 02 — 能力目录：97 个 RPC 服务逐项说明

> 每一行都是真实的 eipc 服务定义（`eo(ns,"Service",senderCheck,{methods,events,stores})`）。
> 方法名与参数名是打包器保留的原始标识符。证据等级全部为 **S**。
> 完整方法签名见 `ledgers/EIPC-METHODS.tsv`（1,170 行）；此处给用途归纳。

---

## A. 会话与 Agent（8 个服务，共 503 个方法）

| 服务 | 方法/事件 | 它实际在干什么 |
|---|---:|---|
| `LocalSessions` | 329 / 10 | **本地 Code 会话的总控**。创建、发消息（17 个参数含粘贴/提及/侧栏）、分叉、分离父会话、上下文用量、输出风格、权限模式、Chrome 域白名单、恢复（`canAutoResume`/`retryStart`/`restartRemoteSession`）、远程控制/共享会话、Claude Code 版本管理与重装。它 spawn 出 `claude` CLI 子进程，是 Desktop 里唯一真正的"本地 agent 执行体"。 |
| `LocalAgentModeSessions` | 115 / 13 | 与上面平行的另一条会话路径，参数偏"模式化"：`documentFunnelEnabled`、`docxEditingCarveout`、`syntheticMessage`、`trailingContentBlocks`。用于文档类任务与预置触发。 |
| `EngineSurface` | 19 / 6 | 执行引擎的表面适配层（19 个方法 + 6 个事件），把会话请求转成引擎调用。 |
| `ClaudeCode` | 10 / 0 | 内置 CLI 的胶水层：`getStatus`、`prepare`、`checkGitAvailable`、`resolveLocalSettings`、`patchUserSettings`、`setEnableWorkflows`、`getPeriodUsage`、`setLocalSandboxEnabled`、`setStrictSandboxMode`、`getLocalSandboxStatus`。 |
| `ClaudeVM` | 12 / 4 | **本地 VM 生命周期**：`download`（`downloads.claude.ai/vms/linux/`）、`startVM`、`restartVM`、`getDownloadStatus`、`getRunningStatus`、`checkVirtualMachinePlatform`、`enableVirtualMachinePlatform`、`restartAfterVMPInstall`、`isHostLoopModeEnabled`、`isHostLoopDevOverrideActive`、`setForceDisableHostLoop`、`setYukonSilverConfig`。 |
| `LocalSessionEnvironment` | 6 / 0 | 会话的环境变量与工作目录配置。 |
| `LocalSessionPresets` | 2 / 0 | 会话预设。 |
| `SessionPopouts` | 4 / 0 | 把会话"弹出"成独立窗口。 |

## B. Cowork（10 个服务，共 110 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `CoworkSpaces` | 33 / 1 | 工作空间（项目容器）的增删改查与成员管理。 |
| `CoworkArtifacts` | 24 / 1 | Artifact 全生命周期：导入、显示/隐藏、`parkAndCaptureArtifact`（离屏渲染截图）、版本恢复、缩略图、HTML 获取、重发布、命名、加星、绑定 MCP 工具、打印 PDF、共享/取消共享、自动发布开关。 |
| `CoworkScheduledTasks` | 16 / 2 | Cowork 定时任务。 |
| `CCDScheduledTasks` | 12 / 1 | Claude Code 侧定时任务（与上面并存）。 |
| `CoworkStorage` | 9 / 1 | Cowork 数据存储层。 |
| `CoworkFilePreview` | 9 / 0 | 原生文件预览（`isVmReady`、`vmReadiness`、`show/hide/parkAndCapture`），依赖 VM 就绪。 |
| `CoworkMemory` | 7 / 0 | Cowork 记忆（跨会话）。 |
| `CoworkArtifactBridge` | 6 / 0 | **渲染侧桥**：`callMcpTool`、`askClaude`、`runScheduledTask`、`navigateHost`、`openExternalUrl` 等——artifact 内页面通过这些方法与宿主交互。 |
| `CoworkFeedback` | 5 / 0 | 反馈提交。 |
| `CoworkUserFiles` | 4 / 0 | 用户文件挂载/列举。 |

## C. 计算机操作（Computer Use，6 个服务，共 29 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `ComputerUseTcc` | 7 / 0 | 屏幕录制/辅助功能等**系统权限**（TCC 风格命名）。 |
| `FramebufferPreview` | 8 / 3 | 屏幕帧缓冲预览（把桌面画面送去模型）。 |
| `SableOtterHud` | 9 / 2 | 语音输入 HUD（那个 460×72 点击穿透的悬浮窗）。 |
| `CuTeach` | 4 / 4 | 计算机操作"教学"模式。 |
| `CuWatchRecordChooser` | 4 / 2 | "录制技能/共享屏幕"选择器。 |
| `CuWatchRecordPill` | 4 / 4 | 录制中的药丸指示器。 |

另有 `ComputerUseLivePreview`（2 方法）实时预览。

## D. 扩展与工具（9 个服务，共 101 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `Custom3pSetup` | 35 / 0 | **第三方（企业）推理配置向导**：提供商、端点、认证、模型映射。 |
| `Extensions` | 24 / 4 | 扩展市场：安装/更新/启用/卸载/校验。 |
| `LocalPlugins` | 16 / 1 | 本地插件。 |
| `CustomPlugins` | 14 / 1 | 自定义插件。 |
| `MCP` | 7 / 2 | MCP 服务器配置读写、状态、日志定位。 |
| `PluginBridgeMcp` | 1 / 1 | 插件 ↔ MCP 桥。 |
| `Custom3pHelperRun` | 3 / 1 | 运行第三方 helper。 |
| `Skills` | 0 / 1 | 技能（事件 `previewSkillFile`）。 |
| `Custom3pUsage` | 1 / 0 | 第三方用量统计。 |

## E. 浏览器集成（3 个服务）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `ChromeExtension` | 6 / 1 | Chrome 扩展配对、native host 注册与状态。 |
| `BrowserNavigation` | 3 / 0 | `goBack`/`goForward`/导航状态（内置浏览器）。 |
| `BrowserNavigation` stores | — | `navigationState_$store$_getState` 镜像。 |

## F. 窗口与界面（11 个服务，共 46 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `WindowControl` | 16 / 0 | `resize`/`show`/`focus`/`close`/`setThemeMode`/`setIncognitoMode` 等窗口级操作。 |
| `WindowState` | 6 / 6 | 窗口几何持久化与变更广播。 |
| `WindowLayout` | 2 / 1 | 布局（分栏/弹出位置）。 |
| `MenuEvents` | 4 / 17 | 菜单点击 → 渲染层事件（17 个事件）。 |
| `MainWindowTitleBar` | 4 / 3 | 自绘标题栏。 |
| `FindInPage` / `FindInPageProvider` | 3/4 · 3/2 | 页内查找与提供者。 |
| `QuickEntry` / `QuickWindow` | 1/1 · 2/0 | 快速输入条。 |
| `DesktopNotifications` | 7 / 1 | 系统通知。 |
| `AboutWindow` | 5 / 0 | 关于窗口内容（`getBuildProps`/`getSupport`/`openHelp`）。 |
| `DeepLink` / `Navigation` / `Toast` | 纯事件 | 深链、导航、Toast 三个**只推不拉**的面。 |

## G. 文件与数据（9 个服务，共 80 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `FileSystem` | 19 / 0 | 读写/列举/监视文件。 |
| `DeviceRegistry` | 18 / 0 | 设备注册（多设备/硬件 Buddy）。 |
| `HistoryImport` | 13 / 2 | 从其他客户端导入历史。 |
| `ClaudeAiImport` | 19 / 5 | 从 claude.ai 导入会话/项目。 |
| `DocumentFunnel` | 9 / 1 | 文档处理管道（上传 → 解析 → 注入上下文）。 |
| `DeviceStorage` | 7 / 1 | 设备级存储。 |
| `FilePickers` | 2 / 0 | 系统文件选择器。 |
| `OsEntryPlaces` / `OsOpenHandlers` | 1/0 · 1/0 | 系统"最近位置"与"用什么打开"。 |
| `CliSessionImport` | 2 / 1 | 导入 CLI 会话。 |

## H. 账号与配置（9 个服务，共 34 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `AppConfig` | 4 / 0 | `getAppConfig`、`setAppFeature`、`setIsUsingBuiltInNodeForMcp`、`setIsDxtAutoUpdatesEnabled`。 |
| `AppPreferences` / `AppFeatures` | 2/1 · 1/1 | 偏好与特性开关。 |
| `Auth` | 2 / 0 | `doAuthInBrowser`、`prepareForSignedIn`。 |
| `Account` | 2 / 0 | 账号变更、账号详情。 |
| `DesktopInfo` | 3 / 0 | 桌面端信息（版本/平台）。 |
| `DesktopIntl` | 2 / 1 | 语言与 locale 切换（事件带 messages）。 |
| `PlanUsage` | 1 / 0 | 套餐用量。 |
| `ManagedConfig` | stores | **托管配置（MDM）镜像**，无方法只有 store。 |

## I. 系统集成（9 个服务，共 27 个方法）

| 服务 | 方法/事件 | 用途 |
|---|---:|---|
| `AutoUpdater` | 8 / 0 | 检查/下载/重启更新、空闲重启、更新状态。 |
| `Startup` | 4 / 0 | 开机自启。 |
| `GlobalShortcut` | 2 / 0 | 全局热键注册。 |
| `SupportBundle` | 1 / 0 | 生成诊断包（stages）。 |
| `Resources` | 15 / 2 | 资源路径解析（含 `ion-dist`、技能、artifact libs）。 |
| `PrintCallReporter` / `RendererMemoryReporter` / `ContentStampReporter` | 各 1 | 遥测上报器。 |
| `OsOpenHandlers` | 1 / 0 | 外部打开。 |

## J. 内部代号与未完全定性的服务（约 13 个）

| 服务 | 方法/事件 | 已知 | 未知 |
|---|---:|---|---|
| `Launch` | 88 / 20 | 启动预览/工作区/标签页（大量 `startPreview`、`openGdriveDocument`、`listChromeImportProfiles`） | 完整语义集 |
| `Simulator` | 54 / 11 | 一个可注入脚本的沙箱页面容器（`claude-simulator` scheme 带 bypassCSP+CORS+fetch） | 具体模拟目标 |
| `GrandPrix` | 5 / 0 | — | 代号含义 |
| `ForgeState` | 3 / 1 | — | 代号含义 |
| `Gorse` | 7 / 0 | — | 代号含义 |
| `ViolinFret` | 1 / 0 | 带 sender 校验的服务 | 代号含义 |
| `SableOtterHud` | 9 / 2 | 语音 HUD | `sable-otter` 完整语义 |
| `WebBuild` | 1 / 0 | — | — |
| `Dictation` | 1 / 0 | 听写 | 引擎来源 |
| `Buddy` / `BuddyBleTransport` / `BuddyRemoteFeed` | 12/2 · 3/1 · 1/1 | 硬件伙伴设备，含 **BLE 传输** | 硬件协议 |
| `CloudMove` | 2 / 1 | 云端迁移 | 迁移对象 |
| `RemoteControlServing` | 9 / 0 | 远程控制服务端 | 协议细节 |
| `WakeScheduler` | 2 / 0 | 唤醒调度（claim 注册） | 与 OS 定时器的绑定 |
| `AgentModeFeedback` | 2 / 0 | 反馈 | — |
| `OfficeAddinFiles` | 9 / 5 | Office 加载项文件桥 | — |

---

## 统计

| 分组 | 服务数 | 方法数 |
|---|---:|---:|
| A 会话与 Agent | 8 | 503 |
| B Cowork | 10 | 110 |
| C 计算机操作 | 6 | 29 |
| D 扩展与工具 | 9 | 101 |
| E 浏览器 | 3 | 3 |
| F 窗口界面 | 11 | 46 |
| G 文件数据 | 9 | 80 |
| H 账号配置 | 9 | 34 |
| I 系统集成 | 9 | 27 |
| J 代号/未定性 | 约 23 | 约 237 |
| **合计** | **97** | **1,170** |

> 事件另计 162 个。所有服务均有可达调用者（见 `ledgers/RPC-REGISTRY.tsv`，1,332 行全 PAIRED）。
