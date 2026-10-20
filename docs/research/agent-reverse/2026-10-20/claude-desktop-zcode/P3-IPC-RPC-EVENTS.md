# P3 — IPC / RPC / HTTP / 事件逐条配对

> 旧账的最大缺口：`ipc-map.tsv` 只有 8 行，而解析器声称 1,535 条 IPC 操作。本轮把口径彻底拆开，给出**可核对的分子分母**。

---

## 1. 为什么旧账只有 8 行（根因）

Claude Desktop **不是**裸用 Electron IPC。它使用自建的 **eipc RPC 框架**，把所有 97 个服务复用在**同一个 Electron channel** 上：

```
$eipc_message$_6010a08f-a0fa-48b4-99da-0689b9e2de7b_$_claude.web_$_
$eipc_message$_6010a08f-a0fa-48b4-99da-0689b9e2de7b_$_claude.settings_$_
$eipc_message$_6010a08f-a0fa-48b4-99da-0689b9e2de7b_$_claude.simulator_$_
...
```

真正的"方法"是 channel 之后拼接的 `Service_$_Method`。因此：

- 按 **Electron channel** 统计 → 只有十几个 channel（旧工具只能看到 8 行）。
- 按 **实际 RPC 调用** 统计 → 1,332 条。

旧解析器报告的 1,535 条与此 1,332 条的差异，来自它把 `webContents.on/once` 等非 IPC 事件也算进去了（本轮单独分出 60 条 `WEBCONTENTS-EVENTS.tsv`）。

## 2. 传输层统计（原始计数，可复核）

| API | 出现次数 |
|---|---:|
| `ipcRenderer.invoke` | 1,272 |
| `ipcRenderer.on` | 231 |
| `webContents.on` | 47 |
| `ipcRenderer.sendSync` | 24 |
| `webContents.once` | 13 |
| `webContents.send` | 6 |
| `ipcMain.on` | 6 |
| `ipcRenderer.send` | 4 |
| `webContents.postMessage` | 2 |
| `ipcMain.handle` | 2 |
| `ipcRenderer.removeAllListeners` | 1 |
| `ipcMain.removeHandler` | 1 |
| **合计** | **1,609** |

`contextBridge.exposeInMainWorld`：**52 处**，其中 42 处 world key 为字面量，10 处为变量（可追溯到同一组 preload 模板）。

**关键事实**：`ipcMain.handle` 只有 **2 处**、`ipcMain.on` 只有 **6 处**。这说明**不存在 1,272 个对应的 `ipcMain` handler** —— 那 1,272 个 `invoke` 全部打到 eipc 框架的单一 dispatcher 上，由框架按方法名路由。

## 3. eipc 服务定义（这是真正的 handler 注册表）

注册形态（真实代码）：

```js
var NS = "$eipc_message$<guid>_$_<namespace>_$_";
eo(NS, "ServiceName", senderCheckFn, {
  methods: [["getAllArtifacts", []], ["getArtifactMetadata", [["artifactId", V]]], ...],
  events:  [["render", V], ...],
  stores:  [...]
})
```

- `senderCheckFn` 是 origin 校验，例如 `e=>e.senderFrame?.parent===null`、`e=>{...new URL(e.senderFrame.url)... origin==="null"||origin===<app>}`。
- `methods` 的第二项是参数表 `[[paramName, Validator], ...]` —— 这就是 **RPC schema**。

提取结果：

| 表 | 数量 |
|---|---:|
| 服务 | **97** |
| 方法 | **1,170** |
| 事件 | **162** |
| **RPC 条目合计** | **1,332** |

## 4. 配对结果

| 口径 | 数字 |
|---|---:|
| RPC 条目（方法+事件） | 1,332 |
| **已配对（有命名空间且 preload 可达）** | **1,332** |
| 未配对 | **0** |
| 无 namespace 的孤岛服务 | **0** |

配对依据：每个服务的 namespace（如 `claude.web`、`claude.settings`）都能在至少一个 preload bundle 中找到对应的 `_claude.<ns>_$_` 字符串，且该服务的方法名能在 preload 中被引用。

| preload | 可触及的 namespace |
|---|---|
| `mainView.js` | settings, simulator, skills, officeAddin, engineSurface, hybrid, web, buddy, telemetry |
| `mainWindow.js` | internal.ui, hybrid |
| `aboutWindow.js` | internal.ui, hybrid |
| `quickWindow.js` | internal.ui, hybrid |
| `buddy.js` | buddy, hybrid |
| `coworkArtifact.js` | coworkArtifact |
| `computerUseTeach.js` | internal.computerUse, internal.sableOtter |
| `computerUseWatchRecord.js` | internal.computerUse |
| `watchRecordChooser.js` | internal.computerUse |
| `findInPage.js` | internal.findInPage, hybrid |
| `localExecConsent.js` | internal.localExecConsent |
| `designWindow.js` | designPdf |
| `claudePagePreview.js` | （无 namespace 字符串，仅 `claudeDesktopArtifactPane` 独立 world） |

