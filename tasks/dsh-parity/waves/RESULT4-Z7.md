# RESULT4-Z7 — 桌面端前端（D 区）WAVE4

**分支**：`wave4-z7`（worktree `D:\Atlas\.worktrees\w4-z7`）
**基线**：`ec0a9d47`（wave3 合并点）→ WIP `92e3d50e` → 本批提交 `030bf8c4`、`17e6542a`
**日期**：2026-11-14
**D 区 CLOSED 门槛**：vitest 通过 + TypeScript 0 错误 + 组件测试覆盖该行为（不需要真实模型回合）

---

## 0. WIP 审查结论（第一步）

上会话遗留：提交 `92e3d50e`「wip(z7): save partial work before model switch」+ 一个未提交的 x6 测试改动。审查结论：

| 文件 | 判断 | 处置 |
|---|---|---|
| `frontend/src/renderer/store/useAtlasStore.ts` | **保留**。探针分页设计正确：`MESSAGE_FETCH_SIZE = 101`（一页 100 + 1 条探针），首页满 101 → 有更早、探针留在服务端不进渲染列表；`loadEarlier` 取 101 全并入并按既有列表去重，短页即停。消除旧"满页启发式"（恰满 100 条时无法判断是否到头）在两端的歧义 | 保留，补测试 |
| `frontend/src/renderer/shell/panels/trajectory.ts` | **保留**。`describeTrajectoryEvent` 接受 `type`（实时 runtime 帧）与 `event`（归档 rollout 行）双键，实时与回放描述一致；新增 `text()` helper 安全序列化 arguments/result | 保留，补测试 |
| `useAtlasStore.test.ts` | WIP 已把断言改成 limit=101，但该测试**在基线 ec0a9d47 上就失败**（stash + checkout 基线两文件复跑验证）：`initialize()` 的 10 连 `mockResolvedValueOnce` 链被无关 fetch 调度打乱，`/api/profiles` 吃到 fallback 空 JSON，`profiles.some` 抛 TypeError，测试死在 :352，分页断言根本没跑到 | 重写为按 URL 路由的 fetch mock（顺序无关），分页断言真正生效 |
| `useAtlasStore.x6.test.ts`（未提交改动） | **意图合理但有 3 处 bug，测试从未跑通过**：① walk 测试期望 `beforeId: 'm-401'`，而实现把整页 101 行并入（边界行 m-400 需要显示），下一游标应为 `m-400`；② 期望数组用对象和 id 字符串比较（`page()` 返回对象，`ids` 是字符串）；③ `getMessages` 绑定未使用（TS6133） | 修正期望值、改 `.map(row => row.id)`、删死绑定；保留"连续满页回溯 + 短页停止"意图并加"重叠页修复"覆盖去重分支 |
| `frontend/vitest-base.json` | **误提交的 vitest 运行结果工件**（135KB 单行 `{"numTotalTestSuites":195,...}`），不是配置文件 | `git rm` 删除 |
| `frontend/package.json` | 加了 `react-test-renderer: 18.3.1`——4 个既有组件测试（ForkTree/MessageThread.x6/PaneWorkspace/UltraplanPanel）都 import 它，依赖在共享根 `D:\Atlas\node_modules` 里真实存在但 package.json 未声明 | 保留并对齐主检出区写法 `^18.3.1`，补 `@types/react-test-renderer` |

## 1. rows → 动作 → 文件清单

派单 26 条 rows（D13 已 CLOSED，D4 已由 W3-X6 关闭）。开工审查发现**大部分行在 W2/W3 已实现且有组件测试，账本行是旧状态**；本批逐行用真实代码+测试证据复核，只对真实缺口施工：

