# ATTEMPTS — 流式取消、失败重试与会话恢复(ZC-DSH-EXEC-02 · B 节)

执行快照:Atlas `wave3` @ `060071ab2ecf86d41cab90e98160183ce126bc69` + 141 项在途改动(归原作者);测试全部用私有 basetemp,未触碰 8765 用户后端。

## EXEC-06 · 问答取消路径与 17 项等价对照(2026-11-18)

### user-question.cancelled / Atlas 取消路径

- DSH 发射点唯一:`packages/sdk/server/src/user-questions.ts:34-57`(abort 监听 → `notify('user-question.cancelled',{requestId,sessionId})`);消费者 TS `client.ts:305-309`、Python `client.py:475-478,513-561`;测试 `user-questions.spec.ts:97-118,121-140`。
- Atlas 路径:desktop `run_drive.py:3522-3545` + `runtime_ws_router.py:186-190`(无 `input.cancelled`);app_server `app_server.py:475-503` + `_wait_with_cancel:19-31`(取消返回 `""`,不发通知,durable `appserver.request=invalidated`)。
- 复跑 `test_app_server_pending_request_reconnects_in_same_process`、`test_app_server_task_cancel_waits_for_worker_cleanup_and_cancels_queued_item`、`test_app_server_invalidates_old_pending_request_after_process_restart`、`test_server.py::TestBackendParityWave1::test_ask_user_event_waits_for_a_response` → **4 passed, exit 0**。明细 `evidence/exec06-user-question-cancel-remoteaccess-20261118.txt`。

### 17 项仅在途失败等价矩阵

| 产品代码 | 测试/夹具 | 17 nodeid 结果 |
|---|---|---|
| 基线 060071ab | 基线测试(仅 8 项存在) | 8 passed, exit 0 |
| 当前树(wave3+在途) | 当前测试 | 17 passed, exit 0 |
| 基线 060071ab(隔离 worktree) | 当前测试+当前夹具(复制) | 11 passed / 6 failed, exit 1 |

- 8 项基线存在项:两套代码均通过 → 无回归。
- 9 项新增:3 项两套均通过;6 项仅基线失败(OLDNEW 拼接、ACP 取消超时、丢弃尝试文本泄漏、allow_once 副作用缺失、项目指令未注入)→ 均为在途产品新增/修复行为,测试范围而非回归。
- 早前 17 项失败不可复现;签名 `SimpleNamespace` 缺 `local_execution_permission_mode`(窄 config stub 泄漏到长生命周期服务线程)属环境/测试顺序污染。旁证:3 文件整跑 2 项 test_projects 失败,单独运行通过。
- 矩阵与逐项原因 `evidence/exec06-17fail-equivalence-20261118.txt`;5 份原始输出 `evidence/exec06-17fail-*.txt`。

## 场景 → 结果

### 1. 用户停止流式输出

| 项 | 内容 |
|---|---|
| 可见入口 | SDK/app-server 客户端发起取消(真实 SDK ↔ app-server 子进程;受控模型替身) |
| 断言核心 | 取消时部分产物回滚;同一尝试的撤回先于终止事件;只持久化失败审计,不把部分输出提交为正文 |
| 事件顺序 | `attempt` 撤回 → 取消终态;被跳过调用有合成结果 |
| 自动化证据 | `tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_cancel_rolls_back_partial_attempt_and_persists_only_audit` **PASS**(exit 0) |
| 状态 | **自动化层已验**(真实 SDK 子进程+替身);桌面 UI 入口与打包端未实测 |

### 2. 失败后重试成功

| 项 | 内容 |
|---|---|
| 可见入口 | 首次请求失败(ATLAS_OLD_ATTEMPT 语义)→ 重试仅返回成功尝试 |
| 断言核心 | 成功返回/重开 DB/重放只含 NEW 尝试;失败尝试留审计且不与成功正文拼接;回执只提交新尝试 |
| 自动化证据 | `tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_subprocess_commits_only_new_attempt_and_reopens_audit` **PASS**;`tests/test_retry_attempt_isolation.py` 全组随批 PASS |
| 状态 | **自动化层已验**;桌面正文/历史投影的真机核对未做 |

### 3. 关闭后重开会话

