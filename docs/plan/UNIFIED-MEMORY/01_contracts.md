# 统一记忆接口与数据契约 UM-WIN-1.0

所有字段、状态和签名均是本期施工要求。新类型放在 MemoryOS `service/unified/contracts.py`；Atlas 使用与其一致的传输类型，不直接导入 MemoryOS Python 包。契约文件与生成的 OpenAPI 进入双仓库共同版本锁。

## 1. 主体与来源

`owner_id` 是用户所有者；`memory_subject_id` 是这个用户使用的 Atlas 记忆主体；`client_id` 固定代表 Atlas 客户端；`actor_id` 区分 Atlas 主执行与被调用工具/Agent。`runtime_session_id`、`task_id`、`project_id`、`model_deployment_id`、`environment_id` 分开。运行实例或模型名字不得推导或新建记忆主体。

本期一个 Windows 用户可有一个 Atlas 主体；同时保留防止误绑定另一主体的校验。多用户产品与设备同步不在本期新增。既有 `CoreSelf.SELF_IDENTITY` 描述受保护主体身份；用户偏好和近况不写进 AUTH_POLICY。

```python
# 两个仓库共享的传输签名；定义与校验在对应 contracts 模块实现。
class MemoryContext:
    owner_id: str
    memory_subject_id: str
    client_id: str
    actor_id: str
    runtime_session_id: str
    task_id: str | None
    project_id: str | None
    environment_id: str
    model_deployment_id: str | None
```

真正客户端身份来自 Atlas 的服务接线/配置绑定，不接受工具输出或用户上传 JSON 自报“我是 owner”来改变身份。MemoryOS 新路由用统一请求上下文检查；按 ID、搜索、媒体、导出、纠错都使用同一上下文。保留原有工具 FULL_ACCESS。

### 1.1 来源类型与信任

| `source_kind` | 允许记录什么 | 不可自动推导什么 |
| --- | --- | --- |
| ATLAS_USER_MESSAGE | 用户实际输入及语音转录，带原消息定位 | 引用/转述中的命令不是用户意图。 |
| ATLAS_ASSISTANT_MESSAGE | Atlas 当次输出 | 自报完成不是任务验证。 |
| ATLAS_TOOL_OBSERVATION | 文件/页面/电脑/工具原结果 | 第三方内容不是用户要求，也不是执行成功证据。 |
| ATLAS_AGENT_TOOL_RESULT | Atlas 调用其他 Agent 的返回和日志 | 对方自己的长期记忆、推理与声明不是 Atlas 的独立事实权威。 |
| ATLAS_VERIFICATION | Atlas 检查文件、窗口、API 或可观察结果的证据 | 验证一个结果不保证所有依赖事实都真。 |
| USER_IMPORT | 用户导入的笔记、照片、文件、录音 | 文件作者和引用发言必须区分。 |
| DERIVED | 总结、画像、学习方法、预测和反事实 | 不得作为新的原始经历进行自我循环佐证。 |

角色字段 `speaker_role`：USER / ATLAS / TOOL / THIRD_PARTY / UNKNOWN。来源事实类别 `epistemic_kind`：OBSERVED / USER_ASSERTED / THIRD_PARTY_ASSERTED / INFERRED / SIMULATED。`confidence` 是校准用元数据，不替代来源、验证或权限。

## 2. Observation：原始观察契约

必填：`source_event_id`、`source_kind`、`source_object_id`、`source_revision`、`content_hash`、`occurred_at`、`source_timezone`、`speaker_role`、`epistemic_kind`、`content`、`context`。`occurred_at` 缺失时允许 null，但必须 `time_status=UNKNOWN`；不接受无时区字符串假装绝对时间。由 service 填写 `recorded_at`。

`source_event_id` 计算：`atlas:{source_kind}:{source_object_id}:{source_revision}:{event_action}`，其中对象 ID 是原消息/工具调用/导入条目等稳定 ID；不可每次重试生成新 UUID。消息尚无原 ID 时，在 Atlas operational outbox 第一次接收时分配并持久化，重试沿用。

