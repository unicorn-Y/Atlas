# PAR-09-MCP 复核收据

日期：2026-11-19（本机时区 UTC+8）
执行：PAR-09-MCP 子代理（独立后台任务，第 5 包补位）
工作树：`D:\Atlas\.worktrees\zcode-exec05-mcp`，分支 `zcode/exec05-mcp-status`，HEAD `060071ab`
状态：复核完成；**不合回、不 commit、不 push、不 merge**。

## 0. 基线与边界

- 动手前工作树只有 IMPL-2 三文件未提交改动，无其他写者（进程列表只命中本子代理自己的检查命令）：
  - `core/atlas/tools/mcp_client.py`（+26/-3）
  - `core/atlas/tools/node_runtime.py`（+10/-4）
  - `core/tests/test_mcp_client.py`（+39/-5）
  - `git diff --stat`：3 files changed, 63 insertions(+), 12 deletions(-)
  - `git diff` SHA-256：`2129b34286605cddaa41629e1cdfd9d6b1c5f17b7b3d3cf086c8efbc290b79b4`
- 复核结束时该 SHA-256 与 `git status` 未变化；本包只新增 `.tmp/` 下测试夹具与本收据/日志，未改任何产品代码。
- 主工作区代码、`data/memory/**`、账号/凭据/在线 registry 均未触碰。未整理既有未提交改动。

环境：

| 项 | 值 |
|---|---|
| OS | Windows 10.0.26200 x64 |
| Python | `C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`，3.11.16 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| mcp SDK | 2.0.0 |
| 系统 Node | v24.18.1 |
| 现有打包 Node | v22.23.3（旧包，见 §4） |

## 1. 既有 MCP 套件复跑

命令（工作目录 `D:\Atlas\.worktrees\zcode-exec05-mcp\core`）：

```
C:\Users\25011\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider ^
  --basetemp=D:/Atlas/.worktrees/zcode-exec05-mcp/.tmp/par09-mcp-basetemp ^
  tests/test_mcp_client.py tests/test_mcp_client_scope.py tests/test_mcp_batch_reconnect.py
```

结果：**29 passed，exit 0**，5 warnings，6.91s。收集 29 项、执行 29 项，无静默 deselect
（`test_mcp_client.py` 自身无 `pytestmark`，但 `core/tests/conftest.py:126` 的
`pytest_collection_modifyitems` 按文件/类自动加 lane marker，默认 `-m unit` 全部选中）。
分文件：`test_mcp_client.py` 22 + `test_mcp_client_scope.py` 5 + `test_mcp_batch_reconnect.py` 2。
日志：`evidence/par09-mcp-suites.txt`。

与 Codex 记录的 29 passed 一致，IMPL-2 的测试确定性修改可用。

## 2. 真实本地 stdio 链路

夹具在工作树 `.tmp/par09-mcp-real/`：

- `mcp_server.py`：用 mcp 2.0.0 官方 low-level `Server` + `stdio_server` 实现的真实子进程，
  提供 `echo` 工具，并在启动/退出时写 marker（PID、时间、argv）。
- `driver.py`：不做内部方法 mock，只注入临时 `atlas.toml`/`ATLAS_DATA_DIR`，通过正常
  `MCPClient.start()` → 工具发现 → `call_tool()` → `stop()`/`restart_server()` 驱动。

命令：

```
cd D:\Atlas\.worktrees\zcode-exec05-mcp
python .tmp/par09-mcp-real/driver.py lifecycle --data-dir .../.tmp/par09-mcp-real/data/lifecycle
```

结果：**25 checks passed，exit 0**。关键观测：

| 阶段 | 观测 |
|---|---|
| `start()` 立即态 | `available=false`，`blocking_reason="MCP server startup is still in progress"`，server=`starting` |
| 握手完成 | protocol `2025-11-25`，`state=connected`，`tool_discovery=complete`，`tool_count=1`，`available=true` |
| 工具清单 | `real__echo`；LLM schema 名为 `real__echo` |
| 真实调用 | `{"content":[{"type":"text","text":"echo:hello"}],"is_error":false}` |
| 停止 | `state=stopped`、`connected=false`、工具索引清空；子进程退出 marker 写入，PID 已不存在 |
| 再次 `start()` | 新 PID、重新发现 `real__echo`、`available=true` |
| `restart_server("real")` | 旧 PID 退出、新 PID 连接、工具重新发现 |
| 禁用服务器 | 同一次 start 中保持 `state=disabled`，未创建进程 |

“停止→重连”正常链路通过 `start→stop→start` 与 `restart_server` 两种方式验证。
日志：`evidence/par09-mcp-lifecycle.txt`。

