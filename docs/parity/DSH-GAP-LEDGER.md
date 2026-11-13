# DSH → Atlas 差距账（证据级）

> 生成日期：2026-11-13
> 基准：DeepSeek-Harness `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`
> 本地基准副本：`D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`
> 方法：4 条并行线各自**读 DSH 实现体**（不是只读文档）→ 回 Atlas 找对应实现 → 给路径行号 → 判定等级。
> 判定词：`PRESENT-PARITY` 同等 / `PRESENT-WEAKER` 有但少关键性质 / `ABSENT` 没有 /
> `PRESENT-STRONGER` Atlas 更强（DSH 侧是缺口，**不要为了"对齐"而削弱**）。

## 结论摘要

| 维度 | 差距条数 | 其中 P0 | 其中 P1 | Atlas 更强的项 |
|---|---|---|---|---|
| 引擎与工具执行 | 36 | 3 | 12 | 2（重连取消、写路径诊断增量） |
| 会话与持久化 | 33 | 2 | 11 | 2（长期记忆、rewind） |
| 插件与扩展 | 33 | 1 | 10 | 3（hook 信任门、skill 依赖门、agent 声明） |
| 桌面与 UX | 33 | 0 | 10 | 5（rewind、多窗口/分栏、消息操作、富预览、托盘） |

**最重要的判断**：DSH 的优势不在功能数量，而在**两条地基**：
1. **会话事件日志是唯一真源**，模型历史由它派生（`deriveMessages()`）。Atlas 是"可变 SQLite 消息表 + 内容被抹掉的 run JSONL"，这是 P0。
2. **一切皆插件的组合根**（Cordis service/seam/profile/bundle/patch）。Atlas 是 51 字段扁平 `AppServices` + 手写 router 元组，这是 P0。

这两条不补，其余所有"补功能"都会退化成再加一个硬编码分支。

---

