# VENDORED — 外部源码搬运登记（unified-memory/waves）

共同要求见 `docs/plan/UNIFIED-MEMORY/03_source_porting.md`「所有搬运项共同要求」。
每个条目登记：来源仓库 / commit / 来源文件与符号 / 目标符号 / 许可证 / 改动理由 /
依赖闭包（逐文件 SHA256）/ parity 测试与结果 / 实际调用方与集成证明。

来源原始副本（仅差分用，不是第二套可运行引擎）：
`work/um03_t03_1/graphiti_src/`（raw.githubusercontent.com 按 commit 抓取，LF 行尾）。

---

## S01 Graphiti — UM03 / T03.1 实体与别名消歧（2026-10-06）

- 仓库：<https://github.com/getzep/graphiti>；固定 commit：
  `2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066`；许可证：**Apache-2.0**
  （各源文件头部版权声明 "Copyright 2024, Zep Software, Inc." 原样保留于
  语义参考副本的出处注释；本仓未整体复制任何上游文件，均为 ADAPT 后的独立实现，
  上游许可证与 NOTICE 通过本登记与源码头注释出处引用满足）。
- 方式：ADAPT；波次：UM03；本条目覆盖 T03.1（identity 半环）；
  T03.2（temporal 半环：valid_at/invalid_at/expired_at、矛盾判定）另条登记。
- 集成证明（实际调用方）：
  - `service/unified/api.py` — `GET /v1/unified/entities`、
    `POST /v1/unified/entities/resolve`（501 占位于 T03.1 移除；
    `NOT_READY_ROUTES` 不再含这两条）。
  - `service/unified/sources.py` — `source_change(DELETE)` 调用
    `identity.invalidate_aliases_for_source`（来源撤回 → 失据 PROPOSED 失效）。
  - `service/unified/repository.py` — `status()` 的 `wired.entities /
    wired.entities_resolve = True`。
  - Atlas 侧经 T01.3 表驱动代理（`core/atlas/api/unified_memory_router.py`
    `PROXY_ROUTES` 已含 `/entities`、`/entities/resolve`）自动跟随，零改动。
  - 测试：`tests/unified_memory/test_identity.py`（20 项，进程内 + TempSvc 真服务）。

### 锁定入口文件（03 清单点名；SHA256 同时给出抓取 LF 行尾值与 04_source_locks.json 登记值）

| 来源文件 | SHA256（LF，work 副本） | SHA256（04 锁定值 = CRLF checkout） |
| --- | --- | --- |
| graphiti_core/edges.py | `0151d72ebfb057033c6d52a163e22f252f67b915722e14315b685c7831b3b1c6` | `6715bbe5763d30aa58134fc601ad21c761aaf4a7b5785809f507146b5f821af2` |
| graphiti_core/utils/maintenance/edge_operations.py | `b773ff4489968af2a996d5074e679cab9806cc0904a7ff9f2aecc74382325abe` | `5f9ff2a5cc3ce5cc0bac4aee202ad6fadb7172464aa7af33e26bc2bcd6cb5d6e` |
| graphiti_core/search/search_filters.py | `a8be03eb976a8c781b04df9a987a3b57704d6ad729ef0417300f31f7487e298f` | `ad26e1ca011a52d433d993d4165d08ce66e211b9cfe3dbf3626467db21430065` |
| graphiti_core/utils/datetime_utils.py | `ff641aed24fa2e04e08264d920faa2e66ec825a66abdd31cd10aa2a9779a89c6` | `b6b029185344a6a74937e91759b6cfbc966cad6df0cfda0498075765bac82d15` |

说明：两组哈希对应**同一字节内容**，仅行尾差异（raw.githubusercontent 下发 LF；
04 锁定值在 CRLF checkout 上计算）。四文件 CRLF 值与 04_source_locks.json 逐一相符，
内容核验通过。

### 依赖闭包（03「施工时必须补齐的依赖文件」要求的逐文件读取与登记）

| 来源文件（commit 2a85bbb） | SHA256（LF） | 读取用途 |
| --- | --- | --- |
| graphiti_core/utils/maintenance/node_operations.py | `a5874fa63bb38ff6a5d89fedcb6c07701b81ca736d435b69fb26ce26bd6bd921` | `_collapse_exact_duplicate_extracted_nodes`(:336-384)、`_semantic_candidate_search`(:418-450)、`NODE_DEDUP_COSINE_MIN_SCORE`(:65)、dedupe 升级路径(:467-624) |
| graphiti_core/utils/maintenance/dedup_helpers.py | `3d9e09169d94b5a04709fa8dfff5d3471dda8b87329a79484afd92af4f7e6ecd` | `_normalize_string_exact`(:39-42)、`_normalize_name_for_fuzzy`(:45-49)、`_shingles`(:88-94)、`_jaccard_similarity`(:131-140)、`_resolve_with_similarity`(:220-279，精确命中/歧义升级) |
| graphiti_core/search/search_utils.py | `304b1acf9fc50adc1b6fe705667853a7774cd54fd8000feb87575e4f6753221f` | `node_similarity_search`(:667-720，embedding 候选召回的形参/下限语义) |
| graphiti_core/utils/maintenance/attribute_utils.py | `9a1f0f885e625af65bf8fe9a5305a1f5af46725aebb1124512794fc9af760d23` | 属性 overlay 合并语义（本波未搬运属性抽取，closure 完整性读取） |
| graphiti_core/utils/text_utils.py | `3617d42cea5a50754cb13802e07d95c239fd67678f70e1c8dbab5a12ab6a741c` | `MAX_SUMMARY_CHARS` / `truncate_at_sentence`（摘要提示词依赖，本波未搬运） |
| graphiti_core/graphiti.py | `2d0ffbb8b6de59787269326a9255d875f74da63ed66fd4f4fad3f159538d0fdd` | `_extract_and_resolve_nodes`(:615-)、`_resolve_nodes_and_edges_bulk`(:846-)（resolve_nodes 编排上下文） |
| graphiti_core/nodes.py | `529eb74b7c93e7551f6287b1a7bf6818d31fd045623b3260967dad573e4d801c` | `EntityNode` labels/特异性语义（坍缩决胜规则的输入形状） |
| graphiti_core/prompts/dedupe_nodes.py | `2e7a9db7e2f6ea73b62cfd10022fcd16828b79ec2e4165a913c16f9b57b7b518` | 提示词语义底线：`node`/`nodes`(:83-93,:145-151)「NEVER mark entities as duplicates if … separate instances」、`node_list` 分组提示 |
| graphiti_core/prompts/extract_nodes.py | `e0d3da2be310b6048cefada866271a64ec21845279faf6fb389754dbb54b5775` | `extract_attributes`(:383-466) HARD RULES（本波未搬运 LLM 抽取；closure）、`ExtractedEntity` 结构 |
| graphiti_core/prompts/dedupe_edges.py | `607cb830bb02a6020fdfea013e321345c0c0d5629f7895dc76622130cefc22c6` | 边去重提示词（T03.2 closure 预读，本波未搬运） |
| graphiti_core/prompts/prompt_helpers.py | `63288541d48d98dcc5fa7f67edf02a81eca46e42be0503f78b618767c828fbc4` | `to_prompt_json`（提示词序列化形状） |

### 搬运对照（来源 file:symbol → 目标 file:symbol）

| 来源（graphiti_core @ 2a85bbb） | 目标（service/unified/identity.py） | 改动 |
| --- | --- | --- |
| `utils/maintenance/dedup_helpers.py:_normalize_string_exact`(:39-42) | `normalize_name` | 前置 NFKC（全半角折叠，本仓扩展；纯 ASCII 输入逐字符等价） |
| `dedup_helpers.py:_normalize_name_for_fuzzy`(:45-49) | `normalize_fuzzy` | 保留 CJK 区段（上游会丢弃全部 CJK，中文人名不可用） |
| `dedup_helpers.py:_shingles`(:88-94) | `shingles` | 含 CJK 串用 2-gram（3-gram 对两三字人名退化）；ASCII 保持 3-gram |
| `dedup_helpers.py:_jaccard_similarity`(:131-140) | `jaccard_similarity` | 语义原样 |
| `dedup_helpers.py:_resolve_with_similarity`(:220-279) 精确命中唯一候选→合并、多候选→升级 | `refresh_identity_index` 步骤 2 | **不自动合并**（总任务书禁令）：归一同名歧义固化为 PROPOSED 候选；审定由人审 resolve 替代上游 LLM 升级 |
| `node_operations.py:_collapse_exact_duplicate_extracted_nodes`(:336-384) | `collapse_exact_duplicates` | 输入形状 EntityNode→dict(name,type)；决胜规则逐语义保留（parity 锁定） |
| `node_operations.py:65 NODE_DEDUP_COSINE_MIN_SCORE=0.6` + `_semantic_candidate_search`(:418-450) | `CANDIDATE_MIN_SCORE=0.6` + `name_similarity` | 本波以归一 shingle Jaccard 模拟 embedding 候选召回（任务书明示） |
| `prompts/dedupe_nodes.py`(:83-93,:145-151) 「同名不等于同人」提示词底线 | 模块 docstring + resolve 审定门（VERIFY_ALIAS/MERGE 必须人审 + 来源 refs） | 提示词语义保留为 API 语义；本模块无 LLM 调用 |
| `search_utils.py:node_similarity_search`(:667-) | SQLite 扫描 + `name_similarity`（subject 作用域 = 上游 group_id 过滤） | 存储替换：SQLite graph_entities/graph_entity_mentions 替代图数据库驱动 |
| `search_filters.py`（SearchFilters/group_ids 语义） | `list_entities` / 扫描按 `memory_subject_id` 作用域 | 同上 |
| `utils/datetime_utils.py:ensure_utc`(:35-37) | **不搬运**（naive-as-UTC 是总任务书禁令）；时间语义归 T03.2 | 授权内偏离 |
| `edges.py:EntityEdge`(:263-) valid_at/invalid_at/expired_at、`edge_operations.py:resolve_edge_contradictions`(:538-573) | T03.2（temporal 半环），本条目未搬运 | 已真读（closure），留待下项 |

### 目标侧新符号（接线）

- `migrations/0025_unified_identity.sql`：`unified_entity_aliases`
  （别名裁定层，entity_id 外键复用 graph_entities，**不建第二套实体库**）、
  `graph_entity_mentions.source_event_id/source_refs_json`（证据列）、
  `graph_relations.recheck/recheck_reason/recheck_at`、`graph_entities.revision`。
- `service/graph_store.py`：`entity_digest` / `prune_orphans`（公开包装，identity 层
  与既有管线共享同一确定性 id 空间与孤儿回收规则）。
- `service/unified/identity.py`：`normalize_name/normalize_fuzzy/core_name/shingles/
  jaccard_similarity/name_similarity/collapse_exact_duplicates/
  refresh_identity_index/list_entities/resolve/invalidate_aliases_for_source`；
  resolve 四动作 MERGE / SPLIT / VERIFY_ALIAS / REVOKE（幂等 change_id、
  expected_revisions→409、`unified_record_revisions` change_basis=
  ENTITY_MERGE/ENTITY_SPLIT/ALIAS_VERIFY/ALIAS_REVOKE）。

### 改动理由（为何是 ADAPT 而非照抄）

1. 身份纪律：上游精确路径会把同名新节点自动合并进唯一同名候选（:236-243）；
   本包总任务书禁令「姓名相同不许自动合并」→ 同名只 PROPOSE，MERGE/SPLIT 必须
   显式审定并留 `unified_record_revisions` 事实行。
2. 无 LLM：上游把歧义/低熵候选升级到 dedupe LLM prompt；本模块零 LLM 调用
   （实体抽取仍走既有 graph_extraction_worker 确定性管线，不重写），LLM 决策位
   由人审 API 替代；LLM 抽取仍属 graph_extraction_worker 现有独立机制。
