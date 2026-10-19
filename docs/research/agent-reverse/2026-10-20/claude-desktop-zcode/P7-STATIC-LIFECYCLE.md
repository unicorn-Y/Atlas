# P7（静态版）— 从代码还原启动 / 任务 / 退出 / 恢复时序

> 依任务书修订（commit `3e2b27b9`）：**不启动、不截图、不登录、不连 API**。  
> 本文件全部结论来自 ASAR 内 bundle、`AppxManifest.xml`、Go pclntab、renderer HTML。  
> 证据等级：`S` = 源码/二进制锚点；`I` = 由代码结构推断；`U` = 无法从静态确定。**本文件不含 R 级结论。**

---

## 1. 启动时序（主进程，S）

从 `index.chunk-lzaSYO3Q.js` 与 `index.pre.js` 恢复的真实顺序：

```
1. claude.exe (Electron) 载入  ── AppxManifest: Application Id="Claude" Executable="app\Claude.exe"
2. 载入 app.asar/package.json → main = .vite/build/index.pre.js
3. index.pre.js 顶部：
   - Sentry SENTRY_RELEASE 注入 + _sentryDebugIds
   - globalThis.__claudeMainJsStartMs = Math.round(process.uptime()*1e3)   ← 启动计时起点
   - V8 GCProfiler 启动，180s 后自动 stop（变量 ce = 18e4）
4. require 主 bundle（index.js → 356 个 chunk）
5. 单实例锁：
     if (!e && !O6a && app.requestSingleInstanceLock()) { app.quit(); }
     else { E6a.onPrimaryInstance(), Bqa(), Hu(() => void Bqa()) }
   - 前置分支：超长 deep-link argv 时先 app.relaunch({args:[...e, mIa]}) 再 app.exit(0)
6. app.on("second-instance", (t,n,r) => { if (TA()) return; Dq(); if (e(n,r)) {...} })
     → 第二实例被抑制（"second-instance: suppressing duplicate..."），并交给深链处理器
7. app.whenReady() → 34 个注册点的总入口
8. 窗口创建 → 主窗口加载本地 index.html（标题栏/错误页），再由其导航到 claude.ai
9. app.setAppUserModelId(`${e}!Claude`)   ← Windows 任务栏/通知身份
10. 生命周期钩子：ready / browser-window-created / web-contents-created /
    browser-window-focus / browser-window-blur / before-quit / will-quit /
    window-all-closed / render-process-gone / select-client-certificate
```

### 1.1 关键钩子语义（S）

| 钩子 | 代码行为 |
|---|---|
| `window-all-closed` | 调用 `HAn()`，**不是**直接 quit |
| `before-quit` | 被拦截器接管：若 handler 尚未执行则 `preventDefault()` 并执行清理 `XAn()`，完成后才放行 |
| `before-quit-for-update` | `bA = true`，随后进入更新重启 |
| `will-quit` | 两个独立监听：一个清理定时器并关闭 `BMr` 列表里的窗口；另一个触发 `willQuit` 生命周期 |
| `second-instance` | 去重 + 深链转发 |
| `render-process-gone` | 三处独立监听（不同窗口各自恢复策略） |
| `session-end`（Windows） | 收到 Windows 会话结束事件时 `wA()` 退出 |

### 1.2 启动命名阶段（S，来自代码里的 stage 名）

`webcontentsview-cleanup`、`before-quit interceptor`、`Chrome Extension MCP: Skipping native host setup: local MCP is disabled by managed config` 等字符串说明启动被拆成**具名阶段**，每阶段可失败并记录原因。

## 2. 窗口生命周期（S）

- 6 套 renderer（`main_window` / `quick_window` / `buddy_window` / `about_window` / `find_in_page` / `local_exec_consent`）+ 运行期动态窗口（artifact、file preview、watch-record chooser、pdf）。
- 主窗口内容分两段：本地 `index.html` 提供标题栏与错误 UI，正文由 `loadURL` 指向远程站点（源码注释明确）。
- `webcontentsview-cleanup` 阶段会在退出前关闭 `V`（主 webContents）与 `no`（第二 webContents），并判 `isDestroyed()`。

## 3. 任务（Agent/Cowork）生命周期（S，方法名级）

### 3.1 本地 Code 会话

```
LocalSessions.start(info)
   → warmSession(sessionId)            预热
   → sendMessage(17 参数)              输入
   → 子进程: spawn(..., "claude", ..., t.allowedDomains)   执行体
   → setPermissionMode / setModel / setEffort / setFastMode
   → getContextUsage / getContextUsageSummary              观测
   → forkSession / detachFromParent                        分叉
   → interruptSideChat / stopSideChat                      侧线路
   → canAutoResume → retryStart → confirmImportedSessionResume   恢复
   → restartRemoteSession / restartRemoteHelper / reinstallRemoteClaudeCode   冷恢复
```