补充观测（**未关闭项，非本包改动引入**）：直接杀掉已连接子进程后，8s 内未出现新 PID，
`get_runtime_status()` 仍报 `connected=true`、工具仍可列出；直到 `stop()` 才清理。
原因在基线代码：`_monitor_connection`（`mcp_client.py:848`）只 `await owner`
（`_start_transport_owner` 的 owner 等待 `stop_event`），transport EOF 不会结束 owner。
IMPL-2 diff 未触碰该路径（diff 仅 `:544` 与 `:1256` 两处），故属基线行为/环境既有缺口，
本包不修、不新增会失败的测试。详见 `evidence/par09-mcp-lifecycle.txt` 的
`OBSERVATION auto_reconnect`。

## 3. 异常状态矩阵

所有场景均使用真实临时配置/数据目录与真实子进程；退出码均为 0。

| 场景 | 结果 | 关键理由/脱敏 |
|---|---|---|
| 命令不存在 | `state=failed`（约 0.7s），`available=false` | `blocking_reason` 只含命令名与 `FileNotFoundError`，不含 `--token`、参数值、绝对参数路径 |
| 立即退出（stderr 打 secret） | `state=failed`（约 0.6s），`available=false` | secret 被替换为 `[redacted]`；脚本绝对路径显示为 `[local path]`；`PAR09_TEST_SECRET` 不出现原值 |
| initialize 返回 JSON-RPC error | `state=failed`（约 0.5s），`available=false` | 只显示 `MCPError` 类型，不显示服务端错误原文中的 secret |
| 一个连通 + 一个失败 | `available=false`，blocker 取失败服务器理由 | 已连服务器的工具仍可发现，但整体 MCP runtime fail-closed |
| 正常停止 | `state=stopped`，子进程 PID 消失 | 退出 marker 已写 |
| 显式重连 | `restart_server` 后新 PID、`connected=true`、工具清单恢复 | 旧 PID 消失 |
| 禁用服务器 | `state=disabled`，`available=true`，无子进程 | `blocking_reason="server is disabled"` |
| 未配置服务器 | `servers=[]`，`available=true`，无 blocker | `start()` 为 no-op |
| 启动过程中 `stop()`（边界观测） | 子进程被清理，但停止后 status 仍为 `starting`，`available=false` | 下一次 `start()` 会重置；基线既有行为，本包不修 |

启动失败路径均验证了 0.6s 后仍为 `failed`，不会回到 `starting`。
脱敏实现位置：`_stdio_startup_diagnostic`（`mcp_client.py:1531`，env 值替换、敏感 key/`sk-` 正则、
`--token` 后值替换、绝对参数路径替换）与 `_failure_reason`（`:1608`，只回传异常类型）。
错误中允许出现启动命令本身（可执行文件名/路径），不含命令行参数原值或凭据。

日志：
`par09-mcp-missing-command.txt`、`par09-mcp-immediate-exit.txt`、`par09-mcp-bad-initialize.txt`、
`par09-mcp-partial-failure.txt`、`par09-mcp-disabled.txt`、`par09-mcp-stop-during-start.txt`。

## 4. 打包 Node 选择：测试真实性判定

### 4.1 `test_bundled_node_resolves_from_installed_application_directory` 是环境模拟

`core/tests/test_mcp_client.py:20-35` 的实现：

- `monkeypatch.setenv("ATLAS_ROOT", str(tmp_path))`；
- 在 tmp 下造 `runtime/node/node.exe`（内容仅为 `b"node"`，从不执行）和
  `runtime/node/npm/bin/npx-cli.js`；
- 只断言 `resolve_node_runtime()` 返回这两个路径。

因此该测试**用的是环境模拟目录形状，不是真实打包安装路径**；它不启动 Node，也不验证
版本、npm/npx 可用性或协议链路。它模拟的形状与打包目标一致：
`frontend/package.json` 的 extraResources 将 `backend-release/runtime/node`
复制到 `resources/atlas/runtime/node`；`frontend/src/main/electron.ts:1795-1798` 在
`app.isPackaged` 时设置 `ATLAS_ROOT=<resources>/atlas`、
`ATLAS_NODE_RUNTIME_DIR=<resources>/atlas/runtime/node`、
`ATLAS_NODE_RUNTIME_REQUIRED=1`。

### 4.2 本机真实打包产物（只读使用）

本机存在旧打包产物：

- 安装/解包目录：`D:\Atlas\frontend\windows-release\win-unpacked\resources\atlas\runtime\node`
- `node.exe --version` = `v22.23.3`
- `windows-release/release-manifest.json`：app 0.1.0，构建时间 2026-10-05，
  commit `6c49b7f62a371c406211bb7ebd99598d38e25c7b`，bundled_node 22.23.3
