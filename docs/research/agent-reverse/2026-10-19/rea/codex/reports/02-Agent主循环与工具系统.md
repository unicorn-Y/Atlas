# Codex Agent 主循环与运行时机制（源码级）

**证据等级：S**。所有引用均来自 `rust-v0.163.0` 源码快照，路径相对于 `codex-rs/`。

---

## 1. 一轮 Turn 的完整执行序列

入口：`core/src/session/turn.rs:166` `run_turn(...)`

```rust
pub(crate) async fn run_turn(
    sess: Arc<Session>,
    turn_context: Arc<TurnContext>,
    mut input: Vec<TurnInput>,
    mcp_startup_requirements: &mut McpStartupRequirements,
    prewarmed_client_session: Option<ModelClientSession>,
    cancellation_token: CancellationToken,
) -> CodexResult<Option<String>>
```

实际顺序（按代码执行序）：

1. **判断是否启用自动压缩**（`turn.rs:177`）
   `auto_compaction_enabled` = 线程扩展数据里没有 `AutoCompactionDisabled`。
   `auto_summarization_enabled` = 前者为真 **且** 未启用 `Feature::TokenBudget`。
   → 说明存在两条压缩路线：**模型摘要压缩** 与 **token-budget 新窗口截断**，二者互斥。

2. **Guardian 预检**（`turn.rs:184`）— 若是 basic session source 则检查挂起的 guardian 输入。

3. **结算上一轮异步 Hook**（`turn.rs:188` `drain_async_hook_results`）。

4. **预采样压缩**（`turn.rs:194` → `run_pre_sampling_compact`，定义在 `turn.rs:1372`）
   规则（`turn.rs:1387`）：
   ```rust
   if token_status.token_limit_reached || candidate.is_some() {
       run_auto_compact(..., CompactionReason::ContextLimit, CompactionPhase::PreTurn, candidate)
   }
   ```
   同时 `maybe_run_previous_model_inline_compact`（`turn.rs:1379`）处理"上一轮换了模型"的情况。

5. **解析本轮的 MCP 依赖**（`turn.rs:236` `required_mcp_servers_for_input`）
   — 用户消息里 `@plugin` 提及会触发插件安装需求（`collect_explicit_plugin_ids`）。

6. **捕获 StepContext**（`turn.rs:271` `capture_step_context_with_required_mcp_servers`）
   StepContext 是"一次模型请求的完整视图"：模型信息、工具清单、环境、设置。

7. **主循环**（`turn.rs:454` `loop { ... }`）

### 主循环内部步骤（`turn.rs:454-800`）

| 步骤 | 位置 | 说明 |
|---|---|---|
| 取出排队输入 | `turn.rs:459` `input_queue.get_pending_input(&sess.active_turn)` | 用户在模型运行中追加的消息 |
| 运行 Hook 并记录输入 | `turn.rs:470` `run_hooks_and_record_inputs(..., PersistContext::SteeredUserInput)` | 返回 true 则 break（Hook 终止本轮） |
| 记录窗口 ID / rollout 预算提醒 | `turn.rs:483` `rollout_budget::maybe_record_reminder` | 长会话预算提醒 |
| 记录世界状态 | `turn.rs:551` `record_step_world_state_if_changed` | 文件系统/git 等状态变化注入 |
| 校验必需 skills | `turn.rs:556` `validate_required_skills` | |
| 记录 reasoning effort 覆盖 | `turn.rs:566` `record_reasoning_effort_override` | 支持同一会话内切 effort |
| **构造模型输入** | `turn.rs:572` `sess.clone_history().await.for_prompt(&input_modalities)` | 历史裁剪成 prompt |
| 发起流式请求 | `turn.rs:579` 起 | 见下节 |
| 采样后 token 估计 | `turn.rs:643` | |
| **判断是否滚动新窗口** | `turn.rs:659` | 见压缩章节 |

## 2. 流式事件处理

- 请求类型：`ResponseEvent`（`core/src/client_common.rs`）
- 事件分发：`core/src/stream_events_utils.rs`
  - `handle_non_tool_response_item` — 普通消息/推理
  - `handle_output_item_done` — 单项完成
  - `finalize_non_tool_response_item` — 收尾
- TurnItem 贡献者策略：`TurnItemContributorPolicy`

工具调用路径：模型返回 function_call → `core/src/tools/router.rs` 构造 `ToolCall` → `ToolRegistry` 查询 runtime → 执行 → `FunctionCallOutputPayload` 回填。

