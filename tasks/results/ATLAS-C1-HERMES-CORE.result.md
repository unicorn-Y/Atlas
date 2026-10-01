# ATLAS-C1-HERMES-CORE 施工结果

日期：2026-10-02  
状态：**部分完成，未验收**。C1 主链路与前端接入已提交并推送；MoA 已接入 Hermes 并有假咨询覆盖；全量测试仍有在 C1 之前复现的失败，CORE-PARITY 的 L9、T11、T19 和 §10 #10 仍有缺口。本结果不把这些缺口记作完成。

## 提交与远端核验

此前已推送的提交：

| 节 | 提交 |
| --- | --- |
| §1 fork 和依赖 | `8cf0a2b`, `acab2bf`；Hermes fork `atlas` 分支 `562ad75` |
| 前端和设置基础 | `d8bbd22` |
| §4 会话同步 | `15b1416` |
| §3 工具桥接 | `698b7bb` |
| §2 运行时和假模型 | `805110c` |
| §9 默认引擎切换 | `0d48720` |

本次续做提交：

| 节 | 提交 | 内容 |
| --- | --- | --- |
| §5 | `35cd874` | Hermes 压缩设置桥接、易变提示词上下文及相关配置 |
| §6 | `b93076b` | Hermes 插件权限钩子、审批、工作目录限制、写前快照与 Hooks 接入 |
| §7 | `4d975de` | Hermes MCP 配置/事件桥接及本地假 MCP 端到端测试 |
| §8 | `fe31ba1` | SSH 工作目录映射及隔离路由测试 |
| §10 | `4357a86` | C1 运行时、MCP、SSH 和压缩回归测试 |
| §2 协议补正 | `fafb7c8` | 新增事件对应的 Runtime Event Protocol 版本从 1.9 升至 1.10 |

`fafb7c8` 推送前执行了 `git pull --rebase origin main`。推送后核验：本地 `fafb7c8a41f4c9f6191dd3563777b66c714c5073`，远端 `origin/main` 同为 `fafb7c8a41f4c9f6191dd3563777b66c714c5073`。

## 各节结果与偏差

- **§1**：Atlas 固定依赖 Hermes fork 的提交；Python 3.14 环境用于本轮验证。Hermes fork 仍在 `atlas` 分支。详细依赖和仍需补充核验的包见下文。
- **§2**：每轮在工作线程运行 Hermes，同步事件回调回 Atlas 队列；接入取消、暂停/继续、排队/插话、压缩及模型用量。新增事件后协议为 `1.10`。既有 Atlas 事件继续使用原名称和字段。
- **§3**：Hermes 核心工具通过 Atlas 注册表路由，保留 Atlas 现有工具注册与权限/快照路径。没有修改 Hermes fork 内核。工具动作覆盖差异见工具表；真终端的 stdin/PTY 操作还未覆盖。
- **§4**：Hermes SessionDB 保存包含工具调用及结果的上下文，Atlas 消息表继续供 UI 使用；跨轮恢复及会话操作桥接已加入测试。旧对话首次继续时按 Atlas 文字历史导入。
- **§5**：接入 Hermes 三层提示词和真实 `ContextCompressor`；Atlas 易变记忆上下文在会话开始时放入易变层；压缩辅助模型默认跟随当前模型，可单独配置。压缩后待办保留并继续工作的假模型场景通过。提示缓存转由 Hermes 处理。
- **§6**：Atlas 插件通过 Hermes `pre_tool_call`/`post_tool_call` 钩子实施 `read_only`、`ask_writes`、`full_access`、工作目录限制、写前检查点和用户工具 Hooks；安全智能审批与危险命令检测仍关闭。C1 测试验证通过/拒绝及快照路径。Atlas 用户 Hooks 只覆盖 Atlas 已有的五个事件，不扩展 CC 全套 Hooks。
- **§7**：Atlas MCP server 设置转换到 Hermes registry/client；写类 MCP 工具走 Atlas 权限及首次写快照。以本地假 stdio MCP 服务验证实际调用、事件及审批路径；没有对真实远端 HTTP/OAuth 服务做网络验收。
- **§8**：`ssh://host/path` 映射到 Hermes 每回合 SSH terminal 环境；Atlas 文件读写继续走既有 SSH 文件回调。SSH 测试只验证隔离配置和回调路由，没有连接真实 SSH 主机。worktree 沿用 Atlas 原服务。
- **§9**：设置默认引擎为 Hermes，`legacy` 保留为显式备用项。外部 Agent 后端不在本波改动中。
- **§10**：下表列十项验收情景。另跑 Atlas 全量测试与 Hermes 相关源测试，但两者均有失败，故整体未验收。
- **§11 前端**：timeline/事件呈现、上下文上限、引擎设置已接入；四项前端检查及 Edge 截图完成，记录见“验证”。
- **安全与语音**：未实现安全审查功能；`core/atlas/safety/` 保持默认关闭；本地语音暂缓，按任务边界处理。

