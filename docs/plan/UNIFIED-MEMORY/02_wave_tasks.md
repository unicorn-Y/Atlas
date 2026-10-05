# 逐波施工任务：40 项任务，14 波

本文件的路径均相对于对应仓库。每项遵循总任务书的隔离、来源与权限约束。M 表示 MemoryOS，A 表示 Atlas。引用 S01–S16 的具体仓库、提交、函数和适配边界见来源书；执行者必须先阅读该来源及本仓库相关调用。

每项任务都要实际修改并接线。代码块给出关键失败判据，不能仅将代码块复制为同名空测试；同时实现本文规定的正常、负例、持久化与入口测试。Python 测试默认 marker 需显式覆盖，不把默认 unit 集合当全验收。

## 公共测试与交付规则

Harness 身份注入只补缺省 TEST context；显式提供 foreign subject/非法 owner 的负例字段必须保留，由真实服务拒绝，不能在客户端偷偷覆盖使负例失效。所有缩写能力名、fixture 工具与 chat 诊断字段按验收书第 3 节实现并从真实收据读取。

UM00 建立 `UMHarness`，在两个独立 Python 环境中通过 HTTP 启动真正 Atlas 与 MemoryOS 隔离服务；fake 模型只替代模型供应商。`h.api(method, path, json=None, params=None)` 根据 `/v1/` 或 `/api/` 访问对应服务，注入固定 TEST context；返回真实 HTTP response。`h.chat(text, session_id=None)` 走 Atlas 真正聊天路径；`h.tool(name, arguments)` 走现有 Atlas 工具派发；`h.restart(component)` 重启隔离进程；`h.fault(name, enabled)` 只作用于测试 runtime。`h.seed(name)` 导入冻结 fixtures 的命名数据集。不可用 mock 替换待验收的 unified_client、facade、记忆服务或调度器。

seed 名称固定：basic、legacy、conversation、agent_tool、identity、temporal、conflict、daily、profile、summary、media、windows_activity、interrupted_task、intent、implicit、association、evidence_gap、correction、erasure、experience、utility、skill、prediction、knowledge_gap、self_probe、policy、desktop、scale、longitudinal。每份 seed 自带独立 ground truth；不因测试失败修改 truth。

每项产物：实际源代码、对应测试、一个 Atlas 入口证明、来源 parity 差分、状态与失败证据。统一放 `artifacts/unified-memory/UMxx/Txx.y/`；至少含 `result.json`、输入摘要、原始结果引用、模型/运行环境、源提交、使用记忆与新写记忆。所有引用文件必须存在且 hash 可核对。

### UM00：基线、权威映射与效果夹具

#### T00.1 当前权威与安全施工基线

**文件：** A 新 `scripts/unified_memory/baseline.py`、`docs/plan/UNIFIED-MEMORY/authority-map.json`、`tasks/unified-memory/CURRENT.json`；M 新 `scripts/unified_memory/baseline.py`。读取现有存储/迁移/入口，不修改生产配置。

**输入/输出：** 输入两个仓库当前 HEAD、工作区哈希和 AST/SQL 表定义；输出 env manifest、37 张现有 Atlas 表的归属、全部 MemoryStore 方法及实际调用者、已有 MemoryOS 写读能力和未验证项。与总任务书基线不同也可以继续规划内工作，但必须记录变化与所有者；活跃写者相同热文件先隔离协调。

- [ ] 不导入会触发 DB 初始化的模块；用静态解析枚举建表语句、MemoryStore 方法、调用方及 MemoryOS 路由。每项归属使用总任务书四类；记录完整 method→consumer→authority→replacement 映射。
- [ ] 保留其他工作区改动，建立本任务分支/worktree；依赖包与解释器在 worktree 单独准备。仅创建本任务目录；禁止清理 D:/MemoryOSData 或已有 artifacts。
- [ ] 生成所有权表、双仓库版本 manifest、禁止生产数据的 test-path 校验。新测试/runner 启动即拒绝未显式绑定的生产数据根。
- [ ] 跑静态基线与原有相关测试，保存已存在失败，不为绿基线修改旧项目。通过条件是每个表、每个实际消费者都有映射且没有遗失未提交内容。

```python
def test_authority_inventory_is_complete(baseline):
    assert set(baseline.tables) == set(baseline.classifications)
    assert not baseline.unmapped_memory_consumers
    assert baseline.production_db_opened is False
```

#### T00.2 真实双服务测试框架与冻结目标

**文件：** A 新 `core/tests/unified_memory/conftest.py`、`core/tests/unified_memory/harness.py`、`core/tests/unified_memory/test_bootstrap.py`、`scripts/unified_memory/run_acceptance.py`；M 新 `tests/unified_memory/conftest.py`；A 新 `tests/fixtures/unified_memory/manifest.json` 及命名 seed JSONL。

**接口：** 产生上文 6 个 harness 方法；UM13 runner 可选择 `component/integration/desktop/live/longitudinal`，输出统一 result schema。fixture 包必须明确其只是测试资料，不是产品实现。

- [ ] 实现 Windows 进程启动、端口动态分配、健康等待、停止和异常收尾；每次创建唯一数据目录，不能复用生产端口或停止非本任务进程。
- [ ] 在 TEST runtime 注入假模型供应商，但所有实际记忆/会话/任务/调度/工具派发走真实实现。live 模式切换现有 ModelManager 配置；测试场景相同。
- [ ] 按验收书生成 320 项冻结核心用例及长期轨迹；按 fixture ID 分开发集与锁定验收集，存 SHA256。测试真值不能进入 Atlas 模型输入或后台学习。
- [ ] 启动旧基线，记录目前失败的统一效果，用于证明后来变化，而不是要求旧版本先通过新效果。

```python
def test_harness_never_uses_production(h):
    assert h.runtime_manifest["event_class"] == "TEST"
    assert h.runtime_manifest["memoryos_db"] != "D:/MemoryOSData/db/memoryos.sqlite3"
```

### UM01：统一记忆接线与迁移

#### T01.1 类型化客户端与 service 新入口

**文件：** A 新 `core/atlas/memory/unified_client.py`、`unified_facade.py`、`core/tests/unified_memory/test_client_contract.py`；M 新 `service/unified/{__init__,contracts,repository,api}.py`、修改 `service/app.py`；M 新 `tests/unified_memory/test_contract.py`。

