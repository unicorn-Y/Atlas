# Atlas 既有失败盘点与定性报告 (KNOWN_FAILURES)

> 本文档针对 2026-10-08 Atlas 全库复跑（8 failed / 2336 passed / 4 skipped）中的全部 8 个失败用例进行逐个盘点与定性。
> 经 K2 任务核实与收尾，其中 1 个属于「测试与提交计划冲突」已成功修复并通过，其余 7 个均为「基线既有」历史已知问题。

---

## 汇总统计

| 序号 | 测试路径与用例 | 定性分类 | 当前状态 | 简要说明 |
|---|---|---|---|---|
| 1 | `tests/unified_memory/test_baseline_inventory.py::test_env_manifest_records_both_repos_and_forbidden_roots` | **计划冲突** | **已修复 (PASSED)** | S1/S6 按计划合入受保护文件并提交 HEAD，断言由「必须 dirty」升级为「必须被跟踪且已提交（clean）」 |
| 2 | `tests/test_lint_gate.py::test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows` | **基线既有** | 保持记录 (FAILED) | Ruff BLE001/S110 规则在旧代码范围（`run_phases.py` 等）的既有宽泛异常抑制 |
| 3 | `tests/test_model_router.py::test_ast_no_acompletion_outside_router` | **基线既有** | 保持记录 (FAILED) | `core/atlas/memory/multimodal_bridge.py` 历史遗留直接调用 litellm，属于待迁移清单 |
| 4 | `tests/test_plugins.py::test_git_source_update_available` | **基线既有** | 保持记录 (FAILED) | Windows 环境下 Git 对 `file://` 临时目录协议克隆的安全限制与环境不兼容 |
| 5 | `tests/test_route_snapshot.py::test_routes_match_frozen_snapshot` | **基线既有** | 保持记录 (FAILED) | 后续 API 演进新增路由，但 OpenAPI 冻结快照 `route_snapshot.json` 未同步刷新 |
| 6 | `tests/test_subprocess_encoding.py::test_text_mode_subprocess_calls_declare_an_encoding` | **基线既有** | 保持记录 (FAILED) | AST 静态门禁扫描到历史测试/工具（如 `harness.py`）中未显式声明 encoding 的 subprocess 调用 |
| 7 | `tests/unified_memory/test_repair_baseline.py::test_r00_b_0026_is_construction_not_foreign` | **基线既有** | 保持记录 (FAILED) | R00 修复期断言 `0026_*.sql` 必须为 dirty，但该迁移已正式提交进 Git 仓库 |
| 8 | `tests/unified_memory/test_repair_baseline.py::test_r00_b_dirty_counts_match_known_baseline` | **基线既有** | 保持记录 (FAILED) | 断言 Atlas HEAD 必须停留在 R00 初始哈希 `234e545a...`，仓库正常推进后必然偏离 |

---

## 逐项详细定性与分析

### 1. `test_env_manifest_records_both_repos_and_forbidden_roots`
- **用例路径**：`core/tests/unified_memory/test_baseline_inventory.py::test_env_manifest_records_both_repos_and_forbidden_roots`
- **定性**：**计划冲突（测试与提交计划冲突）**
- **现象**：
  ```text
  AssertionError: 受保护在途文件未出现在工作区清单: core/atlas/automation/engine.py
  ```
- **根因**：
  在 UM00 基线建立期，`PROTECTED_WORKSPACE_FILES` 中定义的 5 个文件属于他人在途未提交的修改（dirty）。测试原意是防止外部施工在未提交前误丢弃或清理这些文件。在后续 S1 和 S6 施工波次中，这些受保护文件按计划正式集成并提交到了 Git 分支 HEAD（由 I3 合并提交），工作区状态变为 clean。原测试仍死守「必须在 dirty 清单」导致断言与施工计划冲突。
