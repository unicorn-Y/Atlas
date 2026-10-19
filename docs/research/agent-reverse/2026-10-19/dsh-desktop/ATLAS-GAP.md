# Atlas main 实代码差距表

**固定 Atlas main 基线：aa6196f550098cc46081dc6db2c376cb87ddffa5。** 比较行为链而非宣称已有某按钮/模块就等价，且**不误说 Atlas 缺少已经存在的 delegation/WS/health**。

| 行为 | 竞品真实来源 | Atlas main 真实调用点 | 判定 |
|---|---|---|---|
| 创建子代理与并行执行 | 官方 DSH Subagent（A runProfile；B dsh web） | core/atlas/agent/tool_node.py:604-720 的 delegate_task、定义/模型/深度/权限/回调、run_usage；同文件 delegate_parallel | **已有后端**，非缺失；实际并发上限/质量未测 |
| 子代理运行中干预/停止 | 官方 ui-subagent continuable/Stop | core/atlas/api/runtime_ws_router.py:70-112 处理 subtask.message 并调用 delegation.steer_subtask；frontend/src/renderer/components/ConversationActivity.tsx:145-176 有 steer 表单；frontend/src/renderer/store/useAtlasStore.ts:~850 有 cancelSubtask/steerSubtask | **有实线**，但不等于独立子 Session 多轮管理 |
| 展开子代理树并点击进入子 Session | 官方 ui-subagent 从 child catalog 开 target Session，带 parent/child/mode address；侧栏复用 Conversation | frontend/src/renderer/components/ForkTree.tsx:12-55 是普通会话分叉树，按照 parent_session_id；ConversationActivity.tsx StepTrack 是当前父 run 时间线 | **主路径尚不等价**，需实现/确认可寻址 child_session_ref 与主视图/侧栏进入能力（P1） |
| 子代理 Token/运行时长/工具轨迹 | 官方 SubagentHeaderLineage 的 Session projectionValues.tokenUsage、subagentTiming；ui-trajectory 的 durable Event | ConversationActivity.tsx:85-90 显示 usage；tool_node.py:~680 上报 subagent usage 带 subtask_id；frontend/src/renderer/services/runtimeEvents.ts 解释 AgentEvent | **部分具备**，没有查到每个 child 独立完整 projection 面板（P1） |
| 事件流、顺序、断线重放 | 官方 Session events 与 replay/projection（社区 Host 不自造） | core/atlas/api/runtime_ws_router.py:11-33、resume(after_sequence)，frontend/src/renderer/services/runtimeEvents.ts:51-82 按 sequence 去重重排 | **已有实线**；客户端 MAX_RUN_EVENTS=800 丢早期缓存，应能从 durable history 翻页重建（P1） |
| 运行/后台和进程恢复 | A Host controller；官方 DSH session / jobs；B 退出 GUI 留 node engine | core/atlas/runtime/hub.py、hub_control.py 具 detached hub 与 DBOS durable scheduler；core/atlas/api/run_drive.py 有后台 Run 链路 | **有基础**，不能未经中断实测说所有 turn 都恢复或都不恢复（P2/U） |
| 启动健康与失败传递 | A BackendController 分离 ready/error+ACK；B 业务 session/list ready | frontend/src/main/backendProcess.ts:19-31,54-106,178-227 有健康探针、启动进度、stderr 尾；:270+ 校验外部 API token | **已有健康检查**，只引入 A 的精确进程退出/任务锁语义，不重造健康系统（P2） |
| 插件/Profile 装配及状态 | A Cordis profiles/bundles、market/routes；B 官方 profile+可选 tools | core/atlas/api/plugins_router.py、runtime/hooks.py，frontend/src/renderer/pages/SkillDiscoveryPage.tsx/SkillsMarketPage.tsx | Atlas 是**不同扩展架构**，是否有“已注册但未接线”的问题须沿 Registry→实际 invoke 审查（U） |
| Safe Mode 配置隔离与 checkpoint | A NextRecovery 备份配置 + Safe Mode 最小 Profile | 当前已查 backendProcess、Hub 没有对应 A 级别入口证据 | **本轮未找到等价主路径**，不等于全仓绝对不存在（P2） |
| 引擎版本 pin / rollback | B updater.ts、kernelRootDir、verifiedVersions | Atlas 为自身 Hermes engine / model provider 路由；不可套 dsh/npm CLI 版本表 | 可吸收多版本并存的理念，直接复制不兼容（P3） |
| 浏览器 WS 动态撤权 | A webserver.ts 控制 registerUpgrade 和 browserSockets | Atlas FastAPI /ws/chat 与 Electron 进程，尚未全链检查动态撤权与 origin | **未证（U）**，不判缺失 |

