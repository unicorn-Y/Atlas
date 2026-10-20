# P4B — 内部代号服务释义

> 解决 `U-005` 的主要部分。所有释义都有代码或字符串证据，不是猜名字。

---

## 1. `GrandPrix` — 密码管理器伙伴配对

**结论（S）**：第三方**密码管理器应用**与 Claude Desktop 的配对通道，用于安全地共享凭据。

证据（`index.chunk-lzaSYO3Q.js` 内的遥测字段说明文本，原文引用）：

> `partner_id: "grandPrix partner registry key — Anthropic-authored GB configuration (delivered via the desktop-grand-prix flag, identity HMAC-allowlisted at load); never user, model, or partner-supplied text"`

> `unrecognized_partner_code: "... the password-manager partner app's own error code for a pairing it refused. partnerCodeForDiagnosis (grandPrix/index.ts) admits it through clampTelemetryString against ^[A-Za-z][A-Za-z0-9_]{0,31}$ (plus the 40-hex secret backstop) ..."`

方法面：

| 方法 | 参数 | 含义 |
|---|---|---|
| `pair` | `partnerId`, `context?` | 发起配对 |
| `disconnect` | `partnerId` | 断开 |
| `request` | `req` | 通用请求（联合类型 `GrandPrixRequestStatus`） |
| `submitVerificationCode` | `requestId`, `code` | 提交验证码 |
| `dismissVerificationCode` | `requestId` | 关闭验证码提示 |

store：`grandPrixStatus`（初始状态由 `getInitialGrandPrixStatusState` 提供）。

**门控**：GrowthBook flag 名 `desktop-grand-prix`；伙伴 ID 必须命中 **Anthropic 编写的白名单**，且加载时做 **HMAC 校验**。伙伴代码被限制为 `^[A-Za-z][A-Za-z0-9_]{0,31}$`（另有 40 位 hex 兜底）。

**这解释了为什么服务名是"大奖赛"**：内部代号，实际是"密码管理器生态接入"。

## 2. `Gorse` — 记忆迁移向导

**结论（S）**：一次性**记忆迁移**流程（把旧存储格式的记忆迁移到项目，或导出为文件）。

| 方法 | 参数 |
|---|---|
| `preview` | — |
| `migrateToProject` | `includeHistory` |
| `exportToFiles` | `includeHistory` |
| `openExportFallbackFolder` | — |
| `decline` | — |
| `status` | — |
| `progress` | — |

`decline` 的存在说明这是一个**用户可选择跳过**的引导流程；`progress` 说明有进度条。`includeHistory` 说明迁移粒度可选（只迁当前记忆 vs 连历史一起）。

## 3. `ForgeState` — 构建/派生状态快照

**结论（S）**：一个**键值状态快照**服务，与 `GitState` 结构同构（两者都是 `get*Snapshot` + `*Changed` 事件 + 可见键白名单）。

| 方法/事件 | 参数 |
|---|---|
| `getForgeStateSnapshot` | — |
| `setForgeStateVisibleKeys` | `keys` |
| `refreshForgeStateRow` | `key`, `reason?` |
| 事件 `forgeStateChanged` | `changed`, `removed` |

"row" 与 "visible keys" 说明它是**表格/列表形态的实时状态板**（每行一个 key，可单独刷新）。`reason` 参数用于标注为何刷新。

## 4. `GitState` — 仓库状态快照

| 方法与事件 | 参数 |
|---|---|
| `getGitStateSnapshot` | `cwds` |
| 事件 `gitStateChanged` | `changed`, `removed` |

按工作目录（`cwds`）批量取 git 状态，变化时推送增量（`changed` + `removed`）。这是 Code/Cowork 里"文件树上的 git 标记"的数据源。

## 5. `ViolinFret` — 一个开关

**结论（S，但语义未定）**：只有 1 个方法 `setViolinFretChoice(choice)`，有独立的 sender 校验。
"choice" + "fret"（琴格）→ 可能是一个**离散选择的 UI 控件**的偏好设置（类似多档位选择器）。仅此一项，**无法从代码确定业务含义**，保留为 PARTIAL。