- 工作树无 `frontend/backend-release/runtime/node`，主树无 `runtime/node`；
  本机没有由当前源码（v24.21.0）新构建的打包产物。

只读解析 + `_resolve_stdio_command()` 选择（worktree 与主树各跑一次，均 exit 0）：

| 源码树 | 常量 | 选择结果 | status |
|---|---|---|---|
| worktree（IMPL-2） | v24.21.0 | bundled node.exe + npx-cli.js | `available=true`，actual `v22.23.3`，expected `v24.21.0` |
| 主树 `D:\Atlas\core` | v22.23.3 | bundled node.exe + npx-cli.js | `available=true`，actual/expected 均为 `v22.23.3` |

日志：`par09-mcp-node-worktree.txt`、`par09-mcp-node-main.txt`。

### 4.3 真实打包 Node 端到端附加验证

用上述真实打包目录里的 `node.exe` 跑一个自写的最小 Node MCP stdio server
（`.tmp/par09-mcp-real/node_mcp_server.js`，仅用 Node 内建模块），
设置 `ATLAS_NODE_RUNTIME_DIR=<旧包 runtime/node>`、`ATLAS_NODE_RUNTIME_REQUIRED=1`，
通过正常 `MCPClient` 启动：

- 选择命令：`...\win-unpacked\resources\atlas\runtime\node\node.exe`；
- 握手 protocol `2025-11-25`，工具 `nodereal__node_echo`，调用返回 `node:packaged`；
- 子进程 marker 记录的 `execPath` 正是该打包 `node.exe`；停止后 PID 消失；
- **11 checks passed，exit 0**。

日志：`evidence/par09-mcp-node-bundled.txt`。

结论（不冒充）：

- 单元测试本身：**未使用真实打包路径**，只是 tmp 目录模拟。
- 本包附加验证：**使用了本机真实打包目录**，但它是旧包 v22.23.3；
  没有当前源码的新包，因此**不能声称 v24.21.0 的真实打包产物已验收**。
- 观测：`get_node_runtime_status()` 只检查可执行文件能否运行与 npm/npx 脚本是否存在，
  不比较 actual 与 `expected_bundled_version`；旧包 v22.23.3 在 worktree 中仍报
  `available=true`。新版本 pin 的最终验证必须在重新打包后进行。

## 5. 上轮未关闭用例定位

### 5.1 `pair-mcp-failures-sanitized.txt` 的 3 项

当前树全部通过（包含在 §1 的 22 个 `test_mcp_client.py` 用例中）：

| 用例 | 当前结果 | 关闭依据 |
|---|---|---|
| `test_node_release_manifest_pins_official_binary_and_sha256` | PASS | IMPL-2 把 `node_runtime.py` 常量同步到 manifest 的 24.21.0，并去掉测试硬编码 |
| `test_start_records_runtime_config_discovery_and_restart_state` | PASS | 测试改为有界轮询 background 握手完成态 |
| `test_failed_configured_server_blocks_mcp_runtime_without_echoing_arguments` | PASS | 产品 fail-closed（pending/failed 都阻塞）+ 测试等待失败态；真实进程矩阵复证 |

无需新增测试：IMPL-2 已包含回归用例，本次复核未复现任何差异。

### 5.2 WATCH-04 的 5 失败

按 ATTEMPTS.md 的原 F09B 命令在工作树复跑 14 个文件：

```
cd ...\core
python -m pytest -q -p no:cacheprovider --basetemp=.../.tmp/par09-f09b ^
  tests/test_c4_plugin_e2e.py tests/test_c4_skills_commands.py tests/test_codex_plugin_hooks.py ^
  tests/test_atlas_mcp_config.py tests/test_mcp_client.py tests/test_mcp_client_scope.py ^
  tests/test_mcp_instructions_section.py tests/test_mcp_batch_reconnect.py tests/test_agent_skills.py ^
  tests/test_agent_skill_model_invocation.py tests/test_introspect_skill_sources.py ^
  tests/test_library_skill_disclosure.py tests/test_plugin_manager_tools.py tests/test_service_registry.py
```

默认 `-m unit` 口径结果：**91 passed / 2 failed，exit 1**（日志 `par09-mcp-f09b-replay.txt`）。
3 个 MCP 用例已全部通过；剩余 2 个失败均非 MCP、与本包改动无关：

1. `test_c4_plugin_e2e.py::test_installed_plugin_crosses_real_runtime_paths`
   —— hook 信任审查先拦截，返回“尚未通过信任审查”而非插件 hook 的“禁止运行检查”；
2. `test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`
   —— 测试构造的 `models` 无 `model_router`，`AtlasRuntime._compact_session_sync` 抛
   `RuntimeError: Atlas model router is unavailable for compaction`。

