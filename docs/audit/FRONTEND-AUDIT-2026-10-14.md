# Atlas 前端审查与 ZCode 对标报告

- 审查日期：2026-10-14
- 审查范围：`D:\Atlas\frontend`（222 个源文件，218 个 .ts/.tsx）
- 对标基准：ZCode 桌面端 v3.15.3（Electron 44.7.0，商业级 AI agent 桌面产品）
- 实测：`vitest run` 28 文件 / 192 用例全绿（3.37s）
- 抽查复核：本报告全部关键论断已用独立命令二次验证，见文末「抽查复核记录」

---

## 零、总体判断

**这个前端不是「烂工程」。** 基础工程素养明显高于一般 AI 产品：

- 主进程做了 sender 校验、webview 加固、token 注入隔离、优雅关闭、启动进度广播
- 渲染层做了事件合流（80ms/12.5Hz）、虚拟列表、消息分页 + LRU（10 条）、运行事件有界化（800 条）
- preload 是教科书式的：61 行，只有一次 `contextBridge.exposeInMainWorld`，零业务逻辑
- 安全三件套配齐：`contextIsolation:true` / `nodeIntegration:false` / `sandbox:true`
- 依赖版本控制严格：electron 锁死精确版本 `44.7.0`（无 `^`），配合 `allowScripts` 白名单

**真正的短板集中在几个系统性缺口上**：有的是「安全纵深缺一层」，有的是「内存无界」，还有的是「零错误边界」。这些在线上一跑就会变成用户侧白屏。

---

## 一、最严重的 8 个问题

### 1. 渲染进程完全没有 CSP —— 攻击面放大到可任意外发数据

**证据（已抽查复核）**
- `index.html` 全文 17 行，`grep -c "Content-Security-Policy"` = **0**
- `src/main/electron.ts` 全文 651 行，`grep -c "onHeadersReceived"` = **0**
- 唯一存在 CSP 的地方是 `src/renderer/components/message-actions/CodeBlock.tsx:242` 给 SVG 预览 iframe 用的内联 CSP

**为什么严重**
这是 Electron 安全基线的第一条。当前三件套配对了，所以不构成 RCE；但**没有 CSP 意味着 XSS 一旦成立，攻击面直接放大到「可任意外发数据 + 可任意加载远程脚本」**。而这个应用的输入源恰恰是最危险的：LLM 输出、工作区文件内容、远程网页（webview 里抓的 `outerHTML` 会回流成 `PickedElement.html`）。

**怎么修**
在 `app.whenReady()` 里加 header 注入：

```ts
session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
  callback({ responseHeaders: { ...details.responseHeaders,
    'Content-Security-Policy': ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*; frame-src 'self' blob:; object-src 'none'; base-uri 'none'"] }});
});
```

注意：
- `connect-src` 必须含 `http://127.0.0.1:*` / `ws://127.0.0.1:*`，否则打断后端和 WebSocket
- Tailwind v4 生产构建能否去掉 `unsafe-inline` **未验证**
- dev 模式（Vite HMR 用 inline script/eval）几乎肯定需要另一套策略，**未验证但必踩**

---

### 2. 没有任何 React 错误边界 —— 一个组件抛错 = 整窗白屏

**证据（已抽查复核）**
- `grep -rln "ErrorBoundary|componentDidCatch|getDerivedStateFromError" src/` → **0 个匹配**
- `src/renderer/main.tsx:13-15` 直接 `createRoot(...).render(<React.StrictMode><App /></React.StrictMode>)`
- `src/main/electron.ts:412-415`：`render-process-gone` 里 `win.webContents.reload()` —— **无条件 reload**
- `App.tsx` 单文件 **1496 行**、**43 个 useState**、**31 个 useEffect**、**15 个 useRef**，全部状态提升到这一个组件

**为什么严重**
`render-process-gone` 只处理「渲染进程整体崩溃」。React 抛错导致的**渲染树卸载**不会触发它，用户看到的是纯白窗口且无任何提示——这是最典型的「看起来完成、实际不可用」。以 1496 行 × 43 个 state 的规模，`undefined` 解构抛出是迟早的事。而 `did-fail-load` 重试只覆盖「加载失败」，不覆盖「加载成功后 JS 崩了」。

更糟的是：无条件 reload 会把「崩溃-重载循环」变成闪屏循环，把用户锁死。

**怎么修**
1. `main.tsx` 包一层 ErrorBoundary，fallback 提供「重新加载 / 复制错误 / 打开日志」三个出口
2. `render-process-gone` 加崩溃计数，短时间连续崩溃不再无限 reload
3. 中期把 App.tsx 按 view 拆路由，每个 view 各自有边界