| row | 动作 | 文件 |
|---|---|---|
| D3 | 复核（已实现） | `timelineProjection.ts`（TimelineProjection + compactTimelineReplay）+ `timelineProjection.test.ts` 6 项 |
| D4 | 复核 W3-X6 | `ConversationNodeRegistry.test.tsx` 2 项通过 |
| D5 | 复核（已实现） | `attachmentStaging.test.ts` 4 项 + `ComposerAttachmentStatus.test.tsx` 2 项 |
| D6 | **修测试**（既有失败） | `ComposerDraftRestore.test.tsx` 包 TooltipProvider（生产环境 App.tsx:3312 提供，裸渲染缺它） |
| D8 | 复核（已实现，账本过期） | `Inspector.tsx:146-212` per-session 布局 + `inspectorLayout.test.ts` 4 项 + `inspectorTabs.test.ts` 2 项 + `Inspector.parity.test.tsx` |
| D10 | 复核（已实现，账本过期） | `update-coordinator.test.ts` 4 项 + `releaseUpdate.test.ts` 4 项（强制版本策略在 main 侧）+ `UpdateBanner.test.tsx` 5 项 |
| D11 | 复核（并排已实现，账本过期） | `ChangesPanel.tsx:370-469` unified/split + `diffReview.test.tsx` 5 项 |
| D12 | 复核（呈现已升级） | `ConversationActivity.tsx:117` RunChangesSummary + `ConversationActivity.parity.test.tsx` |
| D15 | 复核（不可滚走已实现） | `ConversationActivity.tsx:339` PendingApprovalDock（App.tsx:3464 挂在滚动区外）+ parity 测试 3 项 |
| D16 | 复核 | `documentPreviewRegistry.test.tsx` 3 项 + `FilesPanel.test.tsx` |
| D17 | 复核 | `i18n.ts` namespace + `i18n.test.ts` 7 项 |
| D18 | 复核（radius token 已落地） | `app.css:15-21` 尺度 + `styleContracts.test.tsx` |
| D19 | 复核 | `app.css:219,316` focus/reduced-motion + `styleContracts.test.tsx` + `shortcuts.test.ts` |
| D20 | 复核 | `electron.lifecycle.test.ts` 单实例/深链 2 项 |
| D21 | 复核 | `electron.lifecycle.test.ts` 托盘项 |
| D22 | 复核 | `electron.lifecycle.test.ts` 菜单项 + `shortcuts.test.ts` 3 项 |
| D23 | 复核 | `electron.ts:1029` recoverRendererCrash + `electron.lifecycle.test.ts` 2 项 |
| D24 | 复核 | `useAtlasStore.x6.test.ts` fork 双模式 + `ForkTree.test.tsx` + `ForkTree.regression.test.ts` |
| D25 | **仅回归测试**（行为未动） | `useAtlasStore.x6.test.ts` rewindTo files×2 + redoRewind |
| D26 | 复核 | `UltraplanPanel.test.tsx` + x6 plan 提交/approvePlan |
| D27 | 复核 | `ConversationQueuePanel.test.tsx` 2 项 + x6 redirect |
| D28 | 复核 | `voiceHudProtocol.test.ts` + `VoiceOverlay.component.test.tsx` + `speechPlayback.test.ts` + `audioDevices.test.ts` |
| D29 | **实现补完 + 测试**（接 WIP） | `useAtlasStore.ts` 探针分页 + `useAtlasStore.test.ts` URL 路由 mock + `useAtlasStore.x6.test.ts` 4 项 + `MessageThread.x6.test.tsx` UI 回归 |
| D30 | **实现补完 + 测试**（接 WIP） | `trajectory.ts` type/event 双键 + `trajectory.test.ts` 3 项 + `MessageThread.tsx:171,654` 双模式 + `MessageThread.x6.test.tsx` + `ConversationTrajectory.test.tsx` |
| D31 | **仅回归测试**（行为未动） | `PaneWorkspace.test.tsx` 2 项 + **新增** `electron.multiWindow.test.ts` 5 项（`electron.ts` 仅加 `export`，无行为改动） |
| D32 | **仅回归测试**（行为未动） | `useAtlasStore.x6.test.ts` editMessage 截断重发 + `MessageThread.x6.test.tsx` |
| D33 | 复核 | `slashCommands.test.tsx` 3 项 + `pluginSlashCommands.test.ts` 2 项 |

