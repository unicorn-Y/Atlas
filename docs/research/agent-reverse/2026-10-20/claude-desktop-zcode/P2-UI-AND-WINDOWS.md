# P2 — 前端、全部窗口与交互（纯静态）

> 依据：6 套 renderer bundle、主进程窗口构造点、菜单模板、`ion-dist` 内置 SPA。
> 全部为代码级证据（S）。**无截图、无运行。**

---

## 1. 界面总账：27 个界面对象

| 类型 | 数量 |
|---|---:|
| window（含 BrowserWindow 与 WebContentsView） | 12 |
| offscreen | 6 |
| popup | 2 |
| dialog | 2 |
| tray | 2 |
| menu | 2 |
| **合计** | **26** |

按内容来源：**LOCAL-UI 14 / REMOTE-UI 7 / NATIVE-CHROME 5**。

### 1.1 窗口清单（节选，完整见 `UI-SURFACES.tsv`）

| ID | 类型 | 名称 | 加载内容 | 来源 |
|---|---|---|---|---|
| `W-MAIN` | window | 主窗口外壳（标题栏 + 错误 UI + 启动占位） | `loadFile .vite/renderer/main_window/index.html`，子 `WebContentsView` 加载 claude.ai | NATIVE-CHROME + LOCAL + REMOTE |
| `W-MAINVIEW` | WebContentsView | 主视图 | `loadURL(claude.ai / preview.* / claude.com / app://localhost)` | **REMOTE 或 LOCAL SPA（取决于部署模式）** |
| `W-QUICK` | window | 快速输入条（全局热键） | `quick-window.html` | LOCAL |
| `W-ABOUT` | window | 关于窗口（模态） | `about.html` | LOCAL |
| `W-BUDDY` | window | 硬件 Buddy / Maker 设备 | `buddy.html` | LOCAL |
| `W-DEVICECODE` | window | 设备码登录验证 | `app://localhost/device-code-verify` | LOCAL |
| `W-SETUP3P` | window | 第三方推理配置 | `app://localhost/setup-desktop-3p` | LOCAL |
| `W-DESIGN` | window | Design 表面 | `claude.ai/design...` | REMOTE |
| `W-ARTIFACTPOPUP` | popup | Artifact 弹窗（接管 `window.open` 的 guest） | 由 artifact 主机决定 | REMOTE |
| `W-CODEPOPUP` | popup | Code 子窗口 | `/code` 派生 URL | REMOTE |
| `W-SABLEOTTER-HUD` | offscreen | 语音输入 HUD（460×72，点击穿透） | 运行期写临时 HTML | LOCAL |
| `W-CU-GLOW` / `W-CU-TEACH` | offscreen | 计算机操作高亮/教学覆盖层 | 内联 HTML | LOCAL |
| `W-WATCH-CHOOSER` / `W-WATCH-PILL` | dialog/offscreen | 录屏/技能录制选择器与药丸 | 内联 HTML | LOCAL |
| `W-LOCALEXEC-CONSENT` | dialog | 本地执行同意（连接器 connect/disconnect） | `localExecConsent.html`（**明确无 React、仅 textContent，防注入**） | LOCAL |
| `V-FINDINPAGE` | WebContentsView | 页内查找 | `find-in-page.html` | LOCAL |
| `V-COWORK-ARTIFACT` | WebContentsView | Cowork artifact 视图 | 特权 scheme `cowork-artifact://` | LOCAL |
| `V-COWORK-FILEPREVIEW` | WebContentsView | Cowork 文件预览 | 特权 scheme `cowork-file://` | LOCAL |
| `V-PREVIEW-TABS` | WebContentsView | 内置浏览器标签页（每标签一个视图） | 远程 URL | REMOTE |
| `V-SILENT-AUTH` | offscreen | 静默 IdP 授权（**从不 attach**） | 远程 | REMOTE |
| `V-CHROME-IMPORT` | offscreen | Chrome 导入种子视图（**从不 attach**） | 远程 | REMOTE |
| `M-TRAY` / `M-TRAYMENU` | tray | 托盘图标与右键菜单 | — | NATIVE |
| `M-APP` / `M-CTX` | menu | 应用菜单 / 网页右键菜单 | — | NATIVE |

### 1.2 重要细节（S）

- `W-MAIN` 的注释明确：**"born hidden on login/background launch"**，`close()` 只是隐藏（除非托盘被禁用）—— 这是"关闭窗口但后台继续"的代码根据。
- `W-LOCALEXEC-CONSENT` 的实现刻意 **零依赖、不用 React**，内容经 query 传入并只用 `textContent` 渲染 —— 安全设计，防止被 web-origin renderer 影响。
- `W-SABLEOTTER-HUD` 的 HTML 在**运行期写入临时目录**，说明是动态生成而非打包资源。
- `V-SILENT-AUTH` / `V-CHROME-IMPORT` 是"**never attached**"的离屏视图 —— 只用于跑流程/取数据，永不显示。

## 2. 菜单与快捷键

| 类别 | 条目数 |
|---|---:|
| 应用菜单（File/Edit/View/Go/Help[/Developer]） | 82 |
| 右键上下文菜单 | 13 |
| 托盘菜单 | 4 |
| **快捷键** | **57** |

代表性快捷键（S，含冲突处理）：

