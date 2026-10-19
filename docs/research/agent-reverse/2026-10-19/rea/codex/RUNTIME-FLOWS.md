# 运行时链路（Runtime Flows）

每条链路格式：触发源 → 传播 → 执行 → 回传。标注证据等级。

---

## F01 CLI 启动 → TUI

```
用户执行 codex
  → cli crate 解析参数（clap）
  → 加载 config.toml（config crate, --strict-config 可拒绝未知字段）
  → 认证（auth.json / --with-api-key / --with-access-token）
  → 若 TTY：启动 tui crate（456,055 行）
  → 若非 TTY 或有子命令：走 exec / app-server / 具体子命令
```
**证据 R**：`codex --version` 输出 `codex-cli 0.163.0`；`codex doctor` 打印完整环境诊断。

## F02 Desktop 启动 → 登录页

```
用户点击图标 (AppsFolder\OpenAI.Codex_...!App)
  → Windows AppX 激活 → app/ChatGPT.exe
  → Electron main 加载 .vite/build/early-bootstrap.js → main-C4DYk222.js
  → 创建 BrowserWindow（preload.js）
  → webview/index.html 渲染 React SPA
  → 主进程 sendSync 拉 initial-sidebar-bootstrap / shared-object-snapshot
  → 未登录 → 显示 Sign in to ChatGPT
```
**证据 R**：解包副本（全新 user-data-dir + 空 CODEX_HOME）实测到登录页，截图 `screenshots/100_extracted_signin.png`。

## F03 Desktop → Agent Runtime 进程

```
主进程 resolveCodexPath() 定位 app/resources/codex.exe
  → spawn（区分 isPackaged / platform / WSL）
  → 通过 app-server 协议连接（stdio 或本地 socket）
  → 连接键 codex-app-server，凭据前缀 openai-bearer.
  → 有 SQLite recovery 确认机制：onRecovery({databasePath, backupFolder})
```
**证据 R/S**：进程树实测出现 `codex.exe` 与 `codex-code-mode-host.exe` 子进程；`bootstrap-cdWF4rWM.js` 中含 `resolveCodexPath`、`codex-app-server`、`onRecovery`。

## F04 一轮对话（Turn）

```
turn/start RPC（或 TUI 回车）
  → Session 创建 TurnContext
  → run_turn()  [core/src/session/turn.rs:166]
      ├ 预采样压缩检查 (run_pre_sampling_compact)
      ├ 捕获 StepContext（模型/工具/环境）
      └ loop:
          ├ 取出排队输入
          ├ run_hooks_and_record_inputs
          ├ record_step_world_state_if_changed
          ├ build_prompt() → Prompt{ input, tools, parallel_tool_calls, base_instructions, output_schema }
          ├ run_sampling_request() → ModelClient → Responses API（流式）
          ├ ResponseEvent 分发：
          │   ├ 文本/推理 → TurnItem → 通知 item/agentMessage/delta 等
          │   └ function_call → ToolCall → ToolRouter
          ├ 工具执行 → ToolOutput → 回填 history
          └ 若 needs_follow_up → continue；否则 break
  → turn/completed 通知
```
**证据 S**：`turn.rs:166-800`、`build_prompt`（`turn.rs:1666`）、`run_sampling_request`（`turn.rs:1707`）、`try_run_sampling_request`（`turn.rs:2618`）。

## F05 工具调用（以 shell 为例）

```
模型返回 function_call: exec_command{cmd,workdir,tty,yield_time_ms,max_output_tokens,shell,login}
  → ToolRouter 构造 ToolCall
  → ToolRegistry 查 runtime（按 ToolName）
  → 检查 exposure（direct/deferred/code_mode_only/hidden）
  → 权限策略（SandboxPolicy + execpolicy 前缀规则 + approval 回调）
      ├ 允许 → exec-server 执行
      │     └ Windows: codex-command-runner.exe（命名管道，首帧 spawn_request）
      ├ 需要审批 → 发 ExecCommandApprovalParams，等 ExecCommandApprovalResponse
      └ 拒绝 → 回填拒绝原因
  → 输出流 → item/commandExecution/outputDelta 通知
  → FunctionCallOutputPayload 回填 history
```
**证据 S**：`core/src/tools/handlers/shell_spec.rs:96`；`core/src/tools/router.rs`；`exec-server/src/process_sandbox.rs:60-78`；runner 字符串 `runner: expected spawn_request, go`。

## F06 多 Agent 派生

```
模型调用 collaboration.spawn_agent{...}
  → 解析 parent session_source（agent path / depth）
  → 检查 exceeds_thread_spawn_depth_limit(agent_max_depth)
  → 创建子 Session（继承配置，可覆盖模型）
  → 写入 agent-graph-store
  → 子代理独立跑 run_turn
  → 父代理可：
      send_input（触发新 turn，可 interrupt）
      send_message（只投递）
      followup_task（空闲触发）
      wait_agent（V1 等终态 / V2 等 mailbox）
      interrupt_agent / close_agent / list_agents
  → 通知：subAgentActivity{started|interacted|interrupted|completed}
```
**证据 S**：`core/src/tools/handlers/multi_agents_spec.rs`、`core/src/tools/spec_plan.rs:714`、协议 `CollabAgentTool` / `SubAgentActivityKind`。