| 项 | 内容 |
|---|---|
| 可见入口 | 进程重启后 fallback 尝试隔离;重开 DB 审计可辨 |
| 断言核心 | 重启后旧尝试不复活、审计保留、重开可见历史与终态一致 |
| 自动化证据 | `tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_fallback_attempt_isolated_across_process_restart` **PASS**;`tests/test_kernel_recovery.py` 随批 PASS |
| 状态 | **自动化层已验**;真机重启会话未测 |

## WATCH-05 IMPL-2 · MCP 生命周期 fail-closed 修复(ZC-EXEC-05-IMPL-2,done-in-worktree)

- **隔离 worktree**:`D:\Atlas\.worktrees\zcode-exec05-mcp`(分支 `zcode/exec05-mcp-status`,基线 wave3@060071ab);改动文件均干净无冲突。
- **真实产品缺陷两处**(配对复跑定性后确认):
  1. `get_runtime_status()` 在 enabled 服务器仍处 starting/connecting 时 `available=True`——fail-closed 在未决状态被破坏。修复:available=False 直到所有 enabled 服务器 settled(connected 或 failed),blocking_reason=「MCP server startup is still in progress」。
  2. `_startup_finished()` 捕获后台启动异常后只记日志,**永不把状态置为 failed**(服务器永远停在 starting)。修复:按 task 名回填 `state=failed`+`blocking_reason=_failure_reason(exc)`(不回显参数)+_progress 事件。
- **测试确定性修复**:`test_start_records…` 与 `test_failed_configured_server…` 各加有界轮询(5s),后者轮询置于 patch 存活期内。
- **结果(终态,修正早前"网络依赖"误判)**:`tests/test_mcp_client.py` 修复前 19 过/3 败 → **22 过/0 败(exit 0)**。第三个失败真因并非网络:测试**无任何网络访问**,读仓库内 `frontend/node-runtime.json`(tracked@HEAD,24.21.0 全字段自洽)与 `core/atlas/tools/node_runtime.py` 常量(v22.23.3)**已提交的不同步**,叠加测试硬编码 `22.23.3` 字面量两处。修复:常量同步到部署真源(v24.21.0/sha256 158f7685…)+约定注释+测试字面量改由 NODE_VERSION 派生(防再漂移)。运行记录 `evidence/impl2e-mcp-after.txt`(22 passed,exit 0)。
- **diff**:`evidence/zcode-exec05-mcp-status.diff`(2 文件 +53/-5);运行记录 `evidence/impl2c-mcp-after.txt`;**不合回、不 push**。

## WATCH-05 配对复跑(2026-11-18)

方法:在途树(wave3+未提交)与干净树(zcode/exec04-code-preview@060071ab,core 侧=干净 HEAD)同 nodeid 配对;原始脱敏失败=`evidence/pair-mcp-failures-sanitized.txt`(0 个密钥模式);原始完整输出=`evidence/pair-inflight-mcp-ssh.txt`、`pair-clean-mcp-only.txt`;FAILED 集合 diff=`evidence/pair-failed-diff.txt`。

### MCP(test_mcp_client.py,干净树存在,可配对)

| nodeid | 在途 | 干净 | 根因定性 |
|---|---|---|---|
| test_node_release_manifest_pins_official_binary_and_sha256 | FAIL | FAIL | **修正(WATCH-05 终态)**:测试无网络访问,读仓库内 `frontend/node-runtime.json`(24.21.0 自洽)vs `node_runtime.py` 常量(v22.23.3)——**已提交的数据不同步**+测试硬编码字面量;已在 IMPL-2 修复 |
| test_start_records_runtime_config_discovery_and_restart_state | FAIL | FAIL | 'filesystem' MCP 服务器本机未连上(connected=False,teardown owner_cancelled)→ 环境依赖 |
| test_failed_configured_server_blocks_mcp_runtime_without_echoing_arguments | FAIL | FAIL | 'broken' 服务器确实 background_start_failed,但断言时 status.available 仍 True → 失败传播与时序竞态 |

结论:**3 项均为基线/环境问题,非在途改动引入**(两树同 nodeid 同败);另观察到 MCP 失败数在两次运行间漂移(5→3),不稳定测试。修复候选(可在隔离 worktree 做,test 文件干净):#1 网络 stub/固定 pin fixture;#3 失败传播轮询断言。

### SSH/LSP world(仅在与在途可观测)

