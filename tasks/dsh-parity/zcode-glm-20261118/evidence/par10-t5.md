# PAR-10-T5 MCP 子进程退出状态与恢复

日期：2026-11-19（本机时区 UTC+8）
执行：PAR-10-T5 子代理（后台任务）
状态：候选树实现与真机复验完成；**不合回、不 commit、不 push、不 merge、不 stash**。

## 0. 工作树与边界

| 项 | 值 |
|---|---|
| 候选树 | `D:\Atlas\.worktrees\zcode-par10-mcp-recovery` |
| 分支 | `zcode/par10-mcp-recovery` |
| HEAD | `060071ab2ecf86d41cab90e98160183ce126bc69` |
| 源树（只读） | `D:\Atlas\.worktrees\zcode-exec05-mcp`，分支 `zcode/exec05-mcp-status`，同一 HEAD |
| 源树写者 | 已停止；复核前后 `git status` 与 diff 哈希均未变化 |

- 主工作区、`data/memory/**`、账号/凭据/在线 registry、其他候选树均未触碰。
- 未整理主工作区既有未提交改动；本包只改候选树与 `tasks/dsh-parity/.../evidence/` 回执/日志。
- 测试夹具只在候选树 `.tmp/par10-mcp-real/**` 与 `.tmp/par10-final*/**`（均被 `.gitignore` 的 `.tmp/` 覆盖）。
- 未访问在线 registry；真实 stdio 子进程均为本机临时 Python/Node 脚本。

## 1. 基线、IMPL-2 移入与哈希

### 1.1 源树未提交改动（IMPL-2）

`git diff --stat`：3 files changed, 63 insertions(+), 12 deletions(-)
`git diff | sha256sum`：`2129b34286605cddaa41629e1cdfd9d6b1c5f17b7b3d3cf086c8efbc290b79b4`

| 文件 | 基线 HEAD `060071ab` sha256 | 源树工作副本 sha256 |
|---|---|---|
| `core/atlas/tools/mcp_client.py` | `733bc457f7badaf3f9420a94cfc55fa5b206e257d620a538bfdbed173c506d2c` | `9daae96aefc5bb0dde7d45dcf897bd01bf836dfcdcb61f87f5d2d01f8922de65` |
| `core/atlas/tools/node_runtime.py` | `a71797ee4331a9074d382fcc18c73b68cfa3d7e0474d5a4d4dfbc0734f83c351` | `ff23c6e780409505089c3159b352d92e7c5a939913374418b213e3bc58f2cab6` |
| `core/tests/test_mcp_client.py` | `3e645fba4b19bc318b52a627b51c47bc9ed5d5c22667a110a06f6e2b766edac2` | `fd4a5c48b09b8a6beeb38daf6fe69b1ca9547a985da6d38bd38c155e7dbc60d4` |

移入方式：源树 `git diff --binary` 导出为 `evidence/par10-t5-impl2.patch`（sha256 同为 `2129b34...`），
在候选树 `git apply --check` 后 `git apply`。移入后三文件 sha256 与源树工作副本逐字节一致；
源树 diff 哈希在复核结束时仍为 `2129b34...`。

### 1.2 候选树最终改动

`git diff --stat`（含 IMPL-2）：

```
 core/atlas/api/diagnostics_router.py |  10 +-
 core/atlas/api/run_drive.py          |   1 +
 core/atlas/api/tools_router.py       |   4 +-
 core/atlas/tools/mcp_client.py       | 352 +++++++++++++++++++++++++++++++----
 core/atlas/tools/node_runtime.py     |  10 +-
 core/tests/test_mcp_client.py        |  39 +++-
 6 files changed, 361 insertions(+), 55 deletions(-)
```

另有新增未跟踪测试 `core/tests/test_mcp_recovery.py`（11 个用例）。
`git diff | sha256sum`：`83bbc759fcd348c90591f43cd418386daf0337e1f5464b2e080973f1e161d317`。