`source_revision` 为单个来源对象的版本，不等同全库 authority revision；相同对象版本、相同规范化内容只产生一次观察。编辑生成新版本和新事件，旧版本保留；删除生成对象生命周期变更，不复用旧 source_event_id 改内容。

普通每批最多 100 条，规范 JSON 内容最多 2 MiB；媒体独立提交，文本超限存 blob 并给节选定位，不静默截断。内容哈希采用既有 canonical JSON 规则并包含业务字段；运输重试时间不得纳入同一观察的业务内容哈希。

```json
{
  "contract_version": "UM-WIN-1.0",
  "event_class": "TEST",
  "context": {
    "owner_id": "owner-fixture", "memory_subject_id": "atlas-fixture",
    "client_id": "atlas-desktop", "actor_id": "atlas-main",
    "runtime_session_id": "chat-001", "task_id": null,
    "project_id": "project-demo", "environment_id": "windows-fixture",
    "model_deployment_id": "model-fixture"
  },
  "observations": [{
    "source_event_id": "atlas:ATLAS_USER_MESSAGE:msg-001:1:UPSERT",
    "source_kind": "ATLAS_USER_MESSAGE", "source_object_id": "msg-001",
    "source_revision": "1", "event_action": "UPSERT",
    "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "occurred_at": "2026-10-06T09:00:00+08:00", "source_timezone": "Asia/Hong_Kong",
    "time_status": "KNOWN", "speaker_role": "USER", "epistemic_kind": "USER_ASSERTED",
    "content": {"text": "这周晚上不要给我安排工作，项目明天上午继续。"},
    "locator": {"kind": "MESSAGE", "value": "chat-001/msg-001"},
    "media_refs": [], "derived_from": []
  }]
}
```

例中的哈希为固定夹具字面量；实际传输必须按内容计算并由 service 重算验证。夹具测试不能以该字面量通过哈希校验。

`POST /v1/unified/observe` 在同一事务内：绑定来源对象版本 → 调现有 `storage.append_events` 记录 evidence → 保存源定位与依赖 → enqueue formation → 返回事件 ID 与 ack。事件类型使用新增注册的 `OBSERVATION`/`SOURCE_CHANGED`；旧 `/v1/runtime/events:append` 类型不移除、不改变现有幂等语义。已删除或被屏障阻断的对象返回 423。

水位：`OBSERVATION_ACKED` 表示原始证据可靠落地；`FORMED_THROUGH` 表示形成处理到该版本；`INDEXED_THROUGH` 表示派生索引可用。UI 不把原始落地误显示成“所有记忆已整理完”。

## 3. 统一记录、来源与依赖

继续使用 `memories`、`episodes`、`experiences` 与现有受保护表；不要新增一个通用事实表替代它们。新 `UnifiedRecord` 是读取/扩展契约，包含 `record_ref`、`record_revision`、`facet`、`lifecycle`、`content`、`source_refs`、`dependencies`、`applicability`、`epistemic_kind`、`valid_time`、`recorded_at`。

`record_ref` 规范：`memory:{id}` / `episode:{id}` / `experience:{id}` / `commitment:{id}` / `core-self:{section}` / `entity:{id}` / `focus:{id}` / `intent:{id}` / `strategy:{id}`。已有 ID 不重新生成；客户端不可只传无类型 ID 查另一张表。

facet 枚举：FACT / PREFERENCE / STATE / HABIT / RELATION / EPISODE / KNOWLEDGE / GOAL / COMMITMENT / INTENT / EXPERIENCE / SKILL / PREDICTION / CAPABILITY / WORKING_FOCUS / SUMMARY / COUNTEREXAMPLE。既有 0.1 schema 不原地扩大 enum 破坏老客户端；新扩展在 `memories.extra_json.unified` 或对应记录扩展中保存，新 `/unified` 读出 facet。旧 0.1 兼容投影使用已有 memory_type，不能把 INFERRED 内容改为 FACT。