3. 存储替换：SQLite（graph_entities/mentions/relations）替代上游图数据库驱动；
   `naive` 时间处理不照搬（datetime_utils.ensure_utc 假设 naive=UTC，禁令）。

### parity 测试与结果（2026-10-06，service/.venv）

- `tests/unified_memory/test_identity.py::test_parity_normalize_matches_graphiti_on_ascii`
  —— 12 组纯 ASCII 输入，`normalize_name` ≡ 上游 `_normalize_string_exact`
  （dedup_helpers.py:39-42）。**通过**。
- `::test_parity_exact_duplicate_collapse_same_grouping` —— 5 组/11 样本固定
  fixture，`collapse_exact_duplicates` 分组 ≡ 上游
  `_collapse_exact_duplicate_extracted_nodes`（node_operations.py:336-384，
  测试内逐语义参考副本，出处行号见 docstring）。**通过**。
- `::test_parity_collapse_specificity_and_length_tiebreak` —— 特异性/长度决胜
  parity。**通过**。
- `::test_parity_fullwidth_and_cjk_are_documented_extensions` —— 记录在案的扩展
  （NFKC 全半角、CJK 保留）非 parity 范围。**通过**。
- 套件：`pytest tests/unified_memory -q` → **80 passed**；
  旧套件 `pytest tests --ignore=tests/unified_memory
  --ignore=tests/test_graph_conservative.py -q` → **74 passed**（基线不回退；
  `tests/test_graph_store.py::test_migration_is_idempotent_and_tables_exist` 的
  旧基线构造随 0025 阶段更新：模拟旧基线排除依赖 0022 的 0025，升级断言加 0025）。

### 已知边界 / 未尽事项

- 图是可重建派影：`rebuild_graph_for_subject` 重建后 mention/关系归位，而
  SPLIT/MERGE 需按 `unified_record_revisions` 事实行重放（重放器属 UM08 传播波）。
- VERIFIED 别名引用的证据被撤回时本波不自动降级（传播算法属 UM08）；PROPOSED
  已按 T03.1 判据失效（`invalidate_aliases_for_source`）。
- 精确账号（ACCOUNT kind）已建模并带 409 ACCOUNT_CONFLICT 冲突面；外部账号
  连接（验收矩阵 A02 后半）延后。

---

## S01 Graphiti — UM03 / T03.2 有效区间与相对时间（2026-10-06）

- 仓库：<https://github.com/getzep/graphiti>；固定 commit：
  `2a85bbbf27f3d0d07dd3a8bf6dc8700c5193c066`；许可证：**Apache-2.0**
  （上游 datetime_utils.py 头部版权声明 "Copyright 2024, Zep Software, Inc."
  以本条目与目标文件模块 docstring 的出处引用满足；本仓未整体复制任何上游文件，
  均为 ADAPT 后的独立实现）。
- 方式：ADAPT；波次：UM03；本条目覆盖 T03.2（temporal 半环：
  valid_at/invalid_at/expired_at 分工、区间失效执行、as_of 查询三分类、
  naive 时间处理）。T03.1（identity 半环）见上一条目。
- 集成证明（实际调用方）：
  - `service/unified/repository.py` — `recall()` 的 as_of 三分类
    （CURRENT / HISTORICAL / KNOWLEDGE_REVISION）与记录有效区间过滤；
    `_memory_to_record` / `_event_to_record` 的 valid_time 补
    {source_timezone, basis}；`_sorted_by_time` / recall 候选排序的
    确定性次级键（同秒平局不再由随机 event_id 决胜）。
  - `service/unified/sources.py` — `check_observation_times`（observe 预检：
    坏时区/naive → 422；ack.source_objects.temporal 回带解析依据）。
  - `service/unified/legacy.py` — `_normalize_occurred_at` 不再假设
    naive=UTC：无时区原值 → time_status=UNKNOWN + occurred_at_raw 保留。
  - Atlas 侧经 T01.3 表驱动代理（POST /api/unified-memory/recall body
    原样转发）自动跟随；`core/tests/unified_memory/test_temporal_proxy.py`
    （2 项集成）验证 as_of 两时刻返回不同 valid 集。
  - 测试：`tests/unified_memory/test_temporal.py`（45 项：矩阵 + parity +
    TempSvc HTTP）。

### 来源文件（本条目读取并核验；SHA256 = work 副本 LF 行尾）

| 来源文件（commit 2a85bbb） | SHA256（LF，work 副本） | SHA256（04 锁定值 = CRLF） | 读取用途 |
| --- | --- | --- | --- |
| graphiti_core/utils/datetime_utils.py | `ff641aed24fa2e04e08264d920faa2e66ec825a66abdd31cd10aa2a9779a89c6` | `b6b029185344a6a74937e91759b6cfbc966cad6df0cfda0498075765bac82d15` | `utc_now`(:20-22)、`ensure_utc`(:25-42)、`convert_datetimes_to_strings`(:45-61) |
| graphiti_core/utils/maintenance/edge_operations.py | `b773ff4489968af2a996d5074e679cab9806cc0904a7ff9f2aecc74382325abe` | `5f9ff2a5cc3ce5cc0bac4aee202ad6fadb7172464aa7af33e26bc2bcd6cb5d6e` | `resolve_edge_contradictions`(:538-573 区间不重叠检查 + supersede 执行)、`_extract_edge_timestamps`(:200-320 valid/invalid 解析语义) |
| graphiti_core/edges.py | `0151d72ebfb057033c6d52a163e22f252f67b915722e14315b685c7831b3b1c6` | `6715bbe5763d30aa58134fc601ad21c761aaf4a7b5785809f507146b5f821af2` | `EntityEdge`(:263-) valid_at/invalid_at/expired_at 三分语义与 `reference_time` |
| graphiti_core/search/search_filters.py | `a8be03eb976a8c781b04df9a987a3b57704d6ad729ef0417300f31f7487e298f` | `ad26e1ca011a52d433d993d4165d08ce66e211b9cfe3dbf3626467db21430065` | `DateFilter`/`ComparisonOperator`(:38-65) as_of 比较原语 |

### 依赖闭包补充（本条目新读；tz 数据源）

| 依赖 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| tzdata（PyPI，Windows zoneinfo 标准数据源） | 2026.5（安装进 service/.venv） | Apache-2.0 | `zoneinfo.ZoneInfo` 的 IANA 规则（夏令时歧义检测依赖真实切换表） |

### 搬运对照（来源 file:symbol → 目标 file:symbol）

| 来源（graphiti_core @ 2a85bbb） | 目标（service/unified/temporal.py） | 改动 |
| --- | --- | --- |
| `utils/datetime_utils.py:utc_now`(:20-22) | `utc_now` | 语义原样 |
| `utils/datetime_utils.py:ensure_utc`(:25-42) | `ensure_utc` | aware 分支逐语义保留；**naive→UTC 分支不搬**（总任务书禁令）→ `NaiveTimeRejected`；parity 测试断言偏离在案 |
| `utils/datetime_utils.py:convert_datetimes_to_strings`(:45-61) | `to_utc_iso`（单值语义：序列化前归一 UTC） | 存储层为 SQLite 原生列，无需递归遍历器 |
| `edges.py:EntityEdge`(:271-283) valid_at / invalid_at / expired_at 三分 | 记录 `valid_from` / `valid_to` / `expired_at`（区间左闭右开 + 系统得知失效时刻） | 字段名随本仓契约（01_contracts §4）；三分分工保留 |
| `edge_operations.py:resolve_edge_contradictions`(:538-573) | `intervals_overlap`（:553-561 不重叠判据取反）+ `supersede_interval`（:562-568 失效执行，`expired_at = expired_at or utc_now()`）+ `close_interval` | **只执行已判定语义，不裁决**（语义判定属 T03.3/formation）；迟到旧记录保持旧有效段（上游 skip 分支同一形状） |
| `search_filters.py:DateFilter`(:38-44) | `as_of_mode` / `parse_as_of` / `record_active_at` / `knowledge_view_filter` | as_of 三分类：CURRENT / HISTORICAL（某时刻有效集）/ KNOWLEDGE_REVISION（按 revision 过滤；重放器完整版留 UM08） |

### 目标侧新符号（本仓扩展，非上游功能）

- `parse_user_time(text, source_timezone, now, context)` — 用户相对/绝对时间解析：
  ISO 带/不带时区；相对词（昨天/今天/明天/前天/大前天/N 天前/后/上周五/这周/
  下个月/周 N/「3 月第二个周日凌晨2点」/「M 月 D 日」）；「周五」无法定周 →
  AMBIGUOUS + 候选区间（不伪造日期，01_contracts §4）；「上周某天」日期未知 →
  AMBIGUOUS + 候选区间；条件型（「直到完成/回来后」）→ CONDITIONAL + 引用原文，
  不造 timestamp（intent 条件归 UM06）；跨时区旅行（context.travel 声明按事件
  时区；文本显式时区词）；DST 春季间隙（墙上时间不存在）与秋季回拨（出现两次）
  → AMBIGUOUS + 两个候选 UTC 时刻；无时区且未声明来源时区 → AMBIGUOUS
  （拒绝 naive-as-UTC）。
- `check_observation_time` / `observation_time_basis` — observe 预检与解析依据。
- `intervals_overlap` / `interval_contains` / `record_active_at` — 左闭右开区间
  原语（null = 无界）。

### 改动理由（为何是 ADAPT 而非照抄）

1. naive-as-UTC 禁令：上游 `ensure_utc` 把 naive 时间当 UTC（:35-37）；
   本仓用户本地时间必须先按来源时区解析，「无法定周的周五」形成待澄清时间，
   不伪造日期（总任务书 + 01_contracts §4）。
2. 职责切分：上游 resolve_edge_contradictions 混在矛盾消解管线里（LLM 抽取的
   edge 数据流）；本仓时间函数只做**已判定语义的执行器**（supersede 语义判定
   属 T03.3/formation 波），并独立提供 as_of 三分类查询原语。
3. 存储替换：SQLite 原生列 + ISO 字符串存储（UTC 归一）替代上游图数据库驱动；
   相对词解析为中文语境扩展（上游只有 LLM 提示词抽取 valid_at/invalid_at）。

### parity 测试与结果（2026-10-06，service/.venv）

- `tests/unified_memory/test_temporal.py::test_parity_ensure_utc_matches_graphiti_on_aware_inputs`
  —— None / UTC / 非 UTC aware（含 DST 时区）四组输入，`ensure_utc` ≡ 上游
  `ensure_utc`(:25-42)（测试内逐语义参考副本）。**通过**。
- `::test_parity_naive_input_is_documented_divergence_not_utc` —— naive 输入：
  上游 `replace(tzinfo=UTC)`；本仓抛 `NaiveTimeRejected` / 解析层返回 AMBIGUOUS
  （授权偏离断言，明确不搬）。**通过**。
- `::test_parity_supersede_decision_matches_graphiti_on_fixtures` —— 5 组固定
  fixture，`supersede_interval` 执行/跳过决策 ≡ 上游
  `resolve_edge_contradictions`(:538-573) 判定核心（测试内逐语义参考副本）。
  **通过**。
- `::test_parity_utc_now_is_aware_utc` —— ≡ 上游 utc_now 语义。**通过**。
- 套件：`pytest tests/unified_memory -q` → **126 passed**；
  旧套件 `pytest tests --ignore=tests/unified_memory
  --ignore=tests/test_graph_conservative.py -q` → **74 passed**（基线不回退）。

### 已知边界 / 未尽事项

- 「N 个月前/后」「季度」「节假日」等相对词未实现（返回 UNKNOWN，不猜）；
  条件型时间只标注不落 timestamp（intent 条件归 UM06）。