**消耗：** 01 契约的 MemoryContext 与 API。**产生：** 全部 UnifiedMemoryClient 方法的实际 HTTP transport、错误类，首先 records/status/observe/recall 可运行；尚未实现对应业务的路由显式 501 FEATURE_NOT_READY，在后续任务补全，最终不得保留 501。

- [ ] 先写主体错误、超时、409/423 及按 ID 读取范围一致的失败测试。
- [ ] 按 S15 对照身份/过滤接口，保留现有 MemoryOS 实际表和写规则；不复制 Mem0 存储。服务将上下文绑定与所有新路由共用，数据身份与工具 FULL_ACCESS 分开。
- [ ] 配置走现有 AtlasConfig/ModelManager，连接地址默认本地；health 返回版本/范围/水位。客户端报错保留 code/detail，不把所有异常吞为空列表。
- [ ] 回归旧 `/v1/runtime/events:append`、`/v1/recall/query` 与受保护/删除接口；断连测试证明没有旧事实库 fallback 写入。

```python
def test_foreign_subject_is_rejected(h):
    r = h.api("POST", "/v1/unified/recall", json={"context": {"memory_subject_id": "foreign"}, "query": "我是谁"})
    assert r.status_code == 403
```

#### T01.2 迁移全部长期记忆与旧 API 兼容

**文件：** A 新 `scripts/unified_memory/export_legacy.py`、修改 `core/atlas/memory/__init__.py` 与 `memoryos_adapter.py`；M 新 `scripts/unified_memory/import_legacy.py`、`service/unified/legacy.py`；测试 `test_legacy_migration.py`。

**输入：** T00.1 authority-map。**输出：** 每种 MEMORY_AUTHORITY 的幂等 source refs、记录 ID 对照、差异报告与兼容 facade；运行表不迁成第二套运行权威。

- [ ] 只读导出，legacy 无证据记录标 LEGACY_UNGROUNDED；禁止伪造原聊天或 VERIFIED 标记。已删除/失效/冲突及历史记录必须迁入相同生命周期。
- [ ] 每条 legacy source_event_id 固定，导入两次结果一致；受保护内容只用现有受保护入口和收据，不直接写 core_self/commitments。
- [ ] 所有旧记忆方法按映射委托或返回兼容派生视图。优化/成熟度报告可保留旧审计，但 active 事实读取必须回查统一状态；不得“只迁 facts”。
- [ ] 核对数量、内容 hash、旧→新 ref、来源定位和状态；双读差异归零或逐条有明确语义差异与验收。正式切换留给 UM12，现阶段在隔离副本跑。

```python
def test_legacy_import_is_idempotent(h):
    first = h.seed("legacy")
    second = h.seed("legacy")
    assert second["created"] == 0 and first["record_map"] == second["record_map"]
```

#### T01.3 全入口组成与单一调用路径

**文件：** A 修改 `server.py`、`cli.py`、`runtime/hub.py`、`api/app_services.py`、`api/memory_router.py`；新 `api/unified_memory_router.py`、`core/tests/unified_memory/test_composition.py`。

**接口：** AppServices 引用 operational memory 与 UnifiedMemoryClient；agent/hub/API 各自使用同一 facade。所有消费者的具体替换点来自 T00.1，不能靠只增加一个未实例化 Adapter。

- [ ] 把三个 MemoryStore 构造入口统一 composition；保留运行消息职责，长期记忆方法委托。
- [ ] 旧 `/api/facts` 与 candidate/knowledge 页面写读走统一服务；approve/reject 沿用语义，不直接 insert 本地事实。
- [ ] 入口 smoke：在桌面/API 写偏好，新的聊天、CLI 和任务读到相同 ref/revision，重启后保持。
- [ ] 静态扫描及运行 spy 证明没有 active 记忆消费者绕过 facade；发现绕过先补接线再交波。

```python
def test_ui_and_chat_share_authority(h):
    h.seed("basic")
    records = h.api("GET", "/api/unified-memory/records", params={"facet": "PREFERENCE"}).json()
    assert records["items"][0]["record_ref"] in h.chat("按我的格式输出")['memory_refs']
```

### UM02：可靠记录 Atlas 经历

#### T02.1 来源对象、编辑和耐久 outbox

**文件：** M 新 `service/unified/sources.py`、`migrations/0024_unified_sources.sql`；A 新 `memory/capture.py`、`outbox.py`；测试 `test_source_idempotency.py`。

**输入/输出：** ObservationBatch → existing evidence + source versions + ack + formation job；outbox 明确可靠落地与整理水位。

- [ ] 在数据库层加源对象版本唯一键；content hash 使用既有 canonical 规则，编辑/删除新事件，重试沿用原 ID。
- [ ] Atlas outbox 第一次收到事件即持久化；服务 ack 后再标 ACKED。进程在发送前/服务落地后/ack前退出都可恢复且不重复。
- [ ] formation enqueue 与 evidence 落地保持事务一致；现有 extraction_jobs 可复用则扩 job_type，不另跑一个重复队列。
- [ ] 负例：不同内容复用相同 ID 返回409；删除屏障拒绝复活；超限数据给显式错误或 blob引用，不静默截断。

```python
def test_conflicting_retry_fails(h):
    batch = h.seed("conversation")["observation_batch"]
    batch["observations"][0]["content"]["text"] = "changed without revision"
    assert h.api("POST", "/v1/unified/observe", json=batch).status_code == 409
```

#### T02.2 聊天、模型输出与工具调用的真实捕获

**文件：** A 修改 `agent/run_phases.py`、`agent/tool_node.py`、`engine/hermes_runtime.py`、`engine/session_sync.py`；新 `core/tests/unified_memory/test_capture_lifecycle.py`。

**接口：** 在原消息/工具事件拥有稳定 ID 后调用 `capture.enqueue(Observation)`；不在 UI 每次重绘再采集。Hermes raw history 仍保持当前 source-of-use。

- [ ] 用户原话与 Atlas 输出分别记录，附 session/message ID、branch 和实际时间；编辑/分支沿源事件版本处理。
- [ ] 工具 dispatch/result/verification 三类分开，异常和取消也记录。异步或流式结果完成后落完整原文/受控blob与摘要，不重复流片段。
- [ ] context 压缩保留原消息 refs，只有 summary 时不伪装有原话。用户“忘掉这条”进入纠错/删除路线，不被普通记忆抽取再保存为偏好。
- [ ] 自己刚写的用户当前消息不作为独立历史再次“回忆”；关闭 memory injection 不关闭原始 evidence 捕获。