改动文件清单（本批新增/修改）：
- `frontend/src/renderer/store/useAtlasStore.test.ts`（mock 重写）
- `frontend/src/renderer/store/useAtlasStore.x6.test.ts`（期望修正 + 重叠页测试）
- `frontend/src/renderer/shell/panels/trajectory.test.ts`（type 键覆盖）
- `frontend/src/renderer/components/ComposerDraftRestore.test.tsx`（TooltipProvider）
- `frontend/src/main/electron.ts`（+`export` 一处）
- `frontend/src/main/electron.multiWindow.test.ts`（新增，5 项）
- `frontend/package.json`（react-test-renderer ^18.3.1 + @types/react-test-renderer）
- `frontend/vitest-base.json`（删除误提交工件）
- `docs/parity/DSH-GAP-LEDGER.md`（本批 rows 状态更新）

## 2. 真实命令输出

### 2.1 定向测试（三批，全部通过）

批次 A（D3/D5/D6/D8/D29/D30）：

```
$ npx vitest run --root . src/renderer/store/useAtlasStore.test.ts src/renderer/store/useAtlasStore.x6.test.ts \
    src/renderer/shell/panels/trajectory.test.ts src/renderer/components/ConversationTrajectory.test.tsx \
    src/renderer/components/MessageThread.x6.test.tsx src/renderer/components/timelineProjection.test.ts \
    src/renderer/components/timeline.test.ts src/renderer/services/attachmentStaging.test.ts \
    src/renderer/components/ComposerAttachmentStatus.test.tsx src/renderer/services/composerDraft.test.ts \
    src/renderer/components/ComposerDraftRestore.test.tsx src/renderer/shell/inspectorLayout.test.ts \
    src/renderer/shell/inspectorTabs.test.ts src/renderer/shell/Inspector.parity.test.tsx

 Test Files  14 passed (14)
      Tests  85 passed (85)
```

批次 B（D10/D11/D12/D15/D16/D17/D18/D19）：

```
$ npx vitest run --root . src/renderer/services/update-coordinator.test.ts src/renderer/components/UpdateBanner.test.tsx \
    src/main/releaseUpdate.test.ts src/renderer/shell/panels/diffReview.test.tsx \
    src/renderer/components/ConversationActivity.parity.test.tsx src/renderer/shell/panels/documentPreviewRegistry.test.tsx \
    src/renderer/shell/panels/FilesPanel.test.tsx src/renderer/services/i18n.test.ts \
    src/renderer/shell/themes.test.ts src/renderer/styles/styleContracts.test.tsx

 Test Files  10 passed (10)
      Tests  42 passed (42)
```

批次 C（D4/D20-D28/D31-D33）：

```
$ npx vitest run --root . src/main/electron.lifecycle.test.ts src/main/electron.multiWindow.test.ts \
    src/renderer/services/shortcuts.test.ts src/renderer/components/ForkTree.test.tsx \
    src/renderer/components/ForkTree.regression.test.ts src/renderer/components/UltraplanPanel.test.tsx \
    src/renderer/components/ConversationQueuePanel.test.tsx src/renderer/components/PaneWorkspace.test.tsx \
    src/renderer/services/voiceHudProtocol.test.ts src/renderer/components/VoiceOverlay.component.test.tsx \
    src/renderer/services/speechPlayback.test.ts src/renderer/services/audioDevices.test.ts \
    src/renderer/services/slashCommands.test.tsx src/renderer/services/pluginSlashCommands.test.ts \
    src/renderer/components/ConversationNodeRegistry.test.tsx

 Test Files  15 passed (15)
      Tests  34 passed (34)
```

### 2.2 TypeScript（两个 tsconfig 都 0 错误）

```
$ npx tsc -p tsconfig.renderer.json --noEmit
RENDERER_EXIT=0          # 无输出

$ npx tsc -p tsconfig.electron.json --noEmit
ELECTRON_EXIT=0          # 无输出
```