- **治理策略与结果**：
  **已由 K2 任务修复**。未削弱防篡改要求（不得删除清单），而是升级为生命周期闭环断言：
  1. 验证清单非空，受保护文件在工作区磁盘真实存在且非空（防静默删除）；
  2. 验证受保护文件被 Git 严格跟踪且已提交至 HEAD（防脱管与丢失）；
  3. 验证受保护文件处于 clean 状态，不得存在未审计的工作区修改（防在途篡改）；
  4. 若意外进入 dirty 状态，manifest 必须自动标明 `protected: true`。
  **复跑结果：PASSED**（全模块 10 passed）。

---

### 2. `test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows`
- **用例路径**：`core/tests/test_lint_gate.py::test_critical_exception_scopes_are_clean_and_no_baseline_scope_grows`
- **定性**：**基线既有**
- **现象**：
  ```text
  AssertionError: {('atlas/agent/run_phases.py', 'BLE001'): 3, ('atlas/agent/tool_node.py', 'BLE001'): 3, ('atlas/api/agent_backends_router.py', 'BLE001'): 1, ('atlas/server.py', 'S110'): 2, ...} == {}
  ```
- **根因**：
  Atlas 早前引入的异常门禁规则（select `BLE001,S110,S112`）。在 `run_phases.py`、`tool_node.py`、`server.py` 等核心链路中，历史代码存在较多裸 `except Exception:` 及 pass 处理。该门禁在本次施工启动前已处于失败状态。
- **建议**：
  属 Atlas 核心架构既有代码质量治理项，不应在记忆 V1 业务施工中混入跨范围的大规模异常重构。

---

### 3. `test_ast_no_acompletion_outside_router`
- **用例路径**：`core/tests/test_model_router.py::test_ast_no_acompletion_outside_router`
- **定性**：**基线既有**
- **现象**：
  ```text
  AssertionError: new litellm direct call sites must go through atlas.models.router, got: ['core/atlas/memory/multimodal_bridge.py']; shrink pending_unification as lanes wire up
  ```
- **根因**：
  H2 波次对模型调用统一收敛到 `atlas.models.router`。历史遗留的 `core/atlas/memory/multimodal_bridge.py` 内部直接调用了 litellm 的 `acompletion`，未在 `pending_unification` 清单中免除，也未完成向 router 的接入。
- **建议**：
  在后续模型网关多模态迁移计划中专项收尾。

---

### 4. `test_git_source_update_available`
- **用例路径**：`core/tests/test_plugins.py::test_git_source_update_available`
- **定性**：**基线既有**
- **现象**：
  ```text
  subprocess.CalledProcessError: Command '['git', 'clone', '--depth', '1', 'file:///C:/Users/.../origin-repo', '...']' returned non-zero exit status 128.
  ```
- **根因**：
  Windows 平台及特定 Git 配置下，`git clone` 针对 `file:///` 协议克隆本地临时仓库受 `protocol.file.allow` 安全策略限制，且 Windows 路径转换为 file URI 后的转义在 Git CLI 中返回 exit 128。
- **建议**：
  属于 Windows 平台测试环境特定的插件安装兼容性测试，需在测试内为 subprocess 注入 `-c protocol.file.allow=always` 或使用本地裸路径克隆。

---

### 5. `test_routes_match_frozen_snapshot`
- **用例路径**：`core/tests/test_route_snapshot.py::test_routes_match_frozen_snapshot`
- **定性**：**基线既有**
- **现象**：
  ```text
  AssertionError: assert build_route_snapshot() == expected
  ```
- **根因**：
  FastAPI 应用路由与冻结在 `tests/snapshots/route_snapshot.json` 的接口元数据比对不一致。自快照冻结以来，多个波次（包含持久化、群聊路由、统一记忆 API 等）新增和修改了系统路由，快照未按计划更新。
- **建议**：
  在接口最终冻结里程碑统一重新生成 snapshot。

---

### 6. `test_text_mode_subprocess_calls_declare_an_encoding`
- **用例路径**：`core/tests/test_subprocess_encoding.py::test_text_mode_subprocess_calls_declare_an_encoding`
- **定性**：**基线既有**
- **现象**：
  ```text
  AssertionError: assert ['tests\\unified_memory\\harness.py:975', ...] == []
  ```