```python
def test_model_self_report_is_not_verification(h):
    h.seed("conversation")
    items = h.api("GET", "/v1/unified/records", params={"facet": "EPISODE"}).json()["items"]
    assert all(x["content"]["verification"] != "VERIFIED" for x in items if x["content"]["only_assistant_claim"])
```

#### T02.3 被调用 Agent 与文件导入归入 Atlas

**文件：** A 修改 `api/agent_backends_router.py` 与 `agent/tool_node.py` 的 Agent-tool接线；新 `memory/windows_sources.py`、`test_agent_tool_capture.py`、`test_import_sources.py`。

- [ ] Atlas 给 Codex/ZCode 等工具传相关任务上下文，返回记录使用 actor_id、tool_call ID 与原日志 refs；不替对方安装全局记忆插件。
- [ ] 返回“完成”先记录 THIRD_PARTY/TOOL 声明；Atlas 独立检查实际目标后追加 VERIFICATION，更新 episode outcome。
- [ ] 支持本地 txt/md/json/pdf及图片/音频导入任务。解析沿 Atlas 已有文档/ASR/视觉能力，原文件 hash、版本与片段定位完整；文字导入先做，媒体解析在 UM05接全。
- [ ] 同文件重复导入幂等，内容修改新版本；路径移动不直接制造新事实；引用中的指令不能成为根用户指令。

```python
def test_agent_result_belongs_to_atlas(h):
    h.seed("agent_tool")
    items = h.api("GET", "/v1/unified/records").json()["items"]
    assert {x["memory_subject_id"] for x in items} == {"atlas-fixture"}
    assert any(x["content"].get("actor_id") == "tool-zcode" for x in items)
```

### UM03：人物、时间与冲突

#### T03.1 实体与别名消歧

**文件：** M 新 `service/unified/identity.py`、扩 `graph_store.py`、`graph_types.py`、新 `migrations/0025_unified_identity.sql`；测试 `test_identity.py`。来源 S01。

- [ ] 搬 Graphiti 的实体抽取/去重结构和提示词、精确重复路径，改成现有图实体/mention访问。别名关联独立保存候选和撤销状态。
- [ ] 精确账号/明确用户指认优先；姓名相同和 embedding 相近只产生候选，不跨人物自动强合并。媒体关联引用 UM05 验证结果，不用脸/声向量裸阈值确认身份。
- [ ] 合并/拆分生成 revision与依赖事件；原mention不丢，旧关系重新检查。人物关系带来源和时间，不推断所有未见关系。
- [ ] 用同名、改名、转述、账号相似、明确纠正测试误合并；达到验收书 precision 门禁后再进入 active 检索。

```python
def test_same_name_is_not_same_person(h):
    h.seed("identity")
    entities = h.api("GET", "/v1/unified/entities", params={"query": "小王"}).json()["items"]
    assert len(entities) == 2 and len({x["id"] for x in entities}) == 2
```

#### T03.2 有效区间与相对时间

**文件：** M 新 `service/unified/temporal.py`、修改 `storage.py`/formation 时间入口；测试 `test_temporal.py`。来源 S01 temporal functions。

- [ ] 搬区间不重叠检查与关系失效算法，保留系统接收和事实有效时间。用户无时区时间先按来源时区解析，不能直接套 naive-as-UTC。
- [ ] 处理“昨天/周五/这周/直到完成/回来后”、日期未知与旅行时区；条件型时间留给 intent条件，不伪造固定timestamp。
- [ ] 新说法是否 supersede 由语义与证据决定，时间函数只执行已判定的变更；旧消息迟到保持旧有效段。
- [ ] 当前、历史 as_of、knowledge_as_of_revision 三类查询区分，修正未来日期不改原始事件。

```python
def test_old_backfill_does_not_replace_current_state(h):
    h.seed("temporal")
    r = h.api("POST", "/v1/unified/recall", json={"query": "现在住哪里", "purpose": "CONVERSATION"}).json()
    assert r["context_items"][0]["content"]["value"] == "深圳"
```

#### T03.3 四类冲突与可信依据

**文件：** M `service/unified/formation.py` 的 conflict admission、`lifecycle.py`、API；测试 `test_conflict_resolution.py`。来源 S01/S02，基准思路来自第三轮 MemConflict/TANGLE但不抄未核许可代码。

- [ ] 输出 TEMPORAL_UPDATE / CORRECTION / CONDITIONAL_ALTERNATIVES / UNRESOLVED；保留所有源证据与适用条件，不以“最后一句”通吃。
- [ ] 同来源多摘要视为同一证据链；用户观点与客观事实区分，tool实测只在其可观察范围有效。
- [ ] unresolved 状态能进入 query conflict结果与 UI，模型得到差异和缺失条件；不自动产生确定动作。
- [ ] 验证条件偏好并存、传闻冲突、后来明确纠正及无法确定时间的情况。

```python
def test_unresolved_conflict_stays_visible(h):
    h.seed("conflict")
    r = h.api("POST", "/v1/unified/recall", json={"query": "该按哪个约定办"}).json()
    assert r["conflicts"][0]["kind"] == "UNRESOLVED" and r["missing_evidence"]
```

### UM04：日常经历、偏好与长期理解

#### T04.1 从原记录形成可回忆的事件

**文件：** M `service/unified/formation.py`、修改 `episode_ingest.py`、`candidate_ingest.py`；测试 `test_daily_episode.py`。来源 S02/S03。

- [ ] 搬 Hindsight 观察输入、来源绑定和去重流程；短聊天不丢，工具调用和结果保持成对，多轮同件事跨session关联但不合并无关事件。
- [ ] 事件保存谁/何时/何地/主题/行为/结果/未决事项/理由/原文 refs。既有 episode字段 goal/context/actions/observed_result 承载；新增facet扩展表达日常事件，不强行编出任务goal。
- [ ] 先原始证据再形成候选；每个生成事实必须支持定位，不能把Atlas生成总结作为新独立经历。
- [ ] 通过 Atlas 多次对话说同一事件、插入另一件事、新会话追问，timeline正确且原话可回看。

```python
def test_daily_event_has_original_evidence(h):
    h.seed("daily")
    event = h.api("GET", "/v1/unified/timeline").json()["items"][0]
    assert event["source_refs"] and event["content"]["participants"]
```

#### T04.2 动态画像、临时状态与条件习惯

**文件：** M `formation.py` 的 profile政策、新 `service/unified/profile.py`；测试 `test_profile_updates.py`。复用 S02来源追踪，测试参考 PersonaMem但不需要复制框架。