## F07 上下文压缩

```
触发点 A（PreTurn）: token_limit_reached || background_candidate
触发点 B（MidTurn）: needs_follow_up && (new_window_request || token_limit || candidate)
触发点 C（PostTurn）: turn_end_compaction_threshold_reached
  → run_auto_compact()  [turn.rs:1507]
      ├ Feature::TokenBudget → compact_token_budget::run_inline_auto_compact_task
      │     └ 不调模型，直接 start_new_context_window
      ├ provider.capabilities().remote_compaction == V2 → compact_remote_v2
      └ 否则 → compact.rs（本地模型摘要，用户消息上限 20,000 token）
  → 前后跑 pre_compact / post_compact hooks
  → 发 ContextCompacted 通知
```
**证据 S**：`turn.rs:1507-1560`、`compact_token_budget.rs:24-60`、`config_toml.rs:180`。

## F08 Code Mode 执行

```
模型调用 exec{source, execution_id, enabled_tools, tool_call_id, max_output_tokens}
  → core 把 exec 转给 code-mode-host（gRPC）
  → host.grpc.open_session(session_id, cell_execution_limits)
  → host.grpc.execute → runtime 创建 V8 cell
  → cell 内代码运行
      ├ 调用工具 → SubscribeToToolCalls → delegate → 真实工具执行 → 结果回填 cell
      ├ 超时 → 返回 wait 提示
      └ 完成 → RuntimeResponse
  → 模型可用 wait{cell_id, wait_id} 继续等待
```
**证据 S**：`code-mode-protocol/src/lib.rs`（exec/wait 常量）、`session.rs`、二进制字符串 `code_mode_host.grpc.*`。

## F09 会话恢复

```
Desktop/CLI 重启
  → 读 state_N.sqlite 的 threads 表（rollout_path、tokens_used、git_sha…）
  → 打开 rollout JSONL
  → 若 rollout 缺失或损坏 → doctor 报 "rollout files are missing from the state DB"
  → thread/resume RPC 恢复 Session
  → app-server daemon 若曾中断 → daemon_recovery::RecordedTurnInput 续跑本轮
```
**证据 R/S**：`codex doctor` 实测报告此问题；`state/migrations/0001_threads.sql`；`core/src/session/daemon_recovery.rs`。

## F10 远程控制

```
设备 A: remoteControl/enable + remoteControl/pairing/start
  → 得到配对信息
设备 B: 用配对信息连接 → remoteControl/pairing/status
  → 列出已授权客户端 remoteControl/client/list
  → 可撤销 remoteControl/client/revoke
  → 状态变化推送 remoteControl/status/changed
```
**证据 S**：协议方法存在。**未做实际链路验证（U）**。

## F11 Realtime 语音

```
thread/realtime/start（WebRTC，返回 SDP）
  → 服务端回 thread/realtime/sdp
  → 音频入：thread/realtime/appendAudio
  → 音频出：thread/realtime/outputAudio/delta
  → 转写：thread/realtime/transcript/delta → /done
  → 结束：thread/realtime/stop / closed
  → 可选音色：thread/realtime/listVoices
```
**证据 S**：9 个 RPC + 7 类通知。**未做实际链路验证（U）**。

## F12 Agent Jobs（CSV 批处理）

```
创建 job: agent_jobs 表（instruction, input_csv_path, output_csv_path, output_schema_json）
  → 系统按 CSV 行生成 agent_job_items
  → 每行分配 assigned_thread_id、递增 attempt_count
  → 结果写 result_json
  → 完成写 output_csv_path（auto_export=1）
```
**证据 S**：`state/migrations/0014_agent_jobs.sql`。**未实测（U）**。

## F13 MCP App 沙箱

```
工具返回 MCP App 资源
  → 主进程创建 <webview> 指向 https://<id>.web-sandbox.oaiusercontent.com?app=skybridge#initId=...
  → sandbox-preload.js 校验 origin + initId
  → 通过 MessageChannel 移交白名单端口
  → App 调 navigate / setWidgetData / runWidgetCode 等
  → 结果经 codex_desktop:mcp-app-sandbox-host-message 回主进程
```
**证据 S**：`sandbox-preload.js` 全文。

## F14 自更新

```
主进程 codex_desktop:check-for-updates
  → 请求 persistent.oaistatic.com/codex-app-prod/windows-store-update.json
  → 比对 buildVersion
  → MSIX 分发走 Microsoft Store 更新通道
  → CLI 侧：codex update 子命令独立更新二进制
```
**证据 R/S**：实测 `windows-store-update.json` 返回 buildVersion；CLI 有 `update` 子命令；主进程有该 IPC 通道。