### 3.2 Cowork（本地 VM 路径）

```
ClaudeVM.download            → downloads.claude.ai/vms/linux/     (S: 字符串)
ClaudeVM.getDownloadStatus
ClaudeVM.checkVirtualMachinePlatform
ClaudeVM.enableVirtualMachinePlatform
ClaudeVM.restartAfterVMPInstall
ClaudeVM.startVM(options)    → cowork-svc.exe handleStartVM
   └─ vm.CreateComputeSystem → (*HCSSystem).Start        (S: pclntab)
   └─ vm.NewHVSocketListener / (*HVSocketConn)           (S: pclntab)
   └─ vm.mountSharesInGuest                              (S: pclntab)
   └─ vm.installHostCACertificates / LoadTrustedCACertificates
   └─ vm.fetchPACScript / (*proxyAttempts)
ClaudeVM.getRunningStatus    → handleIsRunning
ClaudeVM.restartVM           → handleStopVM + handleStartVM
ClaudeVM.setForceDisableHostLoop(value)
ClaudeVM.isHostLoopModeEnabled / isHostLoopDevOverrideActive
```

### 3.3 调度

```
wake-scheduler: registered claim id="scheduled-tasks"    (S: 日志字符串 + RPC 服务)
CoworkScheduledTasks (16 方法) + CCDScheduledTasks (12 方法) + WakeScheduler 服务
```

`WakeScheduler` 是**唤醒调度器**（系统休眠/唤醒后补跑），与 `WarmLifecycle`（隐藏时预热）配合。

## 4. 退出与恢复（S）

| 路径 | 代码锚点 | 语义 |
|---|---|---|
| 正常退出 | `before-quit` 拦截器 → 清理 → 放行 | 保证 handler 至少跑一次 |
| 更新重启 | `before-quit-for-update` → `bA=true` | 更新专用路径 |
| 会话结束 | `session-end`（Windows）→ `wA()` | 系统关机/注销 |
| 所有窗口关闭 | `window-all-closed` → `HAn()` | 不直接退出（可能驻留托盘） |
| 崩溃 | `render-process-gone` ×3 监听 | 分窗口恢复策略 |
| 单实例冲突 | `requestSingleInstanceLock` 失败 → `app.quit()` | 只保留一个 |
| 深链过长 | `app.relaunch({args:[...e, mIa]})` + `app.exit(0)` | 重启自身以携带上限内参数 |

**恢复语义四分层**（与 P4 一致，全部 S）：`confirmImportedSessionResume`（历史导入）、`canAutoResume`/`retryStart`（进程内）、`restartRemoteSession`/`restartRemoteHelper`（跨进程冷启）、`RemoteControlServing`/`CloudMove`（云端）。

## 5. Worker 生命周期（S）

9 个 worker 目录各自有独立入口：`file-index-worker`、`heavy-work-worker`（含 `dist-*.js` + rolldown runtime）、`transcript-search-worker`、`shell-path-worker`、`stall-sampler-worker`、`msal-broker-worker`、`pty-host`、`mcp-runtime/{nodeHost,directMcpHost}`。

`pty-host` 配套 `node-pty` 的 `conpty.node` / `conpty_console_list.node`，说明终端能力跑在独立进程并通过 ConPTY 通信。

## 6. 无法从静态断言的部分（U，逐条列明）

| 项 | 为什么静态无法确定 | 需要的条件 |
|---|---|---|
| 各阶段的真实耗时/顺序抖动 | 并发 Promise 的实际调度顺序 | 动态（已按新规不做） |
| `claude` 子进程的具体 CLI 参数全集 | 参数经 `spawn(i,a,"claude",e,void 0,f,u,!1,t.allowedDomains,!0)` 传递，`e` 的内容在运行期组装 | 需读 CLI 源码（不在本包内） |
| VM 启动失败的回滚粒度 | `CleanupStaleVMs` 存在，但回滚分支的具体触发条件需指令级追踪 | 更深反汇编 |
| 云端 agent loop 内部 | 服务端不可得 | `CLOUD-UNAVAILABLE` |
| MCP 服务器的实际握手 | 握手在运行期 | 已按新规不做 |
| `handleEvent` 事件名全集 | 事件名由枚举常量生成，需定位数据段 | 继续静态（见 UNRESOLVED-CALL-EDGES） |

## 7. 与上一篇（OUT-OF-SCOPE）的关系

`out-of-scope/P7-RUNTIME-EVIDENCE.md` 记录了此前启动观察得到的日志。按新规：

- **它不计入完成率**；
- 但它与本文的静态结论**互相印证**（例如"主 UI 由 claude.ai 加载"在源码注释与日志中同时成立）；
- 正文所有结论均以静态锚点为准，不依赖该文件。
