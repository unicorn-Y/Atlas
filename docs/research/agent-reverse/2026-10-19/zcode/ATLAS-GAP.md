# ZCode 3.15.1 vs Atlas main：逐能力真实代码差距

证据基线：Atlas main `aa6196f550098cc46081dc6db2c376cb87ddffa5`（本轮 `git fetch origin main` 后 HEAD 未变化）；ZCode upstream source 3.15.1 `aac4755666d09fdcd70272fcf063c077a639015f`; ZCode Desktop/runtime 3.15.3 verified package hashes见 `extracted-3153/ASSET-HASHES.txt`。旧源码对照和 3.15.3 packaged CJS 均为静态 S，**没有 R 运行验收**。本轮同版 CJS 已证实底层机制确实打包；尚不能把 3.15.1 UI/IPC 源码或旧 Atlas 对照升级成 3.15.3 全链等价结论。

| ZCode 机制 | Atlas main 的真实基础 / 锚点 | 差距判断 | 建议 |
|---|---|---|---|
| ZCODE-001 独立 Electron Host | core/atlas/runtime/hub.py L1-12,L119-161 真实后台 Hub；frontend Electron、core/atlas/api/runtime_ws_router.py | 部分；Atlas 有后台，不是没有；ZCode utilityProcess 专用 Host/Scheduler 的隔离和事件桥需逐功能对比 | P1 把任务执行状态与 host 健康状态分开 |
| ZCODE-002/003 逐步工具调度 | core/atlas/agent/run_phases.py L146-209 有真实 execute_run、事件队列与取消；core/atlas/agent/tool_node.py L58-166 真正执行工具 | 基础存在；未证与 ZCode 的 streaming tool ledger、queued/executing/cancelled 明细一致 | P1 在原工具链补 lifecycle 事件，不重造 Hermes |
| ZCODE-004/005 child agent | core/atlas/persistent_agents/store.py L21-144 可配 Agent 模型/工具；core/atlas/agent/subagent_worktree.py L237-342 真隔离 worktree | 部分；未见 ZCode 所有 ready/watcher/前台转后台、模型借用和 inherited MCP 语义的统一 registry | P0 对齐运行态 ID、status、parent、权限/模型与通知通道 |
| ZCODE-006/008 子代理消息回流 | core/atlas/agent/run_phases.py 有 steer_queue；frontend/src/renderer/store/useAtlasStore.ts L17-21 有 steer/redirect/queue | Atlas 有用户追问队列，但这不等于 child result 的 branchGeneration 过滤和 model-only synthetic notice 的完整闭环 | P0 在父 runtime 下一模型 step 排空 task notification，保留 child provenance |
| ZCODE-007 runtime task registry | Atlas profile store、Hub、scheduler 与外部 process 已分工 | 部分；profile 长期存储不能替代 live task waiter/backgound switch/child pending messages | P0 增加短活 registry 和有归属的 durable 事件分别负责不同状态 |
| ZCODE-009/010/011/014/015 workflow replay journal | core/atlas/scheduler/__init__.py L310+ 真 APScheduler；core/atlas/agent/planning.py 计划工具；core/atlas/agent/checkpoints.py 文件检查点 | **未发现同构机制**：actor ask siteId@ordinal + inputHash + SQLite event/journal + replay/导入缓存。Cron/计划/checkpoint 不等于这套引擎 | P0 建独立 workflow engine / journal / script-host，复用 Atlas agent 执行 |
| ZCODE-012 自适应并发 | core/atlas/models/router.py、agent/fallback_cooldown.py 分别处理模型路由/冷却 | 部分；冷却策略不是按 provider/key 反馈调并发 cap 的 epoch/streak 机制 | P0 单独并发控制器，按真实 429/Retry-After 自适应，不预先静态压低最大并行 |
| ZCODE-013 stopped / errored / interrupted | core/atlas/agent/error_classifier.py、retry_utils.py 有模型/工具错误路径 | 部分；没有确认等价 workflow started/stopped/superseded journal 状态机 | P0 取消、断网/host 崩溃、任务实败分离，重启由 journal 推断 |
| ZCODE-016 请求级+turn 级 usage | core/atlas/api/usage_router.py 存在 usage API，models/tokens.py 估算，Hermes runtime 保留 provider 链 | 部分/待核；不能认定缓存写入/读出、推理 token、retry、TTFT 已全按请求持久化 | P1 按 ModelUsageRecord/TurnUsageRecord 字段逐一核源 |
| ZCODE-017 两级 compact | core/atlas/agent/injection_budget.py、prompt_caching.py、engine/hermes_runtime.py 真实上下文与缓存模块 | 部分；不应断言 Atlas 无压缩；快速反复压缩、失败状态和 token 用量口径需验证 | P1 按上下文装配点对齐 |
| ZCODE-018 fork、ID remap | core/atlas/engine/session_sync.py L1-12 已用 Hermes SessionDB 为唯一写入口，支持 rewind/fork，engine/branch_summaries.py 有分支 | **等价方向**；目标仍应核对 message/part/tool/turn 的 ID 完整重映射，尤其 workflow child | P1 不再造第二套 SessionDB |
| ZCODE-019 MCP 连接池/工具刷新 | core/atlas/tools/mcp_client.py L1-18,L171+ 真 stdio/SSE MCP 客户端 | 部分；MCP 功能已存在。OAuth、elicitation、resources/subscribe、tools/list_changed 到模型下一步是否完整接线未证 | P1 单项查缺补齐 |
| ZCODE-020 插件及多平台 Skills | core/atlas/plugins/runtime.py L1-135 支持 Claude/Hermes 插件、Hooks/commands/skills；skills/registry.py | 部分；ZCode/Claude/Codex/Cursor manifest 跨生态兼容以及 Marketplace UI surface 是否等价待查 | P1 扩已有 loader，而非平行造独立系统 |
| ZCODE-021/022 MCP Apps 动态 UI 沙箱 | frontend/src/renderer/components/MessageThread.tsx L47-95 有消息/事件 UI；plugins/runtime.py 聚焦插件工具/Hook | **本次未找到对等的** AppBridge + JSON-RPC MessagePort + per-app Electron partition + 资源订阅能力 | P1 主进程 guest、renderer bridge、后端 resources 完整接线后才建 UI 卡片 |
| ZCODE-023 Workflow 执行图/报表 | frontend/src/renderer/pages/agents/AgentsPage.tsx L21-57 有 8 个 Agent 标签页，MessageThread 真实展示事件 | 部分；Agent 页面存在不等于 workflow node/phase/actor/artifact/version 的权威投影 | P1 后端 journal/query/event contract 先行，再画 timeline |
| ZCODE-024 定时调度独立进程 | core/atlas/scheduler/__init__.py L1-35,L310+ APScheduler 4；runtime/hub.py 真后台执行 | **等价方向**；ZCode 无 Host 的 transient 派发退避应和 Atlas Hub 状态/任务状态区分比较 | P1 不重造 scheduler |
| ZCODE-025 群聊/远程会话 | core/atlas/api/group_router.py L1-72 真 Group REST/Orchestrator、api/channel_router.py 渠道 API | 部分；有 Group/API 不能直接推断 Feishu WebSocket 与 ZCode 的 task snapshot ETag、远程 replayable 一致 | P2 单独实证查验 |
| ZCODE-027 同版运行差异 | Atlas 本次 HEAD 固定，ZCode 3.15.3 只有采集记录 | **U**：不许从 3.15.1 推断 3.15.3 现状 | 见 EXTRACTION-REQUEST |
| ZCODE-030 tool scheduling / queued lifecycle | Atlas `tool_node.py` 与 `run_phases.py` 有真实工具执行，但本轮未核对 Atlas event schema 是否与 CJS 的 scheduled/tool_queued/executing 持久化逐项对应 | 基础能力在；队列状态、流式 tool call 关闭和取消投影的等价性 U | 先逐项比 event/DB 字段，不增加并行 UI 结论 |
| ZCODE-031/032 子 Agent task registry/background parent detach | Atlas 有 subagent worktree 与 Hub；此前已定位 Atlas 外部 ZCode backend 每轮 subprocess 且 `resume()` 未实现。3.15.3 CJS 已见 registry waiter、background/detach 及 Subagent events | 部分；尚未证明 Atlas child 成果以 generation-safe model-only command 回到父下一轮，或在 detach 后跨 host 重启保持同语义 | 继续核 Atlas runtime IDs/event queue/resume 持久化实现，不将子进程后台状态等于任务恢复 |
| ZCODE-033 dynamic-workflow journal/replay | Atlas Scheduler/checkpoints 不是 DWF `run/node/activity` schema；3.15.3 CJS 已见同版 journal migration 和 input hash/actor sequence anchors | 同构机制本轮未发现于已列 Atlas 路径；差距较可能为实质性，但须直接核 Atlas 现 main 的 scheduler/checkpoint persistence 再定范围 | 查当前 main 的 journal schemas 与 resume dispatch；不在研究阶段施工 |
| ZCODE-034 Retry-After | Atlas fallback cooldown/model router 已覆盖部分 provider fault policy；3.15.3 CJS SDK helper 解析 Retry-After 头 | 部分/未知：header utility 不证明高并发 Agent 修复是同一算法，也不证明 Atlas lacks delay parsing | 对照 Atlas HTTP client/model runner retry handling，维持 release-note 关联为 U |

