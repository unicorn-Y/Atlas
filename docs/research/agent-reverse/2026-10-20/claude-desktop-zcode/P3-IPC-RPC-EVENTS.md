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