---

### 3. `runs` / `artifacts` / `answers` 只增不减 —— `removeRun` 定义了但从未调用

**证据（已抽查复核）**
```
grep -rn "removeRun" src/
→ useAtlasStore.ts:139  (类型定义)
→ useAtlasStore.ts:666  (实现)
```
**只有定义，没有任何调用者。**

- 只增：`useAtlasStore.ts:595-596` `runs: [...state.runs, run]`
- `artifacts` 只在 `removeRun` 内部和 `appendEvent:615` 写入 → 随运行次数无限累积
- `answers` 只在 `:699 / :705 / :716` 追加，从不清除

**为什么严重**
这是唯一一个**确定性的、无界的内存增长**。每轮对话追加一条完整 `AgentRun`，携带最多 800 条事件（`MAX_RUN_EVENTS = 800`）。单 run 事件有界，但 **run 数量无界**：100 轮长会话 = 100 × ≤800 事件对象全部常驻。

对比：同一文件里对「会话正文」做了 `MESSAGE_CACHE_LIMIT = 10` + LRU，对「事件」做了 800 截断。**偏偏最外层的 run 列表漏了。** 团队知道要有界化，只是这层没做完。

**怎么修**
1. 在 `appendEvent` 的终态分支（`:638`）里，对非当前会话的 run 延迟清理（保留最近 1-2 个），调 `removeRun` —— **函数已经写好了，直接接上即可**
2. `answers` 按 run 维度清理：run 终态时删除该 run 所有 `input.required` / `approval.required` 的 eventId key
3. `store.artifacts` 按 run 上限裁剪

---

### 4. 59 处静默吞异常 —— 关键路径失败用户完全不可见

**证据**
- `useAtlasStore.ts:366` 和 `:424`：`void backend.summarizeConversationBranch(previousId).catch(() => undefined)` —— 分支摘要失败静默，后续上下文丢失用户无从知晓
- `App.tsx:481`：待确认记忆数失败时 `pendingCount` 静默停在旧值 → 用户看到「没有待确认记忆」，实际是请求挂了
- `WorkbenchPage.tsx:44`：`.catch(() => undefined)` —— 会话历史加载失败无声
- `MessageThread.tsx:399`：`catch { /* 列表已卸载，忽略 */ }` —— 把「组件已卸载」和其他异常混为一谈

**为什么严重**
应用整体有**中文错误横幅体系**（`useAtlasStore.ts:281-286` 的 `errorPatch` 做中英双字段，UI 有「详细信息」展开）——设计得相当好。问题是这套体系**只覆盖走 store 的调用**，散落的 `api()` / `backend.xxx()` 直调点全都绕过了它。结果是错误处理「看起来统一，实际只有主干统一」。

**怎么修**
1. 把 `.catch(() => undefined)` 收敛成带最小上报的 helper，逐个替换那 5 处非 localStorage 类
2. `MessageThread.tsx:399` 区分 `AbortError` 与其他错误
3. 给 `services/api.ts:2-15` 的 `api()` 加 `onError` 或接入 `errorPatch`

---

### 5. IPC 契约只在 preload 单向声明，7 处 handler 缺 sender 校验

**证据（已抽查复核）**
- 好的一半：`src/shared/ipc.ts:49-86` 定义 `AtlasDesktopApi`，preload（`index.cts:5-59`）标注 `const desktopApi: AtlasDesktopApi` —— **有静态约束**
- 坏的一半：主进程 channel 名是**独立硬编码字符串**，两边无共享常量。`shared/ipc.ts` 只导出了 `BACKEND_STARTUP_CHANNEL` 一个常量
- sender 校验实测 **8 处**（`electron.ts:466/476/480/487/492/500/519` 等）
- **未校验的 handler（实测）**：
```
electron.ts:525  ipcMain.on('window:minimize', () => windowRef?.minimize());
electron.ts:526  ipcMain.on('window:maximize', ...)
electron.ts:531  ipcMain.on('window:close', () => windowRef?.close());
electron.ts:535  ipcMain.handle('update:check', ...)
electron.ts:536  ipcMain.handle('update:apply', ...)   ← 会 spawn + app.quit()
electron.ts:547  ipcMain.handle('dialog:open-directory', ...)
```

**为什么严重**
`sandbox:true` + `lockDownWebviews()` 已经挡住了 webview（强制独立 partition、删 preload），**webview 里的页面够不到 `window.atlasDesktop`**。