- knowledge_as_of_revision 本波只做按 record_revision 过滤；
  按 `unified_record_revisions` 重放完整知识视图属 UM08。
- corrections 路由仍未接线（501）；「修正未来日期」以
  `unified_record_revisions` 事实行留链验证（原始事件不改），应用侧属后续波。
- records 列表排序平局修复（source_event_id 次级键）同时消除了 Atlas
  `test_import_sources` 的顺序 flake；该测试另一处「同批观察异步 flush 部分
  可见」竞态以 `_wait_for_records(expected=N)` 等齐预期数量修复（测试侧）。

---

## S02 Hindsight — UM04 / T04.1 事件形成与时间线（2026-10-06）

- 仓库：<https://github.com/vectorize-io/hindsight>；固定 commit：
  `b89ce287464fe10790d67ba86bfabe29d8926253`；许可证：**MIT**
  （LICENSE 原文 "MIT License / Copyright (c) 2025 Vectorize AI, Inc."，该
  commit 下 LICENSE SHA256=`01fde0bedf83bdc185065d7af524a61690efe576a67f922eaff3a1280c17b63a`；
  本仓未整体复制任何上游文件，均为 ADAPT 后的独立实现，许可证通过本登记与
  目标文件 docstring 出处引用满足）。
- 方式：ADAPT；波次：UM04；本条目覆盖 T04.1（日常事件形成 episodes +
  GET /v1/unified/timeline）。04_source_locks.json 的 S02 target 还列了
  `service/unified/dependencies.py` —— **该模块本波未建**（见「未搬运」）。
- 来源原始副本（仅差分用）：`work/um04_t04_1/hindsight_src/`
  （raw.githubusercontent.com 按 commit 抓取，LF 行尾；本次收尾以
  byte-identical 重新下载复核逐一相符）。**本波真读并核验的判定核心在
  consolidator.py；memory_engine.py 只作 retain→整理触发编排的 closure 阅读
  （无符号搬运）**。
- 集成证明（实际调用方）：
  - `service/unified/sources.py` — `observe_batch`：TEST 批直接
    `process_batch`（:207-211，DIRECT_TEST_BATCH）；PRODUCTION 批只入队
    FORMATION job（:333-360，§12 TEST 不进生产链路的反向：PRODUCTION 不
    绕过队列）；`source_change(DELETE)` 调 `mark_stale_for_source`（:497）。
  - `service/unified/api.py` — `GET /v1/unified/timeline`（:346-365，
    NOT_READY_ROUTES 不含 timeline）。
  - `service/unified/repository.py` — `timeline()` 实现（事件时间排序 /
    unknown 分组 / cursor 分页）；`status()` 的 FORMATION 队列与
    FORMED_THROUGH 水位（:197-231）。
  - `migrations/0026_unified_episode_formation.sql` — episodes.episode_key
    UNIQUE（幂等键物理约束）等形成侧列。
  - Atlas 侧经 T01.3 表驱动代理自动跟随；本次收尾补
    `core/tests/unified_memory/test_timeline_proxy.py`（Atlas 仓集成）。
  - 测试：`tests/unified_memory/test_daily_episode.py`（16 项：进程内 parity +
    PRODUCTION 双路径 + TempSvc HTTP 全链路）。

### 锁定入口文件（04_source_locks.json S02；SHA256 同时给出抓取 LF 行尾值与 04 锁定值）

| 来源文件 | SHA256（LF，work 副本） | SHA256（04 锁定值 = CRLF checkout） | 核验 |
| --- | --- | --- | --- |
| hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py | `9c210e1e934116579cece89e947bafdd2ae494c62528d49bb39951e8d0e0aeb2` | `b6958ada908fcc74a0f2c7173b9b1ca96b2cb87a83fbaf3e8d8547900c0d4c01` | ✓ 与 04 锁定相符 |
| hindsight-api-slim/hindsight_api/engine/memory_engine.py | `3dfc7e8584589ba6d371cc5cd231645c37d17863c229784e28b6cfa2ff9f39c0` | `38d2504b970cb06f6da458f4d57199284ab62586cf0135f2912a11cf79e01aae` | ✓ 与 04 锁定相符 |

说明：两组哈希对应**同一字节内容**，仅行尾差异（raw.githubusercontent 下发 LF；
04 锁定值在 CRLF checkout 上计算）。收尾核验方式：按 commit 重新下载两文件，
与 work 副本 byte-identical（diff 为空），CRLF 变换后哈希与 04 锁定逐一相符。

### 依赖闭包（逐文件读取与登记）

| 来源文件（commit b89ce28） | SHA256（LF） | 读取用途 |
| --- | --- | --- |
| hindsight-api-slim/hindsight_api/engine/consolidation/prompts.py | `aea3d86dfbd84e5dbcca279b625714bfdb0734ec3c26f8f883d40e5418c3e0e6` | PROCESSING RULES 1（prefer UPDATE over CREATE，:39）、2（一个 facet 一条观察，:41）、3（按实体/facet 匹配，:43）、9（无关主题不合并，:55）→ 分组与扩展判定纪律（无 LLM，规则语义保留为判定纪律） |
| LICENSE | `01fde0bedf83bdc185065d7af524a61690efe576a67f922eaff3a1280c17b63a` | 许可证核验（MIT） |

### 搬运对照（来源 file:symbol → 目标 file:symbol，行号逐一核对于该 commit 原文）

| 来源（consolidator.py @ b89ce28） | 目标（service/unified/formation.py） | 改动 |
| --- | --- | --- |
| `_norm_obs_text`(:110-118) | `_norm_episode_text`(:1093-1099) | 语义原样：仅折叠连续空白、保留大小写（case-fold 丢 "TLS"/"tls" 差异，上游注释同理由） |
| `_duplicate_create_target`(:121-139) | `_duplicate_create_target`(:1102-1115) | 单批 shown-observation 分支逐语义（归一正文命中已示事件 → 丢重复 CREATE、来源并入）；**update-in-same-response 分支(:134-135)未搬运** —— 无 LLM 同响应 CREATE/UPDATE 形态，同 key 分组扩展路径覆盖该问题（parity 测试显式断言偏离在案） |
| `_DedupDecision`(:147-213) + `_dedup_adjudicate`(:275-348) | `_episode_dedup_decision`(:1348-1382) | LLM merge/keep 裁决 → 确定性三分支 NEW_EPISODE / EXACT_DUPLICATE / SAME_KEY_EXTENSION（逐成员判定，组锚点不取决于成员排序） |
| `_apply_dedup_create_fold`(:351-407) | `_apply_episode_update` 的 folded_only 路径(:1693-1800；folded_only → `CHANGE_BASIS_EPISODE_FOLDED` :1787-1788) | 上游折叠=并入 LLM 合并文本；本仓折叠=纯证据并集、正文段不重复（确定性，无信息丢失面更保守） |
| `_TemporalBounds.merged_with`(:250-256) | `_EpisodeBounds.merged_with`(:1140-1144)（类 :1118） | start=min / end=max、None 忽略 —— 逐语义 |
| `_aggregate_source_fields`(:832-854) | 时间聚合 → `_EpisodeBounds.of_signals`(:1133-1138)；tags 继承/并集 → `_participants_meta`(:1519-1541) | **注意**：formation.py 模块 docstring（更正前 :45）原把目标写作 `_aggregate_episode_fields` —— 该名义符号**不存在**，实际承载为上述两处（docstring 名陈旧，以本条目为权威对照）；「无来源信息不造时间戳」(:843-844) 语义保留（time_bucket=UNKNOWN 不落 occurred_at） |
| `_filter_live_source_memories`(:629-650) | `_filter_live_source_events`(:1157-1182) | 上游 `FOR SHARE` 行锁 → SQLite 单写者 + 同事务存在性检查 + unified_source_objects DELETED 屏障（存储替换） |
| `_sources_changed_since_read`(:653-674) | `_sources_changed`(:1185-1221) | 上游信号=来源行 `updated_at`（编辑必翻动、整理记账不动）；本仓信号=lifecycle != ACTIVE + 同源对象更晚版本事件（编辑=新 revision 新事件）；「读取后被编辑 → 丢弃旧读重算」语义保留 |
| `_process_memory_batch`(:2263-2674) 编排 | `form_observations`(:1853-1945) | 确定性等价：信号抽取+活来源过滤 → 批内精确重复折叠（exact-text guard :2502-2528 → :1886-1895）→ (topic, 时间桶, participants) 分组 → 逐组三分支 |
| `_apply_update_action`(:2752-2883) | `_apply_episode_update`(:1693-1800) | 来源集合有序去重合并（:2816 `dict.fromkeys` 形状 → :1723）；时间界只放宽（merged_with）；参与者/tags 并集（:2819-2822 `existing | source` → :1754 全 signals 并集）；pre-update 快照（observation_history :2704-2749）→ `unified_record_revisions` 事实行（prev_revision + change_basis） |
| `_apply_create_observation`(:3367-3433) | `_apply_episode_create`(:1604-1690) | 活来源过滤后为空 → skip sources_deleted（:3403-3405 → :1621-1624）；每来源只计一次 proof_count（:3406-3408 → live_set 去重 :1625-1628、`evidence_count` :1651）；tags 继承来源 → participants/role 并集 |
| memory_engine.py `retain`(:6326) / `retain_async`(:6357) / `retain_batch_async`(:6405) | **无符号搬运**（closure）；写入后触发整理的编排对应本仓 `sources.observe_batch` → FORMATION job 入队（service/unified/sources.py:333-360） | retain 批量形状（一批一事务、批次切块）由 observe 批 + job 队列承载 |

### 未搬运（如实登记）

1. `service/unified/dependencies.py`（04_source_locks S02 target 之一）**未建**：
   S02「mental-model 派生知识」在本波无对应物（T04.1 只做确定性事件形成）；
   依赖传播算法属 UM08。`unified_dependencies` 表的现有读写来自 T03.3
   corrections（formation.py:937-939），与 S02 无涉。
2. LLM / embedding 依赖全部不搬（任务书：确定性为主，无模型依赖）：
   `_dedup_adjudicate` 的 LLM merge/keep 裁决、`_DEDUP_TOP_K`(:141-144)
   embedding 近重复召回、observation_history 的 LLM merged_text —— 以
   确定性三分支 + 逐字精确重复判定替代（措辞有差即信息有差，不猜同义）。
3. `_duplicate_create_target` 的 update-in-same-response 分支（:134-135）
   未搬运（该问题形态在无 LLM 响应中不出现；同 key 分组扩展覆盖）。
4. Oracle 分支（COALESCE 包装 :226-233）不适用（SQLite）。
5. formation.py 模块 docstring（更正前 :45）原把聚合目标写作 `_aggregate_episode_fields`
   （名义符号不存在）；本次收尾已将 docstring 更正为实际承载
   （`_EpisodeBounds.of_signals` + `_participants_meta`），与上表一致。

### 目标侧新符号（接线，本仓扩展）

- `migrations/0026_unified_episode_formation.sql`：episodes.episode_key UNIQUE、
  形成侧列（origin / generation_run_id / start_at / end_at / extra_json 扩展）。
- `formation.py`：`episode_key_of`(:1327-1340，(subject, topic, 时间桶, 显式
  participants) 幂等键)、`episode_id_of_key`(:1343-1345)、`_episode_signal`
  (:1281-1324，确定性信号抽取；DELETE/UNKNOWN 时间的处理)、`_episode_segments`
  (:1387-1461，CALL/RESULT 成对)、`_pending_of`(:1464-1478，悬空 CALL)、
  `_episode_verification`(:1591-1601，VERIFIED 需 ATLAS_VERIFICATION 证据)、
  `form_observations` / `process_batch` / `run_formation_worker` /
  `mark_stale_for_source`、`FORMATION_WATERMARK_PREFIX`(:1088)。
