# 模块目录（Module Catalog）

每个模块按"是什么 / 干什么 / 怎么实现 / 输入输出 / 谁调用 / 被谁调用 / 源码位置"给出。

---

## M01 Agent 会话与轮次

| 项 | 内容 |
|---|---|
| 是什么 | 一次用户消息触发的一轮推理 + 工具执行 |
| 干什么 | 驱动模型请求、工具分发、上下文装配 |
| 怎么实现 | `run_turn` 异步函数，内部 `loop` 多 step |
| 输入 | `Vec<TurnInput>`、`TurnContext`、`CancellationToken` |
| 输出 | `CodexResult<Option<String>>`（最后一条助手消息） |
| 调用者 | app-server `turn/start` RPC、TUI、exec |
| 调用 | ModelClient、ToolRegistry、ContextWindow、Compact |
| 源码 | `core/src/session/turn.rs:166` |

## M02 会话状态（Session / Thread）

| 项 | 内容 |
|---|---|
| 是什么 | 长期存在的会话对象，跨多个 turn |
| 干什么 | 保存历史、输入队列、扩展数据、事件发送 |
| 源码 | `core/src/session/session.rs`、`core/src/session/mod.rs` |
| 持久化 | `thread-store` crate + `state` crate（SQLite） |
| RPC | `thread/start`、`thread/resume`、`thread/fork`、`thread/archive` |

## M03 模型客户端

| 项 | 内容 |
|---|---|
| 是什么 | 对 OpenAI Responses API 的封装 |
| 干什么 | 发请求、消费流式事件、重试、切 provider |
| 源码 | `core/src/client.rs`、`core/src/client_common.rs`、`core/src/responses_retry.rs` |
| provider | `model-provider` crate、`providers` 配置 |
| 流式 | `ResponseEvent` → `stream_events_utils.rs` |

## M04 工具运行时

| 项 | 内容 |
|---|---|
| 是什么 | 工具注册 + 执行 + 结果回填 |
| 干什么 | 按 6 种暴露面筛选、构造 spec、路由执行 |
| 源码 | `core/src/tools/registry.rs`、`router.rs`、`spec_plan.rs` |
| 工具实现 | `core/src/tools/handlers/`（57 文件） |
| 扩展 | MCP（`codex-mcp`、`rmcp-client`）、插件（`core-plugins`）、动态工具（`tools/dynamic_tool.rs`） |

## M05 多 Agent

| 项 | 内容 |
|---|---|
| 是什么 | 父代理派生子代理并协作 |
| 干什么 | spawn / 消息投递 / 等待 / 打断 / 关闭 |
| 源码 | `core/src/agent/`、`core/src/agent_communication.rs`、`core/src/agent_message_board.rs`、`core/src/tools/handlers/multi_agents_spec.rs` |
| 存储 | `agent-graph-store` crate、`agent-message-board-client` |
| 版本 | V1（等终态）/ V2（mailbox） |
| 限制 | `agent_max_depth` 嵌套深度 |

## M06 上下文与压缩

| 项 | 内容 |
|---|---|
| 是什么 | 把长历史压到模型窗口内 |
| 干什么 | 三条路径：模型摘要 / 远程 V2 / token-budget 新窗口 |
| 源码 | `core/src/compact.rs`、`compact_remote_v2.rs`、`compact_token_budget.rs`、`core/src/session/context_window.rs` |
| 触发 | PreTurn / MidTurn / PostTurn |
| 配置 | `model_auto_compact_token_limit` 等 |

## M07 Code Mode

| 项 | 内容 |
|---|---|
| 是什么 | 用执行代码代替 JSON 工具调用 |
| 源码 | `code-mode`(9351) / `code-mode-protocol`(5023) / `code-mode-host`(9984) / `code-mode-runtime`(8961) |
| 对外工具 | `exec`、`wait` |
| 传输 | gRPC：open_session / execute / wait / close_session / shutdown_session / event |
| 隔离 | V8 cell + 堆/栈/tick/地址空间上限 |

## M08 app-server

| 项 | 内容 |
|---|---|
| 是什么 | 把 agent 能力暴露成 JSON-RPC 服务 |
| 干什么 | 给 Desktop / TUI / 任何客户端做后端 |
| 源码 | `app-server`(195,443 行)、`app-server-protocol`(36,126 行)、`app-server-transport`(18,385 行)、`app-server-daemon`(10,980 行) |
| 协议 | 172 请求 + 85 通知 |
| 传输 | stdio / UDS / WebSocket (`--remote ws://`) |

## M09 执行与沙箱

| 项 | 内容 |
|---|---|
| 是什么 | 命令/进程执行与权限隔离 |
| 源码 | `exec-server`(66,845 行)、`exec`、`sandboxing`(11,492)、`linux-sandbox`、`windows-sandbox-rs`、`windows-sandbox-service`(6,039)、`execpolicy`(2,975) |
| 策略 | `SandboxPolicy`：DangerFullAccess / ReadOnly / ExternalSandbox / WorkspaceWrite |
| 策略语言 | execpolicy 用 Starlark 前缀规则 |
| 命令代理 | `codex-command-runner.exe`：命名管道 + `spawn_request` 首帧 |

## M10 持久化

| 项 | 内容 |
|---|---|
| 是什么 | 本地 SQLite + rollout 文件 |
| 源码 | `state`(27,664)、`thread-store`(35,593)、`rollout`(17,779)、`rollout-trace`(13,304)、`history` |
| 库 | state / thread_history / goals / memories / logs / queue |
| rollout | 每会话 JSONL，可分页 |

## M11 技能 / 插件 / MCP

| 项 | 内容 |
|---|---|
| 技能 | `skills`、`ext/skills`(23,984) |
| 插件 | `core-plugins`(49,027)、`plugin`、`utils/plugins` |
| MCP | `codex-mcp`(26,314)、`rmcp-client`(39,145)、`ext/mcp` |
| 市场 | RPC `marketplace/*`、`plugin/share/*` |

## M12 Hooks 与 Guardian

| 项 | 内容 |
|---|---|
| Hooks | `hooks`(16,019)、`core/src/hook_runtime.rs`，覆盖 session_start / pre_tool_use / post_tool_use / pre_compact / post_compact / turn_stop |
| Guardian | `ext/guardian-v2`(17,064)、`ext/guardian-reviewer`、`guardian-context`(8,632) |
| 风险分级 | `GuardianRiskLevel` |

## M13 记忆 / 目标 / 队列

| 项 | 内容 |
|---|---|
| 记忆 | `memories/read`、`memories/write`(5,897)，两阶段（stage1_outputs → phase2） |
| 目标 | `ext/goal`(5,876)，`thread_goals` 表，六种状态 |
| 队列 | `ext/queue`(1,703)，RPC `thread/queue/*` |
| 批量任务 | `agent_jobs` / `agent_job_items` 表（CSV 输入输出） |

## M14 前端宿主

| 项 | 内容 |
|---|---|
| 是什么 | Electron 主进程 + preload + 渲染层 |
| 源码 | `.vite/build/*.js`（35 个）、`webview/assets/`（19,490） |
| IPC | `electronBridge` 21 个方法 + 25 个通道 |
| 沙箱 | MCP App 独立源 + MessageChannel 端口白名单 |

## M15 遥测与配置

| 项 | 内容 |
|---|---|
| 遥测 | `analytics`(17,641)、`otel`(10,450)、`otel-trace-websocket`、Sentry |
| 远程配置 | Statsig（10 具名 + 74 匿名 gate） |
| 配置 | `config`(31,241)、`config-schema`、`features`(3,751) |