每个派生记录的 dependency 必须是 `{record_ref, revision, content_hash, relation}`，relation 为 SUPPORTS / DERIVED_FROM / PLANNED_FROM / CONTRADICTS。仅记录 ID 而不记录版本不足以发现旧计划。

`applicability` 含项目、任务类别、时间范围、角色、工具/环境版本、模型消费者约束与前提。参数未知可 null，并在使用时检查；不允许把未知当作普遍适用。

新增 migration 起始 `0024_unified_sources.sql`，后续连续编号；若 UM00 发现已有更高编号，按最高号之后分配并一次性更新 manifest。目标表和唯一键：

| 表 | 内容与键 |
| --- | --- |
| unified_source_objects | `(subject_id, source_kind, source_object_id, source_revision)` 唯一；hash、event_id、locator、lifecycle、时间。 |
| unified_media_assets | asset_id、hash、mime、受控相对路径、字节数、时长/尺寸、来源与保留状态。 |
| unified_dependencies | `(subject_id, child_ref, child_revision, parent_ref, parent_revision, relation)` 唯一。 |
| unified_record_revisions | 各种统一记录的版本摘要、旧/新值及变更依据，不复制原始媒体。 |
| unified_entity_aliases | `(subject_id, alias_kind, alias_value, entity_id)`；支持 unresolved / proposed / verified / revoked。复用 graph_entities，不建第二套实体库。 |
| unified_focus | focus_id、task_id、goal、constraints、step refs、pending refs、authority revision、状态；实际执行状态仍来自原运行权威。 |
| unified_intents | intent_id、用户来源、cue、action、condition、due、expires、lifecycle、绑定 automation ID。 |
| unified_read_receipts | read_id、context、query、装配记录版本、来源定位、上下文 hash、token 使用和后验应用结果。 |
| unified_learning_trials | trial_id、baseline/candidate refs、未见任务 IDs、真实结果、统计与失败证据。 |
| unified_strategies | strategy_id、revision、输入依据、更新操作、适用范围、试验结果与 active 版本。 |
| unified_jobs | formation/maintenance 队列、输入快照、lease、重试与终态；如果现有 extraction_jobs 可承载，则只扩 job_type，不再创建此表。 |

表只在 MemoryOS service 的事务入口写入。`unified_jobs` 的复用判定由 UM00 API/表结构检查决定并写唯一映射；两种队列不能同时启动同一任务。

Atlas operational outbox 放在现有 Atlas operational DB 或单独耐久队列文件中；内容不可作为事实召回。状态 NEW / SENDING / ACKED / RETRYABLE / BLOCKED。重启回收过期 lease，重试不改 observation ID；源事件 ACK 前不得丢弃唯一原始内容。

## 4. 生命周期与冲突

普通记录：CANDIDATE → ACTIVE；ACTIVE 可转 SUPERSEDED / INVALIDATED / CONFLICTED / ERASED。状态词在旧表不支持时，由现有候选表和统一扩展表达，不直接塞违反 CHECK 的值。单源明确的当前偏好/状态可以由自动 policy 验证后 ACTIVE，无需每条人工批准；其语义始终是 USER_ASSERTED。

经验沿用 CANDIDATE / TESTED / ACTIVE / SUSPECT / RETIRED；主动方法或技能上升 ACTIVE 必须有实际验证，不能靠摘要成功。推测与模拟永久保留 epistemic_kind；ACTIVE PREDICTION 表示可测试预测，不表示已经被观察为真。

意图：PROPOSED → ACTIVE → TRIGGERED → RUNNING → COMPLETED；另有 CANCELLED / EXPIRED / BLOCKED / UNKNOWN。只有用户原始指令或已有授权任务能 ACTIVE；条件被改变时返回检查，不盲目重试 UNKNOWN 副作用。调度器不改事实权威。

