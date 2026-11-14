# WAVE5 · D 组（桌面/前端区）结果

- worktree: `D:/Atlas/.worktrees/w5-d`，分支 `wave5-d`
- 基线: `32b76e39`（wave5-d 起点）
- 本组条目: D1 / D2 / D7 / X27
- 提交: `19191714` `95da95dd` `ad9ecf38` `66b94eb7` `d879f7b4` `6cf85749`（全部本地 commit，未 push）

---

## ① 逐条判定

### D1 · 认证本地载体 + boot injection + OS 分配端口 → **CLOSED**

实现侧 WAVE2-V8 已接通（`injectBackendPort` 在 Electron ready 时选 loopback OS 临时端口写 `ATLAS_PORT`；spawn 继承；preload `apiBaseUrl` 与健康探测共用；显式 `ATLAS_PORT` 兼容）。本轮补齐要求的测试门槛：

- 端口分配 + 注入：`backendPort.test.ts`（4 tests）——OS 分配、显式端口保持、空/非法 override（`''`、`abc`、`0`、`-1`、`70000`）回退分配、分配端口释放后可重绑 loopback。
- 健康探测走注入端口 + spawn 继承：`backendProcess.test.ts` 新增 `probes and spawns on the ATLAS_PORT injected at boot`——真实 `injectBackendPort()` 分配 → 断言探测 URL 精确为 `http://127.0.0.1:<注入端口>/api/health` → 断言 spawn env `ATLAS_PORT === 注入端口`（端到端，不是默认 8765）。
- preload `apiBaseUrl` 共用注入端口：`index.lifecycle.test.ts`（ATLAS_PORT=41025 → `http://127.0.0.1:41025`；无注入回退 8765；`ATLAS_API_BASE_URL` 显式优先）。

诚实注记：token 注入共用（`attachBackendToken` 的 webRequest hook）是既有实现，本轮未为其新增专项断言（不在本条要求补测的清单内——任务要求为「端口分配+ATLAS_PORT 注入+健康探测」）。

### D2 · 两进程 typed IPC 生命周期（四态） → **CLOSED**

实现侧已接通（`shared/ipc.ts` 的 `BackendLifecycleEvent`；main 四处 publish；preload typed 订阅）。本轮补齐四态发布与订阅生命周期测试：

- main 侧（`electron.backendLifecycle.test.ts`，3 tests）——驱动**真实 `app.whenReady` boot 流程**（仅 electron/backendProcess 模块 mock）：
  - ready：boot 完成后主窗口收到 `kind:'ready'`、sequence 单调、timestamp 合法；
  - shutdown-complete + fatal：`backend:retry` → `restartBackendNow` 先发 `shutdown-complete` 再因启动失败发 `fatal`（detail 保留错误文案）；before-quit 的第二个 shutdown-complete 发布点也覆盖（两个 shutdown-complete）；
  - quit-inspection：`app:set-quit-activity`(1 running/2 scheduled) 后 `app:quit-request` 发布 `quit-inspection`（带 runningTasks/scheduledTasks）→ 弹确认框 → `app.quit()`；
  - `backend:get-lifecycle` 返回最新事件（订阅补取的服务端半边）；全序列严格递增。
- preload 侧（`src/preload/index.lifecycle.test.ts`，4 tests）——esbuild 转译 preload 源码 + vm 沙箱执行（与 `scripts/test-preload-bundle.mjs` 同法）：
  - 订阅后立刻补取最新状态（`backend:get-lifecycle`）；
  - 推送事件即时到达、**迟到的旧 sequence 补取不回退**、旧 sequence 重放被去重；
  - disposer 可卸载（卸载后推送不再到达，listener 集清空）；
  - 无任何已发布状态时补取为空、不误发。

### D7 · follow 重连 + page() 补缺口 → **CLOSED**

服务端有界 event page、header/tail/cursor/projection baseline 及其服务端单测为既有实现（未动，`core/atlas/api/runtime_ws_router.py`）。本轮补齐 renderer 侧重连路径测试（`backend-adapter/tests/client.test.ts` +3）：

- `reattaches from sequence 0 over a stale persisted cursor...`——adapter 为空时 attachRun 首连发送 `after_sequence: 0`（无视持久化 cursor=9），从 header 重放；随后无断层的传输丢失从连续 cursor（2）续传，而非回到 0。
- `rejoins the websocket from the repaired cursor after a non-terminal page repair`——startRun 路径：收到 1→3 断层 → 补页（只含 2，非终结）→ **从修复后 cursor 2 接回 WebSocket**（`resume after_sequence:2`）→ 继续收 3、4 到终结；全程事件 [1,2,3,4] 无重复无丢失。
- `walks consecutive event pages until the gap is closed, then follows live`——服务端 head（4）超前已消费 cursor（2）时补页循环继续走第二页（`after_sequence=0` → `after_sequence=2` 两次取页均已断言），闭合后从 4 接回 live follow。