| 文件 | 候选树 sha256 |
|---|---|
| `core/atlas/tools/mcp_client.py` | `37683a9061aa7f6dedb6597796fd4f6531f71c5d77229b3e873f5387ecf49503` |
| `core/atlas/api/run_drive.py` | `cb11faf01f183ea8edcd967bd04a6805b0589f31f3b6c3df3933734463a3e657` |
| `core/atlas/api/diagnostics_router.py` | `29cce7a23fc4a48df581b360b101eeee1f52232451f21fbc9de09548b13cd124` |
| `core/atlas/api/tools_router.py` | `96aff0b300747c10c8836d58392992102ccd4eb773ea42064a0c4bfa58e899ce` |
| `core/tests/test_mcp_recovery.py` | `ea79dc0854934eff7185b0958822de8105db95cc5583d977b85d2c70f353556e` |

## 2. DSH 可观察对照（上游 `dsh-v0.2.2-rc.4`，commit `3f321d32`）

源码检出：`D:\ENGINE-V3-UPSTREAM-20261118\deepseek-harness`（`git describe` = `dsh-v0.2.2-rc.4`）。

| DSH 锚点 | 行为 |
|---|---|
| `packages/mcp/mcp-client/src/connection.ts:34-52` | 重连默认 `enabled=true`、`initialDelayMs=500`、`maxDelayMs=30000`、`maxAttempts=10` |
| `connection.ts:196-226` | 掉线后 `failedAttempts++`；超过上限 → `failed/gave-up` 并注销工具；否则指数退避 `min(maxDelay, initial*2^(n-1))`，发布 `reconnecting`（attempt/maxAttempts/nextRetryAtMs/lastError），日志 “connection lost; reconnecting in Xms (attempt n/max)” |
| `connection.ts:210` | 连接存活超过 `maxDelayMs`（稳定性窗口）才清零本轮预算 |
| `connection.ts:292-294` | `client.onclose` → `lost()` → 关闭 generation 后进入 `scheduleReconnect` |
| `connection.ts:329` | 恢复后重同步工具，发布 `connected`，日志 “reconnected and re-synced tools” |
| `packages/mcp/mcp-client/src/types.ts:12-56` | 可观察状态：`closed` / `waiting-credentials` / `connecting` / `connected` / `reconnecting` / `failed{gave-up,reconnect-disabled,unclosed-generation}` |
| `packages/mcp/mcp-manager/src/index.ts:342-...` + `types.ts:38-47` | `restart` 销毁旧实例并以“新鲜重连预算”重建；状态变化经 `mcp-manager/status` 事件发布；`disabled` 条目只发布 `disabled`，不 mount/不 spawn |
| `packages/mcp/mcp-client/tests/reconnect.spec.ts:330,383,575,601,623,641` | 传输关闭后重连并重同步工具；达到上限注销工具并终态失败；退避中 dispose 取消重连；重连禁用；稳定性窗口重置预算；“短暂成功再崩溃”仍耗尽上限 |

Atlas 修复前既有策略（基线）：

- `_monitor_connection` 已有 10 次上限、0.5→30s 指数退避、60s 稳定窗口、`unreachable` 终态与显式 `restart_server` 清预算。
- 但 `_start_transport_owner` 的 owner 只 `await stop_event.wait()`，标准输入/输出 EOF 不会结束 owner；
  `_monitor_connection` 永远等不到掉线，状态、工具索引、健康记录都不会变化（PAR-09 已观测）。
- `restart_server` 路由只接受 `get_server_names()`（当前连接）里的名字，无法重连失败/掉线中的服务器。
- `/api/runtime/dependency-check` 的 `available` 只把 `failed` 视为阻塞，`unreachable` 反而报可用；
  `/api/diagnostics/alerts` 只识别 `failed/error/disconnected`，终态 `unreachable` 不可见。
- 自动重连每次都会撞上 60s 启动失败冷却：`_connect_server` 直接 return，不 spawn，却消耗重试次数。