- [ ] 明确用户偏好/状态可自动形成当前view；行为推断 HABIT附次数、跨度、反例与置信边界，不自动写成永久身份。
- [ ] 临时状态必须 valid_to或可检查退出条件；跨场景差异放 applicability。状态过期不抹去历史。
- [ ] 主观情绪保存表达与上下文，不做心理诊断，不把“我不行”变成客观能力标签；偏见或错误客观声明保留 USER_ASSERTED。
- [ ] 回答/安排通过当前状态影响；无关问题应不强行个性化。

```python
def test_temporary_state_is_not_permanent_identity(h):
    h.seed("profile")
    r = h.api("GET", "/v1/unified/records", params={"facet": "STATE"}).json()["items"][0]
    assert r["valid_time"]["valid_to"] is not None
```

#### T04.3 日/周概括、知识与可回溯总结

**文件：** M 新 `service/unified/consolidation.py`、`dependencies.py`，扩 `compaction.py`；测试 `test_summary_provenance.py`。来源 S02/S03。

- [ ] 搬 TiMem L1–L5多粒度生成调用/提示词；Atlas 使用原子事件、日/周、长期理解三级产品视图，保留源函数职责而不是强制五个独立数据库。
- [ ] 每层包含输入 record/revision refs、未决冲突、时间范围、重要少见信息；不能递归丢条件后把失真总结当原文。
- [ ] Hindsight来源live检查接MemoryOS生命周期；生成后到提交前源版本变了，则丢弃过时结果并重跑。
- [ ] 学到的概念/知识与用户经历互联但分清外部知识和亲历；原始消息访问始终可用。

```python
def test_summary_preserves_dependency_versions(h):
    h.seed("summary")
    summary = h.api("GET", "/v1/unified/records", params={"facet": "SUMMARY"}).json()["items"][0]
    assert all(x["revision"] >= 1 for x in summary["dependencies"])
```

### UM05：Windows 视听与日常观察

#### T05.1 受控媒体与原始片段

**文件：** M 新 `service/unified/media.py`、`migrations/0026_unified_media.sql`；A 扩 `windows_sources.py` 和 `api/unified_memory_router.py`；测试 `test_media_locator.py`。

- [ ] 媒体 hash去重，单独保存受控相对路径、mime、大小、来源与片段区间。读媒体先查scope/lifecycle，不能让模型返回任意本机路径。
- [ ] 导入保留文字/OCR框、音频时间段或图片区域定位；无法解析显式missing，不补虚假caption。
- [ ] 上传/导入中断可恢复；替换文件新版本；删除检查blob的所有live引用，不误删另一个live事件共享媒体。
- [ ] UI 可打开对应片段，原媒体缺失能显示原因；格式/尺寸/时长超限明确处理。

```python
def test_evidence_points_to_media_segment(h):
    media = h.seed("media")
    e = h.api("GET", "/v1/unified/evidence/" + media["record_ref"]).json()
    assert e["snippets"][0]["locator"]["kind"] in {"AUDIO_RANGE", "IMAGE_REGION", "VIDEO_RANGE"}
```

#### T05.2 多模态节点与人物/物品联系

**文件：** M 新 `service/unified/multimodal.py`、扩 `graph_types.py`/`graph_store.py`；A 接现有 ASR/视觉 ModelManager；测试 `test_multimodal_identity.py`。来源 S05。

- [ ] 搬 M3-Agent image/voice/text节点、等价联系和检索相关代码；用 media refs替代base64长期埋入图，接已有实体与来源模型。
- [ ] 标明转录、caption、人物候选与原视频/图像的区别；低置信人物关联不自动确认，必须能回原证据。
- [ ] 音频说话人归属 UNKNOWN允许存在；看到物品位置只形成该时刻观察，不宣称后来仍在原处。
- [ ] 用图片+文字别名、语音+时间、相似人和移动物品样本验证；source erased后派生多模态候选失效。

```python
def test_weak_visual_match_remains_candidate(h):
    h.seed("media")
    people = h.api("GET", "/v1/unified/entities").json()["items"]
    assert any(x["alias_status"] == "PROPOSED" for x in people)
```

#### T05.3 Atlas 电脑/浏览器活动和记录控制

**文件：** A 修改 `tools/x2/computer.py`、`tools/x2/browser.py`、复用 `tools/x2/recording.py`；`windows_sources.py`、`test_windows_activity.py`。来源为现有 Atlas固定基线，不抄当前商业许可 Screenpipe。

- [ ] 工具已经产生的截图、浏览器URL/DOM和动作receipt进入MemoryOS，不建平行computer运行器。
- [ ] 新“记录当前活动”控制只记录用户选择的窗口/会话/媒体入口；默认不开全系统连续录屏。start/pause/stop落真实采集状态与source变化。
- [ ] 观察、点击请求、实际页面/文件结果分开；不可见后台应用不声称已记住。记录隐私范围复用现有设置，没有新的全局settings文件。
- [ ] 真Windows窗口操作：选择窗口、采集、暂停、停止、回看媒体；停止后无新增观察，恢复不重复旧帧。

```python
def test_stop_capture_stops_new_observations(h):
    h.seed("windows_activity")
    h.api("POST", "/api/unified-memory/capture/stop")
    before = h.api("GET", "/v1/unified/status").json()["passive_capture_watermark"]
    h.tool("computer_screenshot", {"fixture_window": True})
    assert h.api("GET", "/v1/unified/status").json()["passive_capture_watermark"] == before
```

此测试只限制主动开启的被动采集器；普通工具截图仍正常记入工具经历，不可误用停止采集禁用Atlas电脑工具。

### UM06：当前任务、中断恢复与未来事项

#### T06.1 真实工作记忆与注意焦点

**文件：** M 新 `working_set.py`、`migrations/0027_unified_focus_intents.sql`；A `memory/context.py`、修改 `run_phases.py`、`hermes_runtime.py`；测试 `test_working_memory.py`。来源 S04。

- [ ] 搬 Myelin observe/commit/attend及session scope机制，工作集持久化到统一focus投影；原任务运行状态只由Atlas/Hermes权威写。
- [ ] 当前目标、约束、已验证步骤、待解决项、外部操作receipt与相关记忆refs进入focus；多个任务不串焦点。
- [ ] context压缩/切模型保留focus与原证据，不让仅会话摘要代替任务状态。当前用户消息优先，不被旧偏好否决明确新要求。
- [ ] 检索之外验证注意预算、任务切换和依赖版本；focus为空时正常新任务，不编前情。