## 3. 工具系统的三层结构

### 3.1 注册层
`core/src/tools/registry.rs`
```rust
pub(crate) trait CoreToolRuntime: ToolExecutor<ToolInvocation> {
    fn finishes_on_cancellation(&self) -> bool;
    fn is_builtin_control_tool(&self) -> bool;
    fn immutable_spec(&self) -> Option<&Arc<ToolSpec>>;
    fn cached_code_mode_definitions(...) -> Option<&[ToolDefinition]>;
    fn wait_until_ready<'a>(&'a self, session: &'a Arc<Session>) -> Option<BoxFuture<'a, ()>>;
    fn is_third_party_tool(&self) -> bool;
    fn mcp_server_name(&self) -> Option<&str>;
    fn telemetry_tags(...) -> ToolTelemetryTags;
}
```

### 3.2 六种工具暴露面（`core/src/tools/router.rs:44-50`）

```rust
const EXPOSURE_DIRECT: &str = "direct";
const EXPOSURE_DIRECT_MODEL_ONLY: &str = "direct_model_only";
const EXPOSURE_DEFERRED: &str = "deferred";
const EXPOSURE_DEFERRED_MODEL_ONLY: &str = "deferred_model_only";
const EXPOSURE_CODE_MODE_ONLY: &str = "code_mode_only";
const EXPOSURE_HIDDEN: &str = "hidden";
```

→ 工具不一定全部进模型上下文：`deferred` 需先被 `tool_search` 检索出来；`code_mode_only` 只能通过 Code Mode 调用；`hidden` 完全不可见但可能被内部调用。

### 3.3 组装层（`core/src/tools/spec_plan.rs:628` `build_model_visible_specs`）

```rust
for tool in registry.entries() {
    if !is_directly_visible(turn_context, model_info, tool) { continue; }
    specs.push(spec_for_model_request(...));
}
specs.extend(hosted_specs);   // web_search 等 hosted 工具
merge_into_namespaces(specs)  // 合并命名空间
```

**Code Mode 分支**（`spec_plan.rs:658`）：当 `ToolMode::CodeMode | CodeModeOnly` 且工具允许在 code mode 内使用时，`augment_tool_spec_for_code_mode` 会把工具 schema 改写成"可被代码调用的声明"。

## 4. 内置工具清单（源码实证）

来源：`core/src/tools/handlers/`（57 个文件）。

| 工具 | 定义位置 | 说明 |
|---|---|---|
| `apply_patch` | `handlers/apply_patch_spec.rs:19` | FREEFORM 文本补丁，非 JSON |
| `exec_command` | `handlers/shell_spec.rs:96` | 参数：`cmd`、`workdir`、`tty`、`yield_time_ms`、`max_output_tokens`、`shell`、`login`、`environment_id` |
| `write_stdin` | `handlers/shell_spec.rs:146` | 向统一 exec 会话写字符 |
| `request_permissions` | `handlers/shell_spec.rs:180` | 请求提权 |
| `update_plan` | `handlers/plan_spec.rs:43` | 计划步骤 |
| `spawn_agent` | `handlers/multi_agents_spec.rs:92` | 派生子代理 |
| `send_input` | `handlers/multi_agents_spec.rs:193` | 发消息并触发新 turn（可 interrupt） |
| `send_message` | `handlers/multi_agents_spec.rs:222` | 只投递，不触发 turn |
| `followup_task` | `handlers/multi_agents_spec.rs:255` | 给非根代理追加任务 |
| `resume_agent` | `handlers/multi_agents_spec.rs:275` | 恢复已关闭代理 |
| `wait_agent` | `handlers/multi_agents_spec.rs:292` | 等待终态或 mailbox 更新 |
| `list_agents` | `handlers/multi_agents_spec.rs:325` | 列出当前根线程树下的活代理 |
| `close_agent` | `handlers/multi_agents_spec.rs:346` | 关闭代理及后代 |
| `interrupt_agent` | `handlers/multi_agents_spec.rs:370` | 打断当前 turn |
| `list_mcp_resources` | `handlers/mcp_resource_spec.rs:25` | |
| `list_mcp_resource_templates` | `handlers/mcp_resource_spec.rs:54` | |
| `read_mcp_resource` | `handlers/mcp_resource_spec.rs:83` | |
| `request_plugin_install` | `handlers/request_plugin_install_spec.rs:102` | |
| `list_available_plugins_to_install` | `handlers/list_available_plugins_to_install_spec.rs:32` | |
| `lookup` | `handlers/tool_search.rs:448` | 工具检索（deferred 工具的前置） |
| `docs` | `handlers/tool_search_spec.rs:132` | |
| `sleep` | `handlers/sleep.rs` | |
| `get_context_remaining` | `handlers/get_context_remaining.rs` | 剩余上下文查询 |
| `new_context_window` | `handlers/new_context_window.rs` | 主动滚动新窗口 |
| `request_user_input` | `handlers/request_user_input.rs` | 反问用户 |
| `request_user_input_async` | `handlers/request_user_input_async.rs` | 异步反问 |
| `send_message_to_user_async` | `handlers/send_message_to_user_async.rs` | 非阻塞回复（persistent 模式用） |
| `extension_echo` | `handlers/extension_tools.rs:267` | 扩展示例 |