## 3. 基线复现（修复前）

夹具：`.tmp/par10-mcp-real/mcp_server.py`（mcp SDK 2.0.0 官方 low-level `Server` + `stdio_server`，真实子进程，`echo` 工具，写 starts/exits/pid marker）。
驱动：`.tmp/par10-mcp-real/driver.py baseline-kill`，不 mock 任何 `MCPClient` 方法，只写临时 `atlas.toml`/`ATLAS_DATA_DIR`。

日志：`evidence/par10-t5-baseline-kill.txt`。关键观测（与 `par09-mcp-lifecycle.txt` 一致）：

- 连接后工具可调用：`real__echo` → `echo:before-kill`。
- kill PID `63452` 后 8 秒采样（t=1.0…8.1）：
  - `starts=1`、`pid` 仍为 63452 且 `killed_pid_alive=false`；
  - `tool_index=["real__echo"]`、状态 `connected=true`、`available=true`。
- 直到 `stop()` 才清理；无有界重连、无状态/健康变化。

## 4. 实现（最小补齐）

### 4.1 传输 EOF → owner 退出（`mcp_client.py`）

- 新增 `_ObservedReceiveStream`：包裹 stdio transport 的读流，转发消息与 `last_context`，
  在 `EndOfStream` / `ClosedResourceError` / `BrokenResourceError` 时标记“传输关闭”并转换为正常 EOF。
- `_start_transport_owner(..., observe_transport_close=True)`（仅 stdio 传入）让 owner 同时等待
  `stop_event` 或“传输关闭”；非停止原因关闭时抛出 `ConnectionError`。
- 不依赖 SDK 私有属性、不增加 ping/协议流量；HTTP/SSE 路径不改，沿用原有会话恢复。

### 4.2 掉线状态与工具索引（`_monitor_connection`）

- owner 结束后立即：从 tool index 移除该服务器全部工具、从 `_servers` 移除 handle，
  发布 `state=reconnecting`、`connected=false`、`tool_discovery=pending`、`tool_count=0`、
  `blocking_reason="MCP connection lost; reconnecting"`，并写 `_progress(..., "reconnecting", ...)`。
- 有界重连循环保留既有 10 次 / 0.5→30s 退避；新增：
  - 每次尝试前清掉该服务器的启动失败冷却（自动重连本身是显式重试），避免“不 spawn 却消耗次数”；
  - 掉线时若已消耗次数 ≥ 上限，直接进入 `unreachable`（覆盖“短暂连上又崩”的 crash loop）；
  - 尝试状态发布为 `reconnecting`（首次启动仍是 `starting`），成功后发布 `connected` + `ready` 进度与
    `mcp.server_reconnected` 日志；
  - 终态 `unreachable` 保持工具索引为空、`tool_discovery=failed`、理由含 “retry explicitly to reconnect”，
    并写 `failed` 进度。

### 4.3 停止 / 禁用 / 并发语义（`mcp_client.py`、`tools_router.py`）

- `_connect_server` 开头检查 `cfg.enabled`：禁用服务器在任何入口（start、restart、重连循环）都不 spawn，
  状态固定 `disabled`。
- `stop()`：先置 `_stopping`，取消重连/启动任务，停止 handle，清索引；最后把所有非禁用状态结算为
  `stopped`（掉线中/握手中不再残留 `reconnecting`/`starting`）。
- 每个服务器一把 `_lifecycle_lock`；`restart_server` 串行化并先取消、join 该服务器的重连循环；
  `disconnect_server` 同样取消重连循环后再停 handle（单服务器用户停止不会留下后台循环）。
- `restart_server` 在 stop 进行中（`_stopping`）直接返回，不复活实例；连接握手完成时若发现已进入 stop，
  会立即停掉该 handle、移除工具并结算 `stopped`（关闭 stop 快照与 connect 完成之间的竞态）。