冲突结果四类：TEMPORAL_UPDATE、CORRECTION、CONDITIONAL_ALTERNATIVES、UNRESOLVED。时间较新不必更可信，重复次数不等于独立证据。UNRESOLVED 不能选一个写成确定答案；必须说清差异或澄清。

事实时间区间统一左闭右开 `[valid_from, valid_to)`；null 表示未知/无界，由 time_status 分辨。保存原时区及解析依据；不把 Graphiti 的 naive-as-UTC 行为直接用于用户本地时间。“周五”无法判定是哪周时形成待澄清时间，不伪造日期。

## 5. 召回与使用契约

请求 `RecallRequest`：context、query、purpose、cue_context、as_of、knowledge_as_of_revision、budget、facets、required_evidence。purpose 为 CONVERSATION / CONTINUE_TASK / PLAN / ACT / LEARN / EXPLAIN / AUDIT。

预算默认 max_tokens=2400、max_records=12、max_source_snippets=8、graph_hops=2、retrieval_deadline_ms=1200；用户/任务可以在既有配置中调大，不另建 settings store。带大量原文证据的审计请求使用显式更大预算；不得把所有来源原文塞入每轮 prompt。

流水线：确定任务/人物/时间线索 → 回查当前工作状态和有效意图 → 并行全文/语义/时间/实体候选 → 必要时联想/图扩展 → 来源、生命周期和适用性校验 → 矛盾/缺证检查 → 多样性和条件效用排序 → token 装配 → read receipt。

返回：`read_id`、`authority_revision`、`context_items`、`source_snippets`、`conflicts`、`missing_evidence`、`freshness`、`completeness`、`context_hash`、`token_usage`、`fallback_mode`、`trace_ref`。context_items 必有 record_ref/revision、epistemic_kind、适用限制、来源，不给模型只有裸结论。

`freshness`、`completeness` 和 `conflicted` 独立；低时效与完整性不足可同时成立。检索失败可返回原始全文路径、适当缩减或明确未知；不能返回一个看似完整的空知识回答。向量/图故障不影响当前明确用户要求与实际任务状态。

模型输入装配在 Atlas 真正调用模型前执行；规划之前加载相关硬约束，工具动作前再检查相关依赖版本。`read_receipt` 只证明装配到了输入；`application_receipt` 记录真实行为用到哪些项，不能混为已学习或已遵守。

```python
class UnifiedMemoryClient:
    async def observe(self, batch: dict) -> dict: ...
    async def recall(self, request: dict) -> dict: ...
    async def evidence(self, record_ref: str, revision: int | None = None) -> dict: ...
    async def correct(self, request: dict) -> dict: ...
    async def source_changed(self, request: dict) -> dict: ...
    async def update_focus(self, request: dict) -> dict: ...
    async def create_intent(self, request: dict) -> dict: ...
    async def transition_intent(self, request: dict) -> dict: ...
    async def record_outcome(self, request: dict) -> dict: ...
    async def apply_feedback(self, request: dict) -> dict: ...
    async def record_application(self, request: dict) -> dict: ...
    async def check_dependencies(self, request: dict) -> dict: ...
    async def get_status(self) -> dict: ...
```

上面的 ellipsis 是 Python 接口签名记法，不是允许施工者留下实现占位；每个方法在对应任务完成时必须有实际 HTTP 实现和失败测试。

## 6. 新 API 与旧接口兼容

