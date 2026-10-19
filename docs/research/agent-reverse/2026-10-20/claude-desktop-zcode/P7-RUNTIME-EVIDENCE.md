# P7 — 真实运行时取证

> 目标版本：**2.42304.0**（与静态分析同一份 MSIX 解包树，字节级同源）
> 环境：Windows x64，非管理员，**未安装 MSIX**（Appx 部署被拒）
> 状态：**PARTIAL — 已取得真实启动/子系统初始化/日志/进程树证据；交互式 Chat/Cowork 流程因未登录且地区受限不可达**

---

## 1. 取证方式（合法、非破坏、隔离）

| 项 | 做法 |
|---|---|
| 二进制 | 直接运行从 MSIX 解包的 `app/claude.exe`（同一 SHA 的包内文件） |
| 用户数据隔离 | `--user-data-dir=D:\Atlas\_research\claude-desktop\2026-10-20\runtime\ud-01`（独立空目录，不触碰 `%APPDATA%\Claude`） |
| 时间 | 2026-10-20 04:21:58 → 04:22:43（约 45 秒） |
| 未做 | 未登录、未上传任何凭据、未读取任何用户聊天内容 |

## 2. 实际观测结果

### 2.1 进程树（真实创建，6 个进程）

`Get-CimInstance Win32_Process -Filter "Name='claude.exe'"` 采集到 6 个 `claude` 进程：主进程（PID 54712，`MainWindowTitle = Claude`）+ 5 个子进程（renderer / GPU / utility / network service / crashpad 等标准 Electron 分解）。原始 JSON 存 `runtime/run01/proctree.json`。

### 2.2 启动性能时间线（真实埋点，单位 ms，相对进程创建）

| 阶段 | 毫秒 |
|---|---:|
| `process_created_to_node_start_ms` | 50 |
| `binary_loaded_to_node_start_ms` | 14 |
| `node_bootstrap_complete_ms` | 8 |
| `main_js_start_ms` | 40 |
| `main_pre_imports_loaded_ms` | 64 |
| `main_pre_managed_config_read_ms` | 69 |
| `main_pre_sentry_init_start_ms` | 73 |
| `main_bundle_start_ms` | 114 |
| `main_imports_loaded_ms` | 215 |
| **`app_ready_ms`** | **305** |
| `window_created_ms` | 425 |
| `window_visible_ms` | 420 |
| `main_window_loads_issued_ms` | 444 |
| `window_did_finish_load_ms` | 563 |
| `island_load_start_ms` / `island_load_end_ms` | 803 / 876 |
| **`main_view_ready_to_show_ms`** | **2188** |
| `main_view_dom_ready_ms` | 2192 |
| `main_view_request_seen_ms` | 484 |
| `main_gc_minor_count` / `main_gc_major_count` | 7 / 1 |
| `main_gc_pause_ms` | 10.2 |
| `main_heap_allocated_bytes` | 74,339,068 |

**这是首次启动的实际数字**（`is_first_run: true`），可直接用于性能基线对比。

### 2.3 真实初始化的子系统（日志逐条，这是"哪些代码真的跑了"的铁证）