这两项与 `mcp_client.py` 的启动/Node 改动无调用关系；原记录为 112 passed / 5 failed，
本次默认 lane 仅收集 93 项（口径/顺序差异），因此把“3 项 MCP + 2 项非 MCP”作为可对应结论，
不宣称精确复刻原批次计数，也不把 2 项非 MCP 归因于本工作树。未新增本树测试。

## 6. 命令 / 退出码汇总

| # | 命令（均在 `D:\Atlas\.worktrees\zcode-exec05-mcp` 下执行；`python` 指 3.11.16 venv） | 退出码 | 结果 |
|---|---|---|---|
| 1 | `cd core && python -m pytest -q -p no:cacheprovider --basetemp=.../.tmp/par09-mcp-basetemp tests/test_mcp_client.py tests/test_mcp_client_scope.py tests/test_mcp_batch_reconnect.py` | 0 | 29 passed |
| 2 | `python .tmp/par09-mcp-real/driver.py lifecycle --data-dir .../data/lifecycle` | 0 | 25 checks passed |
| 3 | `python .tmp/par09-mcp-real/driver.py partial-failure --data-dir .../data/partial-failure` | 0 | 7 checks passed |
| 4 | `python .tmp/par09-mcp-real/driver.py missing-command --data-dir .../data/missing-command` | 0 | 8 checks passed |
| 5 | `python .tmp/par09-mcp-real/driver.py immediate-exit --data-dir .../data/immediate-exit` | 0 | 7 checks passed |
| 6 | `python .tmp/par09-mcp-real/driver.py bad-initialize --data-dir .../data/bad-initialize` | 0 | 7 checks passed |
| 7 | `python .tmp/par09-mcp-real/driver.py disabled ...` + `unconfigured ...` | 0 / 0 | 3 / 3 checks passed |
| 8 | `python .tmp/par09-mcp-real/driver.py stop-during-start ...` | 0 | 3 checks passed（状态观测见 §3） |
| 9 | `ATLAS_NODE_RUNTIME_DIR=<旧包 runtime/node> ATLAS_NODE_RUNTIME_REQUIRED=1 python .tmp/par09-mcp-real/driver.py node-bundled ...` | 0 | 11 checks passed |
| 10 | `python .tmp/par09-mcp-real/node_check.py <core> <旧包 runtime/node>`（worktree 与主树各一次） | 0 / 0 | bundled 选择正确 |
| 11 | 原 F09B 14 文件复跑 | 1 | 91 passed / 2 非 MCP 失败 |

## 7. 未关闭项 / 风险

1. **自动掉线重连未触发（基线既有）**：kill 掉已连接 stdio 子进程后，8s 内无新子进程，
   status 仍报 connected。`_monitor_connection` 只等待 owner task，而 owner 只在
   `stop_event` 上退出；transport EOF 不结束 owner。IMPL-2 diff 未改此路径，本包未修。
   需要主控决定是否另开包处理。
2. **启动中 stop 留下 `state=starting`（基线既有）**：子进程已清理，但 status 未落
   stopped/failed，`available` 保持 false，直到下一次 `start()` 重置。仅边界观测，不阻塞正常启动。
3. **没有当前源码的新打包产物**：真实打包端到端只用了本机旧包 v22.23.3；
   v24.21.0 的安装产物验收仍待重新打包。
4. **版本不匹配不拦截**：`get_node_runtime_status()` 对旧包 v22.23.3 仍报 available，
   仅通过 `expected_bundled_version` 暴露差异；是否要在运行时强制版本一致，需产品决策。
5. WATCH-04 复跑仍有 2 项非 MCP 失败（hook 信任门、compaction model router），
   归属其他包/基线，未在本树处理。

## 8. 交付边界

- 产品改动仍只有 IMPL-2 三文件；本包未新增/修改产品文件，未动主工作区代码与用户数据。
- 未 commit、未 push、未 merge、未 stash。
- 测试夹具只在工作树 `.tmp/par09-mcp-real/**`；日志与本收据只在
  `tasks/dsh-parity/zcode-glm-20261118/evidence/`。
- 未访问真实账号、凭据、在线 registry；未下载 Node 归档。

## 附件日志

`par09-mcp-suites.txt`、`par09-mcp-lifecycle.txt`、`par09-mcp-partial-failure.txt`、
`par09-mcp-missing-command.txt`、`par09-mcp-immediate-exit.txt`、`par09-mcp-bad-initialize.txt`、
`par09-mcp-disabled.txt`、`par09-mcp-stop-during-start.txt`、`par09-mcp-node-bundled.txt`、
`par09-mcp-node-worktree.txt`、`par09-mcp-node-main.txt`、`par09-mcp-f09b-replay.txt`。