## 一、引擎与工具执行（36 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E1 | 只追加会话事件日志 = 唯一真源；`deriveMessages()` 派生模型历史 | `packages/core/session/src/index.ts:798,819`；`docs/subsystems/session.md` | `engine/session_sync.py:385-415` 直接写 role 行；run 事实走 `loop.py:603` JSONL 且**内容被抹掉**（`logs.py:104-116` 存 `{"length":N}`） | ABSENT |
| E2 | turn / step 两级生命周期（turn=一条用户消息，step=一次模型调用），`turn/end` 带 typed reason | `packages/core/agent-loop/src/agent.ts:298,400`；`docs/agent-lifecycle.md` | typed terminal reason 已写入 run journal/result；完整 turn/step state machine 和 per-step end event 仍缺 | PRESENT-WEAKER |
| E3 | 工具执行流水线三瀑布：pre-execute → execute → post-execute → result，带 typed decision | `packages/core/tools/src/index.ts:1375,1499,1151,1787,1838`；`docs/tool-execution-pipeline.md` | 有 PreToolUse/PostToolUse hooks 和 result finalizers；完整 typed decision/waterfall/result observer 尚未统一 | PRESENT-WEAKER |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E4 | 每工具强制输出契约 `{schema, render, presentationMeta}`，成功即校验 | `packages/core/tools/src/index.ts:214,1838` | 处理器自由返回 `{content,data,is_error}`；只校验**输入** `tools.py:172` | ABSENT |
| E5 | 两有序表 durable inbox：`next-turn` / `next-step`，`inject` 不唤醒 | `packages/core/agent-loop/src/inbox.ts:74,109` | `engine/kernel/inbox.py` 持久化两条 lane 并回放/确认；`runtime_ws_router.py` inject 分支写 inbox，不唤醒 steer 队列 | ✅ 本轮关闭 |
| E6 | 请求信封落日志 + 工具增删发 developer 消息告知模型 | `agent.ts:626-700` | `request_envelope.py` 记录请求摘要/角色/长度/工具名；`loop.py` 在工具池变化时发 developer 消息 | ✅ 本轮关闭 |
| E7 | 并发安全按**调用参数**判定，派发前**复检**，不支持者成 barrier | `packages/core/agent-loop/src/tool-calls.ts:60,122,199` | `tools.py` 调用级参数分类并在派发前复检；读写不明的调用串行化为 barrier | ✅ **本次已修**（参数感知 + 派发前复检 + barrier） |
| E8 | 上下文压缩在 **step 边界**按实测压力触发 + 溢出重试需 surface 代次前进 | `docs/subsystems/compaction.md`；`compaction-basic/src/config.ts:20,75,105` | `loop.py` 每次模型调用前检查压缩；overflow 只有 provider history 摘要前进时才重试 | ✅ 本轮关闭 |
| E9 | plan 模式：durable `plan/mode` 事件 + `plan:policy` 提示段 + 拒绝时带用户反馈 | `packages/plan/plan-mode/src/index.ts:52,217,425` | kernel 每次模型调用按 live mode 重建共享 `PlanMode` 指引，持久化 plan-mode 变化并反馈拒绝 | ✅ **本次已修**（每轮按 live mode 重建 + 共享 PlanMode 实例） |
| E10 | todo 每次写入都是 durable 事件，重启/叉分/未压缩也存活 | `packages/todo/tool-todo/src/index.ts:80,118` | `TodoStore` 将 `todo.updated` 快照写入 `session_events`，新 run 从最新快照恢复，写入失败会回滚内存状态 | ✅ 本轮关闭 |
| E11 | goal 变更 CAS `{id, revision}`，过期拒绝；轮数上限默认 256 | `packages/goal/goal/src/index.ts:244` | `engine/goals.py` 持久 goal_id/revision，SQLite 单次写回原子比较并拒绝过期 writer；goal_subgoal 要求并返回当前 CAS token；默认 max_turns=256 | ✅ 本轮关闭 |
| E12 | 审批关闭四值：`allowed-once`/`rejected`/`cancelled`/`unavailable`，全部 fail-closed，且 `ask|never` 在服务内先于任何 answerer 生效 | `packages/interaction/user-approval/src/index.ts:100,225-232` | 审批 asked/decided 通过 append-only `session_events` 持久化；ask/never 策略先于 answerer；失败关闭 | ✅ 本轮关闭 |
| E13 | 权限预设同时绑定 **沙箱模式 + 审批策略**，不匹配时派生 `custom` | `packages/interaction/permission-presets/src/index.ts:189-194` | `approval_policy.py` 预设绑定 permission/sandbox/approval 三维；RunState 和 resume 保留三维设置，不匹配时派生 `custom` | ✅ 本轮关闭 |
| E14 | OS 级沙箱按**每次调用**给 `read-only`/`workspace-write`/`danger-full-access`，并报告实际执行等级 | `packages/sandbox/sandbox-local/src/profiles.ts:16`；`docs/subsystems/sandbox.md` | 只有整 run 的 Docker 容器或主机 + `allowed_paths` 编辑器检查；`full_access` 下 shell 无文件效果边界 | ABSENT |
| E15 | 持久 PTY：owner 鉴权、`waitReason` 四值（stdin_read/inferred_idle/timeout/session_exit）、有界回滚 | `packages/experimental/tool-terminal/src/index.ts:166-395` | `local_execution.py` 按 run owner 隔离进程读写/取消，并返回 `stdin_read` / `inferred_idle` / `timeout` / `session_exit` | ✅ 本轮关闭 |
| E16 | 统一后台作业注册表：`job_output/list/kill`，256KiB 环形缓冲，settle 后 16KiB，每 owner 最多 10 个 | `packages/jobs/jobs-local/src/index.ts:33-42,128` | `ExecManager` 统一 owner-fenced shell 与 subagent 注册/列表/输出/终止；运行缓冲 256KiB、settled 16KiB、每 owner 10 个；`job_*` 工具已暴露模型调用 | ✅ 本轮关闭 |
| E17 | 子代理统一激活：能力声明校验、`toolFilter` 真删且拒执行、fork 子（继承父已完成前缀）、persona | `packages/subagent/tool-subagent/src/index.ts:96,171` | 有 delegate 工具 schema/深度/权限降级/worktree；仍缺 fork 已完成上下文和 persona 的完整激活路径 | PRESENT-WEAKER |
| E18 | 工具内请求沙箱升级：`sandbox_permissions` + `justification`，按调用审批，拒绝不动既有策略 | `packages/core/tools/src/ptc.ts:387-405` | 单次 justification/approval 已接入；Docker 有 per-call 模式，host executor 缺少可执行隔离时 fail-closed | PRESENT-WEAKER |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| E19 | `concludeTurn()`：工具结果可声明"本轮结束" | `packages/core/tools/src/index.ts:435,1428,1860` | 无；总要再付一次模型往返 | ABSENT |
| E20 | 重复调用提醒：按 `(name, canonical_args)` 连续相同判定，阈值 [3,5,8]，只提醒不否决 | `packages/guard/repeat-tool-reminder/src/index.ts:44,58` | `stuck.py` 按连续相同工具名和规范化参数在第 3/5/8 次发提醒，不阻止调用，不纳入结果文本 | ✅ 本轮关闭 |
| E21 | 工作目录 per-session durable `working-directory/change`，沙箱写根不随之移动 | `docs/subsystems/working-directory.md` | 工作区固定 per run；模型只能求用户改 | ABSENT |
| E22 | Agent Teams：root 范围 roster、steer-only 消息、任务 DAG per-mutation revision CAS、`blockedBy` 无环、`waitForChange` | `packages/experimental/agent-team/src/index.ts:135-199` | 存储都在（`groups/store.py`、`kanban.py:15-190`、`peer_inbox.py`），但**没有作为模型工具暴露** | ABSENT（in-loop） |
| E23 | Workflow：模型写编排**脚本**（`agent()`/`parallel()`/`pipeline()`） | `packages/workflow/workflow-ptc/src/index.ts:109` | `workflow` 工具只从目标规划 DAG，模型不能表达自定义控制流 | PRESENT-WEAKER |
| E24 | Ralph：串行上下文重置迭代，`maxRounds` 256，handoff ≤16KiB | `packages/experimental/tool-ralph/src/index.ts:35,151` | 无 | ABSENT |
| E25 | 空闲维护槽 `runMaintenance()`，公开状态仍 idle | `docs/subsystems/core.md#the-agent-handle` | 无；压缩/目标评估在用户消息路径或定时器上 | PRESENT-WEAKER |
| E26 | `tools.restrict()` 注册级 scope 层，未知名/空集注册即失败 | `packages/core/tools/src/index.ts:1103` | run 级 allow/deny glob 交集（`tool_permissions.py:6,35`），无进程内 per-agent 作用域 | PRESENT-WEAKER |
| E27 | PTC 模式：单一 `run_code` 传输，其它工具直调被拒并提示，子调用各记日志 | `packages/core/tools/src/ptc.ts:30` | `execute_code` 是**可选附加**工具，不替换工具面 | PRESENT-WEAKER |
| E28 | 压缩区域安全：位置跨度，不切开 tool-call/result 对，尾部按 token 计价 | `compaction-basic/src/region.ts:117,139` | `context.py:415-440` 行为等价（取最早未配对） | PRESENT-PARITY |
| E29 | `ctx.tokenMeter`：按 surface 节点分别计价，成功请求 usage 可锚定 | `packages/llm/token-meter/src/index.ts:101,146` | `token_meter.py:68-135` 只有压力档位，无逐节点计价 | PRESENT-WEAKER |
| E30 | LSP 四操作闭合联合 + provider registry | `docs/subsystems/lsp.md` | 五操作（`workspace_lsp.py:61-99`）但缺 `goToImplementation` | PRESENT-PARITY |
| E31 | 会话查询五工具（含 event read/trace/lineage） | `packages/experimental/tool-session-query/src/index.ts:66-109` | 只有 `session_search` + `read_session` | PRESENT-WEAKER |
| E32 | Git worktree：从固定 revision 创建，模型可"进入"而不必新开 run | `docs/subsystems/worktrees.md` | `task_artifacts.py:139-152` 可建，但要新 run 才切换 | PRESENT-WEAKER |
| E33 | 兜底补齐：写路径诊断增量（Atlas 独有） | — | `engine/lsp_bridge.py:38-80` | **PRESENT-STRONGER** |
| E34 | 取消时为每个跳过调用生成合成 `tool/result`，保证可重放 | `tool-calls.ts:250` | `tools.py:912,830-845` 已等价 | PRESENT-PARITY |
| E35 | 压缩锁 bracket 落 transcript，可检测孤儿 | `docs/subsystems/compaction.md` | `loop.py:1417-1440` lease 在 DB，崩溃后靠推断 | PRESENT-PARITY |
| E36 | 后台作业完成通知作为 followup 投递 | `tool-jobs/src/index.ts:30,253` | `atlas_runtime.py:880-930` 走 SQLite inbox + system block/steer | PRESENT-WEAKER |

