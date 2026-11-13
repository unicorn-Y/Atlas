# Batch E — Desktop/API

## 结果

关闭：D9（断连提示可重试；Electron restart 会先确认）。

部分完成：D3（去掉 800-event 截断，历史事件不再静默丢失；每次 timeline 仍按全量事件重建，chunk folding/incremental projection 未完成）、D30（Rollout 默认显示可读轨迹，保留原始事件切换；尚未形成完整 Chat/Trajectory 同一视图切换与筛选）。

未关闭：D1、D2、D4、D5、D6、D7、D8、D10、D13、D14、D17。Batch D 的 D4/注册表原语虽可显示自定义节点，但中央内置 switch 迁移仍不完整。

## 改动文件

- `frontend/src/renderer/App.tsx`
- `frontend/src/renderer/components/ConnectionRecovery.tsx`（新增）
- `frontend/src/renderer/components/ConnectionRecovery.test.tsx`（新增）
- `frontend/src/renderer/services/runtimeEvents.ts`
- `frontend/src/renderer/services/runtimeEvents.test.ts`
- `frontend/src/renderer/shell/panels/RolloutPanel.tsx`
- `frontend/src/renderer/shell/panels/trajectory.ts`（新增）
- `frontend/src/renderer/shell/panels/trajectory.test.ts`（新增）

## 测试

```text
rtk npm test -- --run src/renderer/components/ConnectionRecovery.test.tsx src/renderer/services/runtimeEvents.test.ts src/renderer/shell/panels/trajectory.test.ts src/renderer/components/ConversationNodeRegistry.test.tsx src/renderer/components/timeline.test.ts

Test Files  5 passed (5)
Tests       32 passed (32)
```

```text
rtk npx tsc -p tsconfig.renderer.json --noEmit
TypeScript: No errors found
```

另外 `rtk python -m pytest -q -p no:cacheprovider tests/test_event_contract.py` 已包含在 Batch B/C 联合验证中并通过；本批没有修改事件名真源。

## 真实模型回合

命令：`rtk python scripts/dsh_live_ws_check.py 8811 "Reply with exactly the word: OK"`

```text
[reply] 'OK'
[result] terminal=run.completed chars=2
```

终止事件的 runner 输出为 `run.completed`，模型为 `deepseek-v4.1-flash`，input 9794/output 2，cached input 9600。

## 未完成项与原因

D3 的 per-node incremental projection 尚未实现；D30 目前是轨迹/原始 JSONL 视图，不是完整 Chat 与 Trajectory 的双态会话 renderer。其它未关闭行尚无实现或验证证据，故未标成完成。