## 最值得直接吸收的机制链条

1. **双层任务生命线**：短活 task registry 负责进程内等待/状态，持久 journal 负责跨重启；parent-child provenance / branch generation / model-only 回流进入 Hermes 下一次模型请求。目标是“子 Agent 继续执行且父 Agent 真正获取结果”，不是把子 Agent 的通知做得更漂亮。
2. **动态工作流**：workflow script -> child sandbox -> engine ask 调度 -> Atlas 已有执行能力 -> SQLite journal -> replay/resume -> UI projection。避免把 Scheduler、Todo 或 Prompt Planning 假装为 ZCode Workflow。
3. **动态并发治理**：provider/key 为粒度，限流反馈改 cap，4 次成功+待发队列再提升，不设任意全局子代理上限；保持默认最大放权但让实际服务拒绝参与负载治理。
4. **MCP App**：真正 MessagePort/AppBridge/ResourceSubscription/WebContents 沙箱，而非静态插件配置清单；Atlas Agent 本体权限与不受信任插件页面的页面权限是不同概念。

## 清晰可证的 Atlas 接口缺口

core/atlas/agents/backends/zcode.py L22-105 当前只把每个 prompt 交给独立 subprocess 执行，stdout 每行包装成 text，stderr 包装成 progress；resume() L97-99 明确抛出 NotImplementedError。这是**Atlas 外部 ZCode Backend** 的会话续接缺口，不是 Atlas 内部 Hermes SessionDB 的缺口；更不等于 ZCode 原生没有 resume。结构化 tool 子进程事件目前没有从这个适配器发出。

## 研究限制

本次只做研究与代码审阅，**没有改 Atlas 正式业务源码，没有执行 smoke/e2e**。状态“部分”和“未找到同构”均有扫描/已读路径范围；不能根据源码文件名作全仓断言。3.15.3 真包与 v3.15.1 的功能兼容性仍需实物取证。