---

## 二、会话与持久化（33 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S1 | 只追加日志 + `seq = log.length` 连续性契约，事件永不改写 | `packages/core/session/src/index.ts:798,819` | 两份互不相干的记录：run JSONL 文本被**故意销毁**（`logs.py:104-116`），SQLite `messages` 表原地改（`atlas_state_messages.py:559` UPDATE、`:879` DELETE、`:1008` archive_and_compact） | ABSENT |
| S2 | surface 折叠：`replace` 节点遮蔽早前 seq 范围，压缩不删事件 | `packages/core/session/src/surface.ts:120,594` | 压缩只 `active=0, compacted=1`（`:986`）后重写可见列表，无法表达"被摘要替换但保留原文" | ABSENT |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S3 | 会话格式版本 + 相邻迁移链 v0→v4；读到**更新**版本必须拒绝并指出路径 | `packages/core/session/src/types.ts:89`；`session-format/src/chain.ts:41` | `SCHEMA_VERSION = 32`；`atlas_state_schema.py` 对更高版本抛 `SchemaTooNewError` 并给出 DB 路径 | ✅ 本轮关闭 |
| S4 | 崩溃修复是 reader 侧补 closer（含 `turn/end{interrupted}`），不是重写 transcript | `packages/core/session/src/repair.ts:53` | `loop.py:740-745,2497-2502` 写合成**内容行**，后续读者无法识别为合成 | PRESENT-WEAKER |
| S5 | handle 式持久化：read/append/flush/close，单一写者，跨进程 kernel lease | `session-persistence/src/handle.ts:59,97,109` | WAL + busy_timeout + TTL lease（`atlas_state_common.py:569-582`）；TTL 到期即放开，非进程死亡释放 | PRESENT-WEAKER |
| S6 | checkpoint 三屏障 fail-closed，写失败就阻断派发 | `session-checkpoint-policy/README.md` | `require_checkpoint()` 在阶段边界、工具派发前和工具结果持久化后失败即抛错，kernel 阻断继续执行 | ✅ 本轮关闭 |
| S7 | 压缩 bracket 进日志，`summary` 记 shadowed seqs / token / provider / model，可重建 | `packages/compaction/compaction/src/types.ts:24,34,72` | 只有 run-log 一行 + DB 行锁 TTL 300s | PRESENT-WEAKER |
| S9 | 免模型 tool-result 剪枝：8192 阈值 / 4096 头 / 1024 尾，落**遮蔽替换节点** | `compaction-tool-result-pruner/src/config.ts:11-13` | `context.py:315-375` 头尾各 2000，内存标记，全文写文件；**不落盘、resume 不重放** | PRESENT-WEAKER |
| S11 | 投影注册表：纯单元、`stateVersion`、有线视图 schema、`asOfSeq` 快照 | `session-projection/src/index.ts:92` | 注册 `session.summary` 默认 projection；快照含 view schema、`stateVersion`、`asOfSeq` 与数据 | ✅ 本轮关闭 |
| S13 | 会话查询语料库：可丢弃 fts5 索引 + revision/generation 增量 + `current|shadowed|log-only` 分类 | `session-query-sqlite/src/schema.ts:8,127` | 搜索结果提供稳定 `seq`、`after_seq` 游标和 `current|shadowed|log-only` 分类，覆盖 FTS/LIKE/CJK 路径 | ✅ 本轮关闭 |
| S19 | durable 附件：内容寻址不可变 ref、每次读重校验、先准入后追加用户事件 | `attachment-local/src/file-store.ts:14,76` | 图片**从不持久化**——`agent/__init__.py:1022` 造瞬时 wire payload，只有 OCR 文本进 prompt | PRESENT-WEAKER |
| S21 | fs 观察策略：per-session 观察态 + provider version token；未见过 vs 不存在区分 | `packages/fs/fs-observation-policy/src/index.ts:28` | 两套半成品：`edit.py:489,497` 快照随 run 死亡；`local_execution.py:1085,1319` 只有 `_read_paths` 集合，写入 `path.write_text` 存在 TOCTOU | PRESENT-WEAKER |
| S22 | OTel：普通事件与 session-log 双通道独立队列 | `packages/telemetry/otel/src/index.ts:22,30` | `require_checkpoint()` 会产生 `atlas.run_checkpoint.write` 生产 span；普通事件/session-log 独立队列仍未实现 | PRESENT-WEAKER |
| S25 | tokenMeter 逐 surface 节点计价 + route-aware 图像计价 | `packages/llm/token-meter/src/index.ts:146` | `token_meter.py` 新增逐节点 route-aware 计价 API 和 `measure()` 集成；没有生产模型请求调用点或生产图像计价回调 | PRESENT-WEAKER |
| S32 | fork 要求边界不在开放 turn 内，`session/end-seed{inherited:true}` 标记继承切点 | `packages/core/session/src/fork.ts:21` | `session_sync.py` 拒绝未闭合 tool turn；子会话导入事务中追加 `session/end-seed{inherited:true}` | ✅ 本轮关闭 |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| S8 | 压缩策略 0.8 阈值 / 0.16 保留、per-provider-model 覆盖 | `compaction-basic/src/config.ts:20,23,191` | `context.py:196-256` 预留 21k / 缓冲 13k，全局配置 | PRESENT-PARITY |
| S10 | 图像 offload：log-only 决策 + message projection | `compaction-image-offload/src/*` | 无（图片从不进历史，见 S19） | ABSENT（被 S19 阻塞） |
| S12 | 投影持久缓存 `session_projcache`：`(key,ver,seq,val)` 行 | `session-projection-cache/src/spec.ts:29` | 无持久缓存；`state/projections.py:86` 是无关的页缓存 | ABSENT |
| S14 | 模型可见查询工具五件套 | `experimental/tool-session-query/src/index.ts:66-96` | 只有 `session_search` | PRESENT-WEAKER |
| S15 | `sessionStats` 投影：整日志折叠，含 llmMs/toolMs/ttftMs | `session-stats/README.md:42-46` | `conversations_router.py:815-868` 只有消息数/轮数/token 成本 | PRESENT-WEAKER |
| S16 | `turnOutline` 投影 | `session-turn-outline/src/projection.ts:85` | `atlas_state_timeline.py:142` **实现存在但无人 import、无 mixin → 死代码** | ABSENT（不可达） |
| S17 | 会话导出 ZIP：live root 先 flush，含子会话与附件字节 | `session-log-export/src/archive.ts:187-195` | `export_session/import_sessions` 存在（`atlas_state_portability.py:293,734`）但**无 HTTP 路由**，不含附件 | PRESENT-WEAKER |
| S18 | spill 缝：`saveText → {locator, bytes, hint}`，保存失败保留原文 | `docs/subsystems/spill.md:92`；`spill-policy/src/index.ts:27` | `context.py:274-310` 写 sha256 文件 + 路径提示；`spill_store.py:128` 按龄/大小清理；无 locator 抽象、无降级契约 | PRESENT-WEAKER |
| S20 | deliverables `present` 工具 + per-turn `workspace/changes` | `tool-present/src/index.ts:40,105`；`workspace-changes/src/recorder.ts:351` | `canvas_update/push_component` 只推瞬时事件；变更文件只由子代理上报 | ABSENT |
| S23 | session telemetry ledger：每规范事件一条，`(sessionId,formatVersion,seq)` 去重 | `session-telemetry-otel/src/index.ts:121` | 无（没有事件流可镜像） | ABSENT |
| S24 | product telemetry 调用方选事件，OTLP/HTTP，不自动采会话数据 | `host/product-telemetry-otel/src/index.ts:85` | 全仓无 posthog/mixpanel/amplitude/segment | ABSENT |
| S26 | DeepSeek 官方 API 增量上传会话日志，watermark + 8MiB 排空 | `session-log-deepseek/README.md:31,40` | 不适用 | ABSENT |
| S27 | skill provider `list/get`、`skills/change` 失效、不完整观察不缓存 | `packages/skill/skill/src/index.ts:356,439` | 单层索引 + rglob 全量重扫（`skills/__init__.py:291,310`） | PRESENT-WEAKER |
| S28 | 会话标题三来源 newest-wins，用户重命名钉住，`refresh()` 解钉 | `session-title/README.md:32` | `atlas_state_titles.py:43,84` 有 rank 顺序 + 用户标题 | PRESENT-PARITY |
| S29 | `@session` 引用：host 准入的另一会话快照 + untrusted 包裹 | `docs/subsystems/session-reference.md` | `read_session` 返回末 N 条纯文本 | PRESENT-WEAKER |
| S30 | 长期记忆：**DSH 完全没有** | `tool-ralph/README.md:36` | `memory/library/__init__.py:141,252` Markdown+git 页、三元组索引、30s→6h 退避队列、supersede 台账 | **PRESENT-STRONGER** |
| S31 | rewind：**DSH 没有**（`rewind` 只是类型字面量） | `conversation-context.ts:6` | 三模式 rewind + preview + redo + 文件还原（`conversations_router.py:1394,1568`） | **PRESENT-STRONGER** |
| S33 | 尝试级可观测：失败尝试也 durable 可重放 | `docs/architecture.md:120` | `run_replay/` + `run_checkpoints.py:122` 更强，但 run log **不含内容** | PRESENT-PARITY |

