# 01 — 分层架构地图

由外到内，共 11 层。每层标注「是什么 / 在哪里 / 谁创建它 / 它调谁」。

---

## L0 — 安装与宿主契约

**是什么**：Windows MSIX 包与它对系统做出的声明。
**在哪里**：`AppxManifest.xml`（11,655 B）

| 声明 | 内容 |
|---|---|
| Identity | `Name="Claude"`, `x64`, `Version="2.42304.0.0"` |
| 3 个 Application | `Claude`（主程序）、`SshAskpass`、`SshProxy` |
| 服务 | `desktop6:Service Name="CoworkVMService"`，`StartupType="auto"`，`StartAccount="localSystem"`，ETW 触发子类型 `1f81d131-...` |
| 协议/别名 | `claude://`、`claude-desktop.exe`、`claude-ssh-askpass.exe`、`claude-ssh-proxy.exe` |
| 能力 | `runFullTrust`、`localSystemServices`、`packagedServices`、`unvirtualizedResources`、`internetClient` |
| 注册表虚拟化排除 | 11 个键（8 个浏览器的 NativeMessagingHosts、2 个 Chrome 扩展 ID、Office TrustedCatalogs） |
| 文件系统虚拟化排除 | `Claude-3p`、`Claude-Data`、`Claude\logs`、Office WEF |
| 防火墙 | `Claude.exe` 与 `cowork-svc.exe` 各 TCP 入/出全放行 |

**调谁**：启动 `app\Claude.exe`；由 SCM 启动 `app\resources\cowork-svc.exe`。

---

## L1 — Electron 运行时（Chromium + Node 24.21）

**是什么**：`claude.exe`（245,756,240 B，PE x64 GUI，Authenticode `Valid`，签名主体 `CN="Anthropic, PBC"`）。
**在哪里**：`app/claude.exe` + 16 个 Chromium/ANGLE/V8 依赖 DLL + `resources.pak` + `locales/*.pak`（4,283 条）。
**调谁**：加载 `resources/app.asar`。

---

## L2 — ASAR 包内布局

```
app.asar (49,338,428 B, 548 路径 = 506 文件 + 42 目录)
├── package.json            main = .vite/build/index.pre.js
├── .vite/build/            356 主进程 chunk
│   ├── index.pre.js        930,575 B（预入口：Sentry + 启动计时 + GCProfiler）
│   ├── index.js
│   └── 13 个 preload + 8 个 worker 目录
├── .vite/renderer/         6 套窗口（60 文件）
├── node_modules/           45 文件（claude-native, node-pty, ws, agent-base）
├── compile-cache/          3 个 .jsc
└── resources/              artifact-libs(4) / bundled-skills(7) / office365-mcp(6)
```

---

## L3 — 主进程（Electron main）

**是什么**：进程编排中枢。启动时依次做：Sentry 注入 → 启动计时 → GCProfiler → 单实例锁 → deep-link 处理 → `whenReady`（34 个注册点）→ 建窗 → RPC 注册 → 生命周期钩子。
**在哪里**：`.vite/build/index.pre.js` + 356 个 `index.chunk-*.js`。
**调谁**：创建窗口（L4）、注册 RPC（L5）、spawn 子进程（L7/L9）、写盘（L10）。

关键钩子（S）：`before-quit`（拦截器，先清理再放行）、`will-quit` ×2、`window-all-closed` → `HAn()`（不直接退出）、`second-instance`（去重）、`render-process-gone` ×3。

---

## L4 — 渲染层（6 套本地窗口 + 2 种内容源）

| renderer | 用途 | preload |
|---|---|---|
| `main_window` | 主窗口外壳（标题栏/错误页/启动占位） | `mainWindow.js` + `mainView.js` |
| `quick_window` | 全局热键快速输入条 606×470 | `quickWindow.js` |
| `buddy_window` | 硬件 Buddy 700×460 | `buddy.js` |
| `about_window` | 关于窗口 320×428 模态 | `aboutWindow.js` |
| `find_in_page` | 页内查找 | `findInPage.js` |
| `local_exec_consent` | 本地执行同意（零依赖、只用 textContent） | `localExecConsent.js` |
| （动态）`claudePagePreview` | Artifact 预览容器 | `claudePagePreview.js` |
| （动态）`designWindow` | PDF 打印 | `designWindow.js` |

**内容源二选一（关键）**：
- `1p` → `loadURL(https://claude.ai…)`（远程）
- `3p` → `loadURL(app://localhost)` → 映射到 L4b

### L4b — 内置 SPA（`ion-dist`，199.5 MB / 4,224 文件）