### X27 · timeline.ts 从不产出 kind:'extension' → **CLOSED**

纯暴露（实现此前为零，`kind:'extension'` 在事件流不可达）。本轮：

- `timeline.ts`：新增 `registerExtensionNodeClaim({ nodeType, match })` 注册表 + disposer；assembler 的 `default` 分支（内置 switch 不渲染的事件）被 claim 命中时产出 `{ kind:'extension', id, nodeType, data }`。claim 抛错不破坏内置时间线；内置 kind 不受影响。
- `ConversationActivity.tsx`：`ConversationNodeDefinition` 增加可选 `match`；`registerConversationNode` 同步注册/注销 claim（一个 disposer 管两件事）。渲染端 `TimelineRow`（nodeType → 注册表 renderer）与 `MessageThread` 的 'extension' 类目映射为既有实现，未改。
- 测试：`ConversationNodeRegistry.test.tsx`（注册带 match 的扩展定义 → `buildTimeline` 产出对应节点 → `TimelineRow` 渲染断言 → dispose 后不可达；同时断言内置 message.completed 仍正常成节点）+ `timeline.test.ts`（claim 注册/去重/抛错安全/dispose/重注册；`safety.reviewed`、`canvas.update` 均为既有 known 事件类型——**未新增事件名，无三真源同步需求**）。

### 结论

D1 / D2 / D7 / X27 全部 **CLOSED**。D 区门槛三项全绿（见 ③）。无 HARD / NOT-DONE 条目。

---

## ② 改动文件清单

新增（测试）：
- `frontend/src/main/electron.backendLifecycle.test.ts` — D2 main 侧四态发布（3 tests）
- `frontend/src/preload/index.lifecycle.test.ts` — D1 apiBaseUrl + D2 订阅生命周期（4 tests）

修改（产品代码，最小接线）：
- `frontend/src/renderer/components/timeline.ts` — X27：`ExtensionNodeClaim` / `registerExtensionNodeClaim` / default 分支产出 extension 节点
- `frontend/src/renderer/components/ConversationActivity.tsx` — X27：`ConversationNodeDefinition.match` + 注册/注销 claim
- `frontend/src/renderer/components/x2/ComputerStatusSection.tsx` — 门槛修复：`window` 裸引用加 `typeof window !== 'undefined'` 守卫（基线失败，见 ④）

修改（测试）：
- `frontend/src/main/backendPort.test.ts` — D1（+2 tests）
- `frontend/src/main/backendProcess.test.ts` — D1（+1 test）
- `frontend/src/renderer/components/timeline.test.ts` — X27（+1 test）
- `frontend/src/renderer/components/ConversationNodeRegistry.test.tsx` — X27（+1 test）
- `frontend/src/renderer/components/x2/x2.test.tsx` — 门槛修复（基线断言跟上 BROWSER_MODES 现状 6 模式）
- `frontend/src/main/electron.navigation.test.ts` — 门槛修复（electron mock 补齐 boot 所需成员，测试意图不变）
- `backend-adapter/tests/client.test.ts` — D7（+3 tests）+ 门槛修复（deleteFact→deleteKnowledge）

修改（构建）：
- `package-lock.json` — npm install 在干净 worktree 补齐 `react-test-renderer`/`@types/react-test-renderer` 的既有 lock 缺口（`frontend/package.json` 早已声明，lock 滞后，commit 030bf8c4 引入）

未改动：`docs/parity/DSH-GAP-LEDGER.md`（按指令留给调度者）、`config/atlas.toml`、`data/user-settings.json`、`data/memory/**`、任何 `core/` 后端文件。

---

## ③ 测试命令 + 真实输出

全部在本 worktree 的 `frontend/`（node_modules 为本轮 `npm install` 新建，EXIT=0）执行；日志存 `.tmp/`。

```
$ npm install --no-audit --no-fund > ../.tmp/npm-install.log 2>&1; echo EXIT=$?
EXIT=0
```

**门槛 1 — 全量 vitest（最终提交态）：**
```
$ npx vitest run > ../.tmp/vitest-final3.log 2>&1; echo VITEST_EXIT=$?
VITEST_EXIT=0
 Test Files  80 passed (80)
      Tests  365 passed (365)
```

**门槛 2 — TypeScript（frontend 无根 tsconfig.json，按仓库实际的双项目配置）：**
```
$ npx tsc -p tsconfig.renderer.json --noEmit > ../.tmp/tsc-r3.log 2>&1; echo TSC_RENDERER_EXIT=$?
TSC_RENDERER_EXIT=0          # 0 错误
$ npx tsc -p tsconfig.electron.json --noEmit > ../.tmp/tsc-e3.log 2>&1; echo TSC_ELECTRON_EXIT=$?
TSC_ELECTRON_EXIT=0          # 0 错误
```
（裸 `npx tsc --noEmit` 在 frontend/ 下因无根 tsconfig 打印帮助并 exit 1 —— 仓库既有状态，基线即如此，非本次引入。）

