# DSH 官方源码可吸收机制与许可核查

本表的源码机制限定于 `deepseek-ai/deepseek-harness@687f282e8625c6b8d11ff58211a90524be2e4317`。固定源码根 `LICENSE:1-14` 是 MIT License (Copyright (c) 2026 DeepSeek)；复制 substantial portions 时须保留版权与许可证。已核验发布 CLI npm `0.2.0-rc.2` 的 package manifest 标记 MIT，旧 Web npm `0.0.1-rc.5` 则标记 **BSD-3-Clause**；两者和较新源码快照版本均不同，许可证边界不能互相推定。第三方/传递依赖及每份发行包内其它 LICENSE 的完整合规仍未审计。详见 `extracted/manifest-verified.json`、`source-versions.json`、`version-diff.md`。**本表是移植候选，不表示已复制或已改 Atlas。**

| 优先 | 候选机制/源码符号 | 必要依赖与迁移条件 | Atlas main 对应锚点 |
|---|---|---|---|
| P0 | `packages/subagent/subagent/src/manager.ts:129-175,373-465,533-628`：child Session ID 与 resident Activation epoch 分离，独立 ChildLock/parent lineage/cold resume | DSH 依赖 Cordis service、Session、projection、persistence。Atlas 应在 Hermes 原生 delegate_task 和 SQLite SessionDB 设计其等价状态协议，不宜把整个 TS runtime 嵌入 Python 主引擎 | `core/atlas/engine/hermes_runtime.py`，`engine/session_sync.py`，`api/runtime.py` |
| P0 | `packages/core/agent-loop/src/tool-calls.ts:60-101,122-288`：bounded rolling pool/exclusive barrier/live mode reclassify/按模型顺序 finalize；取消写 synthetic result | 先核对 Hermes pin 的实际 tool executor 是否已有等价机制。仅复用数据契约和算法，不应在 Atlas wrapper 再实现第二轮工具执行 | `core/atlas/engine/tool_registry.py`，`engine/hermes_runtime.py` |
| P0 | `agent-loop/src/assistant-stream.ts:48-108`：transient token attempt 与 durable settled seq 对齐；`api/session-controller/src/client/contract/events.ts:6-35`：前端临时/正式事件合并 | 需要共享的 run/turn/step/attempt ID、持久提交序号、替代规则；Atlas 现有 WS 及 Hermes SessionDB 不应保留两个冲突事实源 | `core/atlas/api/runtime_ws_router.py`，`api/runtime.py`，`frontend/src/renderer/services/runtimeEvents.ts` |
| P1 | `packages/client/ui-subagent/src/client/index.ts:55-101`、`SubagentHeaderLineage.tsx:196-395`、`sidebar-chat/index.tsx:18-201`：child 可点击深入会话、右侧栏、停/续聊状态 | DSH React UI 插件 Slot 依赖 Cordis；Atlas 可翻译 UI 数据契约，在现有组件内实现 parent-aware child Session 路由，须从子代理真实数据库事件供数 | `frontend/src/renderer/pages/agents/AgentActivityTab.tsx`，`components/TimelineNav.tsx` |
| P1 | `packages/llm/token-meter/src/turn-usage.ts:170-275`：以 attempt/retry 已提交事件算 token；`route-pricing.ts:32-73`：按实际模型路由对图像/附件估值 | Atlas 已有 usage 页面及计费器，应补齐 retry、cache、reasoning 和 child attempt 粒度，无可证明数据时显示 unknown；不伪造精确账单 | `core/atlas/models/tokens.py`、`frontend/src/renderer/pages/UsagePanel.tsx` |
| P1 | `packages/session/session-persistence-jsonl/src/storage.ts:186-339`、`lease.ts:1-29`：单 writer lease、write-behind/flush/损坏尾恢复 | Atlas 使用 Hermes SQLite SessionDB，不要换成 DSH JSONL；借鉴单 Writer 所有权和事务边界，不能直接移植 POSIX/Windows 文件锁实现 | `core/atlas/engine/session_sync.py` |
| P2 | `packages/mcp/mcp-client/src/index.ts:154-192`、`tools.ts:81-158`：MCP 工具 generation 同步、热卸载与断线重连 | 需与现有注册器/MCP 客户端的动态生命周期兼容，避免重注册漏卸载；先实测服务端工具更新场景 | `core/atlas/plugins/runtime.py`、`engine/tool_registry.py`、`tools/mcp_client.py` |
| P2 | `packages/api/job-controller/src/index.ts:75-111` 与 `packages/jobs/jobs-local/src/pump.ts:53-86`：浏览器旁观日志的 offset 跟随/独立模型消费指针 | Atlas 已有 Hub/DBOS 后台任务，不应叠加第二个系统；按现有 run/job ID 补独立只读日志 cursor 和人类终止端点 | `core/atlas/runtime/hub.py` |
| P3 | `packages/experimental/agent-team/src/task-board.ts:28-255`、`task-graph.ts:20-70`、`journal.ts:55-70`：DAG blockers、成员/任务状态、Lead 日志提交 | **experimental**；不是已证明默认启用。Atlas 已有 TaskPlan/Goal/Kanban，应在现有任务图数据模型中借鉴所需字段，避免平行造轮子 | `core/atlas/agent/planning.py`、`api/run_drive.py` |

## 实施纪律

- 先检查 Atlas 当前真实上游 pinned Hermes 逻辑及对应分支，再判“缺口”；不能将有真实实现的 Agent/Session/Hub/usage 判成空白。
- 工具、Session、Event、UI 统一按同一 child ID/attempt ID/seq 对账；“有按钮/接口/文案”不能作为实现完成标准。
- 复用的是成熟行为契约和调用链，许可合规地引用原实现所需的最小代码；不因迁移而加新一层状态同步系统。
- 原发布 CLI/Web build 的逐包 License/third-party 仍等待 `EXTRACTION-REQUEST.md` 提取与比对。