| 日志时间 | 子系统 | 内容 |
|---|---|---|
| 04:21:58 | 版本 | `appVersion: '2.42304.0'`, `nodeVersion: '24.21.0'`, `platform: win32`, `arch: x64` |
| 04:21:58 | `[windows-app-job]` | `skipped: not an MSIX install` — 证明该 Job Object 逻辑只在 MSIX 安装下启用 |
| 04:21:58 | `[CCD]` | `Initialized with version 2.1.299` — **内置 Claude Code 版本号** |
| 04:21:58 | `[growthbook]` | 特性开关平台为 **GrowthBook**；`API returned status 403`（未登录） |
| 04:21:58 | `[chicago]` | `GrowthBook chicago_config: raw=undefined → enabled=false`，子 gate：`pixelValidation=false, clipboardPasteMultiline=true, mouseAnimation=true, hideBeforeAction=true, autoTargetDisplay=true, clipboardGuard=true, maskFailClosed=true, adaptiveResolution=true`，`coordMode=pixels dispatchTtlMs=1800000 appScoped=false` |
| 04:21:58 | `[remoteMarketplaceMigration]` | `gate=claudeai_cowork_backend_marketplaces value=false` |
| 04:22:00 | `[wake-scheduler]` | `registered claim id=scheduled-tasks` |
| 04:22:00 | `[WarmLifecycle:*]` | `session` / `preview` / `cowork` 三个预热生命周期，`arm=when-hidden` |
| 04:22:00 | `[transcript-read]` | `local-session reads run in the main process` |
| 04:22:00 | `NotificationService` | 使用 Electron 原生通知 |
| 04:22:00 | `[bootPreconnect]` | `proxy for https://claude.ai resolved in 54 ms (direct)`；`asset warm-up ok after 804 ms` |
| 04:22:00 | `[cu-*]` | computer-use 全套初始化：`cu-teach`(controller)、`cu-side-panel`、`cu-notifications`(listeners)、`cu-live-preview`、`cu-glow`、`cu-esc`、`cu-app-indicator` |
| 04:22:00 | `[browser-live-preview]` | `initialized (passive tap)` |
| 04:22:00 | `[claude-in-chrome]` | `local pairing flag reads off; registering once a signed-in account's flags land` |
| 04:22:00 | `[sableOtter]` | `claude-native has no sableOtter entry points; not starting` |
| 04:22:00 | `[compliance]` | `coworkHipaaRestricted at app-ready: unrestricted` |
| 04:22:00 | `[cowork]` | `one-time prune of never-served "/"/home grant entries: 0 removed` |
| 04:22:01 | main view | 加载 `https://claude.com`（真实请求 `_next/static/chunks/*.css`） |
| 04:22:42 | 崩溃 | `Main webview render process gone: { reason: 'crashed', exitCode: 143 }`，随后 Network/GPU 进程同因退出 |

### 2.4 userData 实际写入的文件（首次启动，空目录起步）

**11 个文件 + 17 个目录**，其中：

| 文件 | 内容（真实读取） |
|---|---|
| `config.json` | `{"updaterLastSeenVersion":"2.42304.0","first_launch_at":1792441320186,"version_first_launch":{"version":"2.42304.0","at":1792441317990}}` |
| `claude_desktop_config.json` | `{"preferences":{"coworkLegacyRootGrantsPruned":true,"launchPreviewPersistedWorkspaces":[],"launchPreviewSessionScopedSessions":[]}}` |
| `ant-did` | 设备标识（base64，已脱敏，不在此复述具体值） |
| `logs/main.log` | 21,792 B |
| `logs/cowork_vm_node.log` | 137 B |
| `logs/mcp.log` | 0 B（未初始化 MCP） |
| `logs/ssh.log` | 113 B |
| `logs/claude.ai-web.log` | 765 B |
| `git-worktrees.json` | 空工作树登记 |
| `declarative_performance_observer.db` (+journal) | SQLite，性能观测 |

目录：`blob_storage`、`Cache`、`Code Cache`、`Crashpad`、`DawnGraphiteCache`、`DawnWebGPUCache`、`GPUCache`、`GPUPersistentCache`、`GrShaderCache`、`Local Storage/leveldb`、`Network`、`sentry/queue`、`Session Storage`、`ShaderCache`、`Shared Dictionary`、`logs`。

**这直接验证了 P4 的持久化映射**：`config.json` + `claude_desktop_config.json` 分离、日志按子系统分文件、`Local Storage/leveldb` 用于渲染层状态。

### 2.5 关键运行期发现

