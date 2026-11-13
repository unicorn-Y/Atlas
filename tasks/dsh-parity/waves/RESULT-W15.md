# W15 — D7 / D8

## 状态

- **D7 — PARTIAL**：`startRun` 与 `attachRun` 都检测非连续事件序列；发现缺口时关闭当前 WebSocket，以最后连续 cursor 发起 `resume`，让服务端重放缺页。`attachRun` 在初次连接后断开时也会继续退避重连。当前协议仍没有首帧 header/tail/cursor/投影基线，也没有独立 `page()` API，因此没有关闭整行。
- **D8 — PARTIAL**：右侧 Inspector 已支持 per-session 当前 tab、宽度、浮动状态及 split tab 持久化；加入单层双栏布局、浮动/停靠切换和扩展 tab 注册/卸载 API。split 右侧对内置 tab 目前显示导航占位，布局不是递归 split tree，浮动面板也还不能拖动，因此没有关闭整行。

## 改动文件

- `backend-adapter/src/client.ts`
- `backend-adapter/tests/client.test.ts`
- `frontend/src/renderer/shell/Inspector.tsx`
- `frontend/src/renderer/shell/inspectorLayout.ts`
- `frontend/src/renderer/shell/inspectorLayout.test.ts`
- `frontend/src/renderer/shell/inspectorTabs.ts`
- `frontend/src/renderer/shell/inspectorTabs.test.ts`
- `docs/parity/DSH-GAP-LEDGER.md`

## 测试与检查

命令：

```text
rtk npx vitest run --root .. backend-adapter/tests/client.test.ts -t "same run after disconnect|sequence gap"
```

真实输出：

```text
Test Files  1 passed (1)
Tests       3 passed | 17 skipped (20)
```

命令：

```text
rtk npm test -- --run src/renderer/shell/inspectorLayout.test.ts src/renderer/shell/inspectorTabs.test.ts
```

真实输出：

```text
Test Files  2 passed (2)
Tests       4 passed (4)
```

命令：

```text
rtk npx tsc -p tsconfig.renderer.json --noEmit
```

真实输出：

```text
TypeScript: No errors found
```

`git diff --check`：退出码 0，无输出。

另一次运行整个 `backend-adapter/tests/client.test.ts` 时观察到 17 passed、1 failed；失败用例 `accepts successful empty responses for void backend operations` 报错 `TypeError: adapter.deleteFact is not a function`。这与本批改动无关，但未对照提交前基线，故这里只记录为未归因失败。D7 相关 reconnect/gap 测试单独运行通过。

## 真实模型回合（端口 8835）

执行：

```text
rtk python scripts/dsh_live_ws_check.py 8835 "Reply with exactly the word: OK"
```

服务器启动并接收了 WebSocket `run.start`，但真实模型回合未完成：

```text
[event] run.started
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' ..."}
[reply] ''
[result] terminal=run.failed chars=0
```

后端日志定位到 `core/atlas/engine/kernel/loop.py:1540`：`int(requested_output_limit)` 收到 `None`，异常发生在模型请求前。该 worktree 加载的是生成的 Anthropic 默认模型配置，不是 runner 指定的 DeepSeek 配置；没有模型回复，不能计为真实模型通过。本批未修改后端或 worktree 配置。

## 未完成与环境痕迹

- D7 要补齐服务端的首帧基线与分页读取协议，才能覆盖 header/tail/projection baseline 和 `page()`。
- D8 要将第二个内置 panel 接入真实 renderer，并将单层布局升级为递归 split tree；浮动窗口还需拖动交互。
- 本次后端启动在 worktree 的忽略目录 `data/` 下生成了运行期数据库、日志和状态文件。清理这些递归目录的命令被执行策略拦截；未尝试其他删除方式，未将这些文件加入提交。