`test_ssh_execution_world.py`/`test_lsp_ssh_world.py` 为**在途未跟踪文件**(干净 HEAD 无此文件,无法同 nodeid 配对)——配对结论即"仅在途树可观测";4 项失败(cancel intent late handle×2/disconnect unknown/LSP diagnostics forward)不能归因于在途改动或基线;环境差异=在途树 core/atlas/ssh.py 为原作者修改版。见 `evidence/pair-ssh-note.txt`。

## WATCH-04 定向批次(2026-11-18)

- F09B(插件/MCP/技能):`tests/test_c4_plugin_e2e.py test_c4_skills_commands.py test_codex_plugin_hooks.py test_atlas_mcp_config.py test_mcp_client.py test_mcp_client_scope.py test_mcp_instructions_section.py test_mcp_batch_reconnect.py test_agent_skills.py test_agent_skill_model_invocation.py test_introspect_skill_sources.py test_library_skill_disclosure.py test_plugin_manager_tools.py test_service_registry.py`(basetemp pytest-f09b)→ **112 passed / 5 failed**。失败集中在 test_mcp_client.py(官方二进制 sha256 pin、runtime config discovery、失败服务器阻断不回显参数):`core/atlas/tools/mcp_client.py` 本身干净,疑环境依赖;基线比对待 P4。
- F08(沙箱/LSP/SSH/web 工具):`tests/test_lsp_service.py test_dsh_w7_sandbox.py test_ssh_execution_world.py test_web_tools.py test_tools_router_failures.py test_lsp_ssh_transport.py test_lsp_ssh_world.py`(basetemp pytest-f08,60.92s)→ **73 passed / 4 failed**。失败全部在 SSH 执行世界(cancel intent late handle×2/disconnect unknown/LSP diagnostics forward):`core/atlas/ssh.py` 为原作者在途文件,不作新回归断言;基线比对待 P4。
- IMPL-1(worktree):vitest `documentPreviewRegistry+codePreview+FilesPanel` **10 passed**(exit 0);tsc renderer **0 错误**(exit 0)。

## 批次命令与计数

- core(basetemp `D:\ENGINE-V3-UPSTREAM-20261118\tmp\pytest-core-01`,PYTHONDONTWRITEBYTECODE=1):
  `python -m pytest -q -p no:cacheprovider -o addopts= --tb=short tests/test_event_contract.py tests/test_kernel_recovery.py tests/test_retry_attempt_isolation.py tests/test_app_server_sdk_subprocess_attempts.py::<三个场景>` → **38 passed, 5 warnings in 23.67s**,exit 0
- frontend:`vitest run src/renderer/services/runtimeEvents.test.ts src/renderer/components/timelineProjection.test.ts` → **2 files / 17 tests passed**,exit 0
- core 第二批(basetemp pytest-core-02,F07/F05 定向):`tests/test_state_schema_refusal.py tests/test_conversation_export_route.py tests/test_w3_session_compaction.py tests/test_tool_scheduler_concurrency.py tests/test_hook_missing_script.py tests/test_kernel_compaction_surface.py tests/test_kernel_durable_inbox.py` → **28 passed in 6.09s**,exit 0(当前在途树真实进程证据)
- 支撑链:`core/atlas/engine/kernel/model_call.py`、`loop.py`、`agent/run_phases.py`、`api/run_drive.py`、`frontend/src/renderer/services/runtimeEvents.ts`、`timelineProjection.ts` 的当前实现经测试契约覆盖(事件三真源对账含在 test_event_contract 内)

## 待补(受条件限制,非失败)

1. 打包桌面端真机路径:需打包 Atlas 桌面 + loopback 模型替身,再按首批任务书 B 节三场景逐一点停止/重试/重开。当前仅开发版源码层证据。
2. 官方 DSH 对照:两产品需同条件(同一替身或同一授权 provider/model)才可比较;未做,不做单方宣称。
3. 真实模型回合:未消耗配额;受控替身承担可重复失败/竞态覆盖。

## 链路遗留观察(来自锚点核对)

- `core/atlas/tools/app_server.py` 当前树已出现 `session/enqueue`、`session/retry_recovery`、`session/task_*` 等方法分支,但该文件带未提交改动(在途工作,归原作者)——**不得计为已发布能力**;SDK 协议对照(F04)以其集成状态为准。