---

## 三、插件与扩展（33 条）

### P0

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X1 | 一切皆插件：service graph、`inject` 声明、typed event、无特权核心 | `docs/architecture.md:9,11`；`docs/cordis-primer.md:9-13` | `app_services.py:12-79` 51 字段扁平容器（全默认 None，回退模块单例）；`application.py:135` 手列 75 个 router | ABSENT |

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X2 | 注册即可逆：每个注册返回 disposer，卸载即解绑 | `core/tools/src/index.ts:988` | plugin skill/command/hook 注册有逐项 disposer；异步 MCP lifecycle 贡献尚无 disposer | PRESENT-WEAKER |
| X3 | 插件管理 enable/disable 只改最后一层匹配的 `disabled`，报告 applied/restart-required | `boot/plugin-manager/src/index.ts:458,476` | `plugins/runtime.py:1149-1171` 重跑 `load_all`，**不先 `unregister_source`/`forget_owner`** → 有 skills 的插件先报错，hook 闭包每次切换都重复 | PRESENT-WEAKER（非幂等重载） |
| X4 | profile/bundle/patch 有序层，按 row id 替换/插入，`--dump-config` 预览 | `docs/architecture.md:15-25` | patch 支持 row_id/order 与有序 listing；profile/bundle merge 和配置预览仍缺 | PRESENT-WEAKER |
| X5 | 安装/移除 bundle：包管理器解析依赖、lockfile 快照回滚、取消 | `plugin-manager/src/index.ts:374,497,645` | `plugins/runtime.py:851-982` 只支持本地 copy / marketplace / git，**无依赖解析、无回滚、无取消** | ABSENT |
| X6 | 版本兼容与豁免：peer range 检查 + per-profile `compatibility.json` 精确豁免 + `acceptRisk` | `plugin-manager/README.md:67` | `plugins/runtime.py:342-380` 只校验 manifest 形状 | ABSENT |
| X7 | 安装脚本审批门：`pendingBuilds` 转 `allowBuilds`，逐包持久批准 | `plugin-manager/src/build-approval.ts:49,75` | 无安装脚本执行，故无门 | ABSENT |
| X8 | Agent 预设 = 子插件行 + isolate realm，注册表保留 revision | `packages/preset/agent-preset-registry/README.md:46-60` | `AgentPresetStore` 持久化 revision 化 capability set（tools/skills/MCP/model/mode），并在 run 时应用；尚无 isolate realm/子插件隔离 | PRESENT-WEAKER |
| X9 | 外部入口（webhook/ACP）必须带 agent preset + permission preset | `docs/subsystems/webhook.md:5,25` | automation/webhook 保存并验证两种 preset，AgentRunContext 应用能力；ACP 外部入口尚未接入 | PRESENT-WEAKER |
| X10 | 插件管理作为模型工具，8 个动作，每次需 danger-full-access 或逐次审批 | `plugin-manager/src/tools.ts:20-46` | `engine/kernel/tools.py:412-414` 只有 list/request install | PRESENT-WEAKER |
| X11 | bundle 清单带来源 official/availability/installed/覆盖行 | `plugin-manager/src/index.ts:282` | `plugins_router.py:39` → `discover()` 有基本字段，无 availability 模型 | PRESENT-WEAKER |
| X16 | progressive disclosure：durable `<available_skills>` + 摘要 diff 替换 + `/name` 内联注入 | `docs/subsystems/skills.md:227-233` | skill registry 持久化 digest/active/retired 并生成 revisioned `<available_skills>`；`/name` 注入和摘要 diff 投递仍缺 | PRESENT-WEAKER |
| X21 | MCP 服务器 instructions 成为**独立 prompt 段** | `docs/subsystems/mcp.md:22-60` | `mcp_client.py:639-643` 把 instructions 拼进**每个**工具描述，还加了 untrusted 前缀 | PRESENT-WEAKER |
| X27 | client 扩展面：slots 注册、ConversationNodeDefinition、client 插件 | `docs/subsystems/slots.md:5-25` | `ConversationActivity.tsx:45-98` 中央 switch；`App.tsx` 静态 lazy import ~87 组件 | ABSENT |
| X28 | 人类 slash 命令：插件注册 `{name,description,input,handler}`，不经模型执行，`command/run|done` 落日志 | `docs/subsystems/commands.md:5-95` | `/api/commands` 暴露 plugin handler；前端 slash 输入直接 POST `/api/commands/invoke`，handler 调用不经模型且 append-only 记录 command/run|done | ✅ 本轮关闭 |
| X24 | ACP：`session/new|list|resume|close|set_config_option|prompt|cancel`，per-session MCP 注入 | `acp/acp/README.md:60-80` | `tools/app_server.py:262-408` **自动批准所有工具**（`:114-122`）、拒绝 per-session MCP、无 resume/config-option | PRESENT-WEAKER |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| X12 | Claude Code hooks 桥 | `experimental/hooks-claude-code/README.md` | `runtime/hooks.py:33-45` 28 个事件，`run_drive.py:3353` 接线 | PRESENT-PARITY |
| X13 | Codex hooks 桥 | `experimental/hooks-codex/README.md` | Plugin `.codex/hooks.json` 可装入 HookBus 的受支持事件；repo/user 通用来源与 trust surface 仍缺 | PRESENT-WEAKER |
| X14 | hook 逐条信任/审批门 | DSH **没有** | `runtime/hooks.py:679-735` fingerprint 作用域信任，fail-closed | **PRESENT-STRONGER** |
| X15 | skill 发现根阶梯 | `docs/subsystems/skills.md:64-76` | `skills/__init__.py:599,621-676` 优先级映射等价 | PRESENT-PARITY |
| X17 | `disable-model-invocation` / `user-invocable` 归一化 | `docs/subsystems/skills.md:100-110` | frontmatter 严格归一化两个布尔值；用户 slash 匹配和 `activate_for_model` 分别执行 invocation 门 | ✅ 本轮关闭 |
| X18 | skill provider 协议 + per-scope 分层 | `docs/subsystems/skills.md:9-30,188-200` | `SkillSource` + `with_sources` 请求作用域副本，同步 rglob | PRESENT-WEAKER |
| X19 | skill 新鲜度：chokidar 监听 + 读写路径即时失效 | `docs/subsystems/skills.md:78-81` | `skills/__init__.py:406-433` mtime+size 指纹，读时全量重扫 | PRESENT-WEAKER |
| X20 | skill 依赖/生命周期门 | DSH 无依赖契约 | `skills/__init__.py:547-590` 预检 mcp/python/commands | **PRESENT-STRONGER** |
| X22 | MCP liveness：500ms→30s 翻倍，10 次后移除工具，稳定后重置预算 | `mcp-client/README.md:64-67,89-93,129` | `mcp_client.py:803-840` `while not stopping` 无上限 | ✅ **本次已修**（10 次上限 + `unreachable` 终态 + 稳定 60s 后重置 + 显式重试解锁） |
| X23 | MCP resources + 作用域隔离 | `docs/subsystems/mcp.md:39-70` | runtime MCP server allow-list 贯穿 preset/request 能力、kernel 工具发现与派发，并由 `MCPClient.for_scope()` 隔离资源读取 | ✅ 本轮关闭 |
| X25 | SDK JSON-RPC：NDJSON、`initialize` 等树稳定、`session/wait`、关停 | `packages/sdk/README.md` | `tools/app_server.py:429` 协议 v1，无 settle barrier、无 wait | PRESENT-WEAKER |
| X26 | typed Client↔Host Remote gateway（装饰器生成描述符/编解码/客户端类型） | `docs/api-gateway.md` | 手写 FastAPI router + 手写 TS client，契约靠人 | ABSENT |
| X29 | webhook runtime：provider adapter + 可信规则返回 `WebhookSessionRequest` | `docs/subsystems/webhook.md:5,19-64` | 增加 `WebhookProvider`、HMAC provider adapter 与 typed `WebhookSessionRequest`；路由通过 provider 验证 | ✅ 本轮关闭 |
| X30 | SSH 作为整套执行世界（fs/subprocess/sandbox 一起搬） | `docs/subsystems/ssh.md` | `ssh.py:32-651` 工具级代理，只在 local_file/exec/git 上分流 | PRESENT-WEAKER |
| X31 | schedule 绑定原 session，到期回到该会话 | `docs/subsystems/schedule.md` | 两套并存：APScheduler（synthetic 会话）+ DBOS automation | PRESENT-WEAKER |
| X32 | 组合自省：`--dump-config` 带逐层来源 | `docs/architecture.md:41` | `introspect/registry.py:214` 运行时探针，无"这个值由哪层设置" | PRESENT-WEAKER |
| X33 | agent 类型 / subagent provider 缝 | `docs/architecture.md:130-136` | `agent/definitions.py:84-120` 多格式发现 + `agents/backends/` 适配器 | PRESENT-PARITY |