但应用内嵌了多个 `<iframe>`（`FilesPanel.tsx:463/468/492/502`、`BrowserPanel.tsx:562-563`），其中 `FilesPanel.tsx:502` 和 `BrowserPanel.tsx:563` 用的是 `sandbox="allow-scripts"`。**iframe 与父页同源共享 `window.atlasDesktop`** —— 这正是 `assertTrustedAppSender` 存在的理由（它检查 `event.senderFrame !== event.sender.mainFrame`）。

所以 `window:close` / `update:apply` 这类无校验 handler：任何能拿到 iframe 同源执行机会的内容，都能调 `atlasDesktop.close()` 关窗口，或在 source 模式下触发 `update:apply`（拉代码 + 重建 + 退出）。

**攻击前提是 iframe 内同源脚本执行，而「无 CSP」+ `allow-scripts` 恰好提供了这个前提 —— 问题 1 和问题 5 叠加才是完整攻击链。**

**怎么修**
1. `shared/ipc.ts` 加 `export const IPC = {...} as const` 集中所有 channel 名
2. 给 `window:*`、`update:*`、`dialog:open-directory` 补 `assertTrustedAppSender(event)`
3. 用一张 channel→handler 表在 dev 下断言「每个注册的 channel 都过了校验」，防回归

---

### 6. `busy` / `paused` 是全局单值 —— 多会话并发时状态串线

**证据（已抽查复核）**
```ts
// useAtlasStore.ts:623
return { runs, artifacts, pendingSteers, busy: runs.some((run) => !terminal.has(run.status)), ... };
```
- `activeRunFor(conversationId)` 本身是按会话过滤的（`:1124-1126`，对的）
- 但全局 `busy` 是**跨所有会话的聚合**，UI 多处直接用：`App.tsx:279`、`App.tsx:790`、`MessageThread.tsx:166`、`ConversationActivity.tsx:102`

**为什么严重**
产品已**明确鼓励多会话并行**：`useAtlasStore.ts:592-596` 注释写着「A queued message can start in a conversation the user is not looking at; don't pull the view over to it」，还有 `ConversationQueuePanel` 和 `App.tsx:1333` 的 `SidePane`（旁路会话）。

在这种用法下：会话 A 在跑，用户切到会话 B —— **B 里也会显示「正在处理」和停止按钮**，即使 B 是空闲的。`SidePane.tsx:56` 用另一个会话的 events 渲染同一条时间线，于是侧栏那条「另一会话」的时间线会按**当前会话的 busy** 显示「正在想…」/流式光标。

**怎么修**
`busy` / `paused` 改为按 `conversationId` 派生，UI 层统一用 `activeRunFor`，不读全局 `busy`。

---

### 7. 全量订阅 + 大组件未 memo —— 每次流式 delta 触发整树重渲染

**证据（已抽查复核）**
- `SidePane.tsx:17` `const store = useAtlasStore();` —— **无选择器，订阅整个 store 每次变更**
- `OnboardingDialog.tsx:26` 同样问题
- `MessageThread.tsx:197` 的 `useMemo` 依赖只有 `[answers, profiles]`，但下游 `TimelineRow` 还读 `store.busy`（`ConversationActivity.tsx:102`）→ **取到上一个快照的 busy**（stale 快照）
- 全项目仅 **2 处 `memo()`**（`ConversationActivity.tsx:40`、`ConversationMessage.tsx:205`）。以下大组件**全部裸 `export default function`**：

| 文件 | 行数 | props |
|---|---|---|
| `Sidebar.tsx:130` | 936 | 42 |
| `Inspector.tsx:71` | 340 | ~25 |
| `MessageThread.tsx:158` | 528 | — |
| `Composer.tsx:155` | 623 | — |
| `HomeView.tsx:20` | — | — |

- `App.tsx:168-169` 订阅了整个 `runs` 和 `conversationMessages`
- **但合流做得很好**：`services/eventBuffer.ts:24-61`，80ms 窗口（12.5Hz），`runtimeEvents.ts:68-73` 用 `sequence` 单调性做去重快速路径

**为什么严重**
合流器把**事件频率**从「每 token 一次」降到 12.5Hz —— 这是正确的一半工作。但每次 flush 都会 `setState` 改 `runs` → `App` 的 `useShallow` 选择器里 `runs` 引用变了 → `App` 重渲染 → 因为 `Sidebar` / `Inspector` / `Composer` / `HomeView` 都没 memo，且 props 里有大量内联箭头函数（`App.tsx:1333-1340` 给 `Inspector` 传了十几个 `() => ...`），**整棵树跟着重渲染 12.5 次/秒**。长回复流式期间主线程持续被打满。

叠加 `buildTimeline`（724 行函数）在每次 flush 后**全量重算**（`App.tsx:286`、`MessageThread.tsx:194`），问题更重。

