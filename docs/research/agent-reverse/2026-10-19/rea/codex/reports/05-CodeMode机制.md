# Code Mode 机制（源码 + 二进制双证据）

**证据等级：S**（Rust 源码 + 二进制字符串 + gRPC 方法名）。

---

## 1. 它是什么

Code Mode 是 Codex 的一种**工具调用范式**：模型不再逐个发 JSON function call，而是写一段 **JavaScript/TypeScript 代码**，在隔离运行时（V8 cell）里执行，代码内部再调用各个工具。

对模型暴露的工具只有两个（`code-mode-protocol/src/lib.rs` 末尾）：

```rust
pub const PUBLIC_TOOL_NAME: &str = "exec";
pub const WAIT_TOOL_NAME: &str = "wait";
```

- `exec`：提交一段源码，启动一个 cell 执行
- `wait`：等待某个 cell 的后续事件/输出（因为执行可能超过单次 yield 时间）

## 2. 架构分层

| crate | 行数 | 职责 |
|---|---|---|
| `code-mode` | 9,351 | 与 agent 集成、工具 schema 改写 |
| `code-mode-protocol` | 5,023 | 协议类型：`ExecuteRequest`、`WaitRequest`、`CellId`、`RuntimeResponse` |
| `code-mode-host` | 9,984 | 独立进程，gRPC 服务端，管理 session/cell |
| `code-mode-runtime` | 8,961 | cell actor、V8 运行时、回调调度 |

## 3. gRPC 接口（二进制字符串实证）

从 `codex-code-mode-host.exe` 提取到的方法名：

```
code_mode_host.grpc.open_session
code_mode_host.grpc.execute
code_mode_host.grpc.wait
code_mode_host.grpc.close_session
code_mode_host.grpc.shutdown_session
code_mode_host.grpc.event            (事件流)
```

请求结构（字符串中出现的字段名）：
- `OpenSessionRequest`：`cell_execution_limits`
- `ExecuteRequest`：`source`、`execution_id`、`enabled_tools`、`tool_call_id`、`max_output_tokens`
- `CancelWaitRequest`
- `SubscribeToToolCallsRequest`：`tool_name`

响应/事件类型：
`ToolCallSucceeded`、`ToolCallFailed`、`InvalidIdentifier`、`RuntimeResponse`

## 4. 资源限制（`code-mode-protocol/src/session.rs:27`）

```rust
pub struct CodeModeSessionCellExecutionLimits {
    pub max_yield_time_ms: Option<u64>,
    pub max_heap_size_bytes: Option<usize>,
}
```

默认值（`code-mode-protocol/src/runtime.rs:15-17`）：
```rust
pub const DEFAULT_EXEC_YIELD_TIME_MS: u64 = 10_000;          // 10 秒
pub const DEFAULT_WAIT_YIELD_TIME_MS: u64 = 10_000;
pub const DEFAULT_MAX_OUTPUT_TOKENS_PER_EXEC_CALL: usize = 10_000;
```

二进制里还有更细的硬限制字符串：
```
code-mode host has too many active cells
code-mode session has too many tool subscriptions
code-mode host has too many pending ...
code-mode runtime reused an active cell ID
SandboxSize < address_space_limit
HeapLimitExceeded / TickLimitAlreadySet / CallstackSize / HeapSize
```

→ 每个 cell 有 **堆上限、调用栈上限、tick 上限、地址空间上限**，且 host/session 两级都有并发上限。这是典型的"不可信代码执行"防护配置。

## 5. Cell 生命周期

从 `code-mode-protocol/src/session.rs` 与二进制：

```
open_session
  └─ execute(source, execution_id, enabled_tools, tool_call_id, max_output_tokens)
       └─ StartedCell { cell_id, initial_response }
            ├─ 运行中：通过 SubscribeToToolCalls 订阅工具调用
            │    └─ cell 内调用工具 → host 转发给 agent → 工具结果回填 cell
            ├─ 超时/未完成：wait(cell_id, wait_id) 继续等待
            └─ 完成/取消：close_session / shutdown_session
```

`CodeModeNestedToolCall` 表示 cell 内嵌套的工具调用；`CodeModeSessionDelegate` 负责把嵌套调用转给真正的工具执行器。

## 6. 与 Agent 的集成

`core/src/tools/code_mode/` 目录：
- `execute_spec.rs` — 生成 `exec` 工具 spec（`create_code_mode_tool`）
- `spec_plan.rs:658` — 当 `ToolMode::CodeMode | CodeModeOnly` 时，把普通工具 spec 用 `augment_tool_spec_for_code_mode` 改写成"代码内可调用"的声明
- `EXPOSURE_CODE_MODE_ONLY` — 某些工具只能通过 Code Mode 调用，不出现在普通工具列表

公开工具 `exec` 的描述由 `build_exec_tool_description` 生成，会列出当前可用工具并给出 TypeScript 类型声明（`render_json_schema_to_typescript`，`json_schema_types.rs`）。

## 7. 相关的 feature flag（CLI `codex features list` 实测）

| flag | 阶段 | 默认 |
|---|---|---|
| `code_mode` | under development | false |
| `code_mode_host` | stable | **true** |
| `code_mode_host_grpc` | under development | false |
| `code_mode_interrupt` | stable | true |
| `code_mode_only` | under development | false |
| `code_mode_only_strict_3p_tools` | under development | false |
| `code_mode_prewarm` | under development | false |
| `code_mode_tool_description_first` | under development | false |
| `code_mode_tool_search` | under development | false |
| `code_mode_buffered_exec` | removed | false |

→ `code_mode_host` 已 stable 且默认开（说明 host 进程基础设施已上线），但 `code_mode` 主开关仍是 under development / false。**即：基础设施在，功能默认不启用**。

## 8. 我的判断

Code Mode 是 Codex 相对其他 Agent 最有技术含量的差异化能力：
- 把 N 次 JSON 工具调用压缩成 1 次代码执行，省 token、省往返
- 代码内可以做循环、条件、并发，突破了"一次只能调一个工具"的限制
- 代价是需要完整的沙箱运行时（V8 + 资源限制 + 工具回调代理）

对照 Atlas：如果 Atlas 只有 JSON 工具调用，这是结构性差距，不是补个 UI 能追上的。