### 2.3 完整 renderer+main vitest 套件

```
$ npx vitest run --root .
 Test Files  2 failed | 76 passed (78)
      Tests  4 failed | 349 passed (353)
```

仅剩的 4 个失败都是**基线既有失败，不在 Z7 rows 内**（引用不修）：

```
 FAIL  src/main/electron.navigation.test.ts > Electron development navigation trust > blocks a URL whose text starts with the dev origin but whose parsed origin is different
 FAIL  src/main/electron.navigation.test.ts > Electron development navigation trust > allows pages served from the exact dev origin
   → AssertionError: expected "vi.fn()" to be called at least once (electron.navigation.test.ts:64)
   + 2 个 Unhandled Rejection: TypeError: dialog.showErrorBox is not a function (src/main/electron.ts:1831)

 FAIL  src/renderer/components/x2/x2.test.tsx > BrowserSettingsSection > offers exactly the four takeover modes plus CDP and proxy inputs
   → BROWSER_MODES 实际含 6 项（auto/live_chrome 为 x2 后加），测试断言 4 项（x2.test.tsx:149）
 FAIL  src/renderer/components/x2/x2.test.tsx > ComputerStatusSection > shows the probing hint before the status arrives
   → ReferenceError: window is not defined (ComputerStatusSection.tsx:64, SSR 渲染)
```

（electron.navigation 归 D1/D2 域，x2 归扩展/桌面 x2 批次域，均非本批 rows。）

### 2.4 WIP 审查中的基线复现（证明 useAtlasStore.test 失败是既有的）

```
$ git stash push -m "wip-x6" -- frontend/src/renderer/store/useAtlasStore.x6.test.ts
$ git checkout ec0a9d47 -- frontend/src/renderer/store/useAtlasStore.test.ts frontend/src/renderer/store/useAtlasStore.ts
$ npx vitest run --root . src/renderer/store/useAtlasStore.test.ts
 Test Files  1 failed (1)
      Tests  1 failed | 24 passed (25)
   → TypeError: Cannot read properties of undefined (reading 'some') (useAtlasStore.ts:392)
$ git checkout HEAD -- ... && git stash pop
```

基线上同一测试同一位置失败 → 既有失败；因它挡住本批 D29 的测试文件，按"定向测试负责"原则修复。

### 2.5 D31 新增回归测试（electron.multiWindow.test.ts）

```
$ npx vitest run --root . src/main/electron.multiWindow.test.ts
 RUN  v5.0.4 D:/Atlas/.worktrees/w4-z7/frontend
 ✓ src/main/electron.multiWindow.test.ts (5 tests) 39ms
 Test Files  1 passed (1)
      Tests  5 passed (5)
```

覆盖：每会话一窗且重复打开只聚焦（loadURL 带 conversationId）、非法会话 id 在建窗前抛「无效的会话 ID。」、窗口关闭后 id 可重开、最小化窗口恢复而非新建、will-navigate 只放行 app origin 且外部 http(s) 移交 `shell.openExternal`、window-open 一律 deny + 外链移交。

## 3. 逐行结论