**门槛 3 — adapter（D7 测试所在套件，独立 root）：**
```
$ npm run test:adapter > ../.tmp/vitest-adapter-final2.log 2>&1; echo ADAPTER_EXIT=$?
ADAPTER_EXIT=0
 Test Files  1 passed (1)
      Tests  23 passed (23)
```

**定向（各条目提交时逐个跑过，节选）：**
```
$ npx vitest run src/renderer/components/timeline.test.ts src/renderer/components/ConversationNodeRegistry.test.tsx src/renderer/components/timelineProjection.test.ts
 Test Files  3 passed (3)      Tests  30 passed (30)        # X27
$ npx vitest run src/main/backendPort.test.ts src/main/backendProcess.test.ts
 Test Files  2 passed (2)      Tests  14 passed (14)        # D1
$ npx vitest run src/main/electron.backendLifecycle.test.ts
 Test Files  1 passed (1)      Tests  3 passed (3)          # D2 main
$ npx vitest run src/preload/index.lifecycle.test.ts
 Test Files  1 passed (1)      Tests  4 passed (4)          # D2 preload + D1 apiBaseUrl
$ npx vitest run src/renderer/components/x2/x2.test.tsx src/main/electron.navigation.test.ts
 Test Files  2 passed (2)      Tests  25 passed (25)        # 门槛修复
```

未跑 pytest：本轮未改任何后端文件（按作业守则 D 组无需后端测试）。未新增/改名渲染层事件，无需三真源同步与 `test_event_contract.py`。

---

## ④ 基线既有失败清单与归属

基线（commit 32b76e39，改动前）`npx vitest run`：**Test Files 2 failed | 76 passed (78)；Tests 4 failed | 349 passed (353)**。基线 `npm run test:adapter`：**Tests 1 failed | 19 passed (20)**。tsc 双项目基线均 0 错误。

5 条基线失败全部为**测试/产品漂移**，全部已在本轮修复（commit `d879f7b4`、`66b94eb7`），修复后全量 365/365、23/23 全绿。逐条归属：

| 基线失败 | 根因 | 归属与修复 |
|---|---|---|
| `electron.navigation.test.ts` ×2（blocks/allows dev origin） | 该测试的 electron mock 早于 tray/boot 路径：boot 在 `app.setLoginItemSettings`（undefined）即抛错，落入 `.catch` 后 `dialog.showErrorBox` 也不是 mock 成员 → 未处理 rejection，`BrowserWindow` 从未被构造，`will-navigate` 断言超时 | 导航信任的产品代码无缺陷；mock 补齐 boot 所需成员（Tray/powerSaveBlocker/setLoginItemSettings/showErrorBox/buildFromTemplate/createEmpty/createFromDataURL/once/isDestroyed）+ ATLAS_DATA_DIR 隔离 + fetch/interval stub，boot 真正走到建窗，测试意图原样保留 |
| `x2.test.tsx` · offers exactly the four takeover modes | `BROWSER_MODES` 已从 4 模式增至 6（`8e211b06` 加 auto、`30a0c710` 加 extension，均为有意提交），测试断言停留在旧值 | 断言跟上现状：6 模式值 + 现行文案（自动选择/连接正在使用的 Chrome/自定义 CDP 地址） |
| `x2.test.tsx` · shows the probing hint | `2f401fc2` 在 `ComputerStatusSection` 渲染路径加了裸 `window.atlasDesktop?.retrySessionScreenshot`，非 DOM 环境（renderToStaticMarkup）`window` 未定义 → ReferenceError | 产品代码 SSR/测试安全修复：`typeof window !== 'undefined' &&` 守卫（Electron 内行为不变） |
| adapter · accepts successful empty responses | `6834eb38`（MemOS/legacy memory 清理）删除了 `BackendAdapter.deleteFact`，测试仍调用 → `TypeError: adapter.deleteFact is not a function` | 测试改指现存等价 void DELETE：`deleteKnowledge('temporary')`（204 空体语义不变） |

以上 5 项在基线即可复现（`git stash` 后基线复跑 adapter 得 19 passed/1 failed，同一 `deleteFact` 错误；frontend 4 项在隔离单文件复跑同样失败），**非本组改动引入**。修复后无任何残留失败。

---

## 附：给调度者的核对入口

- 每条判定对应的提交：D1+D2 → `ad9ecf38`+`6cf85749`；X27 → `95da95dd`；D7+adapter 修复 → `66b94eb7`；门槛修复 → `d879f7b4`；lock 同步 → `19191714`。
- 最终门槛数字（提交态复跑）：vitest **80 文件 / 365 测试全过**；adapter **23 全过**；tsc（renderer/electron）**0 错误**。
- X27 说明：extension 节点由**既有 known 事件类型**经 claim 产生，未新增事件名，事件契约无变化。