```python
def test_focus_is_task_scoped(h):
    h.seed("interrupted_task")
    r = h.api("POST", "/v1/unified/recall", json={"purpose": "CONTINUE_TASK", "query": "继续A任务", "context": {"task_id": "task-a"}}).json()
    assert all(x["content"].get("task_id") != "task-b" for x in r["context_items"])
```

#### T06.2 重启接续与副作用对账

**文件：** A `runtime/hub.py`、`engine/session_sync.py`、`memory/context.py`、现有durable task调用方；M focus/dependencies；测试 `test_restart_continuation.py`。

- [ ] 以现有真实task ID绑定source/session；更换chat只换入口，不改变任务主体。多个未完成任务时有明确焦点才自动继续，否则澄清。
- [ ] 重启查询运行权威和focus版本；UNKNOWN外部结果先检查真实文件/API/窗口，不重复调用具有副作用的工具。
- [ ] 恢复包含已验证步骤与不确定步骤；不把助手“完成”文本变为已完成任务。
- [ ] 真进程重启/故障后恢复，证明该继续的继续、已发生的不重做，模型选择改变亦可使用。

```python
def test_restart_does_not_repeat_completed_side_effect(h):
    h.seed("interrupted_task")
    h.restart("atlas")
    result = h.chat("继续刚才那个任务")
    assert result["external_operation_counts"]["write-fixture-file"] == 1
```

#### T06.3 时间与事件型意图接现有 Automation

**文件：** M 新 `intentions.py`；A 新 `intent_bridge.py`、修改 `automation/engine.py`/`triggers.py`；测试 `test_prospective_memory.py`。

- [ ] 从用户明确意图建立cue/action/条件/范围/有效期，不由第三方引文自动授权；建立意图时无需新增每条审批。
- [ ] 用现有Automation trigger与DBOS运行receipt；MemoryOS管意图及依据，Automation仍管触发/运行，双方通过稳定intent ID/automation ID绑定。
- [ ] 加 project_open/tool_result/record_updated等Atlas事件适配，不另造scheduler。cancel/延期/完成与trigger竞争以版本校验阻止重复。
- [ ] 对话中忙另一任务时仍可适时提醒；提醒与自动动作分开；UNKNOWN状态先对账。

```python
def test_cancelled_intent_does_not_trigger(h):
    data = h.seed("intent")
    h.api("POST", f'/v1/unified/intents/{data["intent_id"]}/transition', json={"transition": "CANCELLED", "expected_revision": 1})
    h.tool("open_project", {"project_id": "project-demo"})
    assert h.api("GET", "/v1/unified/intents").json()["items"][0]["lifecycle"] == "CANCELLED"
```

### UM07：自然召回、联想与真实行为

#### T07.1 多路检索与源证据回退

**文件：** M 新 `retrieval.py`/`query_planner.py`、接 `recall.py`、`hybrid_recall.py`、`semantic_recall.py`；测试 `test_hybrid_retrieval.py`。来源 S03/S15及既有MemoryOS。

- [ ] 复用已有全文/中文查询/向量机制；scope/lifecycle/时间过滤放最终结果回查，旧索引不能返回已撤回内容。
- [ ] TiMem复杂度planner改Atlas模型接口；普通精确/时间查询走无planner路径，复杂组合最多一次planner且保留失败回退。
- [ ] 原文/事件/状态/经验多样性装配，每项带来源与限定；用户当前输入不得反向变成检索真值。
- [ ] 精确定位优先走原始搜索，数据不足返回missing_evidence；向量故障仍能回答有全文证据的内容。

```python
def test_vector_failure_has_evidence_fallback(h):
    h.seed("basic"); h.fault("vector_unavailable", True)
    r = h.api("POST", "/v1/unified/recall", json={"query": "记住的输出格式"}).json()
    assert r["context_items"] and r["fallback_mode"] == "RAW_OR_FTS"
```

#### T07.2 联想与多跳联系

**文件：** M 新 `associations.py`/`graph_retriever.py`、接 `graph_query.py`；测试 `test_associative_recall.py`。来源 S06/S07/S01。

- [ ] 搬 A-mem新旧记忆链接与关联扩展；链接是派生索引，不允许process_memory直接改旧权威事实。
- [ ] 搬 HippoRAG事实筛选、passage信号与PPR关联检索；使用现有SQLite图适配，默认最多2跳、有限候选，不安装其独立存储。
- [ ] 抽取图precision门禁未过时保持shadow，修真实抽取/grounding后再开active；不能用人工造好图代替整个功能验收。
- [ ] 测试人物→事件→理由→结果组合，路径中撤回节点即失效；控制错误扩散和与相关但无关旧经历的干扰。

```python
def test_association_keeps_supporting_path(h):
    h.seed("association")
    r = h.api("POST", "/v1/unified/recall", json={"query": "上次跟那个人决定不用该工具的原因"}).json()
    assert any(x.get("association_path") for x in r["context_items"])
```

#### T07.3 主动使用、适当不使用与动作前检查

**文件：** A `memory/context.py`、修改 `run_phases.py` 的plan/context顺序、`_build_messages`/`hermes_runtime.py`、`tool_node.py`；M read receipts/dependencies；测试 `test_behavioral_use.py`。

- [ ] 规划前加载相关状态/约束，模型调用前装配已筛选记忆，动作前验证重要依赖版本；不要在plan已生成后才加载会改变计划的记忆。
- [ ] read_id与真正模型输入hash对应，tool子Agent收到必要任务视图；模型不必口头重复事实才算使用。
- [ ] 无关问题不装配私人经历；隐含问题根据人物/任务/时间cue扩展，低相关原始信息不会因“像用户”而强行插入。
- [ ] 用真实模型输出与实际工具参数验证记忆影响；与memory off对照，正确但没遵守约束也算失败。

```python
def test_implicit_constraint_changes_action(h):
    h.seed("implicit")
    result = h.chat("帮我安排明天的工作")
    assert not result["scheduled_work_in_evening"] and result["application_receipts"]
```

### UM08：纠错、撤回和完整删除

#### T08.1 普通纠正与人物拆分

**文件：** M `lifecycle.py`/`dependencies.py`、API；A统一memory router与UI后端；测试 `test_correction_propagation.py`。

