# Reuse Candidates — 适配价值和许可边界

候选仅基于 openai/codex rust-v0.163.0 固定源码实际读取，与 Atlas main 真实现状对比，不承诺复制闭源 Windows 客户端。

| 来源 | 值得吸收的机制 | 对 Atlas 的可落点 | 许可和依赖 |
|---|---|---|---|
| app-server/src/daemon_thread_recovery.rs | 快照持久线程 ID，重启后冷恢复、删除本世代快照、后台异步加载 | core/atlas/api/runtime.py 与 engine/session_sync.py | 先核对仓库根许可证及该文件第三方声明；优先借鉴状态机而非直接把 Rust 拷 Python |
| app-server/src/thread_state.rs | resume response 与新事件订阅在同 listener 排序；generation/drain waiter 防错乱 | backend-adapter/src/client.ts、runtime_ws_router.py、RuntimeManager | 行为可原生实现；不能宣称 Atlas 已具有这些细节 |
| protocol/common.rs + README read-state | 持久 thread firstUnread，revision CAS，冲突返回新状态 | conversations/router + renderer store | 类型/协议可原创，实验字段需独立选择 |
| protocol/common.rs queue/events | item/turn 状态分层，queue changed 通知 | timeline.ts、runtimeEvents.ts、run queue | 严格区分实验接口，禁止直接拿协议存在当 Windows UI 证据 |
| app-server/src/dynamic_tools.rs | client-side tool request/response，超时/失败显式回模型 | frontend preload IPC + tool registry | 借鉴两端协议；别复制云服务不可见接口 |
| app-server/README MCP App UI | descriptor resourceUri + preferred display mode，历史能还原；与宿主 action 分开 | 新 widget registry + event protocol extension | MCP/Apps 具体嵌入格式需按对应公开规格和授权实现，二进制闭源资源不能搬代码 |
| app-server/src/transport.rs | per-connection experimental gate、通知 opt-out、queue、transport abstraction | backend-adapter 与 runtime_ws_router | 适合规约设计、性能与兼容机制；不要求冗余代理层 |
| app-server/src/command_exec.rs | 交互终端与独立命令进程生命周期、PTY/input 控制 | TerminalPanel + local_execution | 拷不动 Windows sandbox 原生语义时分层保持一致 |

公开上游 repo：https://github.com/openai/codex/tree/rust-v0.163.0；许可文件请由本地提取/实施前核对上游标签及依赖的具体许可证，此阶段**未查到并确认所有单文件版权条件**，不作一揽子 MIT/Apache 断言。官方 Desktop MSIX 属单独发行物；仅分析事实，不复制内置闭源代码/UI 资源至 Atlas。

**使用原则**：先吸收成熟状态/协议机制，避免新造抽象层；代码直用仅限许可核实后且与 Atlas 架构匹配。最终施工顺序等客户端证据补齐再排，不向 main 提交任何改动。

## MSIX 实物检查补记（2026-10-19）

本次确认的桌面包静态机制中，**未发现可直接复制进 Atlas 的代码候选**。`app.asar` 的 Electron `preload.js` (`electronBridge`、chunked message validation/ACK)、`main-C4DYk222.js` 的 JSON-RPC client，以及 Windows `computerUse` pipe-host 生命周期，均来自 OpenAI.Codex `26.1013.4894.0` 的打包桌面端；其源码许可/再分发权在本研究中未核实，因此只登记为可供独立设计的行为参考，不复制代码、资源或 UI。证据定位及 SHA/offset 见 `IMPLEMENTATION-TRACE.md` §8 与 `EVIDENCE-INDEX.md`。

可继续评估的**机制级原创实现**：按 transfer ID + sequence + ACK 设计受限、有界的跨进程大消息传输；把 app-server protocol version/capability 与明确兼容错误接入 adapter；区分 host lifecycle 和用户 run lifecycle。当前证据只说明 Codex 包静态包含这些机制，消息组包端、完整 IPC handler、实际执行拓扑及动态行为未闭环；不要照此推定 Atlas 缺少完整等价物。公开 `openai/codex` Rust 源码仍按上表单独处理，许可须在拟引用的精确 tag/文件/依赖处复核；不能用公开仓库许可覆盖闭源 MSIX。
