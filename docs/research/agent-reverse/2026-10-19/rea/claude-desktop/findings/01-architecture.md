# 01 · 产品骨架与模块划分

> 证据等级：**S**=源码/符号直接可见，**R**=运行时观测，**D**=官方文档，**I**=推断，**U**=不可获得
> 目标样本：`claude-desktop-x64-2bf309665f.msix` · v2.42304.0 · 297,191,037 B
> SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`（已校验）

---

## 1. 这个产品到底是什么

Claude Desktop 不是"一个网页套壳"。拆开后可以看到**四个可独立运行的执行体**，它们各自有不同的信任边界和生命周期：

| 执行体 | 形态 | 大小 | 职责 | 证据 |
|---|---|---|---|---|
| `claude.exe` | Electron 主进程 + Chromium | 245,756,240 B | 窗口、菜单、托盘、更新、原生协议、全部 IPC 服务端 | S |
| `cowork-svc.exe` | **Go 二进制**（非 Rust，非 Node） | 13,761,360 B | Windows Hyper-V / HCS 虚拟机运行时，Cowork 本地沙箱 | S |
| `claude-ssh-*.exe` | 3 个独立小工具 | — | SSH askpass / broker / proxy 子进程 | S |
| `chrome-native-host.exe` | 原生消息宿主 | — | 浏览器扩展 ↔ 桌面端桥 | S |

另外还有**两套前端**，这点容易误判：

- `ion-dist/` — 190.3 MB、**4224 个文件**的 claude.ai Web 应用构建产物（React/Vite），运行在渲染进程里。
- `.vite/build/` — 369 个 JS、19.8 MB 的 **Electron 主进程** bundle。
- `.vite/renderer/` — 6 个窗口各自的 preload。

关键结论：**Claude Desktop 的"产品逻辑"绝大部分不在桌面端，而在 `ion-dist` 的 Web 包里**；桌面端负责的是"能力供给"（文件系统、VM、PTY、Git、浏览器、权限）。

---

## 2. 构建指纹（S）

来自 `app.asar/.vite/build/index.pre.js` 内联的构建元数据：

```
commitHash      = e7f60e658f15cfece9efa384a78a39aec3c12845
commitTimestamp = 2026-10-15T05:54:05.000Z
buildType       = prod
isNestBuild     = false
appVersion      = 2.42304.0
productName     = Claude
package name    = @ant/desktop      ← 注意：不是 @anthropic/…
main            = .vite/build/index.pre.js
```

构建栈：Electron **8.0.0-alpha.10** + Electron Forge + Vite。
打包形态：Windows MSIX（`desktop6:Extension Category="windows.service"` 注册 `cowork-svc.exe`）。

`index.pre.js` 是入口，只有 930,575 B，它的作用是**在加载真正主进程前做启动守卫**（见 `04-安全与信任边界.md`），然后把 `index.chunk-lzaSYO3Q.js`（7.08 MB）拉起来。

---

## 3. 主进程 bundle 的实际分层

按体积和职责，`.vite/build/` 的 369 个文件可归为 6 层。体积不是随机的——最大的几个 chunk 正好对应最重的子系统：

| 文件 | 字节 | 承担什么 |
|---|---|---|
| `index.chunk-lzaSYO3Q.js` | 7,081,117 | **主控**：窗口管理、偏好设置、VM 生命周期、预览/内置浏览器、设置 schema、feature flag |
| `index.chunk-Bn6onBlX.js` | 2,106,696 | **Agent 引擎接入层**：SDK 会话、hook 事件表、ToolPermissionBroker |
| `index.chunk-DNyequwM.js` | 1,224,866 | **CLI 进程传输**：argv 构建、stdio stream-json 协议、进程退出归因、MCP 配置 |
| `index.chunk-BlEfqh4Z.js` | 917,018 | 控制协议：`set_model` / `set_permission_mode` / `interrupt` 等控制消息 |
| `index.chunk-M6SkuaH9.js` | 737,910 | 窗格/分屏/弹出窗口编排 |
| `index.chunk-BvMaI6NQ.js` | 592,251 | 权限与工具授权 UI 逻辑 |
| `index.chunk-CPEA6dKA.js` | 353,429 | SSH 传输层 |
| `index.chunk-Dd4cATog.js` | 317,789 | — |
| `index.chunk-CcveFAuE.js` | 242,613 | 信号/崩溃处理（`SIGABRT`… 表） |
| `index.chunk-DyYrY1NN.js` | 215,517 | 流式渲染 |
| `mainView.js` | 171,276 | 主窗口视图桥 |
| `index.chunk-DoU0pLl3.js` | 151,465 | — |
| `index.chunk-C6OBlOlX.js` | 133,497 | — |
| `index.chunk-1lJXcT8c.js` | 41,464 | **定时任务调度器**（`cron` 出现 133 次） |
| `index.chunk-BPjIr-mn.js` | 50,076 | **第三方历史导入**（ChatGPT/Codex → Claude） |

### 独立 worker（每个都是独立进程）

| 目录 | 文件 | 字节 |
|---|---|---|
| `file-index-worker/` | `fileIndexWorker.js` | 906,737 |
| `heavy-work-worker/` | `heavyWorkWorker.js` | 699,494 |
| `mcp-runtime/` | `directMcpHost.js` | 613,700 |
| `transcript-search-worker/` | — | — |
| `shell-path-worker/` | — | — |
| `stall-sampler-worker/` | — | — |
| `msal-broker-worker/` | — | — |
| `pty-host/` | — | — |

`mcp-runtime/directMcpHost.js` 有一个专门的 `serviceName: "Custom 3P MCP Host"`（S），说明第三方 MCP 宿主被刻意隔离到独立进程——这是权限边界，不是性能优化。

---

## 4. 窗口角色枚举（S）

主进程里有一份硬编码的窗口角色表，直接说明了产品有几个独立窗口：

```js
MZ = {
  CLAUDE_AI_WEB:        "claude.ai-web",       // 主界面（加载 ion-dist）
  FIND_IN_PAGE:         "find-in-page",        // 页内查找
  ABOUT:                "about",
  MAIN_WINDOW:          "main-window",
  QUICK_ENTRY:          "quick-entry-window",  // 全局快捷键唤起的悬浮输入框
  CUSTOM3P_SETUP:       "custom3p-setup",      // 第三方推理端点配置
  CUSTOM3P_DEVICE_CODE: "custom3p-device-code",
  IN_APP_BROWSER:       "in-app-browser"       // 内置浏览器侧栏
}
```

`QUICK_ENTRY` 对应偏好设置里的 `nativeQuickEntry` / `quickEntryGlobalShortcut` / `quickEntryDictation`。`IN_APP_BROWSER` 是侧栏浏览器，对应官方文档的 built-in browser（D）。

---

## 5. 渲染进程 preload 暴露面

`.vite/renderer/` 下 6 个窗口各有自己的 preload。`contextBridge.exposeInMainWorld` 共 19 个节点，其中 5 个是具名 API：

| 全局名 | 来自 | 作用 |
|---|---|---|
| `cowork` | `coworkArtifact.js` | Cowork artifact 内嵌页面回调宿主 |
| `claudeDesktopArtifactPane` | — | artifact 窗格控制 |
| `omeletteDesktopPdf` | — | 设计稿转 PDF |
| `buddy` | `buddy.js` | 硬件伙伴设备配对 |
| `process`（受限） | — | 仅暴露 `desktopEssentialTelemetryDisabled` |

`cowork` 是最值得注意的一个，它把宿主能力直接交给**模型生成的 HTML artifact**：

```js
cowork = {
  callMcpTool(e, t),          // → CoworkArtifactBridge_$_callMcpTool
  askClaude,                  // → CoworkArtifactBridge_$_askClaude
  runScheduledTask(e => r.runScheduledTask?.(e, {
      hasUserActivation: navigator.userActivation.isActive   // 用真实用户手势做门控
  })),
}
```

`navigator.userActivation.isActive` 这一句说明：artifact 里的页面要能触发定时任务，必须由**真实用户手势**驱动，不能由脚本自动触发。这是一个明确的反自动化设计。

---

## 6. 内置能力清单（按 feature flag 反推）

主进程里有一份 **130 项的 feature flag 表**（S，`index.chunk-lzaSYO3Q.js` @1567155 附近），是判断"产品到底有哪些功能"最可靠的单一来源。全表见 `indexes/feature-flags.json`。

按业务域归类（这是产品路线图，不是推测）：

**Cowork / 本地执行**
`coworkArtifacts` `coworkWatchers` `coworkWatchRecord` `coworkBrowser` `coworkBrowserToolsEnabled` `coworkBranchSession` `coworkRemoteSessionSpaces` `coworkScheduledTaskProjects` `coworkLocalSessionProjects` `coworkScheduledTaskRepoint` `coworkThinkingInSend` `coworkCopperHeron` `coworkKappa` `coworkSeededSummon` `selfHostedCowork`

**Claude Code 集成**
`ccdPlugins` `ccdPluginSourceRouting` `ccdGitEngine` `ccdPromptSuggestionsSetting` `ccdLandingTools` `ccdMcpVerbsMidTurn` `ccdMcpTurnOnSshHost` `ccdRestartRemoteClaudeCode` `ccdSshStartsWithoutBlockedPlugins` `ccdConnectorTools` `ccdTeleportSnapshot`

**Computer Use**
`computerUse` `computerUseComplianceGate` `computerUseRollout` `computerUseAppScoped` `computerUsePerAppAccess`

**模拟器（iOS / Android）**
`iosSimulator` `iosSimulatorH264` `iosSimulatorAccessibilityReader` `iosSimulatorDuo` `androidEmulator` `simulatorScreenshotEditor` `simulatorMiniView` `simulatorNativeViewPerPane` `simulatorPopoutShortcuts` `simulatorNativeViewPopout`

**Worktree**
`folderWorktrees` `folderWorktreesRemote` `folderWorktreesListedDiscard`

**WSL**
`wslForkSession` `wslTerminal` `wslMcp` `wslPreview` `wslLocalFiles` `wslRoutines`

**会话与窗格**
`sideSessions` `sideSessionProposalPicks` `sideSessionProposalWorktreePick` `sideSessionOfferCloudStart` `btwChildSessions` `sessionMentions` `sessionPrOwnership` `sessionFolderFileAccess` `conversationFolderGrants` `tearOffHalo` `sidePanePopoutNativeViews`

**调度与保活**
`wakeScheduler` `keepAwake` `codeSessionKeepAwake`

**平台/入口**
`chatTab` `chatIn3p` `desktopHome` `desktopTopBar` `chatCodeExecution` `selfHostedSessions` `multiAccount` `bootstrapConfig` `telescopeBridge`

**实验代号**（无描述，只存在于 flag 表）
`quietPenguin` `louderPenguin` `rubberDuck` `velvetFinch` `chillingSloth*`（5 个子 flag）`yukonSilver` `yukonSilverGems` `yukonSilverGemsCache` `humbleSky` `violinBow` `violinBowHomeSettings` `copperLarkA/B/C` `epitaxyMcpApps` `epitaxyMcpAppPane` `grandPrix` `grandPrixRequest` `sableOtter`

代号在代码里是**稳定的标识符**，可以直接在 `indexes/feature-flags.json` 里检索。

---

## 7. 偏好设置分类（S）

schema 里每个偏好项都带 `.meta(eg("<category"))`，分类是产品自己打的：

| 分类 | 数量 | 代表项 |
|---|---|---|
| `security` | 31 | `chromeExtensionEnabled` `rubberDuckEnabled` `velvetFinchEnabled` `secureVmFeaturesEnabled` `launchEnabled` `allowAllBrowserActions` `previewJitlessKillSwitchEngaged` |
| `other` | 15 | `menuBarEnabled` `ccMaxWarmWorktrees` `vmMemoryGB` `vmCpuCount` `keepAwakeEnabled` |
| `internal_state` | 10 | `wakeSchedulerRegisteredAtVersion` `ccAutoArchiveOnPrClose` `remoteToolsDeviceName` |
| `ui_state` | 2 | `sableOtterDictationCount` `chicagoBackgroundIntroSeen` |

`vmMemoryGB` / `vmCpuCount` 是用户可调的 VM 资源——这证明 Cowork 的本地 VM 是一个**可配置的真实虚拟机**，不是容器。

---

## 8. 与官方文档的对照（D）

| 官方说法 | 代码证据 | 结论 |
|---|---|---|
| Cowork 默认云端执行，本地执行仅保留给 2026-10-06 前启动的任务 | VM 代码完整存在且有 `coworkLocalTasksOffLatched` latch | 一致。本地 VM 代码未删除，只是被策略关闭 |
| 统一 Chat + Cowork = Claude | `chatTab` / `desktopHome` / `surfaceGrants` 三态开关 | 一致，`surfaceGrants` 就是灰度机制 |
| 内置浏览器在侧栏 | `IN_APP_BROWSER` 窗口角色 + `Launch` 子系统 111 个方法 | 一致 |
| 架构说明文章 | `ion-dist` Web 前端 + 主进程能力供给 | 一致 |

---

## 9. 本模块的边界（必须如实标记）

- **U**：Anthropic 服务端实现（模型调用、云端 Cowork 执行、组织策略下发）完全不可获得。
- **U**：`claude.ai` 登录后的真实产品界面在本环境被区域门禁拦截，无法在 R 层截取（详见 `05-运行时观测.md`）。
- **I**：代号 feature（`copperLark`、`yukonSilver` 等）只能确认**存在**，无法确认语义——flag 表里没有描述文本。