- **根因**：
  静态语法检查要求所有 `text=True` 的 subprocess 调用必须显式指定 `encoding="utf-8"`（防止 Windows 默认 gbk 乱码）。在前期编写 `tests/unified_memory/harness.py` 等测试支撑代码时，个别调用遗漏了显式 encoding 参数。
- **建议**：
  在 harness 代码微调中补全 `encoding="utf-8"` 参数即可。

---

### 7. `test_r00_b_0026_is_construction_not_foreign`
- **用例路径**：`core/tests/unified_memory/test_repair_baseline.py::test_r00_b_0026_is_construction_not_foreign`
- **定性**：**基线既有（生命周期过时用例）**
- **现象**：
  ```text
  AssertionError: assert 'migrations/0026_unified_episode_formation.sql' in ...
  ```
- **根因**：
  R00 修复基线用例断言该 migration 文件必须处于工作区 dirty 状态。在实际施工中，该文件已被正常 commit 到 Git 仓库中，故不再出现在 dirty 清单中。
- **建议**：
  该测试属于针对 R00 特定时刻的瞬时守卫，随生命周期结束已失去校验时效。

---

### 8. `test_r00_b_dirty_counts_match_known_baseline`
- **用例路径**：`core/tests/unified_memory/test_repair_baseline.py::test_r00_b_dirty_counts_match_known_baseline`
- **定性**：**基线既有（版本快照过时用例）**
- **现象**：
  ```text
  AssertionError: assert by_repo["Atlas"]["head"] == '234e545aa33f48064618d5d9bd8bfeb1196d7018'
  ```
- **根因**：
  用例将 Atlas 的 HEAD 固定断言为 R00 修复起点 commit `234e545a...`。随着主线和波次推进，HEAD 演进为当前最新提交，该断言必然失败。
- **建议**：
  同为 R00 阶段性锁死用例，属于历史快照性质。

---

## MEMORY-V1 F1-C：`core/tests/unified_memory` 基线 11 项失败定性（2026-10-08）

> 本节独立记录 F1-C 的统一记忆测试基线，不覆盖上文全库 K2 盘点。有效 Atlas 基线为 253 passed / 11 failed / 2 errors / 0 skipped；原始摘要日志：`C:\Users\25011\AppData\Local\Temp\atlas-f1c-atlas-run2-20261008\pytest.log`。run1 使用了共享 pytest 临时目录，结果不作为基线。原始失败节点以 run2 日志为准。