---

## 四、桌面与 UX（33 条）

### P1

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D1 | 认证本地载体 + boot injection + OS 分配端口 | `apps/desktop/src/web-document.ts:41,72`；`main.ts:664,685` | renderer 从 `window.atlasDesktop.apiBaseUrl` 读取 preload 提供的地址；preload 仍依赖 `ATLAS_PORT` / 8765，OS 分配端口及认证 boot injection 未接通 | PARTIAL (W12: renderer 消费既有 apiBaseUrl；allocator 与 main/preload 注入不在本批目录) |
| D2 | 两进程 typed IPC 生命周期（ready/fatal/shutdown-complete/quit-inspection） | `apps/desktop/src/host-process.ts:189,57-78` | renderer 已消费 typed `BackendStartupProgress`；ready/fatal/shutdown-complete/quit-inspection 生命周期生产端仍未接通 | PARTIAL (W12: main/preload/shared IPC 不在本批目录) |
| D3 | 流式增量：chunk 折叠进 per-node state，重连重放压缩流 | `api/session-controller/.../events.ts:8`；`ui-conversation/.../assembler.ts:174,364` | 连续 `message.delta` 现在增量更新 reply node；其它事件仍经全量 `buildTimeline` 投影 | PARTIAL (W12: reply delta 已增量折叠，结构事件仍会全量重建) |
| D4 | keyed ConversationNode renderer 注册表 | `ui-chat/.../register-node-renderers.ts:39-69` | `timeline.ts:73-99` 静态联合 + `ConversationActivity.tsx:42` 单 switch，无注册 API | ABSENT |
| D5 | durable 附件暂存：内容寻址、先存后发、进度、可取消 | `docs/subsystems/attachment.md`；`client/file-upload/src/client/contract.ts` | `App.tsx:1380-1410` 读成 base64 data URL（4 张/4MiB/共 8MiB），`App.tsx:1222` 内联进 run.start | PRESENT-WEAKER |
| D6 | 结构化草稿：chip 进文本模型、per-session 语义草稿、重载存活 | `ui-conversation/.../ReferenceChip.tsx` | `Composer.tsx:740` 纯 textarea；mentions 另存 `App.tsx:413`，草稿只存纯文本 `App.tsx:215` | PRESENT-WEAKER |
| D7 | follow 重连：首帧 header+tail+cursor+投影基线，`page()` 补缺口 | `docs/subsystems/web-client.md:48` | `client.ts:670-694` 永远 `after_sequence: 0`；退避最多 3 次后放弃 | PRESENT-WEAKER |
| D8 | 右侧栏：split 树、浮动面板、可插 tab 类型、per-session 布局 | `docs/subsystems/sidebar-right.md:26,74`；`ui-dockkit/.../FloatLayer.tsx` | `shell/Inspector.tsx:28,156` 单列固定 union，布局不持久 | PRESENT-WEAKER |
| D9 | 应用内连接恢复控件（可点击重试 + 恢复确认） | `ui-primitives/.../ConnectionIndicator.tsx:6-40` | 断连提示提供键盘可操作的“重试连接”；桌面重启动作先确认 | ✅ 本轮关闭 |
| D10 | 自动更新生命周期：调度 + 退避 + 抖动 + journal + 强制版本 | `apps/desktop/src/update-coordinator.ts:16`；`update-schedule.ts:20-26` | `main/releaseUpdate.ts:73,86` 手动检查 + SHA256 校验下载 | PRESENT-WEAKER |

