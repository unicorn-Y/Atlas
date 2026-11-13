# Atlas 对标 DSH 地基改造（第 3 稿）

**日期**：2026-11-13
**来源**：`docs/parity/DSH-GAP-LEDGER.md`
**修订历史**：第 1 稿 REJECT（3/3，方向性错误）；第 2 稿 REJECT（3/3，两个真实死锁 + 三处不可达目标）。本稿只保留**已证明可行**的部分，其余移入"明确不做"。

## 第 2 轮评审的硬发现（我已逐条复核属实）

| 发现 | 复核 | 对本稿的影响 |
|---|---|---|
| `_execute_write` 持有**不可重入** `threading.Lock`（`atlas_state.py:598`），代码库自己在 `:1699-1700` 注明"嵌套 BEGIN IMMEDIATE 会死锁" | 确认 | 事件写入**不得**在别人的 `_execute_write` 回调里再调 `_execute_write`；必须提供 cursor 级 API |
| 在 `archive_and_compact` 事务内开新 SessionDB 等 21s 后 `database is locked` | 确认 | 同上；压缩/rewind 的事件写入改为**同 cursor** |
| `ToolRegistry` 当前 **0 个条目**，`bind_atlas_tools`/`discover_builtin_tools` **无生产调用点** | 确认（实测 `registry entries: 0`，`read_file`/`terminal`/`write_file` 全为 `None`） | **撤销 `output_schema` 目标**：没有条目就没有校验对象，做了是死代码 |
| `server.py:684-692` 的 `globals().get()` 清扫会把注册表填好的字段清空 | 确认 | **撤销"迁移 3 个服务到注册表"**：不改 lifespan 装配，注册表只作为**新增旁路能力**，不接管既有字段 |
| 只读连接不建表，`session_events` 在只读副本上不存在 | 确认 | 报告脚本改为**可写打开**（只写事件表，不碰 `messages`），或先由后端建表 |

## 目标（收敛后）

只做一件系统性改造，配套一项可验证的报告能力：

1. **旁路会话事件流** —— 在 `append_message` 的**同一事务、同一 cursor** 内追加一条事件行；压缩与 rewind 的 `active=0` 变更用**同 cursor** 写 `messages.deactivated`。事件流是审计事实，不改变模型历史来源。
2. **事件覆盖率报告** —— 一个纯只读函数，回答"某会话的 active 消息中，哪些有事件、哪些没有"，用于验收与后续工作。

**明确不做（本稿移出范围，附原因）**
- 不切换模型历史读取源（`deriveMessages` 等价不可达：压缩/rewind 不发事件，另有内核外写入的 1,158 行）。
- 不新建服务注册表 / 不接管 `AppServices` 字段（`globals()` 清扫会覆盖；52 字段装配不变）。
- 不新增 `output_schema`（`ToolRegistry` 零条目，校验无对象）。
- 不新增路由、不改 `SCHEMA_VERSION` 语义、不动 `messages` 表结构。

## 架构

事件写入的唯一入口是 `append_event_on(cursor, session_id, kind, payload)` —— 它接受**已在事务中的 cursor**，不自开事务。两个调用点：

1. `SessionMessagesMixin.append_message`（`atlas_state_messages.py:390`）在自己的 `_execute_write` 回调内、INSERT 消息行之后调用它。这样"消息行 + 事件行"原子落库。
2. `_archive_named_rows`（`:958`）与 `rewind_to_message`（`:1858`）在各自的回调内、`UPDATE ... active=0` 之后，对受影响的行各写一条 `messages.deactivated`。

表结构在 `SCHEMA_SQL` 末尾追加，靠 `_init_schema` 每次可写打开的 `CREATE TABLE IF NOT EXISTS` 生效（已确认 `atlas_state_schema.py:939` 路径），不提升 `SCHEMA_VERSION`。

## 技术栈

Python 3.11 / SQLite WAL / pytest（`@pytest.mark.unit` 必需）

## 验证策略

**级别**：test-suite

```bash
cd core
# 1) 新增
python -m pytest -q -p no:cacheprovider tests/test_session_events.py
# 2) 复用既有行为不回归（这些文件覆盖 append/压缩/rewind/fork/迁移）
python -m pytest -q -p no:cacheprovider tests/test_context_compact_in_place.py \
  tests/test_kernel_recovery.py
python -m pytest -q -p no:cacheprovider -m "unit or integration" \
  tests/test_atlas_session_sync.py tests/test_session_migration.py
```