另有 hosted 工具：`web_search`（`core/src/tools/hosted_spec.rs` `create_web_search_tool`），以及 `view_image` / `image_generation`（由 feature `view_image`、`ImageGeneration` 控制，见 `spec_plan.rs:776`）。

## 5. 多 Agent 机制（重点）

### 5.1 版本与命名空间

`core/src/tools/spec_plan.rs:714` `collab_tools_enabled`：

```rust
MultiAgentVersion::Disabled => false,
MultiAgentVersion::V1 => !exceeds_thread_spawn_depth_limit(
    next_thread_spawn_depth(&turn_context.session_source),
    turn_context.config.agent_max_depth),
MultiAgentVersion::V2 => {
    !turn_context.config.multi_agent_v2.disable_native_tools
    && (turn_context.session_source.get_agent_path().is_none()
        || model_info.multi_agent_version == Some(MultiAgentVersion::V2))
}
```

**V1 必需工具**：`send_input`、`wait_agent`、`resume_agent`、`close_agent`（`spec_plan.rs:750`）
**V2 必需工具**：`send_message`、`followup_task`、`interrupt_agent`、`list_agents`；若 `wait_agent_enabled` 再加 `wait_agent`（`spec_plan.rs:756`）
**V2 可选关闭直连消息**：`disable_direct_message` 时退化为 `interrupt_agent` + `list_agents`。

### 5.2 命名空间包装

`core/src/tools/multi_agent_tool.rs`：
- V1 命名空间常量 `MULTI_AGENT_V1_NAMESPACE`
- V2 命名空间描述 `MULTI_AGENT_V2_NAMESPACE_DESCRIPTION = "Tools for spawning and managing sub-agents."`
- `multi_agent_v2_handler` 支持从"模型目录"下发 `description_override` 与 `parameters_override`（即服务端可改工具描述与参数 schema，不必发版）。
- 加密参数标记 `schema.encrypted = Some(true)` 会被保留到覆盖后的 schema 中——说明**工具参数可被 harness 加密传输**。

### 5.3 消息语义（工具描述原文，S 级）

- `send_input`: "Send a message to an existing agent. Use interrupt=true to redirect work immediately. You should reuse the agent by send_input if you believe your assigned task is highly dependent on the context of a previous task."
- `send_message`: "The message will be delivered promptly. Does not trigger a new turn."
- `followup_task`: "trigger a turn if it is idle. If the target is already running, deliver the task promptly at message boundaries while sampling, or after the pending tool call completes."
- `wait_agent`(V1): "Wait for agents to reach a final status. Completed statuses may include the agent's final message. Returns empty status when timed out."
- `wait_agent`(V2): "Wait for a mailbox update from any live agent, including queued messages and final-status notifications. The wait also ends early when new user input is steered into the active turn."
- `close_agent`: "Close an agent and any open descendants when they are no longer needed"
- `list_agents`: "List live agents in the current root thread tree."

→ V2 引入了**mailbox（信箱）模型**：消息不是直接 RPC，而是进邮箱，`wait_agent` 等邮箱变化。这比 V1 的"等终态"粒度细得多，支持子代理之间细粒度协作。

### 5.4 相关 crate

| crate | 作用 |
|---|---|
| `agent-graph-store` | 代理图持久化 |
| `agent-message-board-client` / `ext/agent-message-board` | 消息板 |
| `agent-identity` | 代理身份 |
| `agent-roles` | 角色定义 |
| `core/src/agent/` | 父会话侧的 spawn/管理逻辑 |
| `core/src/agent_communication.rs` | 通信 |
| `core/src/agent_message_board.rs` | 消息板 |

