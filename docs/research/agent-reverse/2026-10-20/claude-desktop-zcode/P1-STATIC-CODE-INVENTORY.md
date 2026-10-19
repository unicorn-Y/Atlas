# P1 — 静态代码全覆盖发现

> 版本：Claude Desktop Windows x64 enterprise **2.42304.0**
> 包 SHA256：`2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`
> ASAR SHA256：`8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db`

---

## 1. 真实入口链（从 manifest 逐跳确认，不是按文件名想象）

```
AppxManifest.xml
  └─ Application Id="Claude" Executable="app\Claude.exe" EntryPoint="Windows.FullTrustApplication"
       └─ app/claude.exe  (PE x64 GUI, 245,756,240 B, FileVersion 2.42304.0, Authenticode Valid)
            └─ app/resources/app.asar
                 └─ package.json → "main": ".vite/build/index.pre.js"
                      └─ .vite/build/index.pre.js   (930,575 B — 主进程预入口)
                           ├─ .vite/build/index.js  (主入口)
                           ├─ 356 个 .vite/build/index.chunk-*.js   (主进程代码块)
                           ├─ 13 个 preload: aboutWindow / buddy / claudePagePreview /
                           │     computerUseTeach / computerUseWatchRecord / coworkArtifact /
                           │     designWindow / findInPage / localExecConsent / mainView /
                           │     mainWindow / quickWindow / watchRecordChooser
                           ├─ 9 个 worker 目录: file-index-worker, heavy-work-worker,
                           │     transcript-search-worker, shell-path-worker,
                           │     stall-sampler-worker, msal-broker-worker, pty-host,
                           │     mcp-runtime(nodeHost, directMcpHost)
                           └─ .vite/renderer/ 6 套窗口 (60 个文件)
```

`index.pre.js` 开头即为 Sentry 注入 + `globalThis.__claudeMainJsStartMs` 启动计时，说明主进程有明确的启动性能埋点。

## 2. 文件覆盖总账（506 个 ASAR 文件，100% 有归属）

| 层 | 文件数 | 说明 |
|---|---:|---|
| `main` | 356 | Electron 主进程：入口 2 + preload 13 已单列，其余为主 chunk / 其它主进程模块 |
| `renderer` | 60 | 6 套窗口的 HTML/JS/CSS/字体 |
| `preload` | 13 | 每窗口一个 preload，负责 contextBridge |
| `worker` | 9 | utilityProcess / Worker 子进程 |
| `mcp-runtime` | 2 | `nodeHost.js`、`directMcpHost.js` |
| `dependency` | 45 | asar 内 `node_modules`（`@ant/claude-native`、`node-pty`、`ws`、`agent-base` 等） |
| `resource` | 17 | `artifact-libs`、`bundled-skills`、`office365-mcp` |
| `cache` | 3 | V8 code cache `.jsc` |
| `metadata` | 1 | `package.json` |
| **合计** | **506** | 与 P0 的 ASAR 文件计数完全一致 |

**解析状态**：`ok` 435、`n/a`（非 JS，按 P0 账本登记）69、`FAIL` 2。
两个 FAIL 都是 TypeScript 声明文件 `node_modules/agent-base/dist/helpers.d.ts` 与 `index.d.ts`，内容是 `import`/`export` 类型声明、无可执行代码 —— **已解释，不是未知**。

> 旧记录“437 个 JS parse success”的口径至此澄清：437 = 431 个 `.js` + 4 个 `.mjs` + 2 个 `.ts`（不是 437 个 `.js`）。本轮实测 `.js` 为 431。

## 3. 符号索引

| 表 | 行数 | 内容 |
|---|---:|---|
| `SYMBOLS.tsv` | 59,658 | 函数声明（名/行/列/参数数/async/generator）、类、以及 `app./ipcMain./protocol./session./Menu./Tray./globalShortcut./powerMonitor./nativeTheme./shell./dialog.` 调用点 |
| `CALL-EDGES.tsv` | 3,053 | `imports` / `requires` / `dynamic-import` 边，含导入的具体名称 |
| `DYNAMIC-IMPORTS.tsv` | 1 | 唯一的运行期动态导入点 |
| `STRING-ENUMS.tsv` | 1,179 | 打包器生成的字符串枚举表全部成员（这是理解压缩代码语义的关键） |

**说明**：59,658 个符号不等同于 59,658 个“功能”。绝大多数是被内联的第三方库函数（minify 后名字为 `r`/`e`/`t`）。第一方语义主要体现在 `STRING-ENUMS.tsv`、`EIPC-*`、`IPC-*` 三张表里。

## 4. 压缩代码的破译方法（为什么能读懂了）

该 ASAR 由 rolldown/vite 压缩，所有标识符被重命名为单字母。**但打包器保留了字符串枚举生成器**：