### P2

| # | 能力 | DSH 证据 | Atlas 现状 | 结论 |
|---|---|---|---|---|
| D11 | 回合 diff 审阅（并排/换行/hover 预览/二进制标记） | `ui-deliverables/.../ReviewTab.tsx:107,131` | `ChangesPanel.tsx:199,343` hunk 级接受/拒绝 + 行评论（Atlas 更强），无并排 | PRESENT-PARITY（动作更强，阅读更弱） |
| D12 | 每回合变更文件摘要 | `workspace-changes/src/recorder.ts:230` | `run_drive.py:1165` checkpoint manifest difflib，渲染成一行脚注 | PRESENT-PARITY（数据）/WEAKER（呈现） |
| D13 | `present` 声明的交付物卡片 | `tool-present/src/index.ts:81`；`PresentedFileCard.tsx` | 无 `present` 工具，只有 artifact.created → Inspector 列表 | ABSENT |
| D14 | 问题意图标签（`plan-review` 路由到专用面板） | `docs/subsystems/user-questions.md:25` | `intent=plan-review` 的 `input.required` 渲染进入现有计划审查、批准、修改控件 | ✅ 本轮关闭 |
| D15 | 审批接管 composer（不可滚走） | `ui-approval/.../ApprovalPanel.tsx:1-62` | `ConversationActivity.tsx:351-400` 内联卡片（选项更丰富），可被滚走 | PRESENT-PARITY（选项强，位置弱） |
| D16 | 文档预览 renderer 注册表 | `ui-sidebar-documentpreview/src/client/*` | `FilesPanel.tsx:635-690` 有 md/图片/PDF/xlsx/pptx/HTML | PRESENT-PARITY |
| D17 | 命名空间 i18n | `client/locale/src/locale-settings.ts:16` | `services/i18n.ts:15-80` 用 MutationObserver 对 7.7k 条源串做 DOM 替换 | PRESENT-WEAKER |
| D18 | 半径 token 尺度 + token-only 颜色（spec 强制） | `docs/ui-radius.md`；`ui-theme/src/styles/base.css` | `shell/themes.ts:4` 3 套主题 + 自定义 7 色，组件里 `rounded-[9px]` 随意 | PRESENT-WEAKER |
| D19 | 无障碍契约（框架级 focus/IME/reduced-motion） | `ui-theme/src/styles/focus.css`；`packages/client/shortcuts` | `styles/app.css:205` 全局 focus-visible；手写 aria | PRESENT-WEAKER |
| D20 | 单实例 + deep link | `apps/desktop/src/single-instance.ts:16` | `electron.ts:1171-1185` | PRESENT-PARITY |
| D21 | 托盘 | `apps/desktop/src/tray.ts:13-45` | `electron.ts:229-280` 更丰富（后端阶段/组件状态/安全模式） | PRESENT-PARITY（Atlas 更强） |
| D22 | 原生菜单 + 快捷键注册表 | `apps/desktop/src/keybindings.ts` | `electron.ts:614`；`services/shortcuts.ts` + Keymap | PRESENT-PARITY |
| D23 | 崩溃恢复（含"禁用全部插件重启"） | `apps/desktop/src/main.ts:80-100` | `electron.ts:121` 脱敏崩溃报告 + 安全模式 | PRESENT-WEAKER |
| D24 | 消息分支/fork（任意 assistant 尾） | `tool-.../TurnTailNodeView.tsx:69,98` | `useAtlasStore.ts:189`、`App.tsx:3024` fork/fork+summary、`ForkTree.tsx` | PRESENT-PARITY（Atlas 更强） |
| D25 | rewind | **DSH 无** | 三模式 + preview + redo | **PRESENT-STRONGER** |
| D26 | plan 模式/计划审阅 | `docs/subsystems/plan.md` | `ConversationActivity.tsx:557` + UltraplanPanel | PRESENT-PARITY |
| D27 | 队列/steer/redirect | `ui-conversation/.../QueueDock.tsx` | `ConversationQueuePanel.tsx`；`useAtlasStore.ts:22,760` | PRESENT-PARITY |
| D28 | 语音输入 | `docs/subsystems/voice-input.md:27` | `VoiceHud.tsx` + `App.tsx:1450-1530` + TTS + 通话浮层 | PRESENT-PARITY（Atlas 更宽） |
| D29 | 更早历史分页 | `docs/subsystems/web-client.md:48` | `useAtlasStore.ts:452` 按 id 游标 + 满页启发式 | PRESENT-WEAKER |
| D30 | 备选会话视图（Chat / Trajectory） | `ui-trajectory/.../TrajectoryView.tsx` | Rollout 提供可读 trajectory 与原始事件切换；完整 Chat/Trajectory 双模式会话 renderer 尚未实现 | PRESENT-WEAKER |
| D31 | 多窗口/分栏 | DSH 单窗口 | `electron.ts:563,600`；`PaneWorkspace.tsx:28` 递归 split 树 | **PRESENT-STRONGER** |
| D32 | 消息级操作 | `MessageIconActions.tsx:11-15`（仅复制+分支） | `App.tsx:3007-3032` 编辑重发/fork/fork+摘要/rewind/copy | **PRESENT-STRONGER** |
| D33 | slash 命令注册表 | `docs/subsystems/commands.md:5-40` | `services/slashCommands.ts:29,52` 有去重与模糊排序；命令源仍是 `App.tsx:2240-2290` 静态数组 | PRESENT-PARITY |