1. **GrowthBook 是 feature flag 的真实后端**（不是只写在代码里的字符串）。未登录时返回 403，所有 gate 走默认值。
2. **`chicago` 是 computer-use 的配置命名空间**，含 8 个已生效子开关（鼠标动画、动作前隐藏、剪贴板保护、失败关闭掩码、自适应分辨率等），`coordMode=pixels`，`dispatchTtlMs=30min`。
3. **内置 Claude Code 版本 2.1.299**（`[CCD] Initialized with version 2.1.299`）—— 这是 Desktop 实际捆绑的 CLI 版本，可直接与 `claude-code-releases` 下载源对照。
4. **`WarmLifecycle` 三实例（session / preview / cowork）且 `arm=when-hidden`** —— 说明存在"窗口隐藏后预热"机制，这是后台任务持续运行的宿主基础。
5. **`claude-native-binding.node` 在解包树下加载失败**（`ERR_DLOPEN_FAILED`）。原因：该 `.node` 依赖 MSIX 环境/签名上下文；**这也是我未做更深入运行时验证的客观限制**，同时说明 `[sableOtter] has no entry points` 并非功能缺失而是该构建下原生模块未加载。
6. **主 webview 在 04:22:42 崩溃**（exitCode 143 = SIGTERM 类，符合我的 45 秒超时终止）。崩溃前已完整加载 `claude.com` 的 Next.js 静态资源 —— **证实主 UI 确实由远程站点渲染**。

## 3. 第二次与第三次取证（MCP 与进程拓扑）

### 3.1 Run-02：配置 MCP 服务器后的真实行为

在隔离 profile 写入 `mcpServers: { "probe-fs": { command: "node", ... } }` 后启动。结果：

- `mcp.log` 仍为 **0 字节** —— 该服务器**没有被拉起**。
- 但 main.log 出现了此前没有的 MCP 相关子系统：
  ```
  [Chrome Extension MCP] Failed to sync native host in Windows registry: Claude Native is missing
  [Chrome Extension MCP] Native host sync complete
  [Chrome Extension MCP] Watching Chrome for extension changes
  [Chrome Extension MCP] Watching Edge for extension changes
  ```
- **结论（S+R）**：`Chrome Extension MCP` 是独立于用户 `mcpServers` 的**内建 MCP 通道**，它在启动时就注册/监视 Chrome 与 Edge 的扩展变化；其原生宿主注册依赖 `claude-native`，在非安装环境下缺失。
- 用户级 MCP 服务器在**未登录**时不启动（与 `MCP` 服务的 eipc 层需要账号上下文一致）。

### 3.2 Run-03：完整进程拓扑与 URL Scheme（高价值发现）

6 个进程的真实父子关系：

```
48536  (main, MainWindowTitle="Claude", WS 210.3 MB)
 ├─ 55576  --type=crashpad-handler
 ├─ 53168  --type=gpu-process
 ├─ 46180  --type=utility  --utility-sub-type=network.mojom.NetworkService
 ├─ 54048  --type=renderer
 └─ 49184  --type=renderer
```

**每个子进程的 CommandLine 都携带完整的自定义 scheme 注册表**，这是 Electron 的 `registerSchemesAsPrivileged` 落点，直接暴露内部内容通道：

| scheme | standard | secure | bypassCSP | CORS | fetch | service-worker | streaming |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `cowork-artifact` | ✅ | ✅ | | | ✅ | | |
| `cowork-file` | ✅ | ✅ | | | ✅ | | ✅ |
| `claude-media` | ✅ | ✅ | ✅ | | ✅ | | ✅ |
| `claude-simulator` | ✅ | ✅ | ✅ | ✅ | ✅ | | ✅ |
| `app` | ✅ | ✅ | | ✅ | ✅ | ✅ | |
| `sentry-ipc` | | ✅ | ✅ | ✅ | ✅ | | |

