# DSH 官方固定源码：能力发现总账
证据级别：S=固定提交源码实际读取；D=官方文档，仅供佐证；I=推断；U=未确认；R=实际动态运行（本阶段无 R）。**以下 S 仅证明 0.2.1-rc.2 固定源码的实现。**

| ID | 能力与关键发现 | 符号与位置 | 证据 | 边界 |
|---|---|---|---|---|
| DSH_CORE-001 | Agent 驱动显式 `idle/maintenance/running`，`kick/turn/step` 由会话日志构建请求 | `packages/core/agent-loop/src/agent.ts:42-50,97-150,252-265,298-400` | S | 未动态跑 |
| DSH_CORE-002 | `followup/steer/inject` 分别写 `next-turn/next-step` durable inbox；取消后 waking input 进入下个 Turn | `agent-loop/src/agent.ts:154-180`; `inbox.ts:20-55` | S | 时序基于源码 |
| DSH_CORE-003 | 每 Step 写 `step/start/end`，异常补写缺失 tool/result，Turn 末尾有终止原因 | `agent-loop/src/agent.ts:307-388` | S | 崩溃中间态待运行 |
| DSH_CORE-004 | 模型 attempt stream 暂态帧与已提交 seq 解耦，提交失败标记 `abandoned` | `agent-loop/src/assistant-stream.ts:18-107` | S | Web 对应 projection 另查 |
| DSH_CORE-005 | 工具并行 rolling pool + exclusivity barrier + ordered finalize；取消为未派发工具合成失败结果 | `agent-loop/src/tool-calls.ts:60-100,122-246,249-286` | S | 动态模式变更仍需实测 |
| DSH_CORE-006 | 模型路由提案 waterfall → `llm.prepareCall` → durable header/context；工具 schema 变动也记 developer message | `agent-loop/src/agent.ts:563-684` | S | 当前源码版本 |
| DSH_CORE-007 | 子 Agent provider 可替换、`startActivation` 返回 child id，不同步等待工作完成 | `packages/subagent/tool-subagent/src/index.ts:193-220,319-379` | S | provider 类型差异 |
| DSH_CORE-008 | 子代理 manager 拥有 process-local resident map、每子锁、capacity pool、初始化回滚及父子拥有关系 | `packages/subagent/subagent/src/manager.ts:129-179,373-465,735-761,930-964`; `activation.ts:15-36,164-183` | S | 子树逻辑需更多演练 |
| DSH_CORE-009 | 冷恢复直系 continuable child；send_message 双向相邻消息，`steerPrompt/queuePrompt` 决定 Step 或 Turn | `manager.ts:533-628,707-730`; `tool-subagent-control/src/index.ts:27-111` | S | 外部子进程不可续 |
| DSH_CORE-010 | start/end 生命周期边缘事件、以子 Session 真实 turn outcome 判终结而非以 disposal 成功推断 | `subagent/src/lifecycle.ts:63-114,118-170` | S | 尚无 runtime log |
| DSH_CORE-011 | 子代理深度预算写入 child meta；父的当前 route/reasoning 传给孩子，改 route 可清 inherited effort | `subagent/src/child-agent.ts:49-57,68-118,135-160` | S | depth 默认按插件 |
| DSH_CORE-012 | Browser 可直接 `subagents.prompt`、`interruptByParent`；模式与 parentSessionId 校验 | `subagent/src/index.ts:436-527`; `control.ts:16-28,56-104` | S | 一次性 provider 禁 follow-up |
| DSH_CORE-013 | UI 可点子代理树打开子 Session 或右侧嵌套对话，明示活动状态/运行时长/只读原因 | `client/ui-subagent/src/client/index.ts:52-101`; `SubagentHeaderLineage.tsx:18-45,196-395`; `sidebar-chat/index.tsx:18-21,51-82,129-201` | S | 仅源码 UI |
| DSH_CORE-014 | 真实 `SessionController` 的 page/follow/control/projections 与 Web `MutableSessionEventSource` 增量合流 | `api/session-controller/src/index.ts:118-176,524-603`; `control.ts:17-79`; `client/contract/events.ts:6-35,97-120` | S | 网络中断实测未做 |
| DSH_CORE-015 | Typert RPC 跨一个 WebSocket 多路复用逻辑流 `/api/remote.mux`；ping/pong / connection 失败归因 | `api/gateway/src/stream-protocol.ts:6-19`; `stream-server.ts:44-127`; `client/stream-client.ts:52-105,241-380` | S | in-flight stream 失连会 fail |
| DSH_CORE-016 | JSONL 事件日志有写入批处理、进程间单 writer 内核锁、损坏尾修复与格式版本通道 | `session/session-persistence-jsonl/src/storage.ts:35-60,85-118,186-224,270-339`; `lease.ts:1-28,39-60`; `format.ts:1-43,194-280` | S | Windows 运行未验证 |
| DSH_CORE-017 | Turn 级 token 精确归集按 attempt 事实验证，具 cached input/write、reasoning、total；失败样本不冒充精确 | `llm/token-meter/src/turn-usage.ts:6-35,81-139,170-275` | S | 不等同用户账单价格精确 |
| DSH_CORE-018 | 压缩模型复用上下文前缀，另有无模型工具结果裁剪与 durable shadow-price | `compaction/compaction-basic/src/summarizer.ts:110-179`; `compaction-tool-result-pruner/src/index.ts:44-68,128-170` | S | 触发策略在 Basic Engine |
| DSH_CORE-019 | MCP stdio/HTTP bridge 以 server/raw tool 稳定命名，断线重连、list changed resync 及注册撤销 | `mcp/mcp-client/src/index.ts:1-14,154-192`; `tools.ts:1-12,81-158` | S | 需动态断线 |
| DSH_CORE-020 | 实验 Agent Team 是独立 Service：持久化 Lead Session DAG tasks，member roster，spawn、message、wait、interrupt | `experimental/agent-team/src/index.ts:55-109,129-211`; `task-board.ts:28-255`; `journal.ts:55-70` | S | experimental，不等于默认开启 |
| DSH_CORE-021 | 后台 jobs 对浏览器提供按 offset follow 与 kill；浏览读取不消费模型自己的 cursor | `api/job-controller/src/index.ts:1-8,75-115`; `jobs/jobs-local/src/pump.ts:53-86` | S | 与 agent task 不同概念 |
| DSH_CORE-022 | Trajectory 具有 turn/step/tool-call ledger、请求重试详情、prompt diff、虚拟化、timeline | `client/ui-trajectory/src/client/TrajectoryView.tsx:132-380`; `TrajectoryTable.tsx:2080-2257,3170-3194` | S | UI 是否在旧 npm 构建中 U |
| DSH_CORE-023 | CLI 是先选择 Profile 的薄启动器，后由可组合插件树解析内部命令，`plugin` 把操作交 pnpm | `apps/cli/src/args.ts:1-14,83-99,143-210`; `bin.ts:1-79` | S | 发布 CLI 版本 U |
| DSH_CORE-024 | schedule 是带持久化 delivery history 的 Host service；Goal round driver 带异步轮次/等待子 Agent | `schedule/schedule/src/index.ts:1-25,90-118`; `goal/goal-round-driver/src/index.ts:1-20,77-103,173-255` | S | 默认启用需证实 |
| DSH_CORE-025 | PTC node 支持独立 worker process 或保留作用域 REPL 状态；可选 sandbox 由 runtime 约束 | `ptc-runtime/ptc-runtime-node/src/index.ts:1-11,36-105,186-240` | S | 需实际运行验证 |
| DSH_CORE-026 | 插件以 Cordis effect-scope 注册与卸载；插件管理用 pnpm/profile overlay 与原子写入 | `boot/plugin-manager/src/operations.ts:1-16,285-450`; `mcp/mcp-client/src/index.ts:154-192` | S | 单独官方 host，非社区 Desktop |

## 要避免的误判
- `Agent Teams` 属于 **experimental**；未检查其是否在任一发布 CLI/Web 默认 profile 装配，故不能说所有用户默认具备。
- `send_message` 只有确认接收，不是 child 的回答；`interrupt_agent` 不会自动级联中止全部后代。
- `subagent` 的 local continuable 与 external one-shot 行为不能混为一谈。
- 可查看 token 具体字段 != 实际供应商提供所有这些字段；代码在无充分依据时允许返回 undefined。
- 源码存在 UI 不代表 `0.0.1-rc.5` 的旧版打包包含同一组件。
