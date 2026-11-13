# W16 — 自动更新、交付物呈现与命名空间 i18n

## 结果

- **D10 — PARTIAL。** `UpdateBanner` 改用可测试的更新协调器：启动 8 秒后首次检查，成功后每 5 分钟检查；失败按指数间隔退避，加入 ±20% 抖动，最长 30 分钟。检查启动、成功和失败写入 `localStorage` journal，最多保留 200 条。强制版本策略没有接入，因此不标 CLOSED。
- **D13 — NOT-DONE。** agent 可调用的 `present` 工具没有注册。现有 agent 工具注册入口在 `core/atlas/engine/tools/registry.py`，超出 W16 的 `frontend/src/` 与 `core/atlas/api/` 所有权；本批没有用独立 API 或未连接的卡片冒充工具闭环。
- **D17 — PARTIAL。** 增加 locale namespace 注册和 `tn(namespace, source)` 查询，并把更新提示中的六条操作文案放进 `updates` namespace。其余约 7.7k 全局 source-string 目录和 DOM MutationObserver 翻译路径仍未迁移。

## 改动文件

- `frontend/src/renderer/components/UpdateBanner.tsx`
- `frontend/src/renderer/services/update-coordinator.ts`（新增）
- `frontend/src/renderer/services/update-coordinator.test.ts`（新增）
- `frontend/src/renderer/services/i18n.ts`
- `frontend/src/renderer/services/i18n.test.ts`
- `docs/parity/DSH-GAP-LEDGER.md`
- `tasks/dsh-parity/waves/RESULT-W16.md`（本文件）

没有修改 `core/atlas/api/`；D13 的实际工具注册层不在本批文件所有权内。

## 测试与构建

测试先行时，新协调器测试因 `update-coordinator` 尚不存在失败，namespace 测试因 `tn` 尚不存在失败；实现后运行：

```text
npm test -- --run src/renderer/services/update-coordinator.test.ts src/renderer/services/i18n.test.ts

Test Files  2 passed (2)
Tests       7 passed (7)
```

```text
npm run build
✓ built in 21.30s
BUILD_EXIT=0
```

构建脚本链包含 Electron TypeScript、preload 打包、renderer TypeScript 检查和 Vite production build；整体退出码为 0。Vite 输出仍有仓库既有的大 chunk 与动态导入提示。

## 真实模型回合

使用 `ATLAS_DATA_DIR` 隔离的临时数据目录，端口 `8836`，命令：

```text
python scripts/dsh_live_ws_check.py 8836 'Reply with exactly the word: OK'
```

最终真实输出：

```text
[event] run.started
[event] run.usage
[event] message.completed
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", ...}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

本次 smoke 证明通用 WebSocket run 使用 `deepseek-v4.1-flash` 完成；它没有调用 D10 更新源或 D13 `present` 工具。第一次隔离启动未复制当前 model-selection 配置，得到 HTTP 401；修正临时配置副本后最终回合通过。启动日志提示环境缺少 `fastembed`，该提示没有阻止这个精确回复回合完成。

## 收尾状态

- uvicorn 已停止，端口 `8836` 确认为空闲。
- 本次 live 使用的临时配置副本中的 `config/atlas.toml` 已删除。自动执行策略拒绝递归清理临时数据目录，因此 `%TEMP%\atlas-dsh-w16-live-20261114044903-2` 中还留有本次运行生成的数据与日志；没有写入 worktree 以外的项目数据目录。
- D10 和 D17 仍是 PARTIAL，D13 仍是 NOT-DONE。关闭它们需要补强制版本契约、迁移其余 i18n 文案，并由拥有 `core/atlas/engine/` 的批次实现和验证 agent 工具。