完整的 Claude Web 前端：3,554 JS、25 CSS、3 WASM、35 MB i18n、3.1 MB 语音音频。
通过 `app://` 协议本地提供；`frame-shell.html`（标题 `Artifact`）是 Artifact 沙箱外壳。
与外壳的桥是全局对象（`claudeAppBindings`、`claudeDesktopArtifactPane`、`__frameSessionId`），**不走 eipc**；靠 UA 里的 `claude/<version>` 识别是否在桌面内。

---

## L5 — Preload 与 contextBridge

**是什么**：13 个 preload，每个只向对应窗口暴露受限 API。
**在哪里**：`.vite/build/{aboutWindow,buddy,claudePagePreview,computerUseTeach,computerUseWatchRecord,coworkArtifact,designWindow,findInPage,localExecConsent,mainView,mainWindow,quickWindow,watchRecordChooser}.js`
**暴露面**：52 处 `exposeInMainWorld`（42 个字面量 world key），如 `claudeAppBindings`、`claudeAppSettings`、`desktopBootFeatures`、`desktopEnterpriseConfig`、`electronWindowControl`、`buddy`、`cowork`、`omeletteDesktopPdf`。

---

## L6 — eipc RPC 层（97 服务 / 1,170 方法 / 162 事件）

**是什么**：自建的跨进程 RPC。所有服务复用同一 Electron channel，按 `Service_$_Method` 路由。
**注册形态**：`eo(namespace, "Service", senderCheck, {methods, events, stores})`。
**sender 校验**：每个服务自带 origin 白名单（`https://claude.com`、`https://preview.claude.com`、`app://localhost`、`.ant.dev`、开发态 localhost、打包态 `file:`）。
**按域归类**：会话与 Agent（8）、Cowork（10）、计算机操作（6）、扩展（9）、浏览器（3）、窗口界面（11）、文件数据（9）、账号配置（9）、系统集成（9）、其它代号服务（约 13）。

---

## L7 — Worker 与子进程（8 个 worker）

| worker | 字节 | 作用 |
|---|---:|---|
| `heavy-work-worker` | 1,133,689 | 重任务后台执行 |
| `file-index-worker` | 906,737 | 文件索引 |
| `mcp-runtime` | 619,607 | MCP 宿主（nodeHost / directMcpHost） |
| `transcript-search-worker` | 35,452 | 会话全文检索 |
| `msal-broker-worker` | 21,601 | MSAL 认证 |
| `pty-host` | 12,018 | ConPTY 终端宿主 |
| `shell-path-worker` | 9,575 | 解析 shell PATH |
| `stall-sampler-worker` | 2,033 | 主线程卡顿采样 |

另有 **spawn 出的 `claude` CLI 子进程**（Code/Agent 的实际执行体）。

---

## L8 — 原生宿主（18 个 PE）

| 二进制 | 字节 | 说明 |
|---|---:|---|
| `claude.exe` | 245,756,240 | Electron 主程序 |
| `cowork-svc.exe` | 13,761,360 | **Go 1.25.14**，VM 服务（15,181 函数） |
| `github-mcp-server.exe` | 20,566,352 | 内置 GitHub MCP |
| `claude-ssh-broker.exe` | 2,599,248 | Go，SSH 凭据代理 |
| `claude-ssh-askpass.exe` | 2,648,912 | Go，SSH 口令 GUI |
| `claude-ssh-proxy.exe` | 1,976,144 | Go，SSH 代理 |
| `chrome-native-host.exe` | 1,130,832 | 浏览器扩展 native messaging |
| `claude-native-binding.node` | 3,778,896 | N-API 原生绑定 |
| `conpty.node` / `conpty_console_list.node` | 312,144 / 155,472 | ConPTY |
| `msal-node-runtime.node` / `msalruntime.dll` | 365,904 / 3,261,536 | Entra 认证 |
| Chromium DLL ×6 | 41,693,680 | d3dcompiler/dxcompiler/dxil/ffmpeg/swiftshader/vulkan |

---

## L9 — 服务与 VM（`cowork-svc.exe`）

```
Windows SCM (CoworkVMService, localSystem, auto)
  └─ cowork-svc.exe
       ├─ pipe.(*Server)          \\.\pipe\cowork-vm-service
       │    handleConfigure(10,112 B) / handleStartVM / handleStopVM /
       │    handleIsRunning / handleWriteStdin / handleGetNetworkDrives /
       │    handlePassthrough / handlePersistentRPC / handleRefreshGuestProxy /
       │    handleSubscription / handleSendGuestResponse / handleRunEdrExtension /
       │    handleIsDebugLoggingEnabled / handleSetDebugLogging
       │    + InitSignatureVerification / verifyClientSignature / dispatchVerified
       ├─ vm.(*WindowsVMManager)  StartVM / StopVM / installHostCACertificates
       ├─ vm.(*HCSSystem)         CreateComputeSystem / Start / Shutdown
       ├─ vm.(*HVSocketConn)      HVSocket 通信
       ├─ vm.(*RPCServer)         Start/Stop/handleEvent/handleMessage/writeFrameUnless
       ├─ edrgate / edrpolicy     第三方 EDR 接入
       └─ logsink.Writer          日志汇聚
```