### 全量失败逐项核对

六个依赖旧 LangGraph 行为的集成测试已在 `tests/conftest.py` 的 `legacy_agent_engine` fixture 下明确选择 `agent_engine=legacy`，没有删除用例：三个 `test_local_execution.py` Agent 运行测试，及 `test_planning.py` 的三个规划/验收回归测试。八项当前分支新增失败中的其余两项也已修复：手动压缩 API 测试注入假的 `HermesRuntime.compact_session`；Hub smoke 改用 event trigger 避免意外发起真实模型回合，并用临时 `sitecustomize.py` stub DBOS 启动，只检验服务生命周期。Hub app 与进程 smoke 聚焦测试 `2 passed`，六个 legacy 测试与压缩 endpoint 合并聚焦测试 `7 passed`。

基线核验按指示先将 `docs/plan/CORE-PARITY.md` 与 `tasks/CURRENT.md` 暂存，再切到 `0d48720^ = 805110c` 跑完整 pytest，完成后切回 `main` 并恢复文档。基线失败 9 项；当前分支最终全量的 7 项失败全部是基线失败的子集。基线另有两项（真实桌面剪贴板、Windows batch 参数引用）在当前分支全量中通过。当前没有只出现在 C1 当前分支的全量失败，但全量汇总仍非全绿，因此依此记录为“当前失败均已证实为 C1 之前存在”，不声称 pytest 全量通过。

## 事件映射

| Hermes 回调/状态 | Atlas 事件 | 载荷 |
| --- | --- | --- |
| 流式文本 | `chunk` | `{content}` |
| 思考文本 | `thinking` | `{content}`；外层旧循环兼容转换为 `run_status` reasoning 展示 |
| Hermes 工具开始 | `tool_call` | `{id,name,arguments}` |
| Hermes 工具完成 | `tool_result` | `{id,name,content,is_error}` |
| 用户问题 | 现有 Atlas 输入回调；无回调时 `input.required` | 沿用现有问题字段 |
| 普通状态 | `run.status` / 兼容外层 `run_status` | `{status,text}` |
| 子 Agent 进度 | Atlas 已有子任务事件 | 沿用 Atlas 子任务事件字段 |
| Token 用量 | `run_usage` | `{usage}`，包含可用的实际用量和上下文元数据 |
| `session:compress` | `run.compaction.progress` | `{data}` |
| 后台进程完成 | `process.completed` | `{data}` |
| 恢复、重试、fallback 状态 | `run.recovery.notice` | `{data:{message}}` |

`/api/runtime/protocol` 当前返回 `{"version":"1.10"}`。协议版本的三个原测试函数名仍写着 1.8/1.9，但断言值已更新为 1.10。

## 旧工具到 Hermes/Atlas 工具映射

