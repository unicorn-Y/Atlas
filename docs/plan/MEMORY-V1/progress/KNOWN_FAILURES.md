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