## 5. 必须重新查的已知样例（本轮结论）

| 样例 | 结论 | 证据 |
|---|---|---|
| `CoworkArtifactBridge.callMcpTool` | **存在**，属 `CoworkArtifactBridge` 服务，namespace `claude.coworkArtifact` | `EIPC-METHODS.tsv` |
| `askClaude` | 同上 | 同上 |
| `runScheduledTask` | 同上 | 同上 |
| `navigateHost` | 同上 | 同上 |
| `openExternalUrl` | 同上 | 同上 |
| MCP setup | `MCP.setMcpServerConfigs / getMcpServersConfig / getMcpServersConfigWithStatus / revealConfig / revealLogs / revealServerLog / isLocalDevMcpEnabled` | `MCP` 服务 7 方法 |
| scheduler | `CoworkScheduledTasks`(16 方法) + `CCDScheduledTasks`(12) + `WakeScheduler` | 三个服务并存 |
| ComputerUseLivePreview | 服务存在，含 `methods,stores`；配套 `FramebufferPreview`、`CuWatchRecordPill` | `EIPC-SERVICES.tsv` |
| ClaudeVM | 12 方法，见 P4 §3 | `EIPC-METHODS.tsv` |

## 6. 事件生产者/消费者

`EIPC-EVENTS.tsv` 共 162 条，按服务分布前列：

| 服务 | 事件数 |
|---|---:|
| LocalSessions | —（以方法为主） |
| WindowState / WindowLayout | 有 stores+events |
| Launch | stores+events |
| Simulator | stores+events |
| ClaudeVM | stores+events |
| MenuEvents / Navigation / DeepLink / Toast | 纯事件服务 |

`DeepLink`、`Navigation`、`Toast` 三个服务**只有 events 没有 methods** —— 说明它们是纯推送面（主进程 → 渲染进程）。

## 7. 网络端点

`NETWORK-ENDPOINTS.tsv`：**405 个唯一 URL**。

| 类别 | 数量 | 说明 |
|---|---:|---|
| first-party-web | 44 | claude.ai / claude.com / preview.* / staging |
| first-party-api | 18 | api.anthropic.com、assets-proxy、OAuth 端点 |
| first-party-download | — | `downloads.claude.ai/vms/linux/`、model-catalog、claude-code-releases、claude-ssh-releases |
| telemetry | 1 | Sentry DSN |
| third-party-github | 70 | GitHub API / 文档 / 插件源 |
| third-party-google | 15 | OAuth、Chrome Web Store |
| third-party-ms | 23 | MSAL / Entra / Office |
| third-party-slack | 1 | anthropic.slack.com |
| third-party-box | 2 | api.box.com |
| cdn | 16 | jsDelivr / cdnjs（artifact 运行库） |
| placeholder | 49 | `example.com`、`*.invalid`、`127.0.0.1` 等测试桩 |
| other | 166 | 多为 schema 命名空间（json-schema.org 38、w3.org 13、chevrotain.io 17） |

**两个值得注意的真实主机**：
- `vpce-0123-abcd.bedrock-runtime.us-east-1.vpce.amazonaws.com` —— Bedrock **VPC Endpoint** 模板，证实企业版支持私有网络直连 Bedrock。
- `sts.windows.net` —— Azure AD token 端点，对应 `entraClientId`/`entraScope` flag。

## 8. 未解项

| 项 | 状态 | 原因 |
|---|---|---|
| eipc dispatcher 的具体实现体 | 部分 | 找到了注册与调用两端，但 dispatcher 内部（如何解析 `Service_$_Method`、如何做 validator 校验、超时策略）尚未逐行展开 |
| `$store$_getState` / `update<X>Store` 的双向同步语义 | 部分 | 已知是 store 镜像（`getDispatcher(e).for(...).setImplementation`），未做时序验证 |
| 162 条事件的运行期实际触发顺序 | U | 需 R 级 |
| `Simulator` / `Launch` / `GrandPrix` 的业务含义 | U | 方法名已全列，语义待 P6/P4 交叉 |

## 9. 产物

