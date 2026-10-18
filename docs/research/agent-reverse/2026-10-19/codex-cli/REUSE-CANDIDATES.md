# Codex 0.163.0 源码可复用候选与 Atlas 适配边界

固定源码：openai/codex@83086188ae0614bd882818ff1aa23f3194962012；上游根 LICENSE 为 Apache License 2.0。**这是仓库总体许可证，并不保证每个 vendored/第三方资产可直接复制**。迁移前看目标文件版权头、依赖许可证、NOTICE；保留适用许可证、作者与 NOTICE；不应将 Codex 的商标、服务端私有协议、认证实现视为自动可移植。

| 候选 | 真实上游锚点 | 建议吸收方式 | 与 Atlas 的代码落点、难点 |
|---|---|---|---|
| 工具调用调度/事件归因 | codex-rs/core/src/tools/{registry.rs,router.rs,parallel.rs,orchestrator.rs} | 优先**移植抽象及状态机**：ToolCall 记录、queued/started/yielded/completed/cancelled、dispatch/handler 计时、结果写回顺序 | agent/tool_node.py、engine/tool_registry.py、api/runtime.py；Rust trait 与 Python async 不直接复制 |
| 多 Agent durable 控制树 | core/src/agent/control.rs、control/{spawn.rs,residency.rs,mailbox.rs,completion.rs} | 迁移 parent/child/thread ID、reentrant resume、mailbox、LRU 驻留、terminal event，不照搬 Codex 的系统权限策略 | agent/__init__.py、runtime/backend_host.py、engine/session_sync.py、persistent_agents；Atlas 临时 worker 会话在 finally 删除，必须另定义 durable child |
| 会话上下文差分与代际 | core/src/context_manager/history.rs、session/world_state.rs、session/async_compaction.rs | 迁移 context version、reference baseline、世界状态 diff、后台压缩候选的版本校验与费用记账原则 | agent/run_phases.py、engine/hermes_runtime.py、agent/injection_budget.py；Hermes history API / Token 估计口径不同 |
| Code Mode 宿主协议 | code-mode-protocol、code-mode-host/src/grpc、code-mode-runtime/src/service.rs、core/src/code_mode_host.rs | 如果确需 JS 编排多工具：单独服务/worker、双向 Core callback、cell ID/wait/terminate、lease、backpressure。先评估从协议/状态机**重新实现**，再决定复用 Rust 模块 | core/atlas/tools、runtime/backends.py；tonic gRPC/HTTP2 over pipe + v8 crate 与 Python/Node 并非无缝移植，宿主存在不等于安全或兼容 Node |
| 工具目录按需检索 | core/src/tools/handlers/tool_search.rs | 借鉴 BM25 + 动态工具缓存失效及命名空间分层；Atlas 可使用已有检索设施而非重复引入重栈 | engine/tool_registry.py、tools/mcp_client.py、agent/tool_catalog.py |
| 恢复语义与 rollout 组织 | core/src/thread_manager.rs、session/daemon_recovery.rs、session/turn_input.rs | 输入记录之后才恢复、持久化 flush、Turn 开始与 steered input 的原子性、线程/工具进程恢复边界 | engine/session_sync.py、api/runtime.py、runtime/external_process.py；需保留 Atlas 数据格式、迁移策略 |
| CLI/TUI 动态层契约 | tui/src/{slash_command.rs,multi_agents.rs,app_command.rs} | 可吸收状态语义与指令注册策略；不原样克隆终端 UI | frontend/src/renderer、api/runtime_ws_router.py；Atlas 不是同一个 TUI 组件体系 |

## 不直接照搬的内容

- Code Mode 的 gRPC 服务和 V8 运行时是完整独立子系统；如果 Atlas 只需要常规脚本工具，单独安装 Host 未必有收益。
- Codex 的 provider auth、ChatGPT 后台、云端能力、专有提示策略无法从本地 Apache-2.0 源码自动重建，也不能由源码目录推断服务器功能。
- 源码中的 feature flags（例如 AsyncCompaction）与插件/扩展、特定 OS 分支要视运行条件落地；不要把实验模块当生产默认能力。
- 并发 semaphore 限额属于 **Host 资源边界**，不等于用户希望的全局子代理固定并发上限。Atlas 的用户授权与资源策略可独立配置。
- 不能以一套旧测试矩阵判定完成：应在真实 Windows 系统经用户授权验证 start→tool→yield/wait→cancel/recovery→rollout 和 Atlas 事件输出的一致性，但本研究阶段不运行重型测试。

## 迁移决策规则

只有三类合格输出：A) 可直接参考和改写且许可明确，附具体路径/符号；B) 应移植机制/状态机，不复制跨语言代码；C) 仅有能力线索须进一步取证。**本阶段是研究，不进行 Atlas 正式代码改动**。