**通过意味着**：新增测试全绿；压缩、rewind、fork、迁移的既有测试**失败数不超过上表实测值**。

**基线已知失败（本稿不修，验收口径 = 不增加）**
- `tests/test_atlas_session_sync.py::test_history_mutations_keep_doctor_sessions_consistent`（`KeyError: 'missing_in_hermes'`，断言与实现不一致）
- `tests/test_session_migration.py` 7 项（`ModuleNotFoundError: atlas_state`，同类裸名别名缺口）
- `tests/test_route_snapshot.py` 2 项（856 vs 839）
- `tests/test_c4_plugin_e2e.py` 1 项（hook 信任门文案）
- `tests/test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`

---

### Task 1: cursor 级事件写入器
**Goal:** 提供只接受已开启事务 cursor 的事件写入函数，绝不自己开事务。
**Dependencies:** None
**Files:**
- Modify: `core/atlas/engine/state/atlas_state_common.py`
- Create: `core/atlas/engine/state/session_events.py`
- Create: `core/tests/test_session_events.py`

**Acceptance Criteria:**
- [ ] `SCHEMA_SQL` 含 `session_events`：`id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL`，含 `UNIQUE(session_id, seq)`。
- [ ] 打开已存在的 v31 库（可写）后该表存在，且 `SCHEMA_VERSION` 仍为 31。
- [ ] `append_event_on(cursor, session_id, kind, payload)` 只用传入的 cursor 执行 `SELECT COALESCE(MAX(seq),0)+1` 与 `INSERT`，**函数体内不出现 `BEGIN` / `COMMIT` / `_execute_write`**。
- [ ] 同一 session 连续调用得到 1,2,3…；不同 session 各自从 1 开始。
- [ ] `EVENT_KINDS` 为封闭 frozenset，**必须含** Task 2 与 Task 3 会用到的全部 kind：`message.user`/`message.assistant`/`message.tool`/`message.system`/`messages.deactivated`；未登记 kind 抛 `ValueError`。
- [ ] `messages.deactivated` 在 `EVENT_KINDS` 中已登记（若漏登记，压缩事务会因 `ValueError` 整体回滚；有测试断言该 kind 已登记）。
- [ ] `read_events(conn, session_id, after_seq=0)` 按 `seq` 升序返回事件 dict 列表。

**Step 1:** 在 `atlas_state_common.py:373` 的 `SCHEMA_SQL` 末尾追加建表语句；新建 `session_events.py` 实现上述三个函数。写 6 个单元测试，其中一个**显式断言**：在 `_execute_write` 回调内调用 `append_event_on(cursor, ...)` 不抛 `OperationalError` 且行落库（用真实临时库，`with SessionDB(...) as db: db._execute_write(lambda c: ...)`）。

### Task 2: 消息写入时同步记事件
**Goal:** 每条消息落库时在同一事务内写一条对应事件。
**Dependencies:** Task 1
**Files:**
- Modify: `core/atlas/engine/state/atlas_state_messages.py`
- Test: `core/tests/test_session_events.py`

**Acceptance Criteria:**
- [ ] `append_message` 在 INSERT 消息行之后、同一回调内写事件，kind 按角色映射：`user→message.user`、`assistant→message.assistant`、`tool→message.tool`、`system→message.system`。
- [ ] 事件 `payload` 含 `message_id`（新行 id）与 `role`，JSON 可解析。
- [ ] `append_messages_batch` 对每条消息各写一条事件，事件 `seq` 顺序与消息插入顺序一致。
- [ ] 事件写入抛异常时**消息仍然落库**且 `append_message` 正常返回行 id（事件失败被 `suppress` + warning 吞掉，不破坏主路径）。
- [ ] 既有 `tests/test_context_compact_in_place.py` 与 `tests/test_kernel_recovery.py` 失败数不增加。

**Step 1:** 在 `append_message` 的 INSERT 之后、同一回调内调用 `from atlas.engine.state.session_events import append_event_on`，即 `append_event_on(cursor, session_id, kind, payload)`（Task 1 定义的就是这个名字，无别名）；`append_messages_batch` 对每行同样调用。测试覆盖四种角色映射、批量顺序、异常降级。