| row | 结论 |
|---|---|
| D3 | ✅ CLOSED — TimelineProjection（delta 折叠保节点身份/非投影事件基线不变）+ compactTimelineReplay（重连压缩、语义等价、首节点 id 不变）；6 项组件测试 |
| D4 | ✅ CLOSED (W3-X6，复核在位) — keyed 注册/卸载 API + ConversationNodeRegistry.test.tsx 2 项 |
| D5 | ✅ CLOSED — SHA-256 IndexedDB 暂存/进度可取消/草稿引用恢复；4+2 项测试；base64 内联为发送协议设计 |
| D6 | ✅ CLOSED — per-session 草稿 + chip 序列化进模型文本 + 重载恢复；修复既有 TooltipProvider 失败后 2 项组件测试过 |
| D8 | ✅ CLOSED — per-session 布局持久（dock/split tab/浮动+位置）、浮动拖拽视口钳制、可插扩展 tab（builtin 不可遮蔽）；4+2+1 项 |
| D10 | ✅ CLOSED — 退避+抖动+journal+防并发 + 强制版本策略（低于声明最低版本强制/跳过不抑制/不可满足拒绝）+ 强制升级对话框无跳过入口；4+4+5 项 |
| D11 | ✅ CLOSED — unified/split 双模式（并排已实现）+ hover 预览 + 二进制标记 + hunk 接受/拒绝 + 行评论；5 项 |
| D12 | ✅ CLOSED — RunChangesSummary 每回合文件数/+add/−del 可点击进 Changes；组件测试覆盖 |
| D15 | ✅ CLOSED — PendingApprovalDock 挂滚动区外不可滚走 + Alt+1/2 + 选项更丰富；3 项 |
| D16 | ✅ CLOSED — 内置全族预览注册表 + 扩展注册/去重/dispose；3 项 + FilesPanel |
| D17 | ✅ CLOSED — namespace 注册/优先/隔离 + MutationObserver 重定位；7 项；全局目录保留为 fallback |
| D18 | ✅ CLOSED — --atlas-radius-xs..3xl 单调尺度绑定 Tailwind --radius-*；styleContracts 断言 |
| D19 | ✅ CLOSED — 全局 focus-visible + reduced-motion + IME 期不捕获快捷键；测试覆盖 |
| D20 | ✅ CLOSED — 单实例锁归属 + atlas:// 深链解析/拒绝凭据/重复参数/未知 section |
| D21 | ✅ CLOSED — 持久托盘（后台状态/安全模式/显式退出/驻托盘不退出） |
| D22 | ✅ CLOSED — 原生编辑角色 + 非冲突加速键 + renderer 快捷键注册表（IME 安全） |
| D23 | ✅ CLOSED — recoverRendererCrash 重新加载/禁用全部插件并重启/稍后 + safeMode 持久化 + 脱敏 bug bundle |
| D24 | ✅ CLOSED — forkFrom 任意尾双模式 + ForkTree 组件导航 + 空会话守卫 |
| D25 | ✅ CLOSED（仅回归测试，行为未动）— rewindTo files×2 + redoRewind 精确重做 |
| D26 | ✅ CLOSED — UltraplanPanel 载入/编辑保存/批准次序 + plan mode 带进 run + approvePlan 修剪 |
| D27 | ✅ CLOSED — 队列顺序/暂停恢复/steer 门槛 + redirect 立即转向保留未确认消息 |
| D28 | ✅ CLOSED — HUD 状态机 + 通话浮层控件 + TTS 设备路由 + 输入设备回退 |
| D29 | ✅ CLOSED — 探针分页（101 取一）消除满页歧义，不重不漏；4+1 项 store/UI 回归 |
| D30 | ✅ CLOSED — Chat/轨迹双模式 + 可读轨迹 + type/event 双键描述；3 项测试文件 |
| D31 | ✅ CLOSED（仅回归测试，行为未动）— PaneWorkspace 递归 split 树 + 新增 electron 多窗口回归 5 项 |
| D32 | ✅ CLOSED（仅回归测试，行为未动）— editMessage 截断重发 + fork 双模式 + MessageThread 历史控制 |
| D33 | ✅ CLOSED — 来源式注册表（去重/id 冲突拒绝/快照发布）+ 插件命令 JSON 校验 |

**没有 PARTIAL 遗留、没有 HARD**。26/26 rows CLOSED（含 3 条仅回归测试行）。

## 4. 提交

- `030bf8c4` fix(z7): finish recovered WIP — D29 probe pagination tests + D30 live-type trajectory descriptions
- `17e6542a` test(z7): D6 draft-restore UI fix + D31 multi-window regressions
- 本文件 + 账本更新（见随后的 docs 提交）

## 5. 事件名三源同步

本批**未新增/改名/删除任何桌面事件**，`core/atlas/api/event_names.py` / `runtimeEvents.ts` / `types/runtime.ts` 无需同步；未改 `core/` 任何文件。