| 方法与路径 | 请求 / 返回 | 幂等与失败 |
| --- | --- | --- |
| POST /v1/unified/observe | ObservationBatch / ack IDs、各水位 | 同 ID 同内容 DUPLICATE_OK，异内容 409；屏障 423。 |
| POST /v1/unified/recall | RecallRequest / 上节返回 | 记录 trace；deadline 返回带原因的 fallback，不能假成功。 |
| GET /v1/unified/records | facet/status/project/cursor / items、next_cursor | 按主体和 lifecycle；版本化稳定分页。 |
| GET /v1/unified/records/{record_ref} | expected_revision 可选 / UnifiedRecord | 错主体 403、不存在 404、版本冲突 409。 |
| GET /v1/unified/evidence/{record_ref} | revision / 原始定位与片段 | 删除后 410 或屏障状态，不回落旧缓存。 |
| GET /v1/unified/timeline | start/end/entity/project/cursor / episodes | 事件时间排序，时间未知单独分组。 |
| GET /v1/unified/entities | query/cursor /实体和候选别名 | 未决关联不装成已确认。 |
| POST /v1/unified/entities/resolve | source refs、alias、entity、expected revisions / resolution | 有来源；merge/split 产生依赖失效。 |
| POST /v1/unified/corrections | request_id、target_ref、expected_revision、replacement、source / revision与受影响项 | idempotent；不一致 409。 |
| POST /v1/unified/sources/change | object ref、source version、action / ack | source edit/delete 重试幂等。 |
| POST /v1/unified/focus | context、focus snapshot、runtime revision / focus ref | 旧运行版本拒绝覆盖；不能凭模型改 runtime completed。 |
| POST /v1/unified/intents | user source、cue、action、scope、due / intent ref | 无直接授权来源只可 PROPOSED。 |
| POST /v1/unified/intents/{id}/transition | expected_revision、transition、receipt /状态 | UNKNOWN 先对账；完成必须结果依据。 |
| GET /v1/unified/intents | status/project/cursor /items | UI 与触发器读同一意图。 |
| POST /v1/unified/outcomes | task refs、结果、验证、使用记忆/技能 / outcome ref | UNKNOWN/FAILED/SUCCEEDED 分开；未验证自报不能 SUCCEEDED。 |
| POST /v1/unified/feedback | read/record/skill refs、反馈来源 / ack | 反馈不直接把经验 ACTIVE。 |
| POST /v1/unified/applications | read_id、输入 hash、动作/答案 refs、依据 / application ref | 未实际装配的 read_id 不能伪造已使用。 |
| POST /v1/unified/dependencies/check | child ref、动作依赖前沿、current heads / VALID或STALE及差异 | 动作前检查，STALE 需要重新理解/计划。 |
| GET /v1/unified/learning | stage/type/cursor /方法、试验、能力缺口 | 试验候选与已验证方法分开显示。 |
| POST /v1/unified/maintenance | job_type、snapshot、budget /job ref | 实际工作由队列完成；重试同 snapshot 去重。 |
| GET /v1/unified/status | /接线、数据、outbox、形成、索引、模型和worker状态 | 显示降级原因与最后水位。 |
| POST /v1/unified/export | request_id、选择范围 /export job与manifest | 先屏障过滤再导出；可控副本登记。 |

删除流程调用既有 `/v1/erasure/*` 实际 API，不复制另一套授权。UM08 扩 erasure controller 覆盖新表/媒体/技能/派生缓存。Atlas 代理路径统一 `/api/unified-memory/*`，后缀与 MemoryOS 相同；旧 `/api/facts` 等行为按 facade 映射保留。UI 不直接访问 MemoryOS 数据库或原始文件路径。

### 6.1 Atlas 本地采集与诊断的补充契约

`POST /api/unified-memory/capture/start|pause|stop` 由 Atlas 本地采集控制器处理，不代理为 MemoryOS 的同名路由。输入 `request_id`、`expected_revision`、已授权的 `sources` 和现有配置引用；返回 `state`（RUNNING/PAUSED/STOPPED）、`revision`、`passive_capture_watermark`、`last_error`。重复 request_id 幂等，状态版本冲突 409。pause/stop 只停止后台被动观察，不能丢掉用户正常聊天和主动工具操作的归档；在途观察先完成或显式记为缺口，再报告停止成功。status 分开显示 conversation/tool/passive 各水位，不能用总水位判断被动采集已停止。