### Task 3: 压缩与 rewind 的失活事件
**Goal:** 让"某条消息为什么不在 active 集合里"可审计。
**Dependencies:** Task 2
**Files:**
- Modify: `core/atlas/engine/state/atlas_state_messages.py`
- Test: `core/tests/test_session_events.py`

**Acceptance Criteria:**
- [ ] 失活语句共 4 处，**全部**被覆盖：`_archive_named_rows` 内的 `UPDATE ... SET active=0, compacted=0 ... IN (...)`（`atlas_state_messages.py:980-985`）与其后的 `_ARCHIVE_ACTIVE_SQL`（`:986`）；`archive_and_compact` 回退分支的 `UPDATE ... IN (...)`（`:1072-1075`）与其后的 `_ARCHIVE_ACTIVE_SQL`（`:1076`/`:1078`）。
- [ ] 每处先取受影响 id 再写事件：在每条失活 SQL 执行**前**用同 cursor 查 `SELECT id FROM messages WHERE <与该 SQL 相同的 WHERE>`，执行后用该 id 列表写 `messages.deactivated`（`payload.reason` 为 `compaction`）。
- [ ] `rewind_to_message` 的失活 UPDATE 之后同样写事件，`reason: rewind`。
- [ ] 全部事件写入使用同一回调的 cursor，**不新开事务**。
- [ ] 一次 `archive_and_compact`（有 `covered_ids`）后：`messages.deactivated` 条数 == 该次被置为 `active=0` 的行数；`covered_ids=[1]` 这种混合分支也成立。
- [ ] 一次 `rewind_to_message` 后：条数 == 该次失活行数。
- [ ] `tests/test_atlas_session_sync.py` 的 rewind/fork 测试通过数不减。

**Step 1:** 在 4 处失活 SQL 前各加一次 id 查询，执行后逐条写事件，抽成局部 helper `_record_deactivation(conn, session_id, ids, reason)`。测试用临时库构造 3 条消息，分别覆盖「全部 covered」「部分 covered」「无 covered」三种分支，断言事件条数分别等于 3、3、3 且 reason 正确；rewind 同理。

### Task 4: 覆盖率报告
**Goal:** 回答"某会话哪些 active 消息没有事件"，供验收与后续使用。
**Dependencies:** Task 3
**Files:**
- Create: `core/atlas/engine/state/session_event_report.py`
- Test: `core/tests/test_session_events.py`

**Acceptance Criteria:**
- [ ] `coverage_report(db, session_id)` 返回 `{session_id, active_messages, covered: int, uncovered_active: [int], deactivated_events: int, event_count: int}`。
- [ ] `covered` 统计 active 消息中有对应 `message.*` 事件（按 `payload.message_id` 匹配）的条数。
- [ ] 对新会话（经 `append_message` 写入 3 条）返回 `covered == 3`、`uncovered_active == []`。
- [ ] 对缺事件的存量会话返回非空 `uncovered_active` 且不抛错（如实报告历史缺口）。
- [ ] 函数只读：不写入任何行（测试断言调用前后 `messages` 与 `session_events` 行数不变）。

**Step 1:** 实现 `coverage_report`（一条 `SELECT id FROM messages WHERE session_id=? AND active=1`，一条事件聚合）。测试覆盖新会话全覆盖、存量会话有缺口、只读性。

### Task 5: 最终验证
**Goal:** 运行验证策略并确认无新增失败。
**Dependencies:** Task 4
**Files:**
- Test: `core/tests/test_session_events.py`

**Acceptance Criteria:**
- [ ] `tests/test_session_events.py` 全通过。
- [ ] `tests/test_context_compact_in_place.py`、`tests/test_kernel_recovery.py` 全通过。
- [ ] `tests/test_atlas_session_sync.py` 通过数 ≥ 9/10（第 10 项为已记录的环境问题）。
- [ ] `tests/test_session_migration.py` 通过数等于实测基线（在 Step 1 记录）。
- [ ] 基线表中每一行的失败数不增加，逐项记录实测数并输出对照表。

**Step 1:** 先跑一遍全部命令记录基线数字（含 `test_session_migration.py` 与 `test_atlas_session_sync.py` 的实测通过/失败数），再从 Task 1 结束起复跑，逐项对比并输出对照表。