**怎么修**
1. `SidePane.tsx:17` / `OnboardingDialog.tsx:26` 改窄选择器
2. `App.tsx` 去掉 `runs` / `conversationMessages` 整体订阅
3. 给 5 个大组件加 `React.memo`，`App.tsx:1333+` 的内联回调用 `useCallback` 固定

---

### 8. 编译后的测试文件打进了安装包

**证据（已抽查复核，实测确认）**

`tsconfig.electron.json:13` 的 `include: ["src/main/**/*.ts", ...]` 会包含所有 `*.test.ts`，两份 tsconfig **都没有 `exclude`**。构建脚本 `package.json:15/17` 用该 tsconfig 编译 → 测试文件进 `dist-electron/`。

实测 `dist-electron/main/`：
```
backendProcess.python.test.js
backendProcess.test.js
electron.navigation.test.js
sourceUpdate.test.js
```

**更深一层：我直接解开了已打包的 `windows-release/win-unpacked/resources/app.asar`（433 MB）**：
```
=== ATLAS 自己的 .test.js 在安装包里: 3 ===
  /dist-electron/main/backendProcess.python.test.js
  /dist-electron/main/backendProcess.test.js
  /dist-electron/main/electron.navigation.test.js
=== node_modules 里的第三方自带: 30 ===（这部分正常）
```
**确认：Atlas 自己的 3 个测试文件真的在安装包里。**

(注：`sourceUpdate.test.js` 在 asar 中未见，可能与构建时间差有关 — `dist-electron` 是本次构建产物，asar 是 10-06 构建的)

**为什么严重**
测试文件里通常包含 mock 路径、断言逻辑（`electron.navigation.test.ts` 直接展示了导航白名单的实现细节）。交付给用户既无必要也泄露实现。同时说明**构建配置没有「测试文件不进产物」的守门**。

**怎么修**
1. `tsconfig.electron.json`（和 renderer）加 `"exclude": ["**/*.test.ts", "**/*.test.tsx"]`
2. 更稳的做法：建 `tsconfig.build.json` 只含产品文件
3. `electron-builder` 的 `files` 收紧为 `"!dist-electron/**/*.test.js"`

---

## 二、分维度详情

### 维度 1：架构与 IPC

**做得对的**
- 三段式职责**清晰**：main（`electron.ts` 651 行 + `backendProcess.ts` 426 行 + `sourceUpdate.ts`）、preload（61 行，零业务逻辑）、renderer
- **后端进程管理质量很高**（`backendProcess.ts`）：
  - `STARTUP_MAX_WAIT_MS = 300_000`（`:26`）配合 `probeHealth`（`:55-73`）做**进度感知等待**，而非死等固定超时
  - 用**单个 append-only fd** 收 stdout+stderr（`:159-171`），确保 process exit 前写完，崩溃不丢 traceback
  - `terminate`（`:263-291`）优先走 `POST /api/runtime/shutdown`（带 `X-Atlas-Backend-Shutdown-Token`），失败再走 Windows `taskkill /T /F` 或 `SIGTERM`
  - `externalAcceptsSessionToken`（`:307-321`）用 `Origin: null` + token 探测，避免「端口被另一个 Atlas 占用」时静默降级
- **安全配置基本齐全**：主窗（`:368-375`）三件套 ✓；浮窗（`:145-150`）三件套 ✓；`setWindowOpenHandler` 三处全部 `{action:'deny'}`；`will-navigate` 两处严格 origin 比对
- **后端 token 隔离设计得好**（`:340-350`）：`onBeforeSendHeaders` 只给顶层请求加 `X-Atlas-Api-Token`，`fromSubframe` 判断会跳过子框架（子框架展示工作区内容 = 不可信内容）
- `lockDownWebviews`（`:319-338`）：`delete preferences.preload`、禁 node、强制 sandbox、强制独立 partition、限制 `params.src` 协议白名单

**问题**
1. 无 CSP（问题 1）
2. **无权限处理器**：`grep` 无 `setPermissionRequestHandler` / `setPermissionCheckHandler`（实测 = 0）。webview 里请求摄像头/麦克风/地理/通知/剪贴板时走默认策略
3. channel 名无共享常量（问题 5）
4. `shell:open-path` 的 `RUNNABLE` 正则（`:555`）按扩展名黑名单，`.py` / `.scf` / `.jnlp` / `.msc` 未列入（**后端是否会下发这类路径：未验证**）
5. **`BackendAdapter` 物理上不在 `frontend/src` 下**（在 `D:\Atlas\backend-adapter\src\client.ts`，691 行），通过 `file:../backend-adapter` 引入。它承担了绝大部分 REST + WebSocket 契约，却不在 `shared/ipc.ts` 覆盖范围内 —— **这是问题 5 的根因**