- `api.py`：`GET /v1/unified/timeline`(:346-365)；`repository.timeline`
  （KNOWN 升序 + unknown 分组 + cursor 稳定偏移分页 + start/end/entity 过滤）。

### 改动理由（为何是 ADAPT 而非照抄）

1. 无模型依赖：上游整理由 LLM 决定 create/update/merge；本仓 T04.1 判定
   全确定性（topic/participants 从结构化字段抽取，无显式主题时 raw: 前缀键
   —— 逐字重复才同键），LLM 概括留 T04.3。判定语义（活来源过滤、来源变化
   丢弃重算、时间界合并、来源集去重合并、每来源计一次）逐条保留。
2. 存储替换：SQLite episodes 表 + unified_source_objects 版本语义替代
   asyncpg/PostgreSQL（FOR SHARE、LEAST/GREATEST、observation_history 表
   → unified_record_revisions 事实行）；§8 防自我循环：generation_run_id
   如实登记「无模型运行」（unified-formation:deterministic:v1）。
3. 验证纪律：上游不约束观察可信度；本仓 VERIFIED 必须有 ATLAS_VERIFICATION
   来源证据（对齐 episode_ingest §4），助手自述完成永不自证。

### parity 测试与结果（2026-10-06，service/.venv；tests/unified_memory/test_daily_episode.py）

- `::test_parity_norm_text_matches_hindsight_on_fixed_samples` —— 8 组固定
  样本，`_norm_episode_text` ≡ 上游 `_norm_obs_text`(:110-118，测试内逐语义
  参考副本)。**通过**。
- `::test_parity_duplicate_create_target_matches_hindsight_on_fixtures`
  —— 8 组固定样本（精确重复/空白折叠/措辞有差/新事件），shown-observation
  分支 ≡ 上游 :121-139；update-in-same-response 分支偏离显式断言在案。**通过**。
- `::test_parity_temporal_bounds_merge_matches_hindsight_on_fixtures`
  —— 6 组固定样本，`_EpisodeBounds.merged_with` ≡ 上游 :250-256
  （start min / end max / None 忽略）。**通过**。
- `::test_parity_episode_decision_tree_matches_hindsight_semantics`
  —— 8 组固定样本（精确重复×2 / 同 key 扩展×3 / 新事件×3，注释逐条标来源
  行号：consolidator.py:2502-2528 + prompts.py RULES 1/9），决策输出与
  形成路径同树（receipt action + change_basis 双断言）。**通过**。
- 套件：`pytest tests/unified_memory -q` → **163 passed**；
  旧套件 `pytest tests --ignore=tests/unified_memory
  --ignore=tests/test_graph_conservative.py -q` → **74 passed**（基线不回退）。

### 已知边界 / 未尽事项

- LLM 概括（topic 归并、narrative 摘要）留 T04.3；当前无显式主题的观察走
  raw: 逐字精确重复语义（保守：措辞有差即新事件，不强行归并）。
- 「N 个月前」等相对词时间桶仍 UNKNOWN（T03.2 temporal 边界不变）。
- 来源 DELETE 只如实标 stale 依据（ALL_SOURCES_DEAD / PARTIALLY）；
  删除传播/失效算法属 UM08。
- timeline 的 entity 过滤只认**出现过**的参与者（角色/显式姓名），不做
  个性化推断。

---

## S03 TiMem — UM04 / T04.3 日/周概括、知识与可回溯总结（2026-10-06）

- 仓库：<https://github.com/TiMEM-AI/timem>；固定 commit：
  `6d279a5f5d40ee229e1995df15c182cb2062c71c`；许可证：**Apache-2.0 + MIT
  (directory specific)**（LICENSE 原文：core engine（timem/, storage/, llm/ 等）
  Apache-2.0；tools/, cloud-service/, docs/ 为 MIT。本条目搬运的 timem/ 目录
  文件适用 Apache-2.0；LICENSE SHA256（LF）=
  `f8e7b0eb7de5c9b9b487ed04650893c196d59ce9d390f676dccda65f5f208edc`。
  本仓未整体复制任何上游文件，均为 ADAPT 后的独立实现；上游提示词文本按
  Apache-2.0 搬运并以本登记 + consolidation.py 出处注释满足归属）。
- 方式：ADAPT；波次：UM04（本条目）；**检索面（memory_retrieval.py /
  llm_retrieval_planner.py）属 UM07 / T07.1，本波只做 closure 阅读未搬运**
  （见「偏差」）。目标：`service/unified/consolidation.py`（新）、
  `service/unified/dependencies.py`（新，04 锁定清单 S02 曾列名、本波建成）、
  `service/compaction.py`（最小扩展）。
- 三层产品视图（02_wave_tasks T04.3：保留源函数职责，不强制五个独立数据库）：
  L1 fragment → 原子事件 EPISODE（formation T04.1 承载）；L2 session 并入
  DAY 层；L3 daily → DAY 日概括；L4 weekly → WEEK 周概括；L5 high-level →
  LONG_TERM 长期理解。
- 来源原始副本（仅差分用）：`work/um04_t04_3/timem_src/`
  （raw.githubusercontent.com 按 commit 抓取，LF 行尾；三个锁定文件 CRLF
  变换后与 04_source_locks.json 逐一相符 —— 即与 04 锁定值同一字节内容）。
- 集成证明（实际调用方，如实登记）：
  - `tests/unified_memory/test_summary_provenance.py` —— 本波调用方（进程内
    + TempSvc 真服务全链路）。**生产 HTTP 触发路由未接线**（§6 的
    POST /v1/unified/maintenance job 或专用路由属后续波；本波不宣称已上线
    生产链路 —— api.py 不在本任务文件所有权内）。
  - `service/compaction.py` `upsert_summary_compact_unit` —— 概括提交同事务
    写 compact_units（由 consolidation.record_summary 调用）。
  - `service/unified/dependencies.py` —— consolidation 提交路径的依赖快照
    写入方；frontier 判定供 T08.2 传播复用。
  - facet=SUMMARY 经 `repository._memory_to_record`（既有投影，零改动）自动
    可读：`GET /v1/unified/records?facet=SUMMARY`（extra.unified.facet /
    dependencies 投影）—— 判据测试原样通过。

### 锁定入口文件（03 清单点名；SHA256 同时给出抓取 LF 行尾值与 04 锁定值）

| 来源文件 | SHA256（LF，work 副本） | SHA256（04 锁定值 = CRLF checkout） | 核验 |
| --- | --- | --- | --- |
| timem/memory/memory_generator.py | `21582b6b0350cbac662021c7e0156c90e8340c2416ce969f3e769813e585faa0` | `870bfaa2d243eefad3cd685c03be5010b6f9d3dd310606af31ea0c46a5204452` | ✓ 与 04 锁定相符 |
| timem/workflows/memory_retrieval.py | `fe15dc97c472f3584a77ec71a57f0deebc3dc93c4bcc5dcafdbc2dc293e1bc3f` | `247c5c1ff7c45874fcbc1219f07f92ae2c6bb95b6b0ee25f566ffdedd14324a0` | ✓ 与 04 锁定相符（closure 阅读，未搬运） |
| timem/workflows/retrieval_nodes/llm_retrieval_planner.py | `9c560aac4e3f39e962502c405b372afdbfa14eaa42725ca23a619a54d7b5c162` | `3f4792ee519ecb144f197f2f48ebf90c3469362663f6faf332e528c6700676f9` | ✓ 与 04 锁定相符（closure 阅读，未搬运） |

### 依赖闭包（03「施工时必须补齐的依赖文件」点名的 prompt_manager / prompts.yaml 逐文件读取与登记）

| 来源文件（commit 6d279a5） | SHA256（LF） | 读取用途 |
| --- | --- | --- |
| config/prompts.yaml | `f293ea3a9c8e468b0ca950e7ebe02d03d5640047027d5e319c9a17d855b6885a` | l1_fragment_summary(:3-26) / l2_session_summary(:29-51) / l3_daily_summary(:53-85) / l4_weekly_summary(:87-120) / l5_high_level_summary(:122-166) **提示词原文搬运**进 consolidation.PROMPTS；query_complexity_analysis(:168-188) 属检索 planner（未搬运，closure） |
| timem/utils/prompt_manager.py | `93362bd61073b63a5a5abf215599d11fe35079b42888deaca1163e746397dea5` | PromptManager 单例(:15) / get_prompt 键查+语言回退(:71-122) —— 本波以模块级 PROMPTS dict + LEVEL_PROMPT_KEY 等价承载（不引 langchain 依赖） |
| timem/memory/l3_daily_memory.py | `502b67cda5641dd3d02859130a92ec6abbf5b096c50c156cb9a189c32f42fc0a` | add_session_memory 缓冲+按时间排序(:74-100，:93)+触发；_generate_daily_memory 日桶键(:158)/近期窗口(:111) |
| timem/memory/l4_weekly_memory.py | `e44f97a868bad70d142ad30aa46378ea8aef415ebe71bab39849af71f37357e0` | add_daily_memory(:77-102)；_generate_weekly_memory 周窗=最早日锚定(:141-145)+6 天跨度(:145)；generate_weekly_memory_with_history 渐进上下文(:451+，近 3 条历史 :508) |
| timem/memory/l5_high_level_memory.py | `8c0a2283c8326a967d7565ec77a2ceb3f024b3d4d150b9144273d13526c82fc6` | UserDeepProfile / HighLevelMemoryType 结构（closure；长期理解输出形状参考） |
| timem/workflows/memory_generation.py | `6af83f381d22c891e9a9a28609c0108d3e260020b85edceb5a87f63d352a27c4` | MemoryGenerationWorkflow 编排（L1→L5 触发次序 closure；本波编排=generate_summary 单层显式入口） |
| timem/workflows/nodes/layer_memory_generator.py | `7e67a92641dca374c8a70efb7c8831a7d0560e206f379dcce224db267520695b` | 逐层生成节点（closure；generate_fn 注入位对应） |
| timem/utils/config_manager.py | `7676654f9557410bc62053e4bdf170d1a7c31862057e0aec1f269a19c7e77a5b` | prompt_manager 的配置来源（closure；本波无新配置文件） |
| LICENSE | `f8e7b0eb7de5c9b9b487ed04650893c196d59ce9d390f676dccda65f5f208edc` | 许可证核验（双许可结构；timem/ = Apache-2.0） |

### 搬运对照（来源 file:symbol → 目标 file:symbol，行号为该 commit 原文）