- `restart_server` 对 `disabled` 配置只发布 `disabled`，不连接。
- `/api/mcp/servers/{name}/restart` 现在接受“已配置但当前未连接”的服务器（不再仅限 live 连接），
  使 `failed`/`unreachable`/`reconnecting` 能走显式恢复入口。

### 4.4 健康/状态可观察面

- `get_runtime_status()`：`failed` 与 `unreachable` 都 fail-closed；`starting`/`connecting`/`reconnecting`
  均为 pending；`available=false`，blocker 分别为失败理由 / “MCP server is reconnecting” /
  “MCP server startup is still in progress”。
- `/api/diagnostics/alerts` 与 `/api/diagnostics/tasks`：告警状态集合加入 `unreachable`（理由优先取
  `blocking_reason`）；任务列表包含 `reconnecting`。
- `run_drive.py` 重放 `mcp.startup.progress` 的 state 白名单加入 `reconnecting`（仍使用既有事件名，
  未新增/改名事件；三真源事件表未变）。
- `_progress` 记录 `reconnecting` / `failed` / `ready`，按原有安全文本截断，不含命令参数或凭据。

## 5. 状态机 / 重连参数（候选树最终语义）

```
disabled ──(永不 spawn)──────────────────────────────────────────────┐
starting/connecting(attempt=0) ──成功──> connected ──EOF/掉线──> reconnecting
        │                                   │                         │
        └─失败─> failed（启动失败，冷却 60s）  │  工具索引清空、connected=false
                                               │                         │
connected ──stop()/disconnect()──> stopped     │        每次尝试 n=1..10
                                               │        延迟 0.5*2^(n-1)，上限 30s
                                               └──成功(ready)──> connected（60s 后预算清零）
                                               └──n>10 或已耗尽──> unreachable（终态，工具不可见）
restart_server：清 unreachable/attempts/冷却 → disconnect（取消重连）→ connect；disabled 只回 disabled
```

| 参数 | 值 | 位置 |
|---|---|---|
| 重连次数上限 | 10（每轮掉线独立预算；稳定 60s 后清零） | `_MCP_MAX_RECONNECT_ATTEMPTS` |
| 初始退避 / 上限 | 0.5s / 30s，逐次翻倍 | `_MCP_RECONNECT_INITIAL_DELAY_SECONDS`、`_MCP_RECONNECT_MAX_DELAY_SECONDS` |
| 稳定性窗口 | 60s 连续在线才清预算 | `_MCP_RECONNECT_STABLE_SECONDS` |
| 启动失败冷却 | 60s（自动重连尝试会绕过它） | `_MCP_START_FAILURE_COOLDOWN_SECONDS` |
| 传输关闭观察 | 仅 stdio（本次缺口） | `_start_transport_owner(observe_transport_close=True)` |

## 6. 真机验证（真实本地 stdio / 真实子进程）

环境：

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 x64 |
| Python | `C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`，3.11.16 |
| pytest | 9.1.1；pytest-asyncio 1.4.0 |
| mcp SDK | 2.0.0（`--basetemp` 均在候选树 `.tmp/` 下，`-p no:cacheprovider`） |

所有场景日志均在 `evidence/par10-t5-*.txt`；夹具真实启动/退出 marker（PID）并直接 `kill(PID, 9)`。