- [ ] 用户直接纠正生成新revision和来源，保留原历史；不要求用户手动找每个派生摘要。
- [ ] 人物split恢复mention的独立归属；相关事件、关系、画像和计划标STALE并重算。
- [ ] 所有读路由、旧facts API和记忆块均回查最新状态；索引更新延迟期间旧结果拒绝用于当前事实。
- [ ] 重复纠错请求幂等，竞争修正expected_revision不匹配409；UI得到受影响项与进度。

```python
def test_correction_invalidates_derived_profile(h):
    d = h.seed("correction")
    r = h.api("POST", "/v1/unified/corrections", json=d["correction_request"]).json()
    assert d["profile_ref"] in r["affected_refs"]
```

#### T08.2 新事实不能配旧计划继续执行

**文件：** M dependencies check；A `tool_node.py`、durable plan/intent接线、`run_phases.py`；测试 `test_stale_plan.py`。

- [ ] plan/skill/intent记录当时用到的ref与版本；执行前检查只检查相关依赖前沿，不重扫整库。
- [ ] 新事实改变相关约束时刷新并重新计划；若仍无法确定，阻止该过时动作并向用户说明具体冲突。
- [ ] 不涉及动作的无关新记忆不造成全任务失效；方案尚有效的版本修正只更新依据。
- [ ] 竞争情形在“规划后、执行前”插入修正，证明真实工具收到新参数而非只回答知道新要求。

```python
def test_latest_memory_does_not_validate_old_plan(h):
    d = h.seed("correction")
    r = h.api("POST", "/v1/unified/dependencies/check", json=d["old_plan_dependencies"]).json()
    assert r["status"] == "STALE" and r["changed_refs"]
```

#### T08.3 扩展 HARD_ERASE、备份恢复与派生残留

**文件：** M 修改 `erasure.py`/`erasure_barriers.py`、新增controller注册，扩unified媒体/策略/图/索引；A outbox与skill artifact登记；测试 `test_erasure_layers.py`/`test_restore_barrier.py`。

- [ ] 复用现有preview/request/authorize/execute/verify流程，逐层注册新表、媒体、focus、intent、read trace含敏感片段、策略和技能引用；不创建第二套删除按钮流程。
- [ ] 被控源已删，outbox和迟到模型输出不能重新导入；备份恢复先应用删除/撤回屏障，再重建索引。
- [ ] 共享媒体只删除该源可达内容或在无live引用时删除blob；引用其他用户/事件时不得误删。
- [ ] 验证按层给manifest；墓碑与quarantine不是HARD_ERASE。已发邮件、第三方工具缓存、模型权重影响不谎称可清除，列不可控范围。

```python
def test_restore_does_not_resurrect_erased_source(h):
    d = h.seed("erasure")
    h.tool("fixture_authorized_erase", d["erase_request"])
    h.tool("fixture_restore_backup", d["backup_request"])
    assert h.api("GET", "/v1/unified/evidence/" + d["record_ref"]).status_code == 410
```

### UM09：真实经验、策略与条件效用

#### T09.1 结果验证与多种学习产物

**文件：** M 新 `experience_distiller.py`，接 existingexperiences/validations；A修改 `agent/enrichment.py`、run finalize；测试 `test_experience_distillation.py`。来源 S08/S02。

- [ ] 搬 ReasoningBank成功/失败轨迹格式与策略提炼提示；轨迹输入使用Atlas真实工具结果，不要求保存模型私有思维链。
- [ ] 结果UNKNOWN不标success，self-judge只作候选反馈；真实文件/API/窗口或明确定义结果判据产生validation。
- [ ] 产物含知识、方法、反例、能力缺口和状态更新；必要的事实更新走UM03/04，不能只生成SKILL.md。
- [ ] 失败来源与适用条件完整；一条失败不自动归因某个技能或人物。既有Experience ACTIVE/REUSABLE规则保留。

```python
def test_failed_task_produces_counterexample(h):
    h.seed("experience")
    items = h.api("GET", "/v1/unified/learning").json()["items"]
    assert any(x["facet"] == "COUNTEREXAMPLE" and x["source_refs"] for x in items)
```

#### T09.2 有版本的增量策略

**文件：** M 新 `strategy_updates.py`、`migrations/0028_unified_learning.sql`；测试 `test_strategy_operations.py`。来源 S09。

- [ ] 搬 ACE curator ADD/UPDATE/MERGE/DELETE解析与playbook操作，不把playbook文件作为新事实权威。
- [ ] 每个操作带origin、输入refs、expected revision和作用域；UPDATE保留前版，MERGE保留全部来源，DELETE是策略退役不直接删除原始经历。
- [ ] 策略可用于限定场景建议，ACTIVE必须有试验门禁；用户明确规则不由统计策略覆盖。
- [ ] 错误JSON、缺source、错误revision及跨作用域merge拒绝；atomic操作失败不留半更新。

```python
def test_strategy_update_requires_expected_version(h):
    d = h.seed("policy")
    r = h.api("POST", "/v1/unified/maintenance", json=d["stale_strategy_update"])
    assert r.status_code == 409
```

#### T09.3 场景化效用与使用反馈

**文件：** M 新 `utility.py`，接 read/application/outcome；测试 `test_conditional_utility.py`。来源 S10/S04。

- [ ] 搬 MemRL相关性筛选与效用排序/Q更新；key至少含memory或skill version、task family、tool/env与consumer model，禁止一份全局Q覆盖所有场景。
- [ ] 已检索、装配、引用、实际应用与结果分别统计；成功的整任务奖励不能直接归因全部检索记忆。
- [ ] Myelin cite结果反馈接口接真实read/应用receipt；没有确实使用的候选只记检索反馈。
- [ ] 相似但低效方法排名下降，有效方法在匹配场景上升；对明确用户事实不以utility低为由忘掉。

```python
def test_utility_is_consumer_conditioned(h):
    h.seed("utility")
    items = h.api("GET", "/v1/unified/learning").json()["utility_profiles"]
    assert len({x["model_deployment_id"] for x in items}) >= 2
```

### UM10：技能、预测、主动学习与迁移

#### T10.1 可执行技能与隔离演化

**文件：** A新 `memory/skill_evolution.py`，接 `skills/agent_collections.py`/现有registry；M skill binding/read validation；测试 `test_skill_transaction.py`。来源 S12/S13。