```js
var Za = function(e){return e.ListMcpServers="list-mcp-servers",
  e.ConnectToMcpServer="connect-to-mcp-server",
  e.McpServerConnected="mcp-server-connected", ...}({})
```

因此可以从“枚举变量 → 键 → 字面值”恢复语义。本轮共提取 **1,179 条枚举成员**，覆盖 127 个枚举表。

同时，RPC channel 由拼接生成：

```js
"$eipc_message$_6010a08f-...-_$_claude.web_$_" + "CoworkArtifacts_$_getAllArtifacts"
```

本轮把 1,284 条 `BinaryExpression` 拼接**全部折叠成字面量**，得到 1,250 个唯一 channel 名。

## 5. 模块级真实发现（每条都有 code anchor）

### 5.1 主窗口 UI 是远程的

`.vite/renderer/main_window/index.html` 第 1 行原注释：

> `<!-- this is the html for app title bar and error UI. everything else gets loaded from claude.ai -->`

这意味着：**本地主窗口只负责标题栏 + 错误页 + 启动占位**，聊天/项目/设置等业务界面由 `claude.ai` 远程渲染。这是本次解剖最重要的架构事实之一，直接决定了 P2 的“本地 UI vs 远程 UI”分界，也说明大量产品行为无法从包内静态得出。

### 5.2 IPC 不是裸 `ipcMain`，而是自建 eipc RPC 框架

- `ipcMain` 直接使用只有 **9 处**（`handle` 2、`on` 6、`removeHandler` 1）。
- 真正的 RPC 面是 `$eipc_message$<guid>_$_<namespace>_$_<Service>_$_<Method>` 形态，由框架函数 `eo(namespace, serviceName, senderCheck, {methods:[[name,[[param,Validator]],...]], events:[...]})` 注册。
- 每个服务都带 **sender 校验函数**（如 `xSe(e){return e.senderFrame?.parent===null}`、`rg(e){... new URL(e.senderFrame.url) ... origin==="null"||origin===nu}`），即 origin 白名单。
- 共 **97 个服务、1,170 个方法、162 个事件**。

### 5.3 服务清单即产品能力地图（97 项）

详见 `index/EIPC-SERVICES.tsv`。按业务域归类：

| 域 | 服务 |
|---|---|
| 会话/Agent | `LocalSessions`(329 方法)、`LocalAgentModeSessions`(115)、`LocalSessionEnvironment`、`LocalSessionPresets`、`SessionPopouts`、`ClaudeCode`、`ClaudeVM`、`EngineSurface` |
| Cowork | `CoworkSpaces`、`CoworkArtifacts`、`CoworkArtifactBridge`、`CoworkMemory`、`CoworkStorage`、`CoworkUserFiles`、`CoworkFilePreview`、`CoworkScheduledTasks`、`CCDScheduledTasks`、`CoworkFeedback` |
| 计算机操作 | `ComputerUseLivePreview`、`ComputerUseTcc`、`CuTeach`、`CuWatchRecordChooser`、`CuWatchRecordPill`、`FramebufferPreview` |
| 扩展 | `MCP`、`Skills`、`Extensions`、`CustomPlugins`、`LocalPlugins`、`PluginBridgeMcp`、`Custom3pSetup`、`Custom3pHelperRun`、`Custom3pUsage` |
| 浏览器 | `ChromeExtension`、`BrowserNavigation`、`SableOtterHud` |
| 窗口/界面 | `WindowControl`、`WindowLayout`、`WindowState`、`MainWindowTitleBar`、`FindInPage`、`FindInPageProvider`、`QuickEntry`、`QuickWindow`、`MenuEvents`、`Toast`、`DeepLink` |
| 文件/数据 | `FileSystem`、`FilePickers`、`OsEntryPlaces`、`OsOpenHandlers`、`DocumentFunnel`、`DeviceStorage`、`DeviceRegistry`、`HistoryImport`、`ClaudeAiImport`、`CliSessionImport` |
| 账号/配置 | `Auth`、`Account`、`AppConfig`、`AppFeatures`、`AppPreferences`、`ManagedConfig`、`PlanUsage`、`DesktopInfo`、`DesktopIntl` |
| 系统集成 | `GlobalShortcut`、`DesktopNotifications`、`AutoUpdater`、`Startup`、`SupportBundle`、`Resources`、`PrintCallReporter`、`RendererMemoryReporter`、`ContentStampReporter` |
| 其它 | `Simulator`(54)、`Launch`(88)、`GrandPrix`、`ViolinFret`、`Gorse`、`ForgeState`、`GitState`、`Dictation`、`RemoteControlServing`、`CloudMove`、`WebBuild`、`OfficeAddinFiles`、`SableOtterHud` |