---

### 维度 2：渲染层质量

**状态管理**：Zustand 5.0.15，**单一巨型 store**（`useAtlasStore.ts` 1148 行，约 100 个 state 字段 + 约 90 个 action）。另 `persistentSlice.ts`（431 行）展开合并 agents/groups/channels/devices/localModels/automations 六块。

**重复源 / 失控点**
- `SidePane.tsx:17`、`OnboardingDialog.tsx:26` 全量订阅
- **localStorage 三套封装并存**：`useAtlasStore.ts:240-249`（storageGet/storageSet/readList）、`App.tsx:144-149`（pref/setPref/readDraft/writeDraft）、`themes.ts:42-43`（自己的 storageGet/storageSet）
- **theme 三处独立读写**：`shell/themes.ts:28`、`AppearanceNotificationsPanel.tsx:31`、`index.html:7` 的内联脚本。内联脚本硬编码「只有 dark/aurora 才需预置」→ **将来加第四个深色主题会静默失效**（`'custom'` 值它就完全不认识）
- 全局 `settingsBusy`（`:39`）被 **7 个互不相关的操作共享**（`:461,473,485,499,547,560,581`）→ 设置页改两样东西会互相 disable 按钮

**超大文件（>500 行）**

| 行数 | 文件 |
|---|---|
| **1496** | `src/renderer/App.tsx` |
| **1148** | `src/renderer/store/useAtlasStore.ts` |
| **936** | `src/renderer/shell/Sidebar.tsx` |
| 724 | `src/renderer/components/timeline.ts` |
| 677 | `src/renderer/pages/ConsolePage.tsx` |
| 650 | `src/main/electron.ts` |
| 623 | `src/renderer/components/Composer.tsx` |
| 618 | `src/renderer/shell/panels/BrowserPanel.tsx` |
| 592 | `src/renderer/components/ConversationActivity.tsx` |
| 557 | `src/renderer/shell/panels/FilesPanel.tsx` |
| 534 | `src/renderer/shell/panels/ChangesPanel.tsx` |
| 528 | `src/renderer/components/MessageThread.tsx` |

前 3 个（App / store / Sidebar）是真正需要拆的。

**内存泄漏逐项核对 —— 结论：listener/interval/WebSocket 都健康，但有两处真实慢性泄漏**

健康的：
- **listener 配对**：33 `addEventListener` vs 29 `removeEventListener`，4 处差额逐条核对后确认是注入到 webview 内页面的字符串脚本（在页面上下文自行 remove）→ **无泄漏**
- **interval 全配对**：16 `setInterval` vs 18 `clearInterval` → **无泄漏**
- **WebSocket 清理到位**：`TerminalPanel.tsx:183` 的 cleanup 完整（`observer.disconnect(); input.dispose(); resize.dispose(); selected.dispose(); socket.close(); term.dispose()`），且用 `let disposed` 守卫迟到的 socket 回调（StrictMode 双挂载下必须）→ **做得对**
- `setTimeout` 30 vs `clearTimeout` 18：差额主要是一次性延迟，**可接受**

两处真实泄漏：
1. **run 层无界**（问题 3）
2. **localStorage 游标残留**：`backend-adapter/src/client.ts:555-585` 的 `atlas.runtime.cursor.${run_id}` 只在 `terminal === true` 时 `removeItem`（`:621`）。**运行异常终止（进程被杀/渲染器崩溃/用户关窗）→ 游标永久残留**。无 TTL、无扫描清理、无上限。**每个失败的 run 泄漏一个 key。**

其他：
- `AbortController` 只用 1 处（`FilesPanel.tsx:281`），而 renderer 有 **52 处 `fetch(`**。其余靠手工 `let stale = false` 守卫（全项目 31 处）→ 不是泄漏，但组件卸载后请求仍在跑

---

### 维度 3：错误处理

**做得好的**
- `probeHealth`（`backendProcess.ts:55-73`）里 `await response.json()` 的失败单独 catch，不吞 HTTP 层信息
- 后端启动失败走**原生错误框 + 日志尾部**（`electron.ts:620-624`），`logTail` 取最后 50 行
- **双字段错误模型**（`useAtlasStore.ts:281-286`）：中文主文案 + 英文原文，UI 折叠展示 —— 产品级细节
- `startRun` 传输层失败会**合成一条 `run.failed` 事件**（`:1119`）而非只弹 banner → 时间线上能看到失败点