---

## 五、施工优先级（按依赖排序）

**第 0 层（地基，其它一切依赖它）**
1. `S1+S2+E1`：只追加会话事件日志 + `deriveMessages()` + surface replace。
2. `X1`：把 `AppServices` 变成真正的服务/接缝组合根（先做注册表，不求重写全部）。

**第 1 层（不改地基就能独立交付，且用户可感知）**
3. `E3+E4`：工具流水线三瀑布 + 输出契约（`post-execute` 统一做截断/脱敏/落 spill）。
4. `E9` ✅ 已完成、`E7` ✅ 已完成、`X22` ✅ 已完成。
5. `S3`：读到更新版本 DB 必须拒绝（低成本、防数据损坏）。
6. `S17`：会话导出 HTTP 路由（`export_session` 已有，只缺接线）。
7. `D4`：节点渲染注册表（消除中央 switch，后续 UI 才有扩展面）。

**第 2 层（策略面，需要第 0 层才有意义）**
8. `E12+E13`：审批四值 + durable ask/decide + 权限预设绑沙箱。
9. `S6`：checkpoint fail-closed。
10. `S19+D5`：durable 附件（图片可重发）。

**明令不动（Atlas 已更强，别为"对齐"退化）**
`S30` 长期记忆、`S31` rewind、`X14` hook 信任门、`X20` skill 依赖门、
`D25` rewind、`D31` 多窗口/分栏、`D32` 消息操作、`D21` 托盘、`E33` 写路径诊断增量。