| # | 基线失败节点 | 定性 | 当前处理 / 证据状态 |
|---|---|---|---|
| 1 | `test_capture_lifecycle.py::test_chat_capture_user_and_assistant_observations` | 测试断言把一个 source event 的多个合法投影误当多条来源事件 | 改为核对唯一 source event IDs 与投影计数；focus2 定向结果通过 |
| 2 | `test_client_contract.py::test_service_down_raises_and_no_local_fallback_write` | ①原断言把 Atlas 启动所需的 DBOS SQLite 误判为统一记忆本地回退写入；②修订后 MemoryOS 侧快照仍宽匹配，把 SQLite checkpoint 的 `-wal`/`-shm` 边车涨落误判为写入（间歇 flake） | 双侧快照均只认权威主库文件（Atlas `atlas.db`、MemoryOS `memoryos.sqlite3`）；主库 mtime+size 仍精确比对，断言强度未降。单文件 20 passed；全量三连复验 0 flake。详见下文专项 |
| 3 | `test_import_sources.py::test_import_text_files_via_real_atlas_service` | 导入确有新 revision，测试却依赖非契约的返回顺序/每次恰好一个 projection | 按 source event IDs 和 locator 集合验证真实 HTTP 导入；focus2 定向结果通过 |
| 4 | `test_legacy_migration.py::test_legacy_export_import_roundtrip_idempotent_and_counts` | **真实 MemoryOS 产品缺陷，已由 A 修复，Atlas roundtrip 复验通过** | legacy_ref 派生链此前改变原始内容 hash；现严格校验 hash、重复导入与生命周期。Atlas focus5：`D:\Temp\F1-C-20261008\focus5-legacy\pytest.log`，1 passed |
| 5 | `test_multimodal_proxy.py::test_associate_via_proxy_returns_candidates_and_groups` | V1 多模态理解未开放，服务按契约返回 `MEMORY_V1_FEATURE_FROZEN` | 仅此冻结能力标注 `frozen_v1` 并显式 skip；理由为 V1 不执行多模态理解，不以假响应伪装成功 |
| 6 | `test_release_composition.py::test_desktop_correction_is_visible_in_new_chat` | 原测试经 helper 造假“已纠正”结果，没有旧值或 corrections API；属于不诚实脚手架 | 旧版 focus2 失败是 replacement 没装入新 chat provider context；现已改为真实 observe → record/profile/recall 旧值 → Atlas corrections API → revision/current fields/profile/recall 新值 → 新 Atlas WebSocket chat。Atlas 仅用 fake provider 检查模型请求装配，明确标记 `fake_provider`，不计真实模型效果。后续真实HTTP依次发现活动 title、CURRENT raw episode旧值回流、CURRENT context_items泄漏 `corrected.prev_value` 审计字段。A已修活动投影及CURRENT来源过滤；当前只待 recall 投影隐藏审计元数据，持久化审计、不可变source和AS_OF历史都必须保留 |
| 7 | `test_repair_baseline.py::test_r00_b_0026_is_construction_not_foreign` | R00 瞬时守卫过时：迁移已在 Git 跟踪，不应要求仍处于 dirty | 改为核验 migration 仍被跟踪；focus2 定向结果通过。没有降低迁移存在性要求 |
| 8 | `test_repair_baseline.py::test_r00_b_dirty_counts_match_known_baseline` | R00 锁定旧 HEAD、dirty path/count 的快照基准已过期 | 改为基于当前仓库 HEAD/status manifest 做真实性核验；focus2 定向结果通过。只更新时效性基准，不忽略当前状态 |
| 9 | `test_source_idempotency.py::test_flush_roundtrip_records_readable_status_counts_outbox_drained` | 同一 source event 可合法形成多种 projection；旧断言把 projection 数当 event 数 | 按唯一 source IDs/readable statuses 检查，outbox 在 finally 关闭；focus2 定向结果通过 |
| 10 | `test_windows_activity.py::test_capture_lifecycle_over_http` | 测试曾要求 V1 未提供的被动屏幕采集产生新水位，从而把冻结能力混入有效生命周期断言 | 保留真实 HTTP capture 状态与 Atlas chat 有效路径；移除被动采集伪成功前提。focus2 定向结果通过 |
| 11 | `test_windows_activity.py::test_running_capture_passive_watermark_advances` | V1 被动屏幕/媒体采集能力冻结 | 仅水位推进断言标注 `frozen_v1` 并显式 skip；一般 capture 生命周期和有效文本导入仍保留测试 |

### 基线 teardown / fake provider 脚手架问题

- run2 的两个 teardown errors 与测试父进程 `psutil.pid_exists(pid)` 的 PID 重用假阳性有关。harness 现在基于本轮持有的 Popen/子进程句柄终止进程树，并在 stop 后检查本轮 Atlas/MemoryOS 端口已释放；focus2 无 teardown error。端口检查保留，不能只检查父 launcher 退出。
- Observer 合约假 provider 曾持续返回不符合结构的文本并制造大量 schema rejection。现在只有 Observer schema 路径返回合法空 observations `{"observations":[]}`；不合成事实，其他 fake provider 覆盖明确只作为接口/基础设施测试，不计真实效果。
- F1-C focused 结果不是全套验收：focus2 原始摘要为 8 passed / 1 failed / 2 skipped，唯一失败为旧版 T12 provider context 未包含 replacement；该断言路径已由真实纠正链替换。后续真实纠正运行先后发现活动 title、CURRENT raw episode 旧值回流、CURRENT context_items泄漏 `corrected.prev_value` 审计字段。当前活动value/title/summary/text、自然召回新值、不可变source及持久化审计均已通过，但上下文泄漏待A修；完整全量门禁留在 `progress/F1-C.md`，目前未完成、不得标记 ACCEPTED。