`GET /v1/unified/learning` 返回 `items`、`next_cursor`，以及诊断查询时的 `utility_profiles` 和 `active_skill_hash`。每个 utility profile 含 task_family/model_id/environment_version/sample_count/estimate/uncertainty；active_skill_hash 来自现有技能注册表实际加载版本，不由记忆服务猜测。常规列表不得把这些诊断字段解释为现实任务成功证明。

ObservationBatch 的 context 由服务验证，批内 observation 继承同一 context；如果 observation 自带主体字段，必须一致，禁止混合主体批次。source_revision 是外部源版本字符串，record revision 是仓库递增整数，两者不能互换。

## 7. 可执行方法、预测与学习门禁

`SkillBinding`：skill registry ID、包版本、experience refs、preconditions、tool/environment/model profile、known_failures、verification cases、active revision、rollback revision。安装包是派生可执行产物，依据和 ACTIVE 状态属于统一记忆；skill registry 保持包管理职责。

学习结果不能只有 Skill：支持 knowledge、state update、counterexample、strategy、prediction 和 capability gap。ReasoningBank/ACE 产生候选，真实结果或用户直接纠正进入验证；WorldMind 风格预测保留“预测什么、输入依据、预计结果、实际结果、误差与适用域”。没有真实误差反馈就不能说 world model 已改善动作。

针对性学习先分类 KNOWLEDGE_GAP / IMPLEMENTATION_BUG / RETRIEVAL_GAP / AUTH_OR_DATA_GAP / UNKNOWN，再决定查证、修代码、重检索或说明缺口。外部研究材料进入 THIRD_PARTY 来源，不自称亲历。

技能演化：复制当前包到隔离工作区 → 来源与失败归因 → 修改候选 → 原结构测试 → 本地真实结果 → held-out 对照 → registry 原子激活 → 旧版可回滚。失败留下记录且旧 ACTIVE 包保持完整。自动演化仅修改候选技能/记忆策略，不自动改 Atlas 主代码、权限或权威数据库 schema。

门禁区分工程可部署、局部修复、迁移收益和统计显著。Recuris 原 ACCEPT 不要求置信区间下界大于 0；本项目对“已证明增长”另要求独立冻结集的增益置信区间下界大于 0，否则标记“局部可用/尚未证明总体增长”。

## 8. 配置、预算和故障

配置复用 Atlas `AtlasConfig`、现有 user-settings API 与 ModelManager。新增 namespace `memory.unified`：enabled、service_url、subject_binding、capture_mode、retrieval_budget、maintenance_budget、model_roles、media_retention、source_scopes、feature_versions。model_roles 指向现有 deployment ID，不写死某个来源项目的 Gemini/OpenAI 默认模型。

默认：Atlas 自身对话/工具可靠采集开；整台电脑持续后台录屏不开。用户主动打开“记录当前活动”后采集已选择范围，暂停/停止必须真实停止生产新记录。普通工具自身截图与记录按现有行为接入；不要因为引入记忆禁用既有电脑能力。

预算：原始记账无模型； formation 以小批次处理；一次在线复杂查询至多 1 次 planner 模型调用，正常查询不需要；后台每周期限制任务数/模型 tokens/时间，持久化未完成工作。预算值可配置、成本实际统计；超限返回预算状态，不静默宣称整理完成。

服务不可达：本轮明确用户要求和当前运行状态继续可用，观察留 outbox；长期记忆显示 DEGRADED，不能读另一个旧事实库冒充统一。受保护变更与删除按既有失败语义处理，绝不能 fallback 绕过授权。

媒体缺失：保留来源和缺失状态，回答说明“记录存在但原媒体不可用”；不生成替代证据。磁盘满：停止新增媒体并报错，outbox 保留未 ACK 原文；恢复空间后重试。图/向量不可用：回全文/原始证据，记录 fallback。MODEL_FAILED：重试有次数上限，不用伪造结构化结果通过。
