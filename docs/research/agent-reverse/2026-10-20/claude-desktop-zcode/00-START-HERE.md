# 00 — START HERE：Claude Desktop 全量静态解剖

**执行者**：ZCode（DeepSeek V4.1 Flash）  
**日期**：2026-10-20  
**分支**：`research/zcode-claude-desktop-anatomy-20261020`  
**模式**：**纯静态离线逆向**（按任务书 commit `3e2b27b9` 纠偏；不启动、不截图、不登录、不连 API）

---

## 目标样本（固定，可复验）

| 项 | 值 |
|---|---|
| 产品 | Claude Desktop，Windows x64，enterprise / Store 线 |
| 版本 | **2.42304.0**（`AppxManifest Identity Version="2.42304.0.0"`；`claude.exe` FileVersion `2.42304.0`） |
| 包 | `claude-desktop-x64-2bf309665f.msix` |
| 字节 | **297,191,037** |
| SHA256 | `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee` |
| 主 asar | 49,338,428 B，SHA256 `8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db` |
| cowork-svc | 13,761,360 B，SHA256 `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f` |

本地材料根目录：`D:\Atlas\_research\claude-desktop\2026-10-20\`  
离线浏览器：`viewer/index.html`（单文件，双击即用，无需网络）

---

## 一句话结论

Claude Desktop 不是一个"聊天客户端"，而是**一个 Electron 外壳 + 一整套 97 个 RPC 服务的本地代理层 + 一套内置 VM 执行环境 + 一份完整的本地 Web 前端（199.5 MB）**；真正的智能体循环既不在壳里也不全在云上，而是**由壳 spawn 出一个 Claude Code CLI 子进程来跑**。

---

## 五条最重要的发现

### 1. 安装包里藏着完整的 Chat 前端（199.5 MB）

`app/resources/ion-dist/` 有 **4,224 个文件 / 199,562,129 字节**，占 MSIX 条目总数的 **95%**，含 3,554 个 JS、3 个 WASM（8.25 MB / 1.36 MB / 205 KB）、35 MB i18n、3.1 MB 语音音频。

它通过主进程安装的 `app://` 协议提供服务，产物是 `app://localhost`。

**它不是备用资源，而是 3P 部署的主 UI**：

```js
// 标准（1P）
getMainWindowUrl(){ return this.deps.anthropicOriginUrl() }   // https://claude.ai
// 第三方（3P）
getMainWindowUrl(){ return ql }                               // app://localhost
```

由持久化的 `deploymentMode`（只接受 `"3p"` / `"1p"`）决定。详见 `P1B-ION-DIST-CORRECTION.md`。

### 2. IPC 不是裸 `ipcMain`，而是自建 RPC 框架

全应用只有 **2 处** `ipcMain.handle`、**6 处** `ipcMain.on`。真正的接口是 eipc：

```
$eipc_message$<guid>_$_<namespace>_$_<Service>_$_<Method>
```

注册形态 `eo(ns, "Service", senderCheck, {methods:[[name,[[param,Validator]]]], events:[...]})`。

提取结果：**97 个服务 / 1,170 个方法 / 162 个事件 = 1,332 条，全部有可达调用者，0 条未配对**。

### 3. Agent 执行所有权是三层，不是一层

| 层 | 谁执行 | 证据 |
|---|---|---|
| Chat | **云端**（1P）或 **本地 SPA + 网关**（3P） | `getMainWindowUrl()` 两实现 |
| Code / LocalSessions | **本地 CLI 子进程** | `spawn(..., "claude", ..., t.allowedDomains)` |
| Cowork | **本地 Hyper-V VM** 或云端 | `ClaudeVM.startVM` → `cowork-svc.exe handleStartVM` |

### 4. 本地 VM 是「Hyper-V + gVisor 用户态网络栈」

`cowork-svc.exe`（Go 1.25.14，15,181 个函数）的依赖树直接暴露：

```
HCS (CreateComputeSystem / HVSocket)
  + gvisor-tap-vsock + gVisor      ← 用户态 TCP/IP
  + 第一方 win-httpproxy + PAC 脚本
  + 宿主 CA 证书注入（TLS 中间人信任）
  + edrgate / edrpolicy            ← 第三方 EDR 接入
```

### 5. 技能不由 Desktop 执行

Desktop 打包了 6 个 `.skill`（docx/pptx/xlsx/pdf/pdf-reading/frontend-design），但通过环境变量把它们交给 CLI：

```js
CLAUDE_CODE_DISABLE_BUNDLED_SKILLS
CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL
```

全包共 **1,062 个环境变量**（653 个 `CLAUDE_CODE_*`）。

### 补充：主窗口本地部分到底有多少代码

主窗口自身 webContents 在正常路径下渲染 `null`，只承担启动骨架/错误卡片。本地代码约 **1.84 MB**，其中 **1.24 MB 是一个懒加载的彩蛋小游戏**；真正的产品界面对等在兄弟 `WebContentsView`（`W-MAINVIEW`）里。
`mainView.js` 接通 **81 个服务 / 1,127 个方法**（另加 6 个 `WindowManager` 方法 = 1,133），其余 11 个服务是其它窗口的私有面。
详见 `P2-UI-AND-WINDOWS.md` §1.0b–§1.0d 与 `RENDERER-ENTRIES.md`。