## 基线实测（本计划 seal 前测得，作为 Task 5 的对照基准）

| 文件 | 实测 | 说明 |
|---|---|---|
| `tests/test_atlas_session_sync.py` | 9 passed / 1 failed（逐项单跑） | 失败项 `test_history_mutations_keep_doctor_sessions_consistent`：`KeyError: 'missing_in_hermes'`（`cli.py:2930` vs 测试 `:245`），是**断言与实现不一致**，非环境问题 |
| `tests/test_session_migration.py` | 1 passed / 7 failed | 全部 `ModuleNotFoundError: No module named 'atlas_state'`（同一类别名缺口，另一批裸名） |
| `tests/test_context_compact_in_place.py` | 4 passed | 全绿 |
| `tests/test_kernel_recovery.py` | 18 passed | 全绿 |
| `tests/test_route_snapshot.py` | 2 failed | 856 实际 vs 839 冻结 |

> 本节数字是 Task 5 的**唯一对照口径**；任何一项失败数上升即视为回归。

## 风险与回退

| 风险 | 触发 | 回退 |
|---|---|---|
| 事件写入拖慢 `append_message` | 单次写入耗时显著上升 | 事件写入包在 `suppress` 内；必要时改为每批一次批量 INSERT；表可 `DROP`（旁路数据） |
| 死锁 | 任何嵌套事务 | Task 1 的 AC 显式禁止自开事务，并有一个真实库测试锁定"回调内不崩" |
| 事件表增大 | 长期运行 | 表可整表删除，不影响任何既有功能；不设 retention 是刻意选择，避免在数据层引入裁剪逻辑 |
| 存量会话无事件 | 历史数据 | 这是事实而非缺陷；`coverage_report` 如实报告 `uncovered_active` |

## Critic Responses

### 对第 2 轮（round-2）的处置

| # | 评审意见 | 处置 |
|---|---|---|
| R2-F1 | `append_event(db,...)` 在回调内会死锁（不可重入 Lock） | Task 1 改为 **cursor 级** `append_event_on(cursor,...)`，AC 明文禁止自开事务，并有真实库测试锁定 |
| R2-F2 | `message.tool`/`message.assistant` 无写入点 | Task 2 落在 `append_message`/`append_messages_batch` 内部（覆盖全部 17 个 `persist_async` 调用点），不依赖 loop |
| R2-F3 | `FakeLLMServer`→`run_turn` 载体是红的、无既有测试证明 | **删除该验证路径**；本稿不驱动内核，只用 `SessionDB` 直接测数据层 |
| R2-F4 | `ToolRegistry` 零条目，`output_schema` 是死代码；`register()` 无该参数 | **撤销 Task 7/8**（整个输出契约目标移出范围） |
| R2-F5 | 无 generation-bound declared-path baseline | 本稿路径全部写入各 task 的 Files 列表 |
| R2-I1 | Task 7 与 Task 2 共享 `loop.py` 却无依赖边 | Task 7 已删除；本稿无任务改 `loop.py` |
| R2-I2 | 压缩/rewind 事务内写事件死锁（已复现 6s 挂起 / 21s 后 locked） | 改为**同 cursor**写入，Task 3 的 AC 明确"不新开事务" |
| R2-I3 | `server.py:684-692` `globals()` 清扫会清空注册表字段；20+ 处以模块全局读同批服务；`register` 无法 `await init()` | **撤销服务注册表目标**，`server.py` 装配完全不动 |
| R2-I4 | 只读连接不建表，报告在只读副本上 `no such table` | Task 4 的 `coverage_report` 接收**已打开的 `SessionDB`**；报告脚本不在本稿范围内 |
| R2-I5 | `tool_finalize.py` 未纳入 git，HEAD 无 `tool_finalizers` | 本稿不依赖该文件（已验证它存在于工作树，但不作为任何 AC 的前提） |
| R2-I6 | 引用错误的 conftest 守卫；`test_api_runtime` 契约测试已红 | 本稿**不新增 `AppServices` 字段**，该测试不受影响 |

### 对第 1 轮（round-1）的处置

已由第 2 稿的修订覆盖；本稿进一步撤销了仍在纸上但不可落地的目标（`deriveMessages` 等价、服务注册表、`output_schema`）。