| 来源（timem @ 6d279a5） | 目标（service/unified/consolidation.py 除注明外） | 改动 |
| --- | --- | --- |
| memory_generator.py `generate_l1_content`(:449) prompt `l1_fragment_summary` | 职责由 formation（T04.1）承载：对话→原子事件 EPISODE；PROMPTS["l1_fragment_summary"] 模板保留给 LLM 增强波 | 三层产品视图适配（不重复生成 L1） |
| memory_generator.py `generate_l2_content`(:572) prompt `l2_session_summary`，fragment_summaries="Fragment i:"(:616) | 并入 DAY 层（同日多 session 一次聚合）；模板保留 | 同上 |
| memory_generator.py `generate_l3_content`(:832)：session_summaries="Session i:"(:875)、format(date, session_summaries, previous_daily_memories)(:886-890)、渐进 previous(:878) | `build_prompt`("DAY") 逐参对应；`previous_content`=既有概括旧文本（重算时渐进上下文） | 提示词原文搬运（PROMPTS["l3_daily_summary"]） |
| memory_generator.py `generate_l4_content`(:986)：daily_summaries="Daily Report i:"(:1015)、format(year, week_number, week_start, week_end, daily_summaries, previous_weekly_memories)(:1037-1044)、周一起点公式(:1026-1034) | `build_prompt`("WEEK") + `week_start_from_iso`（公式逐行搬运）+ `week_start_of`（ISO 归一） | 同上；W1 边界（公式落前一年周一）如实保留 + parity 断言 |
| memory_generator.py `generate_l5_content`(:1118)：expert_memories="Weekly Report i:"(:1147)、format(year, month, month_name, month_start, month_end, expert_memories, previous_monthly_memories)(:1176-1184) | `build_prompt`("LONG_TERM") 逐参对应 | 同上 |
| l3_daily_memory.py 日桶 `day_key`(:158)、按 session_start 排序(:93)、触发窗口(:96-98,:111) | `day_of` / `group_by_day`（UTC 日桶 = episode 形成层 time_bucket 同基；桶内 (start, ref) 稳定排序） | 存储替换：内存缓冲 → 快照函数（生成时点显式输入） |
| l4_weekly_memory.py 周窗=最早成员日(:141-145)+6 天(:145)、缓冲排序(:93) | `week_window_from_days` / `normalize_period`("WEEK") | 同上 |
| l3/l4 的重要性/模式分析（_calculate_daily_importance、_analyze_interaction_patterns 等） | `notable_of`（重要少见信息：期内频次=1 的主题/参与者 —— 确定性承载，不交给模型猜） | 上游该职责在 LLM 提示词维度里；无 LLM 下以显式结构字段承载 |
| memory_generator.py `_ensure_prompts_loaded`(:100)/关键提示词检查(:107-110) | build_prompt 缺占位符 → format 即失败（不静默降级）；parity 测试断言模板原文段存在 | 存储替换：模块常量（无运行时 YAML 加载） |
| memory_generator.py `_is_generic_content`(:710)/`_get_enhanced_l2_prompt`(:767)/`_add_content_warning`(:804) | 未搬运（LLM 输出质量护栏）；确定性 fallback 以 DEGENERATE_TEXT=true 标注替代「通用内容检测」问题面 | 未搬运（如实登记） |
| memory_generator.py 流式/重试（chat_stream、_retry_with_exponential_backoff :189-412） | 未搬运；generate_fn 由调用方注入（重试/流式是 provider 职责） | 接线归属 Atlas ModelManager（后续波） |
| **来源版本校验闭环**（03 任务面；S02 Hindsight `_sources_changed` :653-674 语义已在 formation.py:1185-1221 搬运） | `stale_reasons`（快照 diff + formation._sources_changed / _filter_live_source_events 复用）+ generate_summary 丢弃重跑循环 + 提交前事务内终验 | 「生成后到提交前源版本变了→丢弃过时结果重跑」逐语义 |
| memory_retrieval.py `MemoryRetrievalWorkflow`(:37)/`_llm_retrieval_planner_wrapper`(:348)/`_route_retrieval_strategy`(:556)；llm_retrieval_planner.py `LLMRetrievalPlanner`(:27)/`analyze_query_complexity`(:185)/`_parse_complexity_response`(:256) | **未搬运**（检索规划属 UM07 / T07.1；parity 测试显式断言本模块无 planner 符号） | 波次边界（03 锁定注明 UM04;UM07） |

### 目标侧新符号（接线，本仓扩展）

- `service/unified/consolidation.py`：PROMPTS / LEVEL_PROMPT_KEY（提示词搬运）、
  `normalize_period` / `day_of` / `week_start_of` / `week_start_from_iso` /
  `group_by_day` / `week_window_from_days`（时间窗切分）、`snapshot_inputs` /
  `current_heads`（输入快照）、`build_prompt`、`degenerate_generate_fn`
  （DEGENERATE_TEXT=true 标注 + §8 如实 generation_run_id）、
  `generate_summary`（生成入口：快照→生成→重扫丢弃→事务内终验→提交）、
  `record_summary`（提交：memories extra.unified.facet=SUMMARY 行 +
  unified_dependencies 全量 DERIVED_FROM 快照 + unified_record_revisions
  change_basis='SUMMARY' + compact_units 投影）、`unresolved_conflicts_in_window`
  / `notable_of`（每层必含：未决冲突 / 重要少见信息）、`check_summary_freshness`
  / `mark_stale_summaries`（溯源与 stale 重算标注）。
- `service/unified/dependencies.py`：`add_dependency`（0024 表直 SQL、六元组
  幂等）/ `parents_of` / `children_of` / `delete_frontier` /
  `dependency_frontier` / `compare_frontier`（纯函数）/ `check_frontier`
  （VALID|STALE + changed_refs；T08.2 完整传播的判定基础）。
- `service/compaction.py`（最小扩展）：`summary_compact_unit` /
  `upsert_summary_compact_unit`（kind 复用 EPISODE_SUMMARY —— 0015 CHECK 约束
  不动 schema，偏差在案）；新增常量 SUMMARY_ORIGIN。
- **无新 migration、无 api.py/repository.py/sources.py/formation.py 改动**
  （文件所有权边界；全部经既有接口投影/复用）。

### 偏差与未尽事项（如实登记）

1. **检索 planner 不搬运执行**：memory_retrieval.py / llm_retrieval_planner.py
   已真读并核验 SHA256，但属 UM07 / T07.1（查询规划）；本波生成面只留
   generate_fn 注入位。parity 测试
   `test_llm_planner_not_ported_deviation_recorded` 显式锁定该边界。
2. **LLM 生成接线留偏差**：generate_fn 的模型适配（接 consolidator worker 的
   ModelManager 配置路径）未接线；本波默认确定性 fallback（DEGENERATE_TEXT=true
   显式标注，不冒充模型概括）。prompt 文本已搬运可用。
3. **compact_units kind 复用 EPISODE_SUMMARY**：0015 的 kind CHECK（SQLite 不
   支持 ALTER CHECK）未含 DAY/WEEK 档位；schema 不动（无新 migration 属所有权
   边界），层档位在 title / extra.unified 层承载。
4. **sources/change(DELETE) → 概括 stale 的一行接线未做**：sources.py 不在本
   任务所有权内（且 T04.2 并行开发中）。行为函数
   `mark_stale_summaries(source_kind, source_object_id)` 已提供，并有真实
   sources/change DELETE 之后的进程内 + HTTP 测试（标注断言）；一行调用挂接
   随 sources.py 属主波次 / UM08 传播接入。
5. **生产 HTTP 触发路由未接线**：生成入口为 service 函数（generate_summary）；
   §6 maintenance job / 专用路由属后续波。集成证明如实登记为测试 + 投影读取
   路径（facet=SUMMARY 经既有 repository 投影零改动可读）。
6. **「学到的概念/知识与用户经历互联」半边**：概括一律 INFERRED（不冒充亲历）、
   原文经 episode source_refs 始终可回看；外部知识来源（THIRD_PARTY）的独立
   KNOWLEDGE facet 管线属后续波。

### parity 测试与结果（2026-10-06，service/.venv；tests/unified_memory/test_summary_provenance.py）

- `::test_dependencies_add_query_and_frontier` —— add_dependency 幂等（六元组
  唯一）/ 非法 relation 422 / parents_of / children_of / 前沿 VALID→STALE
  （翻版、缺失两路）+ 纯函数与存储读写一致。**通过**。
- `::test_parity_window_splitting_matches_timem_on_fixed_sample` —— 固定样本
  3 天×2 事件：日桶 ≡ l3_daily_memory.py:93/:158（测试内逐语义参考副本）；
  周窗 ≡ l4_weekly_memory.py:141-145（最早日锚定 +6 天）；周一公式 ≡
  memory_generator.py:1026-1034（5 组 (year, week) 样本 + ISO 归一幂等）。
  **通过**。
- `::test_parity_layered_aggregation_shape_matches_timem` —— 分层聚合输入列表
  形状 ≡ memory_generator.py:875/:1015/:1147（Session i / Daily Report i /
  Weekly Report i）；占位符装配 + 层→提示词键映射。**通过**。
- `::test_three_level_generation_inputs_conflicts_time_range` —— 3 天事件 →
  日概括 3 条 + 周概括 1 条 + 长期理解 1 条；每层含全量输入 refs
  （revision>=1）、期内 UNRESOLVED 未决冲突（双方 refs + missing_evidence，
  上卷不丢失）、时间范围；unified_dependencies 全量 DERIVED_FROM；溯源链
  LONG_TERM→WEEK→DAY×3 全部 VALID。**通过**。
- `::test_summary_regenerate_updates_revision_and_frontier` —— 重放
  DUPLICATE_OK 零写入；输入翻版 → 前沿 STALE → 重算 UPDATED revision+1、
  前沿重写、事实行 change_basis='SUMMARY'；compact_units 投影存在。**通过**。
- `::test_source_changed_before_commit_discards_and_recomputes` —— 竞态构造：
  生成 fn 内落新版本 → 丢弃重跑，提交的是新版本快照（依赖 parent_revision=2）；
  持续不稳 → DISCARDED_UNSTABLE、过时结果一律不提交。**通过**。
- `::test_source_delete_marks_summary_stale_and_regenerates` —— 真实
  sources/change DELETE → mark_stale_summaries ALL_SOURCES_DEAD；
  check_summary_freshness STALE（SOURCES_DEAD）；幂等重放零标注。**通过**。
- `::test_summary_preserves_dependency_versions`（svc）—— **任务书判据原样**：
  `GET /v1/unified/records?facet=SUMMARY` 的 dependencies 每项 revision>=1，
  且全量可回指输入 episode refs（relation=DERIVED_FROM + content_hash）；
  content.input_refs / time_range / epistemic_kind=INFERRED 投影可见。**通过**。
- `::test_http_observe_then_week_summary_with_conflict_and_stale`（svc）——
  真服务全链路 3 天 → 日 3 + 周 1；冲突上卷；HTTP DELETE 后
  SOURCES_PARTIALLY_DELETED。**通过**。
- `::test_llm_planner_not_ported_deviation_recorded` —— planner 不搬运执行
  的边界锁定断言。**通过**。
- 套件：`pytest tests/unified_memory -q` → **191 passed**（163 基线 + 本任务
  10 + 并行 T04.2 的 18；T04.2 并行开发中，以完成时刻全量绿为准）；旧套件
  `pytest tests --ignore=tests/unified_memory
  --ignore=tests/test_graph_conservative.py -q` → **74 passed**（基线不回退）。

### 已知边界 / 未尽事项

- L1/L2 提示词模板已搬运但无调用方（对应职责在 formation / 并入 DAY）；LLM
  增强波接线。
- check_frontier 的「heads 多出新依赖 ref 不判变」是 T04.3 保守语义；「出现新
  输入应重算」由生成方全量窗口重扫负责，T08.2 如需反向判定可扩展纯函数。
- LONG_TERM 层要求显式 start/end（不隐式猜长期范围）；自动滚动窗口属维护波。

## S03 TiMem — UM07 / T07.1 检索 planner（query_planner.py，2026-10-06 追加）

- 本小节是上文 S03 生成段「偏差 1（检索 planner 不搬运执行）」的**后续完成
  登记**：UM07 / T07.1 把锁定文件中的查询规划面搬运为
  `service/unified/query_planner.py`（ADAPT），并接入
  `service/unified/retrieval.py` 的多路检索编排。仓库与 commit 同生成段
  （`6d279a5f5d40ee229e1995df15c182cb2062c71c`；许可 Apache-2.0，timem/ 目录）。
- 来源原始副本（仅差分用）：`work/um07_t07_1/timem_src/`（raw.githubusercontent.com
  按 commit 抓取，LF 行尾；锁定文件与 04_source_locks.json 逐一相符）。

### 锁定与依赖闭包文件（SHA256：抓取 LF 值 = 04 锁定 CRLF 值）