---

## 覆盖率（可再计算）

| 对象 | 分子 / 分母 | 状态 |
|---|---|---|
| MSIX 文件登记 | **4,443 / 4,443** | ✅ 100% |
| MSIX 哈希复验 | **4,443 / 4,443**，0 不符 | ✅ |
| ASAR 文件分类 | **506 / 506** | ✅ 100% |
| ASAR 路径登记 | **548 / 548**（506 文件 + 42 目录） | ✅ |
| ASAR JS 解析 | **435 ok / 437**（2 个 `.d.ts` 已解释） | ✅ 99.5%，剩余已解释 |
| 内置 SPA JS 解析 | **3,588 / 3,588**，0 失败 | ✅ 100% |
| Go 函数登记 | **23,018 / 23,018**（4 个二进制） | ✅ 100% |
| PE 二进制 | **18 / 18**（含签名与版本资源） | ✅ |
| 技能内部文件 | **188 / 188**（6 个 ZIP） | ✅ |
| RPC 条目配对 | **1,332 / 1,332** | ✅ 0 未配对 |
| 界面对象 | **26**（12 window / 6 offscreen / 2 popup / 2 dialog / 2 tray / 2 menu） | ✅ 已登记 |
| 菜单 / 快捷键 | 99 / 57 | ✅ |
| 路由 | 64（远程 62 + 本地 2）＋ SPA 内 716 | ✅ |
| Feature flags | 380 条 / 186 唯一键 | ✅ |
| 环境变量 | 1,062 | ✅ |
| Worker | 8 | ✅ |

**未闭合的只有两类**：
1. **服务端实现**（标 `CLOUD-UNAVAILABLE`，物理上不可得）；
2. **压缩代码里逐函数的语义**（3 万多个第三方内联函数，只记录了地址/大小，不逐个编造用途）。

---

## 报告导航

| 文件 | 内容 |
|---|---|
| `01-LAYER-ATLAS.md` | 分层架构地图（包 → OS → Electron → renderer → host → service → VM → tool → cloud） |
| `02-CAPABILITY-CATALOG.md` | 97 个服务的逐项用途说明（中文） |
| `P0-PACKAGE-AUTHENTICITY.md` | 包真实性、哈希、嵌套容器 |
| `P1-STATIC-CODE-INVENTORY.md` | 入口链、506 文件全归类、符号索引 |
| **`P1B-ION-DIST-CORRECTION.md`** | **199.5 MB 内置前端的发现与架构修正（必读）** |
| `P2-UI-AND-WINDOWS.md` | 27 个界面、99 菜单项、58 快捷键、路由 |
| `P3-IPC-RPC-EVENTS.md` | 1,332 条 RPC 全配对、405 个网络端点 |
| `P4-AGENT-RUNTIME.md` | Chat/Cowork/Agent 三层执行、持久化、恢复 |
| `P5-NATIVE-SERVICE-VM.md` | Go 服务 15,181 函数、管道 RPC、VM 依赖架构 |
| `P6-EXTENSIONS-TOOLS-SKILLS.md` | 6 技能、MCP、8 worker、1,062 环境变量、380 flags |
| `P7-STATIC-LIFECYCLE.md` | 启动/任务/退出/恢复的代码级时序 |
| `P7-STATIC-STATE-AND-EVENTS.md` | 状态机（127 个枚举）与事件通道 |
| `13-COVERAGE-AND-ACCEPTANCE.md` | 覆盖率、差集、独立审计结果、验收判定 |
| `SERVICE-RPC.md` | cowork-svc 管道 RPC 的指令级证据（帧格式、分发表、事件名） |
| `VM-LIFECYCLE.md` | HCS/HCN 动态解析与 VM 创建/启动/停止全过程 |
| `SSH-HELPERS.md` | 三个 SSH 辅助程序 |
| `NATIVE-ADDON.md` | `claude-native-binding.node` 的 109 个 napi 导出 |
| `MCP-HOSTS.md` | nodeHost（本地 stdio shim）与 directMcpHost（远程 HTTP/SSE）的分工 |
| `SKILL-SCHEMA.md` | `manifest.json` 的字段语义 |
| `RENDERER-ENTRIES.md` | 6 套 renderer 的逐项解剖 |
| `12-UNKNOWN-AND-BLOCKERS.tsv` | 未解清单（逐条含原因） |
| `PROGRESS.md` | 阶段进度与每轮新增 |
| `viewer/index.html` | 离线浏览器（97 服务可搜索） |
| `out-of-scope/` | 按新规降级的运行取证归档（不计入完成率） |

---

## 状态声明

**STATUS: PARTIAL**

- 静态分解**已完成到文件/函数/注册点粒度**，四类总账齐备，独立审计通过。
- **不是 COMPLETE** 的原因有二，且均可精确定位：
  1. `ion-dist` 的 3,588 个 SPA 文件目前只做了模块级索引（imports/functions/classes/routes），**未逐组件展开 React 树**；
  2. 3 万多个 Go/JS 函数记录了地址与大小，但只对关键链路做了语义解读。
- **没有**使用任何运行证据作为结论依据；`out-of-scope/` 全部不计分。