这张表说明：
- **`cowork-file` 是 streaming scheme** → Cowork 文件按流读取（大文件不整载入）。
- **`claude-media` bypass CSP** → 媒体资源不受页面 CSP 限制，这是 artifact 能内嵌图片/媒体的机制。
- **`claude-simulator` 同时具备 bypassCSP + CORS + fetch** → `Simulator` 服务（54 个方法）是一个**可注入脚本的沙箱化页面容器**。
- **`app` 是 service-worker scheme** → 本地应用页可注册 Service Worker，具备离线能力。
- **`sentry-ipc` 单独成 scheme** → Sentry 通过自定义协议与主进程通信，而非 HTTP。

### 3.3 截图失败说明

`CopyFromScreen` 抛 `ExternalException`（会话隔离/无交互桌面），**未能取得窗口像素截图**。这是环境限制，不是应用问题。窗口本身真实存在（`MainWindowTitle="Claude"`，WS 210.3 MB，2 个 renderer 进程）。**报告中不提供任何伪造截图。**

## 4. 明确未能取证的部分（不得含糊）

| 项 | 原因 | 补采条件 |
|---|---|---|
| Chat 发送/流式返回 | 未登录，`claude.com` 停留在登录页 | 需要可用账号 + 非受限地区 |
| Cowork 任务创建与执行 | 无账号；且 `cowork_vm_node.log` 明确 `workspace VM not supported (status=unsupported)` —— 本机未启用 Virtual Machine Platform | 需要管理员开启 Hyper-V/VMP + 登录 |
| 本地 Code 会话（LocalSessions） | 需要登录后才有 `accountId/orgId`（日志：`Cannot initialize sessions: accountId=null`） | 登录后 |
| MCP 服务器加载 | `mcp.log` 为 0 字节，未配置任何 MCP | 配置 `claude_desktop_config.json` 的 mcpServers |
| 调度任务真实触发 | `wake-scheduler` 仅注册 claim，无待执行任务 | 创建定时任务后 |
| 原生窗口截图 | 进程在 45 秒超时后自行崩溃；且非 MSIX 安装下 `claude-native` 加载失败 | 需管理员安装 MSIX 后重做 |

## 4. MSIX 安装阻塞（具体、可补采）

```
Add-AppxPackage -Path claude-desktop-x64-2bf309665f.msix
→ HRESULT 0x80073D28: 需要管理员权限才能安装打包服务
  Claude_2.42304.0.0_x64__pzs8sxrjxfjjc
```
签名本身**有效**（`Get-AuthenticodeSignature` → `Valid`，Signer = `CN="Anthropic, PBC"`），所以这不是证书信任问题，而是 **`packagedServices` 能力要求管理员**（AppxManifest 声明了 `localSystemServices` + `packagedServices` 用于注册 `CoworkVMService`）。

补采只需：**以管理员运行一次** `Add-AppxPackage`，随后即可完整执行 Chat/Cowork/VM/服务全链路取证。

## 5. 证据文件

```
runtime/ud-01/                     真实首次启动的完整 userData（11 文件 + 17 目录）
runtime/ud-01/logs/main.log        21,792 B，含启动性能埋点与 19 个子系统初始化
runtime/ud-01/logs/cowork_vm_node.log  VM bundle 支持性检查
runtime/ud-01/logs/ssh.log         ClaudeSSHManager 版本 683cc6a9cd1d99430efd762587e02dd076fd5ada
runtime/ud-01/logs/claude.ai-web.log  远程站点资源加载
runtime/run01/proctree.json        6 进程树（PID/PPID/CommandLine）
runtime/run01/raw-userdata/        配置与日志快照副本
runtime/run01.log                  stderr（Electron 警告：MaxListeners 等）
```

## 6. 结论（诚实版）

- **R 级证据：已取得**（真实进程、真实日志、真实文件系统写入、真实性能数字、真实子系统初始化顺序）。
- **但覆盖面有限**：只到"启动 + 子系统装配"层；**没有任何一次真实的对话、工具调用、Cowork 任务、VM 启动**。
- **因此本阶段 = PARTIAL**，不能写成 COMPLETE，也不能把"看到 `cu-live-preview initialized`"写成"计算机操作功能已验证可用"。
