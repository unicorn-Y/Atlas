# WAVE 2 — V10 结果（D8、D10、D17）

## 结论

- **D8 — 实现完成，验收 PARTIAL。** 保留递归 pane split 与可注册 Inspector tab；浮动 Inspector 现在能从标题栏拖动，坐标限制在视口内并按 conversation 保存。dock、活动 tab、split tab、浮动状态及坐标都有 session-scoped layout 存储。全量 Vitest 有 4 个不相关测试文件失败，未把该全局门槛写成通过。
- **D10 — 实现完成，验收 PARTIAL。** 保留既有调度、退避、抖动和 200 条 journal；新增强制版本策略。Release notes 可声明 `Minimum-Atlas-Version: x.y.z`。主进程验证最低版本不高于当前 Release 并计算 `mandatory`；renderer 即使处于 source 更新通道也会检查 Release。低于最低版本时覆盖并锁定应用，mandatory 不受“跳过”或“稍后提醒”影响。全量 Vitest 有 4 个不相关测试文件失败，未把该全局门槛写成通过。
- **D17 — PARTIAL。** `updates` namespace 新增强制更新文案和带 3 个插值槽的版本提示，`tn()` 已支持 namespace 内的插值模式。其余约 7.7k 全局 locale 条目仍由 `t()` 和 `MutationObserver` 兼容路径消费；本轮没有将它们谎报为已迁移。

## 代码与测试

- D8：`frontend/src/renderer/shell/Inspector.tsx`、`inspectorLayout.ts`、`inspectorLayout.test.ts`。已有 `PaneWorkspace.test.tsx` 覆盖多层递归 split；新增坐标持久化、会话隔离和视口边界用例。
- D10：`frontend/src/main/releaseUpdate.ts`、`releaseUpdate.test.ts`、`frontend/src/shared/ipc.ts`、`UpdateBanner.tsx`。强制最低版本无论普通提醒偏好如何都会置为 mandatory；Release 最新版本低于其自报最低支持版本时拒绝该策略结果。
- D17：`frontend/src/renderer/services/i18n.ts`、`i18n.test.ts`、`UpdateBanner.tsx`。增加 namespace 插值匹配测试。
- `docs/parity/DSH-GAP-LEDGER.md` 已更新 D8、D10、D17 状态。

验证输出：

```text
npm test -- --run src/renderer/services/i18n.test.ts src/renderer/services/update-coordinator.test.ts src/renderer/shell/inspectorLayout.test.ts src/renderer/components/PaneWorkspace.test.tsx src/main/releaseUpdate.test.ts
Test Files  5 passed (5)
Tests       15 passed (15)
```

```text
npm run build
✓ built in 26.68s
```

构建包含 Electron TypeScript、preload 构建、renderer TypeScript 检查和 Vite production build，退出码为 0。Vite 仍提示既有动态/静态重复导入和大 chunk。

整个 `npm test` 也已运行：60 个测试文件中 56 个通过、4 个失败；277 项中 265 通过、12 失败，另有 8 个异步错误。失败文件为 `components/x2/x2.test.tsx`、`store/useAtlasStore.test.ts`、`main/electron.navigation.test.ts`、`main/backendProcess.test.ts`，均不属于本批改动。backendProcess 输出明确显示外部 PID 26980 占用 8765；未终止该进程。D8/D10/D17 聚焦测试仍全部通过。

## 指定 Atlas 通道实测

在启动后端的 PowerShell 进程设置 `http_proxy=http://127.0.0.1:7897` 与 `https_proxy=http://127.0.0.1:7897`，端口 `8840`；临时 `ATLAS_DATA_DIR` 使用隔离副本，key 没有写入环境变量。执行：

```text
python scripts/dsh_live_ws_check.py 8840 "Reply with exactly the word: OK"
```

观察到：

```text
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", ...}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

这证明指定 Atlas 通道的真实模型 WebSocket 回合成功；它不替代 D8/D10 的前端测试，也不证明 D17 全量迁移。PID 59040 的服务进程已停止，端口 `8840` 已确认关闭。模型回合数据在 `C:\Users\25011\AppData\Local\Temp\atlas-dsh-v10-live`；该目录没有进入仓库。Windows 执行策略拒绝了对这个已核实路径的删除操作，因此临时目录尚未清理，其中包括本轮复制的 `config/atlas.toml` 和 `data/user-settings.json`。

## 尚未关闭项

D17 的约 7.7k 全局 locale 条目和 MutationObserver 替换仍待按 UI namespace 批量迁移与组件验证，因此该 row 保持 PARTIAL。