| 快捷键 | 动作 | 备注 |
|---|---|---|
| `CmdOrCtrl+N` | New Chat / New Task / New Session（按表面变名） | — |
| `CmdOrCtrl+;` | New Side Chat | `registerAccelerator:false`（不进系统注册） |
| `CmdOrCtrl+,` | Settings | — |
| `Ctrl+Alt+Shift+O` | Open File…（code 表面） | 三键组合避免冲突 |
| `CmdOrCtrl+Shift+O` | Open Folder… | 同上 |
| `CmdOrCtrl+W` | Close Chat/Task/Page/Session/Pane 或 Close Window | 依表面语义 |
| `CmdOrCtrl+Shift+W` | Close Window | **`acceleratorWorksWhenHidden`**（隐藏时也生效） |

## 3. 路由面

`UI-ROUTES.tsv`：64 条路由，其中 **62 条 remote / 2 条 local**。

本地 SPA（`ion-dist`）内部另有 **716 个路由字面量**（`ION-ROUTES.tsv`），例如：
`/new`、`/settings/capabilities`、`/settings/desktop`、`/customize/memory`、`/customize`、`/code`、`/cowork`、`/epitaxy`、`/artifact`、`/hub`、`/scheduled-task`、`/task/new`、`/needs-input`、`/login`、`/logout`、`/sso-callback`、`/magic-link`、`/api/desktop/`、`/api/bootstrap/`、`/mcp-registry/`、`/sandbox/`、`/releases/`。

**这说明**：即使是 1P 模式，客户端的**路由命名空间**也是与本地 SPA 共用的一套；远程与本地是同一应用的两份部署，不是两个产品。

## 4. UI → 状态 → RPC 的链路（S）

每个窗口的 preload 决定它能触及哪些 eipc 命名空间（`IPC-SURFACE-BY-WINDOW.tsv`）：

| 窗口 | 可触及 namespace |
|---|---|
| `mainView.js`（主视图） | `settings`、`simulator`、`skills`、`officeAddin`、`engineSurface`、`hybrid`、`web`、`buddy`、`telemetry` |
| `mainWindow.js` / `aboutWindow.js` / `quickWindow.js` | `internal.ui`、`hybrid` |
| `buddy.js` | `buddy`、`hybrid` |
| `coworkArtifact.js` | `coworkArtifact` |
| `computerUseTeach.js` | `internal.computerUse`、`internal.sableOtter` |
| `computerUseWatchRecord.js` / `watchRecordChooser.js` | `internal.computerUse` |
| `findInPage.js` | `internal.findInPage`、`hybrid` |
| `localExecConsent.js` | `internal.localExecConsent` |
| `designWindow.js` | `designPdf` |
| `claudePagePreview.js` | 独立 world `claudeDesktopArtifactPane` |

三步链路（以"打开设置"为例）：

```
菜单项 accelerator CmdOrCtrl+,
  → 主进程 menu click handler
  → ipcMain.handle(Za.RequestOpenMcpSettings) / 或 nav RPC
  → new URL(`/${Dl.Settings}/connectors`, pO())   ← pO() 返回 getMainWindowUrl()
  → mainView.webContents.loadURL(...)
```

注意 `pO()` 就是 P1B 中的 `getMainWindowUrl()`：**同一段导航代码在 1P/3P 下会分别打到 claude.ai 或 app://localhost**。

## 5. 本地 SPA 的 UI 结构（新增，来自 `ION-*` 索引）

`ion-dist` 内 3,588 个 JS 全部解析成功，含：
- `assets/v1/frame-shell*.js` —— **Artifact 沙箱外壳**（`frame-shell.html` 标题为 `Artifact`），配套 `_frame-rt/_runtime/artifact.*.js`；
- `assets/highlightWorker-*.js`（1.58 MB）—— 代码高亮 worker；
- 25 个 CSS（最大 1.79 MB）、3 个 WASM（8.25 MB / 1.36 MB / 205 KB）；
- `i18n/` 35 MB。

SPA 与外壳的通信不经过 eipc，而是：
- 靠 **UA 识别**：主进程把 `claude/<version>` 追加进 UA，SPA 用 `/claude(nest|gov)?\/[^ ]/i` 与 `window.claudeAppBindings` 判断是否在桌面内；
- 通过 `window.claudeAppBindings`、`window.claudeDesktopArtifactPane`、`window.__frameSessionId`、`window.__framePregrant` 等注入的全局对象。

## 6. 未闭合项（明确计数）

| 项 | 数量/状态 |
|---|---|
| 已登记界面 | 26 |
| 已登记菜单项 | 99（82+13+4） |
| 已登记快捷键 | 57 |
| 本地 SPA 路由 | 716 |
| 远程路由 | 62 |
| **UI→执行链未闭合** | **远程 UI 部分不可静态闭合（UI 代码在服务端）；本地 SPA 部分已定位入口但未逐组件展开** |

## 7. 产物

```
index/work-P2/UI-SURFACES.tsv         26 行（含文件+字节偏移锚点）
index/work-P2/UI-ACTIONS.tsv          29 行
index/work-P2/MENUS.tsv               99 行
index/work-P2/HOTKEYS.tsv             57 行
index/work-P2/UI-ROUTES.tsv           64 行
index/work-P2/IPC-SURFACE-BY-WINDOW.tsv  20 行
index/ION-MODULES.tsv              3,588 行
index/ION-ROUTES.tsv                 716 行
index/ION-WASM.tsv                     3 行
```