### 5.4 网络端点（真实字符串，含 staging 与下载源）

| 类别 | 端点 |
|---|---|
| API | `https://api.anthropic.com`、`https://api-staging.anthropic.com` |
| 产品前端 | `https://claude.ai`、`https://claude.com`、`https://preview.claude.ai`、`https://preview.claude.com`、`https://claude.com/cai/` |
| Staging | `https://claude-ai.staging.ant.dev`、`https://preview.claude-ai.staging.ant.dev`、`https://beacon.claude-ai.staging.ant.dev` |
| **下载源** | `https://downloads.claude.ai/vms/linux/`（VM 镜像）、`https://downloads.claude.ai/model-catalog/v1/catalog.json`、`.../schema.json`、`https://downloads.claude.ai/claude-code-releases`、`https://downloads.claude.ai/claude-ssh-releases` |
| MCP | `https://microsoft365.mcp.claude.com/mcp` |
| OAuth | `https://claude.ai/desktop/callback`、`https://claude.com/cai/oauth/authorize`、`https://api.anthropic.com/api/oauth/claude_cli/create_api_key`、`.../roles` |
| 第三方 | `api.github.com`(+graphql, /user)、`accounts.google.com`(OAuth2)、`api.box.com` |
| CDN（artifact 运行库） | `cdn.jsdelivr.net`（chart.js 4.5.0 / gridjs 5.0.2 / mermaid 11.17.2 / us-atlas / world-atlas / tabler-icons）、`cdnjs.cloudflare.com`（d3 7.8.5 / three r128 / topojson 3.0.2 / Chart.js 4.4.1） |
| 遥测 | `sentry.io`（`o1158394.ingest.us.sentry.io`，DSN `2f98127cbffe4740b1f767a2de77d23b`） |
| 企业 | `anthropic.enterprise.slack.com`、`anthropic.slack.com` |

`downloads.claude.ai/vms/linux/` 是 **ClaudeVM 从网络下载 Linux 镜像** 的直接证据，与 `ClaudeVM` 服务的 `download`/`getDownloadStatus`/`startVM` 方法对应。

### 5.5 原生桥与 worker

- `claude-native-binding.node`（3,778,896 B）+ `node-pty` 的 `conpty.node` / `conpty_console_list.node` —— 原生窗口控制与 **ConPTY 终端**。
- 9 个 worker 目录，其中 `pty-host`、`file-index-worker`、`heavy-work-worker`、`transcript-search-worker`、`shell-path-worker`、`stall-sampler-worker`、`msal-broker-worker`、`mcp-runtime/{nodeHost,directMcpHost}`。
- `stall-sampler-worker` 与 `index.pre.js` 的启动 GC 采样结合，说明有**主线程卡顿监控**。

## 6. 未解项（不隐藏）

| 项 | 状态 | 原因 |
|---|---|---|
| 主 chunk 内 59,658 个符号的逐条语义 | 部分 | minify 后大多数为第三方内联代码；第一方语义已通过枚举/RPC 表恢复，但不逐个编造 |
| `.jsc` 编译缓存与源 JS 的对应 | 已登记未解析 | V8 code cache，非独立逻辑；3 个 `.jsc` 对应 `index.chunk-lzaSYO3Q.js` 等，功能等价 |
| `us-atlas`/`datamaps` 等 CDN 引用是否真被使用 | U | 静态字符串存在 ≠ 运行期加载；需 R 级验证 |
| `Simulator`(54)、`Launch`(88) 服务的完整语义 | 部分 | 方法名已全量列出，行为需结合 P4 追踪 |

## 7. 产物

```
index/MODULES.tsv                    437 行（每个 JS/MJS/TS 文件一行）
index/MODULE-CLASSIFICATION.tsv      506 行（ASAR 全部文件，零遗漏）
index/SYMBOLS.tsv                   59,658 行
index/CALL-EDGES.tsv                 3,053 行
index/DYNAMIC-IMPORTS.tsv                1 行
index/STRING-ENUMS.tsv               1,179 行
index/IPC-REGISTRATIONS.tsv          1,609 行
index/CONTEXTBRIDGE-EXPOSURES.tsv       52 行
index/EIPC-SERVICES.tsv                 97 行
index/EIPC-METHODS.tsv               1,170 行
index/EIPC-EVENTS.tsv                  162 行
index/PE-BINARIES.tsv / PE-VERSION-SIGNATURE.json   18 / 9 行
index/SKILL-CONTAINER-LEDGER.tsv       188 行
```

复现：`node scripts/p1_index.js` → `node scripts/p1_ipc_enum.js` → `node scripts/p3_eipc.js` → `node scripts/p1_classify.js`（需 `NODE_PATH` 指向 `tools/node_modules`）。