**问题**
- 59 处静默 catch（问题 4）
- **无全局兜底**：`grep` 无 `unhandledrejection` / `window.onerror` —— 任何逃逸的 Promise rejection 在生产版用户那里完全不可见
- **无错误上报 / 无本地日志落盘**：非测试代码里 `console.` 只 1 处。没有 crashReporter，用户遇到问题只能靠截图

---

### 维度 4：流式 / 实时能力 —— 这是整个前端做得最扎实的部分

- **传输层**：WebSocket（`backend-adapter/src/client.ts:530-624`），`/ws/chat`
- **协议版本协商**（`:89-102`）：先 GET `/api/runtime/protocol`，`hasEventProtocol` 判定 `major > 1 || (major === 1 && minor >= 2)`。不支持则**明确拒绝**并给可操作提示
- **断线续传**：`lastSequence` 从 localStorage 恢复（`:556`），重连发 `{ type: 'resume', after_sequence }`（`:573-576`）
- **重连退避**：指数退避 `Math.min(1000 * 2 ** (retries - 1), 8000)`（`:607`）
- **事件去重**：`if (runtimeEvent.sequence <= lastSequence) return;`（`:583`）—— 靠 sequence 单调性丢弃重放
- **并发保护**：`activeRuns` Set 防同 run_id 重复启动（`:24`、`:536`），错误信息友好
- **审批降级**：socket 不通时抛明确的 `BackendError`（「和后端的连接已断开，这条操作没能送达」）而非静默失败
- **流式合流**：80ms 窗口把 `message.delta` 合并，非流式事件先 `flush()` 再透传以保序（`:48-53`）

**短板**
- `buildTimeline` 每次 delta **全量重算**（724 行函数 × 12.5Hz）
- `timeline.ts:363/369` 在流式内容解析上暴露 `any` —— **输入最不可控的地方，类型最松**
- `AgentChat.tsx:117-141` 的 workbench 挂件 socket **无自动重连**（`onclose = () => setLive(false)`），要用户手点 —— 与主通道自动续传形成对比
- 游标清理缺口（见维度 2）

---

### 维度 5：配置 / 构建

**vite.config.ts（17 行，干净）**
- 双入口正确（`app` + `floating-composer`），显式 `resolve(import.meta.dirname, ...)` 避免 cwd 依赖
- `base: './'`（`:8`）—— **Electron file:// 加载的必需设置，做对了**
- `strictPort: true`（`:16`）—— 避免端口漂移
- 缺：无 `build.sourcemap` 配置；无代码分包策略（mermaid 手动动态 import 是对的，其余 `@radix-ui/*` 8 包 + `motion` + `react-markdown` 全进主 chunk）

**tsconfig**
- `tsconfig.electron.json`：ES2022 / NodeNext / strict ✓
- `tsconfig.renderer.json`：strict + **`noUnusedLocals` + `noUnusedParameters`**（比多数项目严格）✓
- **两份都没排除 `*.test.*`** → 问题 8
- 缺一个「根」tsconfig

**vitest.config.ts（7 行）**
- `exclude` 里加 `dist-electron/**` 是必要的（说明作者踩过坑）✓
- **没有 `environment` 设置** → 默认 node。这解释了为什么全部 React 测试只能用 `react-dom/server`

**构建产物污染 —— 结论：基本没有**

逐个验证（`git check-ignore -q` 全部 IGNORED，`git ls-files` 全部 0 tracked）：

| 目录 | 大小 | 状态 |
|---|---|---|
| `backend-build/` | 279M | IGNORED |
| `backend-release/` | 525M | IGNORED |
| `dist/` | 30M | IGNORED |
| `dist-electron/` | 97K | IGNORED |
| `windows-release/` | 2.9G | IGNORED |
| `.ruff_cache/` | 2.0K | IGNORED（在 frontend 下有点怪，无害）|

`frontend` 下 256 个 tracked 文件，**无构建产物入库**。

**但有一个真实的组织问题**：`backend-build` / `backend-release` / `windows-release` / `node-runtime.json` 全是**后端与打包**的职责，却和前端源码树混在同一目录，合计 **3.7 GB**。更干净的做法是把打包编排提升到仓库根。

**死代码 / 遗留文件**
- **frontend 内部干净**：只有 `index.html` + `floating-composer.html`，没有 preview 副本
- **但仓库根 `/d/Atlas/` 有 7 个遗留 HTML（约 515KB）**：`atlas-frontend-preview.html`(52KB)、`-preview-v2.html`(116KB)、`-preview-v2.original.html`(119KB)、`-preview-v3.html`(116KB)、`-v3.html`(38KB)、`-v4.html`(42KB)、`pelican-wing-circus.html`(42KB)。其中 **v2 和 v3 字节数完全相同（116122）**，是重复副本。**且 `atlas-frontend-v4.html` 时间戳是 `Oct 14 00:23`（今天）** → 「设计稿与实现双轨」的风险
- `styles/legacy.css`（171 行）**实际在用**（`app.css:2` `@import`），旧类名 `.page`/`.btn`/`.row`/`.detail` 还在 13+ 个页面里使用。**不是死代码，但是技术债的可见形态**
- CSS 总量健康：580 行