依赖栈：`go-winio` + `gvisor-tap-vsock` + `gVisor` + `win-httpproxy` + `gopacket` + `dhcp` + `dns` + `lz4` + `virtsock`。

---

## L10 — 数据与持久化

| 数据 | 位置 |
|---|---|
| 应用配置 | `config.json`、`claude_desktop_config.json` |
| 会话 | `.claude/projects/` |
| 设置 | `.claude/settings.json`、`settings.local.json` |
| 插件 | `.claude/plugins/`、`installed_plugins.json`、`known_marketplaces.json` |
| MCP | `.mcp.json`、`.claude.json` |
| Cowork | `cowork/`、`cowork_settings.json`、`spaces.json`、`scheduled-tasks.json`、`artifacts.json` |
| 窗口 | `window-state.json` |
| 认证 | `auth.json`、`msal-cache.json` |
| 日志 | `logs/{main,cowork_vm_node,mcp,ssh,claude.ai-web}.log` |
| 用户数据根 | `%LOCALAPPDATA%\Claude-Data`（1P）、`Claude-3p`（3P） |

---

## L9b — 代码执行沙箱（`smol-bin.x64.vhdx`）

**是什么**：一个随包交付的 32 MiB FAT32 虚拟磁盘（卷标 `SDK_DAEMON`，creator `claude-vm`），
承载 Agent SDK 的执行沙箱根文件系统。

**在哪里**：`app/resources/smol-bin.x64.vhdx`（37,748,736 B，SHA256 `0f9f5816…`）

**里面有什么**（5 个文件，全部解出）：

| 文件 | 大小 | 作用 |
|---|---:|---|
| `sdk-daemon` | 16,703,672 | Go 1.25.14；`AskClaude` 入口 + HTTP/HTTPS 代理栈 + SocketPath |
| `cli-wrapper` | 2,400,440 | Go 1.25.14；CLI 启动包装 |
| `claude-shim` | 2,351,288 | Go 1.25.14；伪装 `claude`，转发到 `/run/coworkd/ask-claude.sock`，只许 `claude -p` |
| `sandbox-helper` | 2,199,736 | Go 1.25.14；`usage: sandbox-helper <uid> <gid> <command>`，施加 **seccomp BPF** |
| `srt-settings.json` | 1,145 | 出网白名单 + MITM 代理 + 文件系统策略 |

**调谁**：沙箱内代码 → `claude-shim` → unix socket → `sdk-daemon` → 宿主/网络（受 `srt-settings.json` 约束）。

**关键约束**：网络只允许 npm/yarn/PyPI/crates/GitHub/Ubuntu 源/Anthropic；文件系统 `allowWrite: ["/"]` 但禁读 `/run/systemd/resolve`、`/run/dbus`；`claude` 调用被收窄为单轮提示。

---

## L11 — 云端边界（`CLOUD-UNAVAILABLE`）

| 端点 | 用途 |
|---|---|
| `https://claude.ai` / `claude.com` / `preview.*` / `*.ant.dev` | 1P 主 UI 与 API |
| `https://api.anthropic.com` | 推理 API、OAuth（`/api/oauth/claude_cli/create_api_key`、`/roles`） |
| `https://downloads.claude.ai/vms/linux/` | **VM 镜像** |
| `https://downloads.claude.ai/model-catalog/v1/{catalog,schema}.json` | 模型目录 |
| `https://downloads.claude.ai/{claude-code-releases,claude-ssh-releases}` | CLI/SSH 组件下载 |
| `https://microsoft365.mcp.claude.com/mcp` | 托管 M365 MCP |
| `vpce-*.bedrock-runtime.us-east-1.vpce.amazonaws.com` | Bedrock VPC 端点（企业） |
| `sts.windows.net` | Entra token |

**服务端内部实现一律不做推测**，只记录客户端可观察的请求形状与返回处理。

---

## 跨层调用图（文字版）

```
UI 点击
 └→ preload (contextBridge 暴露的 API)
     └→ eipc invoke "Service_$_Method"
         └→ main 进程 dispatcher（含 sender origin 校验）
             ├→ 本地能力：文件/窗口/剪贴板/通知/快捷键/托盘
             ├→ spawn `claude` CLI ──→ Claude Code agent loop（本地执行）
             ├→ CoworkVMService 管道 ──→ cowboy-svc ──→ Hyper-V VM ──→ guest 内 agent
             └→ HTTPS ──→ claude.ai / api.anthropic.com（1P）或自建网关（3P）
                 └→ 流式事件 ──→ eipc event ──→ UI 更新
```
