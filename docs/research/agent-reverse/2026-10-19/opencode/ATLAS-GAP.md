# OpenCode v2 静态机制 vs Atlas main@aa6196f550098cc46081dc6db2c376cb87ddffa5

**验收用语**：等价（静态代码证据足以支持同类机制）；部分实现；未发现同类实现（只限已审相关文件，不能作全库不存在断言）；动态未知。Atlas 源码证据来自 `main` 的真实文件，不是旧矩阵。

| ID | Atlas 真实锚点/现状 | 与 OpenCode 差异及结论 | 建议 |
|---|---|---|---|
| 002/017 | `frontend/src/renderer/store/useAtlasStore.ts:69-79,289-292,670-726`：queue/pendingSteers 在 Zustand store 初始化为 `{}`，`steerQueued/sendQueuedNow/dispatchQueue` 由 renderer 操作；`core/atlas/engine/session_sync.py:1-90` 的 Hermes SessionDB 保存已成形的会话历史 | **部分实现**；有交互队列/steer，但没有在所查代码里看到 OpenCode 服务器 `session_inbox` 那种 pending durable admit/atomic promote；多端重启时交付语义不等价 | 让后端成为 inbox 唯一所有者（SQLite/SessionDB 侧表），前端只投影，重排/取消以 ID+状态 CAS |
| 003/004 | `core/atlas/agent/run_phases.py:1-30,98-168` 明确 run phase 与 callback、cancel watcher；`core/atlas/engine/hermes_runtime.py:177-187` 仅缓存 process-local `_agent_cache/_active_sessions`；`frontend/src/main/backendProcess.ts:19-26` 有健康检查/重启等待 | **未发现同等执行 claim + startup orphan sweep**；有 run 生命周期与进程启动，并不能推出崩溃后恢复执行。属于要优先核实/补齐的机制，不是“无运行引擎” | 把 run claim、resume_attempt、terminal 原子持久化；重启扫描仅补未 terminal 的 run；明确 at-least-once |
| 005/006 | `core/atlas/agent/tool_node.py:58-138` 提供子任务事件、`core/atlas/agent/run_phases.py:95-120` 子任务 callbacks；`core/atlas/agent/subagent_worktree.py` 有工作树；`frontend/src/renderer/store/useAtlasStore.ts:175-176` 可控制子任务 | **部分实现**；并非 Atlas 无子代理，但这批代码未确认跨进程耐久 child Job recovery + parent synthetic completion 等价 | 先确认实际持久子任务表，再按 OpenCode 的 child session + recoverable Job 机制补全 |
| 007/008 | `core/atlas/engine/hermes_runtime.py:1-9` 表明借用 Hermes 执行循环与上下文压缩；`core/atlas/agent/tool_node.py:58-137` 生成细粒度工具事件；`core/atlas/agent/retry_utils.py` 与 `error_classifier.py` 存在 | **部分实现，功能不应说成没有**；对比重点是 provider stream / tool/result terminal 的持久化原子性与 timeout 分类，而非是否能调工具 | 对 Hermes 事件写路径与 run terminal 做失败注入验证，复用现有 worker 而非换全引擎 |
| 009/010 | `core/atlas/agent/run_phases.py:1-26,150-170` 包含 goal knowledge→plan→context 装配；`core/atlas/agent/injection_budget.py`；`core/atlas/engine/hermes_runtime.py:650-740` 显示可手动压缩并应用 PreCompact/PostCompact hook | **已有实现（部分同类）**；不能错误称 Atlas 没上下文压缩。OpenCode 另有 permission-scoped snapshot、model replay 元数据选择 | 改进缓存前缀、provider reasoning metadata 兼容，而非另造一套互斥 memory |
| 011 | `core/atlas/engine/hermes_runtime.py:70-82` 存在 token 历史估算；`frontend/src/renderer/pages/UsagePanel.tsx` 有用量界面；需要进一步读真实账目持久层 | **部分/待验**；已有计数/UI，但不据此确认 cache read/write 与美元成本的每步归档完全等价 | 对 provider usage adapter 和 DB 写入逐项取证，若缺增加字段 |
| 012/013 | `core/atlas/runtime/hooks`、`core/atlas/skills/registry.py`、`core/atlas/tools/mcp_client.py:171-340`、`frontend/src/renderer/pages/HooksPanel.tsx` 存在；也有插件/Skills 页面 | **部分实现**：已具 Hooks/MCP/Skills，并不等于 OpenCode 统一动态插件 supervisor 的原子 generation 激活与跨域注册。插件热更新完成度需逐链核对 | 可借 supervisor/registry 的状态模型，保留 Atlas Python 扩展接口；不要让安装即自动绕过用户配置 |
| 014/015/016 | `frontend/src/main/backendProcess.ts:19-26` 启动 Python backend；`frontend/src/renderer/services/runtimeEvents.ts:3-69` 标准化 run 序号事件；`frontend/src/renderer/store/useAtlasStore.ts` 处理 UI；`frontend/src/renderer/shell/panels/TerminalPanel.tsx:33-71` WebSocket PTY | **已有本地分层与事件、终端**；但 OpenCode 单一 service 发现/复用协议 + server scoped event cache + MessagePort RPC 是不同细化机制 | 不照抄 Electron 宿主；复核 event loss/replay、renderer reload 后 server 当前状态重建 |
| 018 | `core/atlas/engine/tool_registry.py:290-400` 工具注册与 Atlas 自有分派；`core/atlas/tools/node_runtime.py` 为 Node 执行；Hermes 工具层支持逐工具调用 | **功能相近但不同机制**；v2 Code Mode 的可组合 JS + 限定工具目录 + 工具调用进度构成可复用独立能力，不可以“Node runtime 已有”认定等价 | 先以 opt-in Code Mode adapter 接 Atlas 工具目录，复用权限/事件上下文 |
| 019 | `frontend/src/renderer/components/MessageThread.tsx`、`ConversationActivity.tsx`、`components/TimelineNav.tsx`、`services/eventBuffer.ts`，以及事件上限 `runtimeEvents.ts:49` | **有 UI 组件，但不等于 v2 的虚拟行投影与大型时间线锚点策略等价**；长会话性能待量测 | 先针对 1万+事件/复杂 tool group 观察帧耗时，再决定引用 `@tanstack/solid-virtual` 思想移植 React virtualizer |

## 高收益次序（非强制改造）
1. **P0** 统一后台 Inbox + claim / cancel / restart 恢复：解决任务中断、假排队、误判空闲和失败恢复。
2. **P1** 子代理完成结果耐久化、分层错误重试与前端 resync/replay。
3. **P2** 插件统一激活状态、provider-token账目、复杂时间线和受控 Code Mode。

无当前环境动态运行 Atlas / OpenCode 的证据，故不把“未发现同类实现”夸大为“已证明完全不存在”；更不据源码推断 UI 真正跑通。