| 旧工具/动作 | 新路由 | 覆盖情况 |
| --- | --- | --- |
| `local_file read` | Hermes `read_file` | 已桥接 |
| `local_file write` | Hermes `write_file` | 已桥接并经过 Atlas 写策略 |
| `local_file search` | Hermes `search_files`，`pattern` 转 `query` | 已桥接 |
| `local_edit patch` | Hermes `patch` | 已桥接，保留 LF/CRLF 行为测试 |
| `local_shell` | Hermes `terminal`，Atlas Windows 路由到 PowerShell | 前台/后台命令桥接；Hermes `notify`、watch pattern、heartbeat 参数目前被忽略 |
| `local_process` | Hermes `process_manage` | `list`、`wait`、`poll→status`、`log→read`、`kill→cancel` 已映射 |
| `local_process` 未覆盖动作 | Hermes `process_manage` | `write_stdin`、`submit`、`close`、`handoff` 未由 Atlas process handler 实现；`pty` 也未保留，因此真终端交互未覆盖（T11 缺口） |
| `ask_user` | Hermes `clarify` | 已桥接到 Atlas 输入回调 |
| Atlas `todo_list`、`execute_code`、`session_search`、`delegate_task` | Atlas 原生 handler 注册至 Hermes registry | 已接入；委派与并行场景有假模型测试 |
| Atlas 其他模型可见工具 | Hermes `atlas` 工具集及 Atlas registry | 运行时注册；未对每个工具逐一构造独立端到端场景 |
| `[tools.servers.*]` MCP 工具 | Hermes MCP registry | 假本地 stdio 工具已端到端；没有真实远端服务验收 |

## 第 10 节十项情景

| # | 情景 | 结果 |
| --- | --- | --- |
| 1 | 多轮对话保留上一轮工具调用和结果 | 通过，真实 Hermes + 假模型端到端 |
| 2 | 超过 10 轮工具调用 | 通过，11 轮假模型场景 |
| 3 | 小上下文真实压缩，压缩后继续且待办保留 | 通过；另覆盖手动压缩 |
| 4 | LF/CRLF 编辑保持换行 | 通过聚焦测试 |
| 5 | `read_only`、`ask_writes` 通过/拒绝、工作目录限制 | 通过聚焦测试 |
| 6 | 插话、停止、排队 | 插话/停止及排队路径有运行时测试；本地假模型端到端覆盖运行中 steer；暂停/恢复保留原行为 |
| 7 | 写前快照及回退文件与 Hermes 会话 | 写前快照及会话同步路径已测；完整 UI 回退流程未做浏览器操作验收 |
| 8 | 子 Agent 委派和并行 Worker | 通过假模型端到端 |
| 9 | 本地假 MCP 服务调用 | 通过，确认工具实际执行并经过 Atlas 插件路径 |
| 10 | 新旧内核事件序列对比 | 事件映射和旧事件兼容测试通过；未以同一脚本完整比较所有事件字段序列，仍有验收限制 |

## CORE-PARITY C1 未完成项

- **L9 时间和预算提醒**：Hermes run budget 机制没有接入 Atlas 本轮的会话预算/提醒设置，需补接与测试。
- **T11 真终端交互**：`process_manage` 的 stdin/submit/close/handoff 和 Hermes PTY 参数未映射到 Atlas 执行器。
- **§10 #10**：还缺完整同脚本新旧内核事件序列比较。
- **T19**：Atlas 工具 registry 已接入，但本轮没有逐项核对并独立跑完每一个旧工具动作；上表明确列出已知 process action 缺口。

这些缺口以及全量测试失败意味着 C1 仍未达到验收清单第 2、3、5 项，不应把本波标为完成。

## 依赖与源码测试