| 场景 | 结果（exit 0） | 关键观测 |
|---|---|---|
| `recovery`（real + other 两服务器） | 17 checks passed | kill real → `state=reconnecting`、`connected=false`、`real__echo` 移出索引；other PID 不变且 `other__echo` 仍可调用；约 3s 后新 PID 56900（被 kill 的是 64524）、`mcp.server_reconnected attempts=1`、工具索引恢复、`real__echo` 可调用；progress 记录 `reconnecting → ready`；stop 后无存活子进程 |
| `stop-during-recovery` | 4 checks passed | 掉线进入 reconnecting 后 `stop()`；4s 内 starts 1→1（无自动拉起），无存活子进程，状态 `stopped` |
| `disabled-no-spawn` | 4 checks passed | `enabled=false`：start 与显式 `restart_server` 均不 spawn，状态始终 `disabled` |
| `concurrent-restart` | 6 checks passed | 5 个并发 `restart_server` 全部完成；最终仅 1 个存活子进程，无兄弟进程泄漏；stop 清空所有 PID |
| `concurrent-stop-restart` | 3 checks passed | `restart_server` 与 `stop()` 并发；终态 `stopped`、无存活子进程 |
| `exhaustion`（crash-loop，驱动内把上限调为 3） | 7 checks passed | 初始 + 恰好 3 次重启后 `unreachable`；`starts` 恰为 4 个 PID；工具索引为空；`blocking_reason` 含 retry explicitly；`available=false`；stop 后无子进程 |
| `node-bundled`（旧打包 Node） | 7 checks passed | 真实打包 `node.exe` 启动自写 Node MCP server，kill 后恢复为新 PID；marker `execPath` 两次均为打包路径；stop 后子进程消失 |

补充：一次 crash-loop 观测（修复中）曾显示 6 次成功重连仍未收敛；原因是成功分支提前 return，未在
“下一次掉线”前检查预算。已加入掉线前置检查（见 §4.2），最终 `exhaustion` 以 4 次 spawn 收敛。

## 7. 打包 Node 证据边界（不冒充 v24）

本机只有旧打包产物：

- 路径：`D:\Atlas\frontend\windows-release\win-unpacked\resources\atlas\runtime\node\node.exe`
- 实际版本：`v22.23.3`（`node.exe --version` 与 marker `"node":"v22.23.3"` 一致）
- `frontend/windows-release/release-manifest.json`：app 0.1.0、commit `6c49b7f62a371c406211bb7ebd99598d38e25c7b`、
  构建时间 2026-10-05、`bundled_node.version=22.23.3`（`build.node_version=v24.18.1` 只是构建机 Node，不是打包 runtime）
- 候选树/主树均无当前源码构建的 `backend-release/runtime/node`；没有 v24.21.0 真实打包产物。

实际调用：`ATLAS_NODE_RUNTIME_DIR=<旧包 runtime/node> ATLAS_NODE_RUNTIME_REQUIRED=1`，
配置 `command="node"` 经 `_resolve_stdio_command` 选中上述 `node.exe`；marker 证明 execPath 正是该路径。
`get_node_runtime_status()` 返回 `available=true`、`version=v22.23.3`、`expected_bundled_version=v24.21.0`。

结论：**旧 v22.23.3 打包产物的真实 Node 子进程启动/被杀/重连已验收；当前源码 v24.21.0 的最终打包产物
未在本机验收**，不能声称 v24 真实包已通过。

## 8. 命令与退出码

| # | 命令（均在候选树/相应树执行；`python` = 上述 3.11.16 venv） | 退出码 | 结果 |
|---|---|---|---|
| 1 | `cd core && python -m pytest -q -p no:cacheprovider --basetemp=D:/Atlas/.worktrees/zcode-par10-mcp-recovery/.tmp/par10-final-basetemp tests/test_mcp_client.py tests/test_mcp_client_scope.py tests/test_mcp_batch_reconnect.py tests/test_mcp_reconnect_budget.py tests/test_mcp_recovery.py` | 0 | **47 passed**（22+5+2+7+11） |
| 2 | `python .tmp/par10-mcp-real/driver.py recovery --data-dir .tmp/par10-final2/data/recovery` | 0 | 17 checks, 0 failed |
| 3 | `... driver.py stop-during-recovery ...` | 0 | 4 checks, 0 failed |
| 4 | `... driver.py disabled-no-spawn ...` | 0 | 4 checks, 0 failed |
| 5 | `... driver.py concurrent-restart ...` | 0 | 6 checks, 0 failed |
| 6 | `... driver.py concurrent-stop-restart ...` | 0 | 3 checks, 0 failed |
| 7 | `... driver.py exhaustion ...` | 0 | 7 checks, 0 failed |
| 8 | `ATLAS_NODE_RUNTIME_DIR=<旧包> ATLAS_NODE_RUNTIME_REQUIRED=1 python ... driver.py node-bundled ...` | 0 | 7 checks, 0 failed |
| 9 | `python ... driver.py baseline-kill ...`（修复前代码，IMPL-2 基线） | 0 | 2 checks；8s 内无重连观测 |
| 10 | `python -m py_compile atlas/tools/mcp_client.py atlas/api/run_drive.py atlas/api/diagnostics_router.py atlas/api/tools_router.py` | 0 | 语法通过 |
| 11 | 源树对比：`cd ../zcode-exec05-mcp/core && python -m pytest ... tests/test_mcp_server_atlas_sync.py` | 1 | 2 failed / 5 passed（`ModuleNotFoundError: No module named 'tools'`） |
| 12 | 候选树同批：`tests/test_mcp_startup_diagnostics.py tests/test_mcp_server_atlas_sync.py` | 1 | 2 failed / 8 passed，失败项与本包无关 |