## 6. `WebBuild` — 提交号上报

**结论（S）**：只有一个方法 `reportCommitHash(commitHash)`。
把前端构建的 commit hash 上报给主进程（用于版本诊断）。对应 `ion-dist/index.html` 的 `data-git-hash="local"`（本包是本地构建，故上报值为 local 类值）。

## 7. `Simulator` — iOS/Android 模拟器控制（54 方法）

**结论（S）**：控制**移动端模拟器**的完整面。

代表性方法：

| 方法 | 说明 |
|---|---|
| `attach(udid)` / `detach(udid)` | 挂载/卸载某设备视图 |
| `shutdown(udid)` | 关机 |
| `startDevice(id)` / `restartDevice(id)` / `renameDevice(udid)` | 设备生命周期 |
| `getSlowAnimations(udid)` / `setSlowAnimations(udid)` | **慢动画调试开关**（iOS 模拟器经典功能） |
| `listDevices(kind)` | 列举设备（`kind` = ios/android） |
| `simulatorProcessRunning()` | 进程探测 |
| `awaitQuitRestart(udid)` | 等待退出并重启 |
| `panelViewed(kind)` | 面板曝光埋点 |
| `stopDevice`(推断) / `setDeviceAppearance`(推断) | — |

配合 feature flag 里的 `iosSimulatorH264`、`iosSimulatorAccessibilityReader`、`iosSimulatorDuo`、`simulatorScreenshotEditor`、`simulatorMiniView`、`androidEmulator`，可确认这是**跨 iOS 模拟器与 Android 模拟器**的能力，且支持 H.264 视频流与无障碍读取。

## 8. `Launch` — 预览服务器与预览窗口（88 方法）

**结论（S）**：管理"本地起服务 + 在应用内预览"的完整链路。

| 方法族 | 说明 |
|---|---|
| `isAvailable()` / `isJitlessForced()` | 可用性与 JS 引擎模式 |
| `getLogs(serverId)` | 取服务日志 |
| `stopServer(serverId)` | 停服务 |
| `showPreview` / `hidePreview` / `destroyPreview` / `refreshPreview` / `focusPreview` | 预览窗口生命周期 |
| `teardownRemoteSessionPreview(sessionId)` / `setRemoteSessionViewed(sessionId)` | 远程会话预览 |
| `setPreviewChromeFocus(previewId)` | 预览区焦点 |
| `startPreview` / `openGdriveDocument` / `startRemoteBrowserPreview` | 打开文档/远程页面 |
| `listChromeImportProfiles` / `listChromeImportSites` | Chrome 导入 |
| `pickHtmlFile` / `setPreviewPaneMounted` / `clearPreviewBrowsingData` | 杂项 |

`isJitlessForced` 值得注意：说明预览窗口可能以 **JIT-less V8** 运行（更严格的沙箱），与 Electron 的 `--js-flags=--jitless` 对应。


### 7.1 Simulator 的完整能力（54 方法 + 11 事件，全部读自方法表）