- [ ] 搬 Memento evolution engine及其prompt与原失败/回滚测试；将LLMClient/config/logger/loader适配到Atlas接口，不能删隔离测试与atomic deploy。
- [ ] 输出skill binding与来源experience；现有skills package manager只管理产物，统一记忆记录验证及active revision。
- [ ] 候选在独立Windows工作区跑真实工具/测试，原结构检查+目标效果+冻结held-out；synthetic judge不是最终判据。
- [ ] gate失败不改现有ACTIVE包；成功原子切换，取消/崩溃可回滚。不能让来源中的shell/Docker默认路径直接控制生产Atlas目录。

```python
def test_failed_evolution_preserves_active_skill(h):
    d = h.seed("skill")
    h.fault("skill_candidate_test_failure", True)
    h.tool("evolve_skill", d["evolution_request"])
    assert h.api("GET", "/v1/unified/learning").json()["active_skill_hash"] == d["baseline_hash"]
```

#### T10.2 预测、失败边界与方法组合

**文件：** M 新 `prediction.py`，扩experience适用性；A context技能组合提示；测试 `test_prediction_feedback.py`/`test_skill_composition.py`。来源 S11/S08。

- [ ] 搬 WorldMind Goal/Process经验提炼与refinement；替换其JSON持久化路径为MemoryOS读写，禁止并行保存经验权威。
- [ ] 预测指定对象/动作、输入状态、环境前提与预计可观察结果；真实结果回来后记误差、反例、信心校准。
- [ ] 软件/桌面任务用真实可检查结果；原项目具身环境指标不能直接沿用为Atlas质量证据。
- [ ] 新任务调用/组合旧方法时检查工具与前提；反事实只用于候选计划，不写成执行经历。

```python
def test_prediction_miss_becomes_feedback(h):
    h.seed("prediction")
    items = h.api("GET", "/v1/unified/learning").json()["items"]
    assert any(x["facet"] == "PREDICTION" and x["content"]["observed_error"] is not None for x in items)
```

#### T10.3 针对性学习与独立效果门禁

**文件：** A新 `targeted_learning.py`；M新 `learning_gate.py`、capability记录；测试 `test_targeted_learning.py`/`test_transfer_gate.py`。来源 S14/S13。

- [ ] 搬 OpenSkill TargetedDRRunner分类、查询构造、研究上下文机制；改用Atlas浏览器/搜索与ModelManager，移除硬编码provider和Docker要求，保留失败分类与重复研究抑制。
- [ ] 五类gap按01契约决定动作，缺数据/权限不伪装知识研究；IMPLEMENTATION_BUG不是不停搜索资料。
- [ ] 搬 independent verifier的独立会话、失败诊断与verification上下文，使用现有Windows隔离执行；验证目标真值与候选生成器分离。
- [ ] Recuris配对gate保留repair/net/regression逻辑，并按本项目未见任务统计增长。学习失败保留候选和证据，旧方法继续可用；能力记录注明任务/模型条件。

```python
def test_data_gap_does_not_trigger_fake_research(h):
    h.seed("knowledge_gap")
    result = h.chat("找出那个没有导入的文件里的人名")
    assert result["gap_kind"] == "AUTH_OR_DATA_GAP" and not result["fabricated_fact"]
```

### UM11：后台复盘与记忆策略

#### T11.1 绑定真实检索的自测与复盘

**文件：** M新 `self_probe.py`/`maintenance.py`，接既有jobs；测试 `test_grounded_probe.py`。来源 S04/S03/S09。

- [ ] 搬 Myelin生成probe/ground prompt/梦循环框架，retriever必须调用当前统一检索，不能传None走未grounded模式。
- [ ] 自测题来源只用已入库经历的证据，记录期望证据集合、实际召回和失败阶段；token answer-key命中仅作诊断，不当完整正确性。
- [ ] 按失败区分没记录、没关联、检索不到、装配丢失或生成错误，修候选并重测；模拟/假设不写原始evidence。
- [ ] 通过现有scheduler/worker按预算运行，默认只在有新证据或失败时做工作；进度放状态页，不周期性打扰用户。

```python
def test_probe_uses_actual_retrieval(h):
    d = h.seed("self_probe")
    result = h.api("POST", "/v1/unified/maintenance", json=d["probe_request"]).json()
    assert result["retriever_mode"] == "UNIFIED_LIVE" and result["source_refs"]
```

#### T11.2 重要性、保持、降级与可回滚策略

**文件：** M consolidation/maintenance/strategy_updates；配置现有memory namespace；测试 `test_retention_policy.py`。

- [ ] 编码重要性组合用户明确要求、目标关联、来源可靠性、稀有性、真实效用与访问历史；不只看embedding惊奇、长度或近期访问。
- [ ] 降级派生索引/总结不等于删除原始证据；少见短约定、反例与安全边界测试长期保持。法定保留等需求由用户单独配置，本期不猜。
- [ ] 策略改变仅在允许参数/提示/排序中形成candidate，冻结试验对照后原子active，失败可回滚；不自动演化schema或工具权限。
- [ ] 检查3个月/一年合成轨迹与30天真实持续使用门禁；后者不到周期只能阶段交付，不能说已经年尺度实证。

```python
def test_rare_short_commitment_survives_consolidation(h):
    h.seed("longitudinal")
    r = h.api("POST", "/v1/unified/recall", json={"query": "我很早答应过什么"}).json()
    assert any(x["record_ref"] == "commitment:rare-short" for x in r["context_items"])
```

### UM12：桌面体验、迁移与发布

#### T12.1 自然可用的记忆页面与证据解释

**文件：** A修改 `frontend/src/renderer/pages/MemoryPage.tsx`；新增 `components/memory/TimelineView.tsx`、`EvidencePanel.tsx`、`EntityView.tsx`、`IntentView.tsx`、`LearningView.tsx`、`CorrectionDialog.tsx`、`StatusPanel.tsx`；新对应Vitest和桌面E2E。

- [ ] 保留旧facts/pending/knowledge入口兼容；主视图增加日常时间线、当前理解、人事、待办、学到的方法与服务状态。
- [ ] 用户能从回答或条目打开“依据”，显示原话/片段、时间、角色与推断标志；回忆页面不用算法术语当产品文案。
- [ ] 修改、拆分人物、取消事项、纠错、删除、暂停采集走真实API，操作后的状态和影响可见；失败不得toast成功。
- [ ] loading/error/empty/conflict/degraded均可见；中文、键盘、长内容与小窗口验证；不引入第二套settings store。

```python
def test_desktop_correction_is_visible_in_new_chat(h):
    h.seed("desktop")
    h.tool("fixture_desktop_correct_preference", {"replacement": "简短中文"})
    assert h.chat("按我现在的格式来")['applied_preference'] == "简短中文"
```

