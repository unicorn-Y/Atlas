# W12 结果

## 行状态

- **D1 — PARTIAL。** Renderer 继续消费 preload 提供的 `window.atlasDesktop.apiBaseUrl`。OS 分配端口、认证载体和 boot injection 的生产端位于 main/preload，共享 IPC 不属于 W12 的 `frontend/src/renderer/` 目录，本批未改。
- **D2 — PARTIAL。** Renderer 消费现有的 typed `BackendStartupProgress`（含 `ready` / `failed`）；完整的 host IPC 生命周期事件及其 typed producer 位于 main/preload/shared IPC，本批未改。
- **D3 — PARTIAL。** 新增 `TimelineProjection`，按 run 维护投影；连续 `message.delta` 仅更新当前 reply node，并保留其它 timeline node 的引用。历史被替换/截断时会重建；非 delta 结构事件仍调用完整 `buildTimeline`，压缩重连重放也未实现。

## 修改文件

- `frontend/src/renderer/components/timelineProjection.ts` — per-run 增量投影器，高频连续 reply delta 折叠到当前 reply node。
- `frontend/src/renderer/components/timelineProjection.test.ts` — 与 `buildTimeline` 对照投影结果，并验证未变化 node 的引用稳定性及事件前缀替换/截断回退。
- `frontend/src/renderer/components/MessageThread.tsx` — 主会话时间线使用增量投影器。
- `frontend/src/renderer/components/ConversationActivity.tsx` — 活动轨迹使用增量投影器。
- `frontend/src/renderer/components/ProgressCapsule.tsx` — 进度摘要复用增量投影结果。
- `frontend/src/renderer/App.tsx` — TimelineNav 使用增量投影器。
- `docs/parity/DSH-GAP-LEDGER.md` — D1–D3 更新为 PARTIAL，并记录当前差距。

## 验证

命令：

```text
cd frontend
npm test -- --run src/renderer/components/timelineProjection.test.ts src/renderer/components/timeline.test.ts
npx tsc -p tsconfig.renderer.json --noEmit
git diff --check
```

实际输出：

```text
Test Files  2 passed (2)
Tests       22 passed (22)
TSC_RENDERER_EXIT=0
DIFF_CHECK_EXIT=0
```

真实模型验证：按要求在端口 `8832` 启动本 worktree 后端并运行：

```text
python scripts/dsh_live_ws_check.py 8832 "Reply with exactly the word: OK"
```

未通过，退出码 `1`。实际终端事件为 `run.failed`，错误：`TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'`，回复为空。该次进程启动时从示例生成了 worktree `config/atlas.toml`，日志报告配置默认模型为 `claude-sonnet-4`，因此没有验证到计划指定的 `deepseek-v4.1-flash`；未读取或复制真实配置/密钥。后端随后已停止。真实模型链路状态为 **未验证**。

## 结论

W12 未满足 CLOSED 标准：D1、D2 的 host 侧能力超出本批目录边界；D3 仅对连续 reply delta 增量化；真实模型回合失败且没有 DeepSeek 输出。以上未完成项均保留在 ledger 与本结果中。