| 能力组 | 方法 |
|---|---|
| 设备生命周期 | `attach` / `detach` / `shutdown` / `startDevice` / `restartDevice` / `renameDevice` / `awaitQuitRestart` / `simulatorProcessRunning` / `listDevices(kind)` |
| 显示与外观 | `getAppearance` / `setAppearance` / `getSlowAnimations` / `setSlowAnimations` / `displayPointsPerInch(windowId)` |
| **原生视图嵌入** | `nativeViewMount` / `nativeViewUnmount` / `nativeViewSetBounds` / `nativeViewSetVisible` / `nativeViewSetOrientation` / `nativeViewStill` |
| **折叠屏仿真** | `nativeViewSetBend` / `nativeViewFoldPlay` / `nativeViewFoldGo` / `nativeViewFoldConfirm` / `nativeViewFoldEnd`（事件 `nativeViewFold`、`hingeAngle`） |
| 输入与手势 | `gesture(udid)` / `sendClipboard` / `getClipboard` / `editAction` |
| **无障碍** | `describeAccessibility(udid)` / `requestDeviceConsent` / `requestDeviceToolsRepin` |
| 截图与录屏 | `captureScreenshot` / `saveScreenshot` / `readCapture` / `deleteCapture` / `startRecording` / `stopRecording`（事件 `recordingEnded`） |
| 日志 | `getLogEntries(udid)`（事件 `logEntries`） |
| 环境准备 | `checkSetup` / `checkAndroidSetup` / `openXcode` / `openAppStore` / `openAndroidStudio` |
| 快捷键认领 | `setEditShortcutsClaimed` / `setCaptureShortcutsClaimed` / `setKeyboardShortcutClaimed` / `setQuitShortcutClaimed` / `setZoomShortcutsClaimed` |
| 埋点 | `panelViewed(kind)` / `setupStepChanged(kind)` / `setupCtaClicked(kind)` / `captureThumbnailAction(kind)` / `miniViewChanged(kind)` |

事件：`captureShortcut` / `keyboardShortcut` / `quitShortcut` / `zoomShortcut` / `displayPointsPerInchChanged` / `logEntries` / `nativeViewFold` / `hingeAngle` / `recordingEnded` / `modelActivity` / `consentAskShown`。

**这解释了那 54 个方法在做什么**：这是一套**完整的移动端模拟器集成**，包括：
- 把模拟器画面作为**原生视图**嵌进 Electron 窗口（不是截图流，是 `nativeViewMount` + bounds/orientation 控制）；
- **折叠屏设备仿真**（`setBend` + `hingeAngle` 事件 → 真实铰链角度）；
- **无障碍树读取**（`describeAccessibility`），让模型能"看见"UI 元素而非像素；
- 录屏与截图编辑。

配合 GrowthBook 键 `iosSimulatorH264`、`iosSimulatorAccessibilityReader`、`iosSimulatorDuo`、`simulatorScreenshotEditor`、`simulatorMiniView`、`androidEmulator`，可以确认这是**一等公民功能**，不是实验残留。

### 8.1 Launch 的完整能力（88 方法，节选按功能分组）

| 组 | 方法 |
|---|---|
| 服务器生命周期 | `isAvailable` / `isJitlessForced` / `stopServer(serverId)` / `getLogs(serverId)` |
| 预览窗口 | `showPreview` / `hidePreview` / `destroyPreview` / `refreshPreview` / `focusPreview` / `setPreviewChromeFocus` / `setPreviewPaneMounted` |
| 远程预览 | `teardownRemoteSessionPreview` / `setRemoteSessionViewed` / `startRemoteBrowserPreview` |
| 文件与文档 | `pickHtmlFile` / `openGdriveDocument` |
| **Chrome 导入** | `getChromeImportAvailability` / `getCoworkChromeImportAvailability` / `listChromeImportProfiles` / `listChromeImportSites` |
| 浏览数据 | `clearCoworkBrowserData` / `clearPreviewBrowsingData` |
| 会话预览 | `ensureChatBlankPreview(conversationUuid)` |

`isJitlessForced()` 说明预览服务可能以 **JIT-less V8** 运行（更严的沙箱），这也与 `W-VIEW` 的 `--js-flags=--jitless` 相符。

## 9. 仍保留为 PARTIAL 的代号

| 代号 | 已知 | 未知 |
|---|---|---|
| `ViolinFret` | 单方法 `setViolinFretChoice(choice)` | 业务含义 |
| `Baku` | 出现在路由/标识中 | 语义 |
| `SableOtter` | 语音输入系统（见 `P6B-VOICE-PIPELINE.md`） | 代号来源 |
| `YukonSilver` | `ClaudeVM.setYukonSilverConfig(config)` | 具体配置项 |
| `Epitaxy` | 路由族 `/epitaxy/*`（memory/scheduled/routines/artifact/project/thread） | 产品定位（"外延"？） |

这些已按实际状态记入 `12-UNKNOWN-AND-BLOCKERS.tsv`。