## 本轮从实物包确认的队列差异（Atlas main `aa6196f550098cc46081dc6db2c376cb87ddffa5`）

随 A `2.0.19-next` ZIP 嵌入的官方 `@deepseek-ai/dsh-agent-loop@0.2.1-rc.2` 用 session event projection 持久保存 Agent 自己的双队列：`next-turn` (完整后续 turn) 和 `next-step` (运行中下一边界 steer)。同包 `@deepseek-ai/dsh-api-session-controller@0.2.1-rc.2` 对正在运行和冷恢复的 Agent 暴露 `session/updateQueue`，支持对仍 pending 的项 edit/remove/steer，并对过期 ID、子代理所有权、附件及运行状态作校验。详见 `IMPLEMENTATION-TRACE.md` 与 `extracted/A-runtime-symbol-index.md`。

Atlas 当前 UI 的 `frontend/src/renderer/store/useAtlasStore.ts:74-78,291` 把 follow-up queue、pause flag、pending steer 保存在 renderer Zustand state；`:228-230` 的 localStorage helper 存设置，初始化行将这三个队列 state 置空。`sendMessage` (`:623-635`) 会在 queue/steer 间选择；`removeQueued`、`sendQueuedNow`、`steerQueued`、`resumeQueue` (`:686-714`) 管理当前客户端队列；确认事件及 run 结束时的补偿在 `:571-600`。运行中的 steer 实际由 runtime `backend.steerRun` (`:971-975`) 发送。检查到的这条 Atlas 常规 Chat follow-up 队列不是 session 持久 event/冷 Agent 队列，renderer 重建后也没有从后端恢复该队列的逻辑。Atlas 子代理则另有 `delegate_task` / parallel delegation 和 steer/cancel API，不应与用户会话 follow-up 混为一谈。

判定：Atlas 已有本机前端排队、移除、置顶立即执行、运行中 steer 及未确认 steer 回退机制；差别是队列身份/变更是否由后端 session event 持久化并能按 session cold-restore。将 DSH 机制映射到 Atlas 前应先决定是否需要跨 renderer/backend restart 保留用户排队意图，并定义 queue-item 与 run/session 的存储和确认语义。未做 Atlas 运行中重启实验，以上是 main 静态源码比较，不是运行行为证明。

## 明确需解决的实质差距

**不是继续加按钮，而是可寻址的子 Agent 执行实体**：官方 DSH 每个可本地导航的 child 有 direct-parent address、SessionReference、独立投影与 composer 继续/只读行为，点击与侧栏实际使用同一个 Conversation 渲染器。Atlas UI 的现有 ForkTree 是人工会话分叉，ConversationActivity 则是父 run 下的子任务轨迹；两者不自动构成 DSH 那种 child session 用户体验。

**推荐的最小改动闭环**：先追踪 Atlas delegation 的 subtask_id → child agent session_id → parent run/parent session → messages/events/usage 持久化的真实关系；若模型里已存在则只打通 adapter；若缺则补最小持久引用。接着给真实子任务 StepTrack 一个“打开子会话”入口，尽量复用现有 Conversation、SidePane、Event replay；根据 child mode/parent available 区分能否继续输入与单次 Stop；展示真实 child token/time/状态，勿把父 run 的使用量随意分摊。

**第二优先级**：保留已有健康检查与重试，用 A 的 start/stop 单归属、清洁 shutdown ACK、Host IPC 错误详情、配置隔离/恢复手段修实质竞态；B 的“端口 PID 不分所属强杀”是反例，Atlas 不应复制。**第三优先级**才考虑 market UI 的实际激活反馈、版本 pin、多窗口/WS 权限细节，避免泛滥造功能。

## 明确已确认与未查明

S 已确认 Atlas 有 delegation、子代理 steer、token event、WS resume/dedupe、back-end startup progress、Hub durable scheduler 代码。S 主路径没找到独立 child Session 树与多窗导航；但**未逐行遍历 Atlas 全仓**，保留可能有其他隐蔽 API/历史模型的 U 标记。所有“效果是否达到对标”须真正跑至少父子多轮/并行、Stop、失败与断线重连后再 R 验证。