---

## 六、本次已落地的改动（可复核）

| 改动 | 文件 | 测试 |
|---|---|---|
| MCP 重连预算：10 次上限、`unreachable` 终态、稳定 60s 后重置、显式重试解锁、batch 路由纳入终态 | `core/atlas/tools/mcp_client.py`、`core/atlas/api/tools_router.py` | `core/tests/test_mcp_reconnect_budget.py`（6 项） |
| 并发安全按参数判定 + 派发前复检 + demoted 调用成 barrier | `core/atlas/engine/kernel/tools.py` | `core/tests/test_tool_scheduler_concurrency.py`（3 项） |
| plan 模式引导按 **live** mode 每轮重建；`EnterPlanMode/ExitPlanMode` 通过共享 `PlanMode` 实例切换，而非写副本 | `core/atlas/engine/kernel/loop.py`、`core/atlas/api/run_drive.py` | `core/tests/test_plan_mode_live_guidance.py`（6 项） |
| 会话 DB 版本前进拒绝（`SchemaTooNewError`），不再让旧构建写坏新库 | `core/atlas/engine/state/atlas_state_schema.py`、`core/atlas/engine/state/atlas_state_errors.py` | `core/tests/test_state_schema_refusal.py`（3 项） |
| 会话导出 HTTP 路由 `GET /api/conversations/{id}/export`，接通已存在的 `export_session` | `core/atlas/api/conversations_router.py` | `core/tests/test_conversation_export_route.py`（4 项） |
| 审批四值语义 `allowed-once`/`rejected`/`cancelled`/`unavailable` + 每值不同模型可见理由；loop 内 7 处 `== "allow"` 全部替换 | `core/atlas/approval_outcome.py`（新）、`core/atlas/engine/kernel/loop.py` | `core/tests/test_approval_outcome.py`（20 项） |
| 工具结果终化器接缝：有序组合、失败跳过、可逆注册、只允许改内容不得改结果；已接 `AppServices → RunRequest → AgentRunContext → kernel` 全链路 | `core/atlas/engine/kernel/tool_finalize.py`（新）、`core/atlas/engine/kernel/loop.py`、`core/atlas/agent/run_phases.py`、`core/atlas/api/app_services.py` | `core/tests/test_tool_result_finalize.py`（8 项）+ `core/tests/test_tool_finalize_wiring.py`（6 项） |
| 插件 `load_all` 幂等化：重载前按来源清理 capabilities/hooks，切换不再重复注册、不再让插件假性报错 | `core/atlas/plugins/runtime.py` | `core/tests/test_plugin_reload_idempotent.py`（5 项） |
| 禁用插件真正撤回：`set_enabled(False)` 同步撤销 capability 与 hook，而不是只 `_loaded.pop` | `core/atlas/plugins/runtime.py` | `core/tests/test_plugin_disable_withdraws.py`（4 项） |
| MCP instructions 改为**独立 prompt 段** + 工具描述只留短指针；顺带修掉 `str(MagicMock)` 会被当成 instructions 的脆弱点 | `core/atlas/tools/mcp_client.py`、`core/atlas/engine/kernel/loop.py` | `core/tests/test_mcp_instructions_section.py`（6 项） |

定向回归：**112 项通过**（上述 11 个新测试文件 + `test_plugins.py` + `test_kernel_tool_timeout.py` + `test_mcp_batch_reconnect.py` + `test_event_contract.py`）。

### 真实 MCP 数据佐证（`rea` 服务器）

实测本机 `rea` MCP 服务器挂 **184 个工具**、`instructions` **304 字符**。
按旧逻辑每个工具描述都抄一遍 → 约 **56 KB 重复文本/请求**；改后该文本只出现 1 次，工具描述长度 29–62 字符（`git__git_status` 29、`git__git_diff_staged` 40）。

### 实机验证记录

| 验证 | 方式 | 结果 |
|---|---|---|
| 导出端到端 | 起真实后端 `:8799`，`GET /api/conversations/mv-f97e1a6b/export` | **200 / 18391 字节**，`export_format=atlas.session.v1`，6 条真实消息 |
| 未知会话 | 同上 | **404**（路由已注册且校验生效） |
| 引擎层 6 项 | `core/scripts/dsh_parity_engine_proof.py` | plan enter/approve、guidance 文本、只读工具过滤、审批四值、scheduler barrier 全部符合预期 |
| 真实模型·纯文本一轮 | WS `run.start` → 后端 `:8801`，`deepseek-v4.1-flash` | ✅ **`run.completed`，回复 `OK`**（input 9432 / output 2），模型走 Clash `127.0.0.1:7897` |
| 真实模型·带工具一轮 | 同上，要求列出 kernel 目录 | ✅ **`run.completed`**，5 次请求、两批 `local_exec`、`tool.completed` 正常；回复准确列出 **18 个 `.py`**（含新文件 `tool_finalize.py`），input 31911 / output 412 |
| 真实模型·代理持久化 | 停掉带 `http_proxy` 的后端，改用 `:8802`（**清空所有代理环境变量**） | ✅ 仍成功：`test-connection` ok，对话回 `STABLE`，且**缓存命中**（cached 1152 / uncached 8197）——证明走的是 Atlas 已存的 `model_network` 配置，不是环境变量 |

> 模型通道修复记录：`d1api.xin` 的 `deepseek-v4.1-flash` key 此前为空（401 根因）。已通过 Atlas 自己的 `set_model_api_key` 写入 **Windows 凭据管理器**（不落明文配置）；Clash 代理 `http://127.0.0.1:7897` 通过 `PUT /api/model-network-settings` 存入凭据库，`user-settings.json` 里只有可读标签。实测经 Clash **1.6–2.6s**，直连 **24.9s**，所以代理是必需的。前提：`keyring` 需已安装（`pyproject.toml:74` 已声明，当前环境原先缺失，已补装 25.7.0）。