### 跨用例隔离缺陷：`test_legacy_migration` 全库计数被 `test_capture_lifecycle` 污染（2026-10-08，AI计划 定性并修复）

- **现象**：单独运行 `test_legacy_export_import_roundtrip_idempotent_and_counts` 为 `1 passed`；但与 `test_capture_lifecycle.py::test_failing_tool_result_captured_with_error_marker` 同批运行时该用例报 `AssertionError: assert 9 == 8`（第 378 行，`len({legacy_ref}) == expected_rows`）。
- **根因（因果实验铁证）**：`core/atlas/agent/tool_node.py:1354` 在工具失败路径调用真实 agent 的 `record_agent_reflection`；该委托落到**会话级共享** `um` harness 的 MemoryOS 库，写入 `locator.value = legacy:agent_reflections:<uuid>`（`core/atlas/memory/__init__.py:1846`）。`_legacy_records()` 按 `content.legacy_ref` 前缀 `legacy:` 过滤**全库**记录，于是把这条 agent reflection 也计入，得到 9 条而非 8 条。两条证据：①组合跑 = FAIL，②roundtrip 单跑 = PASS。
- **性质**：测试隔离缺陷，非 MemoryOS 产品缺陷；双仓纯 HEAD 同样复现（`git stash` 对照一致）。
- **修复**：将该用例改用函数级隔离实例 `um_fresh`（每用例独立 ATLAS_DATA_DIR/MEMORYOS_DATA_ROOT/MEMORYOS_DB_PATH），断言与夹具**一字未改**，只隔离数据库。组合跑复验 = `2 passed`；全量复验 = `271 passed, 2 skipped, 0 failed`。
- **纪律**：不通过放宽断言、按时间/数量截断全库结果来掩盖隔离问题；全库断言必须有全库隔离的前提。

### 跨用例隔离缺陷（二）：全库快照把 SQLite WAL 边车涨落误判为回退写入（2026-10-08，AI计划 定性并修复）

- **现象**：全量口径 `-o addopts= core/tests/unified_memory` 下，`test_client_contract.py::test_service_down_raises_and_no_local_fallback_write` 间歇失败；`set(memoryos_after) != set(memoryos_before)`，报错显示 `memoryos_before` 含 `memoryos.sqlite3-wal` 与 `memoryos.sqlite3-shm`，而 `memoryos_after` 已无（被 checkpoint 合并回收）。
- **根因**：该用例同时快照 Atlas 侧与 MemoryOS 侧数据目录。Atlas 侧此前已收窄到只认 `data/atlas.db`，**但 MemoryOS 侧仍宽匹配** `*.db`/`*.sqlite*`/`*.sqlite3-*`，于是把运行中的 MemoryOS 服务自身 checkpoint 造成的 `-wal`/`-shm` 边车出现/消失，误当成本地回退写入证据。属测试隔离缺陷，与被测行为无关；`-wal`/`-shm` 只是 SQLite 模式的内部状态，不是写入证据。
- **反向证据**：单文件运行 `test_client_contract.py` = 20 passed；同一用例在全量 run1/run3 通过、run2 失败（时序相关）。
- **修复**：`db_snapshot(root, only)` 增加 `only` 参数；Atlas 侧传 `atlas_memory_db`、MemoryOS 侧传 `runtime_manifest["memoryos_db"]`（`db/memoryos.sqlite3`），两侧都只对权威主库文件比对 mtime+size，忽略边车。**未放宽断言**：主库文件的精确比对原样保留，任何真实写入仍会被捕获；只是不再把 SQLite 内部 checkpoint 的边车涨落当证据。
- **复验**：单文件 20 passed；全量三连（run1/2/3，各独立 basetemp+JUnit）全部 `271 passed, 2 skipped, exit 0`，**零 flake**。证据 `D:\Temp\F1-C-gate-20261008\`。
- **纪律**：不得用删除 MemoryOS 侧断言、或整体跳过该用例来消除 flake；两侧快照必须保持对权威主库的精确比对。