说明：#11 的失败在**只含 IMPL-2 的源树**上完全相同，属既有环境/测试链问题
（`test_api_added_mcp_is_searchable_callable_and_removed_from_atlas`、
`test_plan_binding_does_not_prune_active_atlas_mcp_copy`），非本包改动引入；
日志 `evidence/par10-t5-source-atlas-sync.txt`。

## 9. 未覆盖项 / 风险

1. **初次启动失败不自动重试**：本包只补齐“已连接后子进程异常退出”的恢复；启动阶段失败仍沿用
   60s 冷却 + `failed` fail-closed。DSH 对首次连接也套用重连策略，如需对齐应另开包。
2. **非 stdio 传输没有主动 EOF 监控**：SSE / streamable HTTP 继续依赖调用错误触发的
   `_recover_expired_session`；本次只对 stdio 传 `observe_transport_close=True`，避免改变 HTTP 流语义。
3. **健康事件仍是“重放”而非实时推送**：`mcp.startup.progress` 由 run_drive 在 run 开始时重放
   `startup_progress`；运行中掉线/恢复的实时可观测面是 `/api/runtime/dependency-check`、
   `/api/diagnostics/alerts|tasks`（本次已补 `reconnecting`/`unreachable`）。MCPClient 没有全局事件总线，
   未新增推送通道。
4. **子进程检测依赖 stdout 管道 EOF**：若有孙进程继承并持有 stdout，检测会延迟（SDK transport 同一边界）；
   Job Object/进程树 kill 后的常规场景已实测。
5. **v24.21.0 打包产物未验收**：见 §7，本机只有 v22.23.3 旧包；版本 pin 不匹配在 status 中以
   `expected_bundled_version` 暴露，但 `available` 仍为 true（既有产品决策，本包未改）。
6. **崩溃循环预算上限在真机测试中被调为 3**（驱动内改模块常量，同一生产代码路径）；生产默认
   10 次/0.5→30s 由 `test_mcp_reconnect_budget.py` 的退避序列用例 `[0.5,1,2,4,8,16,30,30,30,30]` 覆盖。
7. 真实桌面 Electron 面板未启动；本次可观察面以 HTTP 路由/状态字典与真实子进程为准。
8. 未测试 OAuth/凭据环境下的重连；未触碰真实凭据。

## 附件

`par10-t5-impl2.patch`、`par10-t5-baseline-kill.txt`、`par10-t5-recovery.txt`、
`par10-t5-stop-during-recovery.txt`、`par10-t5-disabled-no-spawn.txt`、
`par10-t5-concurrent-restart.txt`、`par10-t5-concurrent-stop-restart.txt`、
`par10-t5-exhaustion.txt`、`par10-t5-node-bundled.txt`、`par10-t5-suites.txt`、
`par10-t5-source-atlas-sync.txt`。

PAR10_RECEIPT T5 READY