#### T12.2 Windows 一致启动、健康与性能

**文件：** A现有backend启动/packaging接线，`api/health_router.py`/status；M worker启动与service lifecycle；测试 `test_release_composition.py`/`test_resource_limits.py`。

- [ ] 安装/开发启动都显式配置同一MemoryOS地址、数据根与契约版本；不是开发时注入才有效。
- [ ] 记忆service/worker生命周期可观测，停止Atlas时按配置处理service，不误杀他人进程；重复启动不启动重复后台队列。
- [ ] 真实规模测p50/p95、tokens、DB/媒体增长、启动时间与错误率；用预算和分页控制而非删除必要记忆凑性能。
- [ ] 通过installer或实际发布包运行证据；只Vite build/pytest不算桌面发布接线通过。

```python
def test_packaged_atlas_uses_same_memory_authority(h):
    h.seed("desktop")
    h.restart("packaged_atlas")
    status = h.api("GET", "/api/unified-memory/status").json()
    assert status["authority_id"] == h.runtime_manifest["authority_id"]
```

#### T12.3 正式切换 dry-run、恢复和用户交付

**文件：** A `scripts/unified_memory/cutover.py`/`rollback.py`、`docs/plan/UNIFIED-MEMORY/DEPLOYMENT.md`；M迁移/备份/恢复runner；测试 `test_cutover.py`。

- [ ] 使用用户数据的副本形成只读差异和切换预览，生成一致备份manifest；保留现有未提交内容与旧库。
- [ ] 新旧入口原子切换，在切换窗口暂停语义写或排outbox，保证无双写权威；新写、删除和撤回全部对账。
- [ ] 演练启动失败、切换后新数据、删除后回滚；恢复先屏障，不能盲目恢复旧DB。
- [ ] 产出可审查切换结果和恢复步骤。实际生产切换、发布/推送由用户授权后进行；准备工作和本期隔离效果先完整验证。

```python
def test_failed_cutover_keeps_previous_consistent_version(h):
    h.seed("legacy"); h.fault("cutover_startup_failure", True)
    result = h.tool("fixture_cutover_dry_run", {})
    assert result["rolled_back"] and not result["dual_memory_writers"]
```

### UM13：完整效果与持续使用验收

#### T13.1 320 核心用例及公开基准适配

**文件：** A runner和 `core/tests/unified_memory/test_acceptance_suite.py`；M `tests/unified_memory/public_benchmark_adapter.py`；结果ledger；来源 S16。

- [ ] 搬 MemoryAgentBench增量交互适配，使用同一MemoryOS和Atlas入口，禁止只测另一套框架。
- [ ] 按验收书320项冻结用例执行memory off /原始搜索/完整记忆三配置；模型、工具、预算与history权限相同，真值不注入。
- [ ] public基准可在许可范围外部运行；HaluMem等受限代码/数据不直接vendor。公开QA分数只作补充。
- [ ] 每项失败按摄取/形成/关联/检索/装配/生成/行为归因并保留证据；关键失败不得平均掉。

```python
def test_acceptance_manifest_has_all_domains(acceptance_manifest):
    assert acceptance_manifest["case_count"] == 320
    assert set(acceptance_manifest["domains"]) == set("ABCDEFGHIJKLMNOP")
```

#### T13.2 真实学习、组合与迁移对照

**文件：** A `scripts/unified_memory/learning_trial.py`；M learning_gate；测试 `test_learning_trial_integrity.py`。来源 S13。

- [ ] 12个经历训练任务只用于形成候选；36个未见任务来自4个任务族，3个固定seed，至少2个可用模型消费者；模型不足不能声称跨模型收益。
- [ ] 用真实Windows文件/浏览器/数据处理/日程任务判据，比较学习前后与原始搜索基线；配对执行并控制工具与预算。
- [ ] 记录新增有效方法、反例、实际应用、迁移收益、成本和旧任务回归；候选生成器不得读取held-out答案。
- [ ] 计算配对bootstrap CI；工程部署和统计增长分别报告。若未见任务收益不满足门禁，继续修在本书范围内的检索/方法/使用接线，不能改题。

```python
def test_learning_trial_keeps_unseen_answers_private(trial):
    assert not set(trial.training_ids) & set(trial.heldout_ids)
    assert trial.heldout_answer_reads_by_generator == 0
```

#### T13.3 Windows 真入口、长时间与最终关闭

**文件：** A最终 `tasks/results/ATLAS-UNIFIED-MEMORY-WINDOWS.result.md`、验收 JSON/HTML，双仓库release manifest；来源无新增。

- [ ] 真实桌面完成验收书12条产品效果，至少24条live互动轨迹；经历跨session/重启/模型变化/纠错/删除/未来触发。
- [ ] 长期合成轨迹验证90天/一年范围，启动至少30天真实持续使用观察；前期状态与持续使用验收分开，时间没到不谎称完成。
- [ ] 对照64项覆盖和40任务逐项定位证据、源码来源、接线和测试结果；本期明确排除设备接入，不把它们标已实现。
- [ ] 全门禁通过才ACCEPTED；用户授权后正式切换，核验实际安装来源和两个HEAD。任何必要门禁未过，保留PARTIAL及精确剩余工作，不用单测绿结案。

```python
def test_final_receipt_cannot_hide_missing_gates(receipt):
    assert receipt["status"] != "ACCEPTED" or all(g["passed"] for g in receipt["required_gates"])
    assert receipt["scope"] == "Windows Atlas as primary memory subject"
```

## 每波验证命令与提交边界

MemoryOS 的对应测试全部放 `tests/unified_memory/`，以 service 解释器运行；Atlas对应测试放 `core/tests/unified_memory/`，按总任务书显式override addopts。UI执行 `npm run test`、`npm run build` 与真Electron E2E。live使用runner明确live配置并记模型deployment和真实调用数量，不以fake模式替代。

所有命令从对应worktree根运行，先校验runtime数据根；禁止把旧全库suite里的已知失败悄悄删掉。与本波无关的基线失败单列；如果影响目标闭环，则在允许范围内修并再验证。

每波提交只包含本波自有文件与必要接线。不要把生产DB、用户媒体、API key、原始个人日志或第三方模型缓存提交Git。源代码许可和差分随代码提交，用户验收证据按可控私有artifact管理。与本项目无关的旧CURRENT、H1、C6和私有truth不擅自改写。