| 来源文件（commit 6d279a5） | SHA256（LF，work 副本） | SHA256（04 锁定值 = CRLF checkout） | 用途 |
| --- | --- | --- | --- |
| timem/workflows/retrieval_nodes/llm_retrieval_planner.py | `9c560aac4e3f39e962502c405b372afdbfa14eaa42725ca23a619a54d7b5c162` | `3f4792ee519ecb144f197f2f48ebf90c3469362663f6faf332e528c6700676f9` | **搬运主体**：analyze_query_complexity / _parse_complexity_response / QueryComplexityConfig |
| timem/workflows/memory_retrieval.py | `fe15dc97c472f3584a77ec71a57f0deebc3dc93c4bcc5dcafdbc2dc293e1bc3f` | `247c5c1ff7c45874fcbc1219f07f92ae2c6bb95b6b0ee25f566ffdedd14324a0` | wrapper 失败降级语义 / 复杂度→category/strategy 映射（closure 阅读 + 语义搬运） |
| timem/workflows/retrieval_nodes/\_\_init\_\_.py | `490538fe4d607ac4504e347721a0c90986d037a99c48f2fa1deba81ea8c79525` | —（非锁定） | 依赖闭包确认（同目录节点清单） |
| config/prompts.yaml | `f293ea3a9c8e468b0ca950e7ebe02d03d5640047027d5e319c9a17d855b6885a` | —（非锁定） | `query_complexity_analysis`(:168-188) **提示词原文搬运**进 query_planner.QUERY_COMPLEXITY_ANALYSIS_PROMPT |
| timem/utils/prompt_manager.py | `93362bd61073b63a5a5abf215599d11fe35079b42888deaca1163e746397dea5` | —（非锁定） | 闭包（get_prompt 键查；本仓以模块常量等价承载，同生成段决策） |

### 搬运对照（来源 file:symbol → 目标 file:symbol，行号为该 commit 原文）

| 来源（timem @ 6d279a5） | 目标（service/unified/query_planner.py） | 改动 |
| --- | --- | --- |
| llm_retrieval_planner.py `analyze_query_complexity`(:185-254)（prompt :203-208、重试循环 :200-254） | `analyze_query`（确定性复杂度门 bypass → 有 generate_fn 时**至多一次**调用 → 失败回退保留原因） | max_retries=20 线性退避收敛为 1 次调用（02_wave_tasks T07.1「复杂组合至多一次 planner」）；LLM 实例初始化(:51-122) 换成注入的 `generate_fn`（Atlas 模型接口归 Atlas，不新增第二套模型管理；默认 None → 确定性 fallback，不冒充模型结果） |
| llm_retrieval_planner.py `_parse_complexity_response`(:256-331) | `parse_analysis`（JSON 提取校验 :270-298 → 传统解析 :300-323 → 末位 ValueError :325-329） | 逐语义搬运（含关键词 strip+lower 清洗 :294-296、描述词兜底 :316-323；传统解析恒归 0/1/2 下末位 raise 为防御性路径，如实搬运不编造抛出） |
| llm_retrieval_planner.py `QueryComplexityConfig`(:477-495) + category/strategy 映射(:230-239) | `COMPLEXITY_SIMPLE/MIXED/COMPLEX` + `CATEGORY_MAP`/`STRATEGY_MAP` | 常量等价承载 |
| memory_retrieval.py `_llm_retrieval_planner_wrapper`(:348-419)（失败 → errors 累积、降级继续 :414-419） | `analyze_query` 的 `PLANNER_FAILED:<type>:<msg>` note + 回退确定性计划 | 失败原因写进 QueryPlan.note 并进 recall trace/completeness（保留原因可查） |
| memory_retrieval.py 复杂度→query_category(:381-383) | `CATEGORY_MAP` + QueryPlan.category | 同上 |
| memory_retrieval.py `_route_retrieval_strategy`(:583-589)（complexity→simple/hybrid/complex） | `STRATEGY_MAP` + QueryPlan.strategy | 同上 |
| prompts.yaml `query_complexity_analysis`(:168-188) | `QUERY_COMPLEXITY_ANALYSIS_PROMPT`（`{question}` 占位同构） | 提示词原文搬运（Apache-2.0；本登记 + 模块出处注释满足归属） |
| —（T07.1 任务面新增） | `decompose_query` / `classify_complexity`（时间/实体/主题三维 + 深层个性化/多片段/组合分段确定性分类；与源提示词三档定义 :170-174 对齐） | 无 LLM 时的确定性 fallback：中文 bigram + ASCII 词复用 recall.query_terms；普通精确/时间查询（单片段）→ bypass 直通无 planner |

### 接线（retrieval.py，本波新文件；只读复用既有通道不改其内部）

- `retrieve(conn, ctx, request)` —— §5 流水线：query_planner 计划 → 通道
  （精确 / 时间窗 / 全文 recall.py 打分（memories 经
  hybrid_recall.lexical_shadow_candidates，原始 OBSERVATION 证据同规则评分）/
  语义 semantic_recall READY 队列 / 工作焦点 working_set.attend（仅
  CONTINUE_TASK））→ RRF 融合（复用 hybrid_recall.rrf_fuse 纯函数）→
  生命周期/适用性回查（lifecycle.can_transition 转移合法性；SUPERSEDED/
  INVALIDATED/CONFLICTED/ERASED 不进 context_items，CONFLICTED 双方进
  conflicts[]）→ 冲突（T03.3 open_conflicts）→ 多样性排序（relevance 头位 +
  facet 轮转每类限流 + purpose 偏序）→ token 预算装配 → read receipt 写
  unified_read_receipts（read_id/assembled/context_hash）+ audit trace。
- fallback_mode 判据：向量故障（注入 fault / 有 READY 索引查询失败）→
  `RAW_OR_FTS` 且全文照回；向量/图未接线（部署基线）→ `LOCAL_DETERMINISTIC`；
  语义通道真实参与 → `HYBRID_RRF`；deadline 超时 / 全故障 → 空结果 +
  missing_evidence 明确（不假成功）。
- `service/semantic_recall.py` 故障注入（T07.1 授权的最小改动）：模块级
  `_VECTOR_FAULT`（默认关；`MEMORYOS_VECTOR_FAULT=1` 或 `set_vector_fault()`
  可开）+ `semantic_candidates` 入口 2 行检查，合计 8 行。
- `service/unified/api.py` 唯一改动：POST /v1/unified/recall 从
  repository.recall 切到 retrieval.retrieve（repository.recall 保留为内部
  基线函数）。

### parity 与测试（tests/unified_memory/test_hybrid_retrieval.py）

- `::test_planner_parity_fixed_queries` —— 固定 4 组查询与源语义一致（注释引
  行号）：单片段时间/事实查询 → 0/FACTUAL/simple（prompts.yaml:170）；
  活动整合 → 1/MIXED/hybrid（prompts.yaml:171）；偏好倾向深层个性化 →
  2/INFERENTIAL/complex（prompts.yaml:172 + memory_retrieval.py:381-383）；
  parse_analysis 的 JSON 提取/关键词清洗/描述词兜底/非法档位降级逐语义
  （llm_retrieval_planner.py:256-331）。**通过**。
- `::test_exact_query_bypasses_planner_and_complex_uses_once` —— 精确查询
  bypass 零调用；复杂组合恰一次调用（generate_fn 记录）；无 generate_fn
  确定性回退；planner 异常回退保留原因。**通过**。
- `::test_vector_failure_has_evidence_fallback` —— **任务书判据原样**（隔离
  服务进程注入 MEMORYOS_VECTOR_FAULT=1）。**通过**。
- `::test_stale_vector_index_filtered_and_semantic_fusion` —— 陈旧 READY 索引
  中的 SUPERSEDED 记录被生命周期回查拒绝（rejected 留因）；语义通道真实参与
  → HYBRID_RRF；语义独有命中进装配面。**通过**。
- 其余：基线模式不变（LOCAL_DETERMINISTIC 兼容面）、purpose 多样性（
  CONVERSATION vs CONTINUE_TASK + 每类限流）、撤回过滤与冲突明示、预算截断、
  deadline 带原因 fallback、read receipt 落表 + recall 零证据写入。**通过**。
- 套件：`pytest tests/unified_memory -q` → **267 passed**（256 基线 + 本任务
  11）；旧套件不回退（见任务报告）。

### 偏差与未尽事项（如实登记）

1. **planner 的模型接线留偏差**：retrieve 默认不注入 generate_fn（Atlas 模型
   接口属后续波）；复杂组合查询当前走确定性 fallback（计划如实标注
   planner_source=deterministic + note，不冒充模型结果）。generate_fn 注入位
   与提示词原文已就绪。
2. **max_retries 收敛**：上游 :200-254 的 20 次线性退避收敛为 1 次调用 ——
   T07.1 任务面「至多一次 planner」；重试属 provider 职责（与生成段偏差 2 同
   语义）。
3. **传统解析的防御性 raise**：源 :325-329 在传统解析恒归 0/1/2 的实现下不可
   达（死代码）；逐语义搬运保留该结构，测试如实登记其行为而非编造抛出。

## S05 M3-Agent — UM05 / T05.2 多模态节点与人物/物品联系（2026-10-06）