**依赖版本一致性：全部核对通过**
`react 18.3.1`、`typescript 7.0.2`、`vite 8.3.4`、`vitest 5.0.4`、`tailwindcss 4.3.3`、`zustand 5.0.15`、`electron 44.7.0`、`lucide-react 1.56.0`、`motion 14.2.0`、`react-markdown 10.1.0` —— declared 与 installed **完全一致**。

**依赖管理摩擦点**：`frontend/` 下**没有 `package-lock.json`**（锁文件在仓库根，因 `workspaces: ["frontend"]`）。所以**在 `frontend/` 里直接跑 `npm install` 会破坏 workspace 布局** —— `package.json:10` 的 `install:electron` 相对路径 hack 正是为此存在。建议明确「必须从仓库根安装」。

---

### 维度 6：测试覆盖

**规模**：28 文件 / 192 用例 / 218 源文件 ≈ **12.8% 文件覆盖**，实跑全绿。

| 领域 | 用例数 |
|---|---|
| main 进程 | 23 |
| store | 28 |
| 流式/事件 | 9 |
| 时间线 | 17 |
| 组件 | ~117 |
| adapter（frontend 之外） | 19 |

**测到了（质量不错）**
1. **安全边界有测试** —— `electron.navigation.test.ts` 是最有价值的测试：
```ts
it('blocks a URL whose text starts with the dev origin but whose parsed origin is different', () => {
  navigate?.(event, 'http://127.0.0.1:5173@attacker.example/');
  expect(event.preventDefault).toHaveBeenCalledOnce();
```
**精准命中 URL 解析的经典陷阱**（`userinfo@host` 形式 origin 混淆）→ 说明作者理解这类漏洞

2. **preload 沙箱有专项测试** —— `scripts/test-preload-bundle.mjs` 用 `vm.runInNewContext` + 故意限制的 `require`（只允许 `'electron'`），先断言「tsc 直出的产物会被拒」，再断言 esbuild bundle 能正常暴露。**这是「用测试锁定构建方式」的优秀实践**

3. **核心逻辑有覆盖**：`eventBuffer.test.ts`（合流）、`runtimeEvents.test.ts`（sequence 去重/乱序/800 截断）、`timeline.test.ts`（16 用例）、`useAtlasStore.test.ts`（24 用例）

4. **adapter 断线续传有真测试**（`backend-adapter/tests/client.test.ts:154`）：自己实现 `MockWebSocket extends EventTarget` 驱动重连路径 —— **全项目条件最苛刻、最值得存在的测试**

**没测到**
1. **渲染层几乎全是「字符串断言」** —— 没装 jsdom / happy-dom / @testing-library/react（已核对，三者都不存在），所有 React 测试只能用 `react-dom/server`：
```ts
const html = renderToStaticMarkup(<MarkdownContent content={...} />);
expect(html).toContain('<h2>Summary</h2>');
```
**没有一条测试验证过：点击、输入、useEffect 执行、状态更新、组件卸载清理。** 而维度 2 发现的所有问题（SidePane 全量订阅、removeRun 未调用、interval 清理、websocket 重连）**全部落在 SSR 测试的盲区里**。

2. **`App.tsx` 零测试** —— 1496 行的核心组件完全没覆盖
3. **安全函数零测试**：`parseAtlasDeepLink`（`electron.ts:204-220`，解析外部 `atlas://` 深链，**攻击面明确**）、`assertTrustedAppSender`、`openFileInEditor` 的路径逃逸检查（`:290-308`）、`validateGlobalAccelerator`（`:99-117`）、`RUNNABLE` 正则 —— **全部无测试**
4. **迁移逻辑无测试**：`migrateLegacyFlags`（`:1033-1045`）出错会静默丢用户的置顶/归档

**基础设施问题**
- `vitest.config.ts` 无 `coverage` 配置 → 无法知道真实覆盖率
- 无 CI 配置
- `test:adapter` 用跨包相对路径（`--root ..`），耦合两个包的目录布局

---

## 三、与 ZCode 的差距清单（按严重程度）

