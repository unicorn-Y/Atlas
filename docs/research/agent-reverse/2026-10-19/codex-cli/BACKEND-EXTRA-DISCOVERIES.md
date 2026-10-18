# Codex CLI 0.163.0：超出任务书枚举的六项后端机制

证据来源均为上游 commit 83086188ae0614bd882818ff1aa23f3194962012 中的实际 Rust 代码；S=静态源码。没有把 feature flag 的存在当作默认启用，也没有 Windows EXE 实测。

## CODEX_CLI-028：AgentGraphStore 维护持久化的子线程树

codex-rs/agent-graph-store/src/store.rs:13-61 定义 AgentGraphStore trait：upsert_thread_spawn_edge(parent,child,status)、set_thread_spawn_edge_status(child,status)、list_thread_spawn_children(parent, filter)、list_thread_spawn_descendants(root,filter)。下游 BFS 按深度和 ThreadId 稳定输出；状态筛选作用于被遍历的每条边——closed ancestor 下的 open descendant 不被返回。codex-rs/agent-graph-store/src/local.rs:10-112 有 SQLite-backed LocalAgentGraphStore。更重要的是 codex-rs/core/src/agent/control/spawn_guard.rs:80-99 真正调用 state.agent_graph_store().set_thread_spawn_edge_status，因此此功能不仅是目录名。

## CODEX_CLI-029：独立 Agent Message Board，有不同数据后端

codex-rs/core/src/agent_message_board.rs:38-121 的 install_agent_message_board 注册 MAv2 的通知和 tool namespace，可选 LocalAgentMessageBoard::open(config.sqlite_config()), InMemoryMessageBoards::open(), RemoteAgentMessageBoard::new()。有显式连接时可单独启用；没有显式连接时要求 Feature::AgentMessageBoard 和 Feature::MultiAgentV2，且 ephemeral + non-inmemory + no-remote 情况不启用。Remote board 可从指定环境变量取得 bearer token。**它不是前述 Code Mode tool callback，也不等于简单 send_message mailbox。** 外部远程服务端实现未取证。

## CODEX_CLI-030：Spawn 两阶段所有权与失败清理

codex-rs/core/src/agent/control/spawn_guard.rs:1-105 的 PendingSpawn 暂时持有 child ThreadId、membership 和 edge_write JoinHandle。只有 disarm() 的正常通路转交所有权；否则 Drop 异步清掉 child runtime 和持久化，再先等待 Open edge write，后将 spawn edge 标 Closed 并记录清理失败类别。此设计修的是“创建半途失败导致 ghost child”而不是给所有运行中的 child 超时硬杀。

## CODEX_CLI-031：Daemon 在进程生命周期里恢复不是直接同步加载

codex-rs/app-server/src/daemon_thread_recovery.rs:1-51: snapshot 使用独立命名系统线程写文件，错误时清掉 stale snapshot；start_recovery 在 blocking task 中读取并消费（删除）snapshot，然后 tokio::spawn(processor.restore_daemon_threads(candidates))，不要求服务就绪等待全部冷恢复。源码注释明确已有 client-owned runtime 归原 client。不能据此断言突然断电后全部工作可无损恢复。

## CODEX_CLI-032：MCP 配置变更时避免“刷新事件被取消吞掉”

codex-rs/core/src/session/mcp_refresh.rs:1-57: McpRefresh.pending AtomicBool 表示待刷新，gate Semaphore(1) 约束发布并发；claim() 原子置 false，McpRefreshInvalidationGuard::drop 在未 published 时重新 invalidate()。这是较低层的工具可见目录一致性，不是“支持 MCP”四个字能涵盖。

## CODEX_CLI-033：Retained context 与异步消息的提交边界

codex-rs/core/src/session/retained_context.rs:145-205: record_retained_context() 调用 thread_settings::acquire_persistence_lock 后写入 RolloutItem::RetainedContext，源注释指出避免事实跨 checkpoint/suffix 错误边界；pending_code_mode_message_recordings() / track_code_mode_message() / drain_code_mode_messages() 跟踪并等待尚未存盘的 Code Mode 异步消息。用户已看到回答、模型已结束 Turn、输出已经持久化三者不能被无条件混为一件事。

## Atlas 迁移判断

这六项中，至少 028/030/031/033 值得直接作为任务生命周期与状态同步设计参考；029 要先明确 Atlas 需要哪些 Agent 通讯语义、032 要核对已有 tools/mcp_client.py 实现。Atlas main 确有 checkpoint、conversation branch、child worker、MCP 热重启、WS event，不可臆断等价或全缺。差距详见 ATLAS-GAP.md。本轮没有修改 Atlas 正式代码。