- 环境：Windows，Python `3.14.7`。Atlas venv 内可导入并运行本波组件；依赖元数据观察为 `hermes-agent 0.0.0`（editable）、`APScheduler 4.0.0a6`、`litellm 1.103.0`、`pydantic 2.13.5`。
- Atlas `core/pyproject.toml` 声明的 DBOS、sherpa-onnx、PyInstaller 等全量安装/import 矩阵本轮没有逐项重建验证；不得把它们记为已完全确认。
- Hermes fork 相关源测试选择集（文件读写、patch、MCP、SSH/terminal、压缩、plan prompt）：`21 failed, 279 passed, 14 skipped in 94.48s`。失败集中在 Windows 文件权限/符号链接行为以及源码测试对 macOS SSH socket 路径/平台命令的预期；失败清单保留在执行日志 `%TEMP%\atlas-c1-hermes-source-20261001\`（若该目录被系统清理，需重跑才能恢复逐项日志）。本轮未修改 Hermes fork。

## 验证记录

- A5 MoA 桥接聚焦测试：`4 passed in 0.21s`（`test_hermes_runtime.py`），使用假参考咨询和 fake gateway 配置；验证 Atlas ModelManager 模型选择、现有 `moa_references` 事件、advisory 系统提示注入及 `/moa` 参数路径，无真实模型调用。
- 聚焦 C1：权限/运行时、MCP、SSH、压缩、协议版本测试分别通过；协议补正后 3 个相关断言 `3 passed in 8.41s`。运行时 fallback 修正后的核心旧测试 `3 passed in 0.20s`。
- C1 合并聚焦组在 fallback 修正前：`23 passed, 1 warning in 55.29s`。对应模块为 `test_hermes_runtime_e2e.py`、`test_hermes_mcp_config.py`、`test_hermes_ssh_routing.py`、`test_hermes_runtime.py`。
- 前端检查：`npx tsc --noEmit -p tsconfig.renderer.json` 通过；`npx tsc --noEmit -p tsconfig.electron.json` 通过；`npx vitest run` 为 7 files / 36 tests 全通过；`npx vite build` 成功（有 chunk 大于 500KB 的告警）。
- 无头 Edge 已检查对话页、改动面板、终端面板、设置页；本地截图在 `.playwright-cli/`。页面连接隔离的本地后端；没有访问真实模型。
- **`0d48720^` 基线 pytest 汇总行原文**：`9 failed, 955 passed, 9 skipped, 2 warnings in 223.86s`。基线失败：`test_wave3_two_live_schedulers_have_one_trigger_owner`、`test_wave3_hub_claim_preempts_desktop_lease`、`test_real_desktop_observe_input_clipboard_and_window_management`、`test_goal_and_progress_survive_scheduler_restart`、`test_windows_batch_executable_preserves_argument_quoting`、`TestSchedulerWithAPScheduler::test_start_stop`、`test_start_idempotent`、`test_add_task_while_running`、`test_pause_resume`。逐项观察到的失败为：两个 scheduler lease 用例没有获得预期 owner/claim；goal scheduler restart 等待超时；`test_start_stop` 与 `test_start_idempotent` 立即检查 `_started` 时为 false；`test_add_task_while_running` 与 `test_pause_resume` 没有观察到预期任务触发次数。
- **当前 Atlas 全量 pytest 汇总行原文**：`7 failed, 975 passed, 9 skipped, 1 warning in 235.47s (0:03:55)`。当前失败：`test_wave3_two_live_schedulers_have_one_trigger_owner`、`test_wave3_hub_claim_preempts_desktop_lease`、`test_goal_and_progress_survive_scheduler_restart`、`TestSchedulerWithAPScheduler::test_start_stop`、`test_start_idempotent`、`test_add_task_while_running`、`test_pause_resume`。七项都在上述 `805110c` 基线复现；其余两项基线失败在当前运行中通过。基线日志：`C:\\t\\atlas-c1-baseline-805110c-fullpath-20261002\\pytest.stdout.log`；当前日志：`C:\\t\\atlas-c1-final-full-20261002\\pytest.stdout.log`。不得报告全量通过。

测试数据目录、fake HOME/HERMES_HOME/ATLAS_DATA_DIR 与 pytest basetemp 均隔离到仓库外；未使用真实模型或远端 MCP/SSH 网络。`core/atlas/origin_guard.py` 未放宽。已有未跟踪 `design/` 与 `core/uv.lock` 未改动；截图目录 `.playwright-cli/` 是本轮验收产物。
