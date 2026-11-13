# W13 结果：D4 / D30

## 状态

| Row | 状态 | 证据与未完成项 |
|---|---|---|
| D4 | PARTIAL | 所有内置 timeline kinds 已按 kind 注册 renderer，`TimelineRow` 不再有中央 `switch`；扩展注册/卸载及重复注册有测试。真实进程验收未通过，因此按 CLOSED 门槛仍为 PARTIAL。 |
| D30 | PARTIAL | 在主会话 thread 加入“对话 / 轨迹”视图切换，轨迹显示当前运行事件的可读描述和时间。当前仅使用内存中的运行事件，未覆盖已完成会话的历史归档，也未持久化视图选择。 |

## 修改文件

- `frontend/src/renderer/components/MessageThread.tsx` — 加入主会话视图切换。
- `frontend/src/renderer/components/ConversationActivity.tsx` — 将内置 timeline node 移入 keyed renderer registry，移除 `TimelineRow` 中央 switch。
- `frontend/src/renderer/components/ConversationNodeRegistry.test.tsx` — 覆盖内置 renderer 路由及重复注册保护。
- `frontend/src/renderer/components/ConversationTrajectory.tsx` — 新增可读事件轨迹组件。
- `frontend/src/renderer/components/ConversationTrajectory.test.tsx` — 覆盖轨迹顺序和内容。
- `docs/parity/DSH-GAP-LEDGER.md` — 仅更新 D4、D30 两行。

## 验证

测试命令：

```text
npm test -- --run src/renderer/components/ConversationTrajectory.test.tsx src/renderer/components/ConversationNodeRegistry.test.tsx
```

真实输出：

```text
Test Files  2 passed (2)
Tests       3 passed (3)
```

构建命令：`npm run build`

真实输出摘要：TypeScript 主进程/renderer 检查通过，Vite production build 完成（5436 modules transformed，`✓ built in 25.63s`）。构建有既存 chunk size 和重复静态/动态导入警告。

真实模型验证：按 runner 使用端口 8833 启动 Uvicorn，执行 `python scripts/dsh_live_ws_check.py 8833 "Reply with exactly the word: OK"`。但 worktree 当前配置实际选择 `anthropic/claude-sonnet-4-20250514`，并非 runner 指定的 DeepSeek，因此此轮不算指定模型验证。运行在模型回复前输出 `run.failed`；后端日志定位为 `core/atlas/engine/kernel/loop.py:1540` 对 `requested_output_limit=None` 执行 `int()`，完整异常为 `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'`。没有模型回复 `OK`，本批没有真实模型成功证据。服务已停止。

## 边界

本批只改 W13 前端 components 所有权目录、本结果文件，以及 parity ledger 中 D4/D30 两行；未改其他批次目录，也未处理上述后端失败。