## 6. 压缩（Compaction）机制

### 6.1 三种压缩路径

| 路径 | 入口 | 特点 |
|---|---|---|
| 本地模型摘要 | `core/src/compact.rs` | 用一次模型调用生成摘要，`COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000`（`compact.rs:63`） |
| 远程压缩 V2 | `core/src/compact_remote_v2.rs` | 服务端完成，客户端只收结果；`RemoteCompactionSupport::V2` |
| Token Budget 新窗口 | `core/src/compact_token_budget.rs` | **不调用模型**，直接 `sess.start_new_context_window(...)` 开新窗口 |

`compact_token_budget.rs` 原文注释：
> "Token-budget compaction skips model/server summarization and installs a fresh context window instead. It is still modeled as compaction so compact hooks and `ContextCompaction` turn items observe the same lifecycle."

### 6.2 触发阈值

配置项（`config/src/config_toml.rs:180`）：
```toml
model_auto_compact_token_limit = <i64>          # token 用量阈值
model_auto_compact_token_limit_scope = "total" | "body_after_prefix"
model_post_turn_compact_threshold_percent = <u8>  # 轮次结束后立即压缩的百分比
```
`AutoCompactTokenLimitScope` 语义（协议 schema 原文）：
- `total`：按完整活动上下文计数
- `body_after_prefix`：只计算"携带窗口前缀之后的采样输出及增长"

触发点有三处：
1. **PreTurn**（`turn.rs:194`）— 采样前检查
2. **MidTurn**（`turn.rs:659`）— 采样后若 `needs_follow_up` 且（有新窗口请求 / 触顶 / 后台压缩已就绪）则滚动
3. **PostTurn**（`turn.rs:791`）— `token_status.turn_end_compaction_threshold_reached`

### 6.3 压缩期间的输入保护

`turn.rs:203-215`：预采样压缩失败时会先把用户输入记录进历史再报错，避免用户输入丢失。注释原文：
> "Compaction runs before the new input is recorded, so preserve it on every failure."

### 6.4 压缩与 Hook

`core/src/compact_token_budget.rs:52` 起：压缩前后分别跑 `run_pre_compact_hooks` / `run_post_compact_hooks`，`PreCompactHookOutcome::Stopped` 可中止压缩。

## 7. 上下文窗口与 token 计数

- `core/src/session/context_window.rs` `context_window_token_status(...)` — 返回实时 token 状态
- `ThreadTokenUsage`（协议）：`last` / `total` / `modelContextWindow`
- 通知：`thread/tokenUsage/updated`
- `core/src/token_budget.rs`、`core/src/session/token_budget.rs` — 预算记账
- `rollout_budget`（`core/src/session/rollout_budget.rs`）— 会话级预算提醒

## 8. 中断、取消、恢复

| 机制 | 位置 | 说明 |
|---|---|---|
| CancellationToken | 贯穿 `run_turn` 参数 | 每轮一个，`.or_cancel(&cancellation_token)` 包裹所有 await |
| TurnAborted | `CodexErrorDetails::TurnAborted` | 用户中断 |
| ToolCollision | `CodexErrorDetails::ToolCollision` | 工具冲突，直接终止本轮 |
| 重连重试 | `core/src/responses_retry.rs` `ResponsesStreamRetryState` | 流式中断后续传 |
| 模型切换恢复 | `maybe_run_previous_model_inline_compact`（`turn.rs:1379`） | 换模型自动压缩以适配窗口 |
| 守护恢复 | `core/src/session/daemon_recovery.rs` `RecordedTurnInput` | app-server daemon 重启后续跑 |

`run_turn` 的返回值是 `CodexResult<Option<String>>`：`Some(最后一条助手消息)` 或 `None`（本轮被压缩/hook 终止）。

## 9. 关键结论

1. **Codex 的 agent loop 是"单 turn 内多 step"**：一个 turn 可以包含多次模型请求（每次工具调用后继续），只有模型不再需要 follow-up 才结束。
2. **压缩是一等公民**：三条路径、三个触发点、与 Hook 生命周期绑定，说明长会话是核心场景。
3. **多 Agent 是协议级能力**，不是 prompt 技巧：有独立 crate、独立命名空间、独立 mailbox 语义、V1/V2 两代实现并存。
4. **工具暴露面可被服务端动态改写**：`description_override` / `parameters_override` 来自模型目录，意味着 OpenAI 可以远程调整工具行为而不发版。