```
index/IPC-REGISTRATIONS.tsv      1,609  传输层原始注册点
index/IPC-REGISTRY.tsv           1,232  按 Electron channel 配对（3 闭合 / 1,229 未闭合 → 已解释）
index/UNPAIRED-CALLS.tsv         1,229  上表未闭合明细（根因=单 channel 多路复用）
index/EIPC-SERVICES.tsv             97  服务定义
index/EIPC-METHODS.tsv           1,170  方法 + 参数 schema
index/EIPC-EVENTS.tsv              162  事件
index/RPC-REGISTRY.tsv           1,332  方法级最终配对（1,332 配对 / 0 未配对）
index/CONTEXTBRIDGE-EXPOSURES.tsv   52  contextBridge 暴露
index/WEBCONTENTS-EVENTS.tsv        60  非 IPC 的 webContents 事件
index/NETWORK-ENDPOINTS.tsv        405  唯一 URL 及分类
```

---

## 11. Browser Bridge 与 Chrome Native Host 的完整参数（解决 U-028 的协议部分）

在 `index.chunk-CxUAVDxD.js` 中找到了 bridge 的**全部常量**：

```js
var o = "CLAUDE_BROWSER_BRIDGE",        // 环境变量名
    s = "claude-browser-shim.js",       // shim 文件名
    c = "ccd-br-shim",                  // 前缀
    l = "ccd-br-",                      // 前缀
    u = /^ccd-br-[A-Za-z0-9]{6}$/,      // 会话 id 形状
    d = "b.sock",                       // socket 文件名
    f = 8192,                           // 请求行上限 = 8 KiB
    p = 3e3,                            // 应答超时 = 3 秒
    m = 2e3,                            // 次级超时 = 2 秒
    h = 32,                             // maxConnections = 32
    g = 15e3,                           // 陈旧目录阈值 = 15 秒
    _ = 1e3,                            // 1 秒
    v = /^[0-9a-f]{64}$/                // 64 hex = key 形状
```

这与 `claude-browser-shim.js` 里声明的常量**完全一致**：

```js
const REPLY_TIMEOUT_MS = 3000;      // ← p = 3e3
const MAX_REQUEST_BYTES = 8 * 1024; // ← f = 8192
const MAX_REPLY_BYTES = 1024;
const OPENER_SETTLE_MS = 3000;
```

**两条独立证据互相印证**（主进程常量 与 shim 源码常量）。

### 11.1 socket 路径与安全校验

```js
function xMr(){ return `claude-mcp-browser-bridge-${bMr() ?? Crt() ?? process.env.USER ?? process.env.USERNAME ?? "default"}` }
function SMr(){ return `\.\pipe\${xMr()}` }
```

即 Windows 上是 `\.\pipe\claude-mcp-browser-bridge-<user>`；Linux/macOS 上是
`<dir>/claude-mcp-browser-bridge-<user>/b.sock`。

**目录安全校验**（`validateSocketSecurity`）：

```js
if (platform() === "win32" || this.context.connectVerified) return true;
let dir = dirname(path);
if (dirname(dir).startsWith("claude-mcp-browser-bridge-")) {
  if ((await lstat(dir)).isSymbolicLink())
    throw Error(`Socket directory is a symlink: ${dir}. Directory may have been tampered with.`);
  ...
}
```

**明确拒绝符号链接的 socket 目录** —— 防本地提权劫持。

### 11.2 Chrome Native Host 的注册信息

```js
var V4n = "dihbgbndebgnbjfmelmegjepbnkhlgni",   // 扩展 ID（第三个）
    H4n = "fcoeoabgfenejglbffodgkkbkcdhcgfn",   // 扩展 ID（主）
    U4n = "dngcpimnedloihjnnfngkgjoidhnaolf",   // 扩展 ID（Nest）
    W4n = "com.anthropic.claude_browser_extension",
    G4n = "chrome-native-host.exe",
    XI  = "com.anthropic.claude_browser_extension.json",
    K4n = "ChromeNativeHost",
    q4n = "SOFTWARE\Google\Chrome\Extensions";
```

三个扩展 ID 与 AppxManifest 里虚拟化排除的两个 ID 一致（`fcoeoabgfenejglbffodgkkbkcdhcgfn`、`dngcpimnedloihjnnfngkgjoidhnaolf`），
第三个 `dihbgbndebgnbjfmelmegjepbnkhlgni` 是新发现的（可能是开发版或企业版扩展）。

### 11.3 结论

| 项 | 状态 |
|---|---|
| bridge 协议常量 | **全部确定**（8 KiB 请求 / 3 秒超时 / 32 连接 / b.sock） |
| socket 命名规则 | 确定（`claude-mcp-browser-bridge-<user>`） |
| 安全校验 | 确定（拒符号链接目录） |
| Chrome 扩展 ID | 3 个，其中 2 个与 manifest 一致 |
| `chrome-native-host.exe` 内部的帧前缀宽度 | **仍未定**（Rust 二进制内无源码） |

**`U-028` 从"完全未知"推进到"协议参数全知、仅剩 Rust 内部实现细节"。**
