# 可供 Atlas 吸收的成熟机制与许可边界

**所有项目均按固定源码证据研究，未复制或修改 Atlas 业务代码。** 实际已读：A 根 LICENSE 为 MIT (2026 Anywhere Labs)，A Next LICENSE.upstream 为 MIT (2026 DeepSeek)；B 根 LICENSE 为 MIT (2026 dongdong-agent)；官方 deepseek-harness/LICENSE 为 MIT (2026 DeepSeek)。落地若复制软件须保留许可证及版权声明。A 还含 THIRD_PARTY_NOTICES.md、vendor/agents-anywhere 与运行时包，**这些依赖须逐包核许可，不能误认为顶层 MIT 覆盖所有 tarball/二进制**。logo、图标、商标与可复制源码权利另行区分。

| 候选 | 能吸收的成熟结构及真实依据 | Atlas 落点 / 必要依赖 | 不可直接复制处 |
|---|---|---|---|
| R-01 官方 subagent exact address 与侧栏会话 | O ui-subagent/src/client/index.ts、SubagentHeaderLineage.tsx、sidebar-chat/index.tsx；含 parentSessionId + childSessionId + mode、SessionReference retain/release、递归 lazy catalog、Token/运行时长投影 | 先跟 Atlas backend delegation 的 subtask_id、child session、parent、mode、events/usage 映射，再挂现有 ConversationActivity/SidePane/MessageThread；继续输入/Stop 接到真实 backend | 不能把 Cordis UI 插件直接放进 Atlas 自有 React；没有持久 child session 就不要先造 UI |
| R-02 A BackendController 单归属生命周期 | A Next src/backend-controller.ts:33-172、src/host-process.ts:228-466；stop 后 clean exit、错误保留 cause、IPC ACK、pending RPC reject、聚合清理错误 | Atlas 已有 frontend/src/main/backendProcess.ts 进程与日志管理；针对竞态/更新任务互锁做差分吸收 | 不要复制所有超时及测试；更不能把 Host 失败等同整个 Agent job 自杀 |
| R-03 A Profile 安全模式/配置 checkpoint | A Next src/profiles.ts、src/recovery.ts、src/desktop-runtime.ts；可选插件显式启用、最小临时 Profile、回滚配置快照 | 现有 Atlas hooks/plugins/skills 接入链按 native engine 与扩展注册结构做隔离 Profile 启动；检查插件实际启用状态 | Cordis bundle manifest 不是 Atlas 原生数据模型；checkpoint 只覆盖配置不自动恢复 Agent turn |
| R-04 A HTTP+WebSocket 动态断开 | A Next src/webserver.ts setBrowserAccess、registerUpgrade，撤销已存在 browserSockets；native stream 不受影响 | 先核 Atlas runtime_ws_router 与 Electron API Token / Origin 实际机制是否已经具备；再差分处理动态撤权 | 原版依赖 @deepseek-ai/dsh-host-webserver，不能整体迁移 |
| R-05 B 业务 readiness 分离 | B src/lib/dshEngine.ts probePort/probeEngineReady/waitEngineBusinessReady + Rust src-tauri/src/lib.rs probe_engine_ready | Atlas 早有健康检查，应抽取“HTTP 已起 vs 会话查询真的 ready”判据，避免冷启动擦会话指针；记录原始错误 | B 30s 后照常放行，不能宣称完全消除竞争；HMAC DSH Cookie / 127.0.0.1 特定协议不可用到 Atlas |
| R-06 B kernel 多版本管理 | B src/lib/updater.ts、src/lib/enginePatch.ts、TitleBar.tsx、StatusBar.tsx；已验证版本、回滚、patch overlay 与错误展示 | Atlas 外部 Engine/Provider 的真实版本选择，借 pin / rollback 的机制，不把 npm dsh 包管理强行植入 Hermes engine | B 有 Windows hardcoded Path 和“强杀任意端口占用者”的问题；这部分不借 |
| R-07 A 原生 UI slots 与状态反馈 | A src/client/index.ts ctx.slots.inject、src/desktop-contract.ts DesktopState、dsh-community-market/src/client/MarketSettingsTab.tsx | 让 Atlas Plugin/Skills 市场从真实注册/启用/失败状态派生展示，避免“UI 有开关=已接线” | A 的官方 Cordis Slot API、AA remote bridge 仍为第三方依赖，不能未经协议/许可证审查复制 |
| R-08 官方 Trajectory durable projections | O packages/client/ui-trajectory/src/client/TrajectoryView.tsx + trajectory-event-projection.ts | Atlas 已有 runtime events 和 800 条缓存上限；补历史分页/子会话独立 time & usage 投影，而不是只显示父 run 内存尾部 | 不因“工具事件展示”存在就认定支持全量可追溯轨迹；要后端持久日志配合 |

## 具体优先级与停止条件

P1：**优先读懂和复用 R-01/R-08 的行为契约**。Atlas 应确认每个 delegated child 具有持久可寻址 session identity、parent linkage、独立 usage、工具消息与可继续性；现有 steer/stop 不需要重写。

P2：A 的启动状态和 config checkpoint 是成熟机制，但 Atlas 已经有健康/启动进度、Hub/DBOS，不要另造一个独立核心。只补现存 Host 归属、清洁退出、保留任务与更新锁之间的真实缺口。

P3：市场、版本控制、动态 WS revocation 在明确旧代码不支持的具体业务后才迁移。

**不应吸收** B restartEngine 按端口无条件 taskkill 外部复用进程；B 在任意 401 端口断言找到 DSH；把 Next 配置兼容字段 jobCompleted/jobFailed 当成现成功能；把官方子代理可导航性扩展解释到 external leaf；把可选市场/AA bridge/native CUA 实验驱动写成默认可用。