- 上游：[M3-Agent](https://github.com/ByteDance-Seed/m3-agent) @ `0e3e41939bd8a0b66d756e7b7eb8d5fe9992da5c`
  （Apache-2.0）；方式 ADAPT；目标 `service/unified/multimodal.py`（新）+
  `graph_types.py`/`graph_store.py`（最小扩展）+ Atlas `core/atlas/memory/
  multimodal_bridge.py`（新，媒体导入桥）。
- 上游快照：`work/um05_t05_2/m3agent_src/`（raw.githubusercontent 逐文件抓取）。

### 锁定入口文件（04_source_locks.json S05；SHA256 同时给出抓取 LF 行尾值与 04 登记值）

- `mmagent/videograph.py` —— LF `ce289bbb8b066b9fa64a9982ad5565854c334713628006039be295d4f8520a81`；
  **04 登记（CRLF 行尾形态）`80b4aa8adc5867f90530e636ce70a4d7cfc89c0e71cfceb69eaf5c13e141f613` ✅**（内容逐字节一致，仅行尾差异）。
- `mmagent/retrieve.py` —— LF `c1f12ea1da7c71ed09c65d2b65af33927084bc7b05df9f5db304c82251adefd5`；
  **04 登记（CRLF）`1571169038f40b5766376cfdd2f4096c8dd063ca460d9f036a4ae016bec45ff7` ✅**。

### 依赖闭包（videograph/retrieve 的 import 闭包逐文件读取与登记）

- `mmagent/memory_processing.py`（`parse_video_caption` / `process_memories` /
  `insert_memory` / `generate_full_memories` / `generate_video_context`）—— LF
  `2b17fadd272c034d9207c6b7dbb4664a2ba6a704017b67b225b2ad8b30db35c5`。
- `mmagent/utils/chat_api.py`（`parallel_get_embedding` / `generate_messages` /
  `get_response_with_retry` —— 上游 LLM/embedding 面）—— LF
  `157048dbd9d25a2f49e3de8c2d62df12611ea0a3f9dd27d7e742c7cbe65fae87`。
- `mmagent/utils/general.py`（`validate_and_fix_python_list`）—— LF
  `e132a929bebdc633ad7801c4fc241298be1bb9274e6d3b988501a5a68a2a7685`。
- `mmagent/prompts.py`（检索 action/caption 提示词，仅被未搬运的 LLM 循环引用）
  —— LF `e9967c958b67481e5e0635dcaf3f16df52e1ead8d7433e32417f2c1932a93740`。
- `configs/processing_config.json`（MAX_RETRIES/logging/topk 等）—— LF
  `e57a1dc46735ee1aaca03107cb2c1ec0023ff40873dd0db38ed3ad3646a894ee`。

### 依赖闭包的 NumPy/sklearn/PIL 处置（03 S05「保留或证明等价替代」）

- **NumPy**：服务 venv 有（2.5.3）——稠密 cosine 的 parity 证明用它锁定。
- **sklearn**：服务 venv 无。`sklearn.metrics.pairwise.cosine_similarity` 以
  归一化点积等价替代（数学恒等；`test_cosine_sparse_matches_dense_numpy`
  用 NumPy 稠密实现做 20 组随机向量 parity，abs=1e-12）。`sklearn.DBSCAN`
  只被 `_cluster_semantic_nodes`（argmax/dropout 训练期碰撞模式）引用，
  本仓只搬 eq_only 模式（无需聚类）→ 不引入。
- **PIL/matplotlib**：只被上游调试可视化（`print_faces`/`print_voice_nodes`/
  `visualize`，videograph.py:738-834）与训练上下文拼装
  （`generate_video_context`）引用 → 均不搬运，不引入。

### 搬运对照（来源 file:symbol → 目标 file:symbol；行号为该 commit 原文）

| 上游（videograph.py / retrieve.py / memory_processing.py） | 目标（service/unified/multimodal.py） |
| --- | --- |
| `VideoGraph`（36-61，内存 nodes/edges + pickle 落盘 retrieve.py:430） | `MultimodalGraph`（SQLite 权威证据派生的可重建投影：`build_graph`；零 schema 变更，无第二权威） |
| `VideoGraph.Node`（63-68：id/type/embeddings/metadata） | `ModalityNode`（类型映射 img/voice/episodic/semantic → IMAGE/AUDIO/TEXT(EPISODIC\|SEMANTIC)；VIDEO 为本仓扩展；embeddings → `content_vector` 确定性 shingle 向量，`search_*` 仍接受外部向量） |
| `add_edge`（228-237，双向带权；同类文本禁连） | `MultimodalGraph.add_edge`（同规则原样） |
| `update_edge_weight`（239-251，≤0 删边） | `MultimodalGraph.update_edge_weight` |
| `reinforce_node` / `weaken_node`（253-297） | `MultimodalGraph.reinforce_node` / `weaken_node` |
| `get_connected_nodes`（544-552，类型过滤邻接） | `MultimodalGraph.get_connected_nodes`（sorted 确定性） |
| `search_text_nodes`（554-612，cosine × range_nodes × sum/mean/max/min） | `MultimodalGraph.search_text_nodes`（同形状：向量进相似度出） |
| `search_img_nodes` / `search_voice_nodes`（614-670；阈值 0.3/0.6 见 40 行） | `MultimodalGraph.search_media_nodes`（IMAGE/VIDEO 0.3、AUDIO 0.6；节点向量=关联文本均值，等价派生） |
| `refresh_equivalences`（417-513，并查集 + character_mappings） | `MultimodalGraph.equivalence_groups`（结构等价：携带多 media_refs 的观察即上游 equivalence 语义节点；全序化替代上游 set 序） |
| `fix_collisions(mode='eq_only')`（328-367，voice ≤1 face；随机留一 359-362） | `MultimodalGraph.fix_voice_face_collisions`（确定性：边权和最大 → asset_id 字典序） |
| `parse_video_caption`（memory_processing.py:36-61，`<face_N>` 标签解析+验证） | `parse_node_tags`（`<image:asset-…>/<audio:…>/<video:…>/<person:名字>`；无效引用丢弃不猜，语义原样） |
| `process_memories`/`insert_memory`（memory_processing.py:202-273） | `build_graph` 的观察索引（TEXT 节点 + 按 media_refs 连边） |
| `retrieve_from_videograph` + `get_related_nodes` + `back_translate`（retrieve.py:76-150） | `retrieve`（查询实体/词项 → 种子 → 邻接 BFS ≤2 跳 → 分数截断；等价组即 character 展开对应物） |
| `translate`（retrieve.py:35-48，标签→character 名） | 不搬（无 LLM 标签文本；本仓文本直接来自观察内容） |

### 未搬运（如实登记）

- LLM 记忆生成/检索循环：`generate_full_memories`/`generate_video_context`
  （memory_processing.py:63-200）、`generate_action`/`answer_with_retrieval`/
  `select_queries`/`verify_qa`/`calculate_similarity`（retrieve.py:152-406）——
  关联抽取按任务书为**确定性无 LLM**；LLM 检索规划属 UM07（S06/S07）。
- 评测/训练机制：`expand_route`/`sample_a_route`（随机游走采样）、
  `truncate_memory_by_clip`/`prune_memory_by_node_type`（CLIP 截断）——
  失效语义由证据派生天然给出（撤回/ERASED → 退出重建 → 候选失效）。
- 上游 embedding 模型（text-embedding-3-large，retrieve.py:96）——默认向量
  为确定性 shingle 词频（`content_vector`，复用 identity shingle 语义）；
  活 embedding provider 属 UM07 接线（偏差）。

### 目标侧新符号（接线，本仓扩展）

- `run_association_pass(conn, subject)` —— 确定性关联扫描：OCR/转录文本中
  人名 ↔ identity PERSON 实体 → **只产 PROPOSED VARIANT 候选**
  （`_propose_multimodal_candidate` 镜像 identity._propose_candidate
  identity.py:455-487 的归一去重/REVOKED 保户/机器只进 UNRESOLVED→PROPOSED
  语义；差异仅引用形状 —— 观察证据无 memory 行，refs=`[{source_event_id}]`）；
  非人物实体 → location 观察（valid_from=观察时刻、valid_to=None 不外推、
  epistemic=INFERRED）；失效回收（引用事件不再产生活的文本节点 → PROPOSED
  退回 UNRESOLVED，同 identity.invalidate_aliases_for_source 语义）。
- `graph_types.py`：`MEDIA_ENTITY_TYPE` 保留标记（**刻意不并入**
  ENTITY_TYPES —— sorted(ENTITY_TYPES) 是 LLM 抽取管线 JSON schema 枚举，
  并入会把 MEDIA 广播给抽取面）；`EntityCandidate.media_asset_id` 字段 +
  `GraphCandidate.from_dict` 透传。
- `graph_store.py` `_validate`：MEDIA 候选先显式校验 media_asset_id 形状
  （asset-…），再给可行动路由报错（graph_entities 0022 CHECK 本波不收
  MEDIA；不让 sqlite IntegrityError 裸露）。
- Atlas `core/atlas/memory/multimodal_bridge.py`：`MediaUnderstandingProvider`
  协议 + `FakeUnderstandingProvider`（TEST 确定性）+ `LiveVisionChatProvider`
  （ModelManager 解析 supports_vision 模型；LiteLLM `image_url` 多模态消息
  形状，与 agent 循环同面）+ `build_media_observation`（speaker UNKNOWN /
  epistemic INFERRED / media_refs=[asset_id] / §2 content_hash 与 MemoryOS
  同规则）+ `MultimodalBridge.import_audio/import_image/associate`。

### ModelManager 接线现状（T05.2 探测结论）

- `atlas.models.ModelManager`（atlas/models/__init__.py:78）只有模型目录/
  选择/凭据面，**无推理方法**；`supports_vision` 只是能力标记
  （`list_models()[i]["capabilities"]`）。
- 真正的 chat/视觉调用在 agent 循环（`agent/run_phases.py`，T05.2 禁区）
  经 LiteLLM 以 `state.litellm_model` 完成；Atlas core **无本地 ASR/OCR**。
- 结论：bridge 按「封装调用签名 + 注明接线点」交付 —— 活路径
  `LiveVisionChatProvider` 在无网关密钥/无 vision 模型/音频（无 ASR 面）时
  `available()` False 且**绝不伪造**；测试用 `FakeUnderstandingProvider`
  （TEST 确定性）走完整管线；live 路径偏差如实登记。

### parity 测试与结果（2026-10-06，service/.venv；tests/unified_memory/test_multimodal.py）

- `::test_cosine_sparse_matches_dense_numpy` —— 等价替代证明：20 组随机向量
  sparse ≡ NumPy 稠密归一化点积（abs=1e-12）+ 空向量边界（上游
  `_average_similarity` 空语义）。**通过**。
- `::test_graph_edge_semantics_ported_from_videograph` —— add_edge 同类文本
  禁连 / ≤0 删边 / reinforce/weaken（videograph.py:228-297）。**通过**。
- `::test_equivalence_groups_and_voice_face_collision` —— 共享观察聚组 +
  确定性 + 碰撞留一（随机→字典序的确定性替代）。**通过**。
- `::test_search_text_nodes_modes_and_range_restriction` —— range 限定 +
  1/√2 cosine 数值 + 非法 mode。**通过**。
- `::test_parse_node_tags_verification_semantics` —— 无效引用丢弃不猜
  （parse_video_caption 语义）。**通过**。
- `::test_same_screenshot_reingest_is_single_node` —— **任务书必验收**：
  同一截图重复入库单节点。**通过**。
- `::test_screenshot_ocr_equivalence_and_segment_locator` —— **任务书必验收**：
  截图↔OCR 等价关系；音频转写时间段定位；片段引用可回溯（resolve_media）。**通过**。
- `::test_transcript_time_segment_reference_via_evidence` —— 片段落在资产
  时长内。**通过**。
- `::test_ocr_speculation_is_not_user_asserted` —— **任务书必验收**：OCR
  推测不写成用户断言（派生产物恒 INFERRED；机器候选永不 VERIFIED；用户
  转述源观察也不升级派生位置观察）。**通过**。
- `::test_speaker_unknown_is_valid` —— 说话人 UNKNOWN 合法保留。**通过**。
- `::test_object_location_observation_not_extrapolated` —— 物品位置观察
  valid_from=观察时刻、valid_to=None。**通过**。
- `::test_weak_visual_match_remains_candidate` —— **任务书判据原样语义**：
  实体别名存在 PROPOSED（不自动确认）+ 可回原证据 + 幂等重放不晋升。**通过**。
- `::test_same_name_ambiguity_proposes_single_deterministic_candidate` ——
  歧义只提 entity_id 最小者。**通过**。
- `::test_source_erased_invalidates_derived_candidates` —— **任务书必验收**：
  source erased → 候选退回 UNRESOLVED、活证据候选保留、节点退出投影、
  媒体随后可 ERASED（节点消失）。**通过**。
- `::test_observation_referencing_erased_asset_excluded` —— 引用 ERASED
  资产的观察整条排除。**通过**。
- `::test_retrieve_text_query_hits_associated_media_within_two_hops` ——
  文字查询命中关联媒体节点（≤2 跳硬顶；人名查询双媒体命中；无关查询不
  编造；limit 截断如实）。**通过**。
- `::test_graph_store_media_marker_routing` —— MEDIA 标记形状校验 + 路由
  报错 + from_dict 透传。**通过**。
- `::test_http_media_observation_and_weak_candidate_semantics`（svc）——
  T05.1 HTTP 面上传/观察 + 进程内关联 pass + `GET /v1/unified/entities`
  出 PROPOSED（任务书判据 HTTP 形状）。**通过**。
- Atlas：`core/tests/unified_memory/test_multimodal_bridge.py` 8 项（契约
  形状 / 缺失显式 / fake 确定性 / live 拒伪造 / associate 路由与 disabled
  上抛）。**通过**。

### 已知边界 / 未尽事项（偏差登记）

- **api 挂载一行留给集成收口代理**：`POST /v1/unified/multimodal/associate`
  （服务端 `run_association_pass`）与可选的 retrieve 路由未挂进
  `service/unified/api.py`（禁区）；bridge `associate` 经 facade.call 走
  代理面，挂载前如实 FeatureNotReady。HTTP 判据测试在挂载前以「T05.1 面
  入库 + 进程内 pass + GET /entities」覆盖任务书形状。
- 关联 pass 的触发点（observe 后钩子或收口路由）属集成收口；本波交付
  服务端实现 + 桥 + 判据测试。
- 节点 embedding 默认为确定性 shingle 向量；活 embedding provider 与 LLM
  检索规划属 UM07（S06/S07），偏差已登记（上「未搬运」）。
- graph_entities 的 0022 CHECK 本波不收 MEDIA 行（schema 不动）；MEDIA
  候选显式路由到多模态节点层，若后续波需要把媒体实体入权威图，需新迁移
  放宽 CHECK。

---

## S06 A-mem & S07 HippoRAG — UM07 / T07.2 联想与多跳联系

### S06 A-mem
- 仓库：<https://github.com/agiresearch/A-mem>；固定 commit：`ceffb860f0712bbae97b184d440df62bc910ca8d`；许可证：**MIT**
- 方式：ADAPT；波次：UM07；目标：`service/unified/associations.py`
- 锁定文件：`agentic_memory/memory_system.py`（CRLF SHA256: `22e5bfd1c98060e1e87704aa771e3ab29952d23a1f9e3c1a4b6fed148020e5d1`）
- 符号映射与约束：`process_memory` / `find_related_memories` 适配为派生关联边，仅作为 `SUPPORTS` 记录在 `unified_dependencies`，禁止原地覆写历史权威事实；`candidate=True` 或低置信度边保持候选，不混入已确认关联路径。

### S07 HippoRAG
- 仓库：<https://github.com/OSU-NLP-Group/HippoRAG>；固定 commit：`2bfd831417202b49cda9da7973e141a456e16872`；许可证：**MIT**
- 方式：ADAPT；波次：UM07；目标：`service/unified/graph_retriever.py`、`service/unified/retrieval.py`
- 锁定文件：`src/hipporag/HippoRAG.py`（CRLF SHA256: `63374f66c2e92056026e4f9df27bd417621a2bd70ff045a91094bc90a0830293`）
- 符号映射与约束：`recognize_facts`、passage 信号与 `run_ppr`（Personalized PageRank，最大 2 跳有界扩展）；路径中任一节点或记录处于 `SUPERSEDED`/`INVALIDATED`/`CONFLICTED`/`ERASED` 时整条路径立即失效；图精度门禁未过时降级为 shadow 并记录原因；`context_items` 携带 `association_path`。
- 验收测试：`tests/unified_memory/test_associative_recall.py`（含 `test_association_keeps_supporting_path` 判据原样，全通过）。

---

## S08 ReasoningBank — UM09 / T09.1 结果验证与多种学习产物

- 仓库：<https://github.com/google-research/reasoning-bank>；固定 commit：`ed80611788292ea739f1effd31f16c53823b8a0d`；许可证：**Apache-2.0**
- 方式：ADAPT；波次：UM09；目标：`service/unified/experience_distiller.py`
- 锁定文件：
  - `WebArena/induce_memory.py`（CRLF SHA256: `9efa53164f22772f1716476667577bd222597bdcba24a210ee1f6cb5c2eae169`）
  - `WebArena/memory_management.py`（CRLF SHA256: `ac40e71d216668ed5af49bb5c94b77cf7906ef0149c74e4e55ade792e88fd4e2`）
- 符号映射与约束：`format_trajectory`、成功/失败轨迹提炼提示词与多产物提炼（`EXPERIENCE` / `KNOWLEDGE` / `COUNTEREXAMPLE` / `CAPABILITY` / `STATE`）；`UNKNOWN` 结果与自评不可标记为 `SUCCEEDED`；单一失败不自动归咎具体技能或人物。
- 验收测试：`tests/unified_memory/test_experience_distillation.py`（10 项通过，含 `test_failed_task_produces_counterexample`）。

---

## S09 ACE — UM09 / T09.2 有版本的增量策略

- 仓库：<https://github.com/ace-agent/ace>；固定 commit：`82709de050e1db6e6ef2f07bcb0393560b94992a`；许可证：**Apache-2.0**
- 方式：ADAPT；波次：UM09;UM11；目标：`service/unified/strategy_updates.py`、`migrations/0030_unified_learning.sql`
- 锁定文件：
  - `ace/core/curator.py`（CRLF SHA256: `dafe08bb9392ab5ba66b567921e6b6f38a16f0b5c08a89db61f1cb00e00187a7`）
  - `playbook_utils.py`（CRLF SHA256: `2819e089427e73e6f247715abf9bcaa704df968c1dab9408a84b90057c3b31f4`）
- 符号映射与约束：Curator `ADD` / `UPDATE` / `MERGE` / `DELETE` 协议解析与 SQLite `unified_strategies` 持久化；强制 `expected_revision` 乐观并发校验（不符返回 409）、旧版保留、来源并集、跨作用域合并拒绝（422）、`DELETE` 退役（`RETIRED`）不删原始经历，用户明确规则受保护。
- 验收测试：`tests/unified_memory/test_strategy_operations.py`（11 项通过，含 `test_strategy_update_requires_expected_version`）。

---

## S10 MemRL — UM09 / T09.3 场景化效用与使用反馈

- 仓库：<https://github.com/MemTensor/MemRL>；固定 commit：`c1b322ca43de36ddf64c6712f89d0095bfc35ce0`；许可证：**MIT**
- 方式：ADAPT；波次：UM09；目标：`service/unified/utility.py`、`migrations/0030_unified_learning.sql`
- 锁定文件：
  - `memrl/service/value_driven.py`（CRLF SHA256: `d9b3fc1f9792bf641d4bf615ca53e3893622e1d0ea1268ea836989c54b482079`）
  - `memrl/service/retrievers.py`（CRLF SHA256: `35ae5e0aae26fdd3d36f887ccb972ca275dbb7103d280188715635d390ff21cf`）
- 符号映射与约束：两阶段 `ValueAwareSelector`、`QValueUpdater`；效用 Key 强制绑定 `(target_ref, revision, task_family, environment_id, model_deployment_id)`；独立统计 `retrieved`/`assembled`/`cited`/`applied`/`outcome`；任务奖励仅归因真实使用项；`POST /v1/unified/applications` 校验真实 `read_id` 与 `context_hash`。
- 验收测试：`tests/unified_memory/test_conditional_utility.py`（10 项通过，含 `test_utility_is_consumer_conditioned`）。

---

## S11 WorldMind, S12 Memento-Skills, S13 Recuris, S14 OpenSkill — UM10

### S11 WorldMind
- 仓库：<https://github.com/zjunlp/WorldMind>；固定 commit：`712b0fd53b4bd6a1948603f087a1e9f25a5adaea`；许可证：**MIT**
- 方式：ADAPT；波次：UM10；目标：`service/unified/prediction.py`
- 锁定文件：
  - `Plugin/worldmind_plugin/experience_refiner.py`（CRLF SHA256: `d589d4cce3d514571c65c5dde74da3144bc92363892384130f878999fffe141f`）
  - `Plugin/worldmind_plugin/knowledge_manager.py`（CRLF SHA256: `dae67ab0c8079a37254120341ffb0534cc218cd6168325b0bddf79c59a704989`）
- 验收测试：`tests/unified_memory/test_prediction_feedback.py`（含 `test_prediction_miss_becomes_feedback`）。

### S12 Memento-Skills
- 仓库：<https://github.com/Memento-Teams/Memento-Skills>；固定 commit：`ee9b9a45efd093d669c06fe318b4b1dceb246d19`；许可证：**Apache-2.0**
- 方式：ADAPT；波次：UM10；目标：`D:\Atlas\core\atlas\memory\skill_evolution.py`
- 锁定文件：`core/skill/evolution/engine.py`（CRLF SHA256: `3d4db783a3ecbe28bcf6cec4b7ec10211ca3b0bc82400e36a7cfe303e59bd89f`）
- 验收测试：`D:\Atlas\core\tests\unified_memory\test_skill_transaction.py`、`test_skill_composition.py`（含 `test_failed_evolution_preserves_active_skill`）。

### S13 Recuris
- 仓库：<https://github.com/Gen-Verse/Recuris>；固定 commit：`7d3745ab787b1206ccd981cb1511100476097266`；许可证：**Apache-2.0**
- 方式：ADAPT；波次：UM10;UM13；目标：`service/unified/learning_gate.py`、`D:\Atlas\scripts\unified_memory\learning_trial.py`
- 锁定文件：
  - `src/recuris/skillmemory.py`（CRLF SHA256: `435ca3b0d7da473c1da40f0bbba45e7ccd5646d827172d1becbe5e2070a3ca42`）
  - `src/recuris/metaagent/gate.py`（CRLF SHA256: `0e6a937f2fc72fe0807d26d9fbeb523e2985791b836539feb6ad1f609313af10`）
- 验收测试：`tests/unified_memory/test_transfer_gate.py`、`D:\Atlas\core\tests\unified_memory\test_learning_trial_integrity.py`。

### S14 OpenSkill
- 仓库：<https://github.com/OpenLAIR/OpenSkill>；固定 commit：`84ca182da055fafb6453dcec4a6defdbbfd987c1`；许可证：**Apache-2.0**
- 方式：ADAPT；波次：UM10；目标：`D:\Atlas\core\atlas\memory\targeted_learning.py`
- 锁定文件：
  - `libs/openskill/targeted_dr.py`（CRLF SHA256: `0149fab1259cbe75051e78cb9564b12f5797c4ba1146a05c71064ce3ddf23484`）
  - `libs/openskill/pipeline.py`（CRLF SHA256: `a1f989d224204ef8c862020a01445cc1f926eda660e7046b8bd40213e9fb06fa`）
  - `libs/terminus_agent/evolution/independent_verifier.py`（CRLF SHA256: `a956048e88348e4ebbaa062969c895cabd291909d95ace0cf52c7c994e7dde82`）
- 验收测试：`D:\Atlas\core\tests\unified_memory\test_targeted_learning.py`（含 `test_data_gap_does_not_trigger_fake_research`）。

---

## S04 Myelin (dream.py / health.py) — UM11 / T11.1 绑定真实检索的自测与复盘

- 仓库：<https://github.com/myelinagent/Myelin-AI>；固定 commit：`48b1f47a2b634678ece45adcc71a3b20764b8a04`；许可证：**MIT**
- 方式：ADAPT；波次：UM11；目标：`service/unified/self_probe.py`、`service/unified/maintenance.py`
- 锁定文件：
  - `myelin/_internal/dream.py`（CRLF SHA256: `3336ef540f7d5a80382a697f7acd76f7b1a1f59fe3528f87b20df5ec363dcb7d`）
  - `myelin/_internal/health.py`（CRLF SHA256: `544d0fee3f8d044a7463e9ecb5eac2a6ea107b3b3000ee13ceb41afe9d665f46`）
- 验收测试：`tests/unified_memory/test_grounded_probe.py`、`tests/unified_memory/test_retention_policy.py`（16 项通过，含 `test_probe_uses_actual_retrieval` 与 `test_rare_short_commitment_survives_consolidation`）。

---

## S16 MemoryAgentBench — UM13 / T13.1 公开基准增量交互适配

- 仓库：<https://github.com/HUST-AI-HYZ/MemoryAgentBench>；固定 commit：`538026089d1a8a8eff05121d0db89b388f360eba`；许可证：**MIT**
- 方式：EVALUATION_ADAPTER；波次：UM13；目标：`tests/unified_memory/public_benchmark_adapter.py`
- 锁定文件：
  - `agent.py`（CRLF SHA256: `fb313eea68abaab01aec5d29a09b8e7f9bddee1ea71e96689becf83d747bf747`）
  - `main.py`（CRLF SHA256: `809c44650730ad64cc93757f56980330c5db4de19c2abde5a2aef059210e7677`）
- 验收测试：`tests/unified_memory/test_public_benchmark_adapter.py`、`D:\Atlas\core\tests\unified_memory\test_acceptance_suite.py`（全通过）。