| # | 差距 | ZCode 的做法 | 影响 |
|---|---|---|---|
| 1 | **缺 CSP + 缺权限处理器** | `onHeadersReceived` 注入严格 CSP + 权限显式白名单 | 「能不能上线」的门槛项 |
| 2 | **缺错误边界 + 崩溃恢复语义** | ErrorBoundary + 崩溃日志 + 「恢复上次会话」入口 | 真实用户机器上最高频的差评来源 |
| 3 | **无界内存增长** | 逐层内存预算 + 上限 | 长会话必然劣化 |
| 4 | **多会话状态串线** | 运行态完全挂 conversation 维度 | 随使用深度快速暴露 |
| 5 | **流式重渲染放大** | 保证流式期间稳定不掉帧 | 长回复界面发涩、输入延迟 |
| 6 | **IPC 契约未入类型系统** | 共享 contract 同时约束 main + renderer | 通道数增长后漏配成常态 |
| 7 | **测试只到字符串层** | 组件交互测试 + E2E | 「能不能持续演进」的差距 |
| 8 | **无 sourcemap / 无错误上报 / 无本地日志** | 能拿到「用户在哪一步、哪个组件、什么错误栈」 | 决定问题定位速度 |
| 9 | **测试文件进安装包** | 构建守门 | 泄露实现 + 包体积 |
| 10 | **仓库组织** | 构建编排、产物、设计稿与源码树彻底分离 | 3.7GB 与源码同目录 |

### ZCode 最值得学的一块：进程自省（泄漏监控）

ZCode 每隔 60 秒，**每个进程上报一份资源计数快照**，实测原文：

```
[main]     taskBus.leases=0  taskBus.sessionRoutes=127  ws.host=217176
           broadcast.claims=0  app.willDownloadListeners=0  app.windows=1
[host]     agent.pendingPermissions=0  agent.seqStates=0  agent.sessionEmitters=0
           bots.typingIntervals=0  fileWatcher.open=0  terminal.open=0
           task.overlays=0  task.toolMemoryTasks=0
[renderer] projection.rows=7  sessionStore.workspaces=1  shiki.highlighters=0
           shiki.tokensCache=0  taskSnapshotCache.entries=0  xterm.sessions=0
```

每个数字都是一个**已知的泄漏点**：监听器、定时器、文件句柄、终端会话、订阅。

**这就是「连续跑 24 小时不崩、不漏内存」那道题的答案。** Atlas 前端当前恰好缺这个 —— 而问题 3、维度 2 的两处泄漏正是它能立刻抓到的。

---

## 四、抽查复核记录

以下论断由主控用独立命令二次验证，全部**确认属实**：

| 论断 | 验证命令 | 结果 |
|---|---|---|
| 无 CSP | `grep -c "Content-Security-Policy" index.html` | 0 ✓ |
| 主进程无 header 注入 | `grep -c "onHeadersReceived" src/main/electron.ts` | 0 ✓ |
| 无 ErrorBoundary | `grep -rl "ErrorBoundary\|componentDidCatch" src/ \| wc -l` | 0 ✓ |
| `removeRun` 无调用者 | `grep -rn "removeRun" src/` | 仅定义 2 处 ✓ |
| tsconfig 无 exclude | `grep -n "exclude" tsconfig.*.json` | 空 ✓ |
| 测试文件进构建 | `ls dist-electron/main/*.test.js` | 4 个 ✓ |
| 测试文件进安装包 | 解开 `windows-release/.../app.asar` 扫 `.test.js` | 自己 3 个 + 第三方 30 个 ✓ |
| SidePane 全量订阅 | `grep -n "useAtlasStore()" SidePane.tsx` | `:17` ✓ |
| 全局 busy | `grep -n "busy: runs.some" useAtlasStore.ts` | `:623`、`:670` ✓ |
| 无权限处理器 | `grep -rn "setPermissionRequestHandler" src/ \| wc -l` | 0 ✓ |
| 安全三件套已配 | `grep -n "contextIsolation\|nodeIntegration\|sandbox:" electron.ts` | 主窗 `:147-149` ✓ |
| sender 校验 8 处 | `grep -c "assertTrustedAppSender" electron.ts` | 8 ✓ |
| `window:*` 未校验 | `grep -n "ipcMain.on('window:" electron.ts` | `:525/526/531/543` ✓ |
| 测试文件总数 | `find src -name "*.test.*" \| wc -l` | 28 ✓ |

**主控未独立验证**（沿用探子结论，标注为待验证）：
- Tailwind v4 能否去掉 `style-src 'unsafe-inline'`
- `@fontsource-variable/geist` / `cmdk` 是否真未使用
- `shell:open-path` 能否被诱导打开 `.py`
- 类型检查与生产构建是否 100% 通过（探子未跑 `tsc` / `vite build`）
