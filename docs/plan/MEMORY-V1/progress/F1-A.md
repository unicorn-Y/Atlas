# F1-A 语义召回与纠正链路修复 · 验收报告

2026-10-08；执行者 AI计划（接续 Codex 桌面端 F1 施工线）。权威：`04_修复包F1.md`、`F1-dispatch.md`。
本轮不写 ACCEPTED（审查方专属）；不提交、不推送；不改生产数据或配置。

## 1. 完成判据对照（F1-dispatch.md §17）

| 判据 | 阈值 | 实测 | 证据 | 结果 |
|---|---|---|---|---|
| 真实 HTTP + 本地模型改述召回 | ≥9/10 | **10/10**（含 2 英文、1 跨语言中英混问） | `D:/Temp/F1-A-verify-20261008/smoke-10k/run.json` → `quality.passed=10` | ✅ |
| 中英命中 | 中英均命中 | P1/P9 英文、P2–P8/P10 中文、P4 中英混问，全部 `target_rank` 命中 | 同上 `quality.results[]` | ✅ |
| 删除归零 | 硬擦除后目标不可召回 | 受控层 23×`VERIFIED_ZERO` + 1×`NOT_APPLICABLE`(hindsight/honcho)，unified 17 层全 `VERIFIED_ZERO`，总状态 `VERIFIED`；post_delete `context_refs=[]` | 同上 `erase_http.verification` | ✅ |
| 1 万条预热 p95 | ≤800ms | **391.5ms**（p50 282.0 / max 414.4，n=50） | 同上 `latency.memoryos_http_recall_ms` | ✅ |
| 同事务索引 / 后台预热 / 真实状态回填 | 无 pending、worker READY | 10000 active=ready=native，pending=0，`indexing_s=176.8`，worker `state=READY device=cuda` | 同上 `scale` / `worker_ready` | ✅ |
| Atlas 本地装配 p95 | —（记录项） | 109.6ms（23 refs / 10 samples） | 同上 `atlas_local_assembly` | ✅ |

**官方冒烟最终结论：`status = PASS`。**

## 2. 修复内容（相对开工基线）

| 文件 | 改动 | 解决的问题 |
|---|---|---|
| `service/unified/formation.py` | 纠正分支标题三分类规则 | 旧实现把 `new_title` 粗暴覆盖为 `new_text`，抹杀语义标题（如「咖啡偏好」），导致改述查询命中数不足被 weak-match 丢弃 → E7 纠正项召回丢失 |
| `service/unified/retrieval.py` | ① 语义分存在时以语义相似度为 relevance，否则回退 RRF 排名归一化；② `context_items` 装配剥离 `corrected/correction_source/evidence_chains` 审计字段；③ 语义通道状态机优先级 `FAULT→NOT_WIRED→DISABLED→ERROR→WARMING→OK`；④ `_exact_channel` 动态 Unicode 折叠谓词 + 候选 ID 定向水合 | ① 修 `test_decay_sorting_recent_vs_old` 同分打平退化为 DB 迭代乱序的 flaky；② 修 T12 `context_items[].content.corrected.prev_value` 把旧值审计字段泄漏给模型上下文；③ 修 hybrid 状态词与 fallback 模式冲突；④ **10k 延迟门禁 FAIL 根因** |
| `service/hybrid_recall.py` | 清除未使用 `_sys` 引用 | 调试残留清理 |
| `tests/unified_memory/test_e7_page_closure.py` | 清除 `[E7 DIAG]` print | 调试残留清理 |

- 精确通道差分回归保留完整扫描结果对照，覆盖标识符、数字、ASCII 大小写、标点、中英混合、Unicode `K`、JSON 根字段覆盖、项目隔离和 as-of。`narrowanchor` 的预筛护栏允许最多 4 个候选：真实命中、整词边界假阳性、`extra_json` 根字段覆盖行及必要时的 Unicode 小写折叠行；最终 Python 匹配和生命周期 gate 决定结果，实际命中仍只有目标记录。

### 2.1 延迟门禁根因（本轮最关键发现）

- 首次 10k 实测 **FAIL**：`p95=954.014ms > 800ms`（证据 `D:/Temp/F1-A-cuda-20261008-174500/smoke-10k/run.json`，永久保留原结果）。
- 逐阶段剖析（`phase-profile-*.json`）定位：`_exact_channel` p95 达 **442–620ms**，且**与查询是否含 ASCII/拉丁词严格相关** —— 纯中文查询该通道 0.01ms，含 ASCII 词（P1/P4/P9）则整表扫描 4MB 折叠文本。
- 根因：`_exact_channel` 对全 subject 行做 `instr(lower(...))` 全表扫描，并对每条命中行做无界 Python 水合。
- 修复：SQL 层按查询词动态构造 `instr` 谓词预筛（含动态 Unicode 折叠安全网，仅在查询确含对应 ASCII 字母时追加 raw 谓词），并按候选 ID 分块（400/批）定向水合，替代整表 `SELECT *`。
- 修复后 `_exact_channel` p95 → **127.7ms**，整体 HTTP p95 → **391.5ms**（余量翻倍）。
- **注**：该修复在 20:18 落地后从未被官方冒烟验证过；本轮首次以官方门禁复核通过。

## 3. 门禁结果

| 门禁 | 命令 | 结果 |
|---|---|---|
| MemoryOS 全量 | `service/.venv/Scripts/python.exe -m pytest tests/unified_memory -q --basetemp D:/Temp/...` | **421 passed, 7 warnings**（基线 5 failed → 0） |
| Atlas 全量（含被默认 `-m unit` 过滤的非 unit 用例） | `core/.venv/Scripts/python.exe -m pytest core/tests/unified_memory -q -m "" --basetemp D:/Temp/...` | **270 passed, 1 failed, 2 skipped**（基线 2 failed；T12 已修复） |
| 官方 10k 语义冒烟 | `scripts/f1_semantic_smoke.py --latency-samples 50` | **PASS** |

- MemoryOS 全量三连：见 §3.1。
- Atlas 唯一失败 `test_legacy_export_import_roundtrip_idempotent_and_counts`（`assert 9 == 8`）**已定性为既有跨测试隔离缺陷**，非本轮引入，详见 §4。

### 3.1 连续三连（验收纪律：连续三次全绿）

| 轮次 | 结果 | 耗时 | 证据 |
|---|---|---|---|
| run1 | 421 passed, 7 warnings | 125.17s | `D:/Temp/F1-A-final-gate-20261008/mos-full.log` |
| run2 | 421 passed, 7 warnings | 122.52s | `D:/Temp/F1-A-final-gate-20261008/mos-triple.log` |
| run3 | 421 passed, 7 warnings | 121.89s | 同上 |

三连全绿，0 failed / 0 error。

### 3.2 Atlas 全量

- 默认 marker（`addopts = -m unit`）：209 passed, 64 deselected。
- 显式 `-m ""`（全集）：**270 passed, 1 failed, 2 skipped**，286.09s；唯一失败为 §4 已定性的既有隔离缺陷。
- Atlas 全集三连属 F1-C 门禁职责（须先修该隔离缺陷），F1-A 不代为宣称全绿。

## 4. Atlas 既有失败归因（严密对照）

- 现象：`test_legacy_migration.py::test_legacy_export_import_roundtrip_idempotent_and_counts` 报 `assert 9 == 8`（第 352/378 行），多出记录为 `legacy:agent_reflections:<uuid>`，内容 `local_shell requires a non-empty command`。
- 机制：`test_capture_lifecycle.py::test_failing_tool_result_captured_with_error_marker` 执行时产生该 agent reflection，残留于 session-scoped 共享服务实例，污染后续 legacy 导出计数。
- 单跑 `test_legacy_migration.py`：**15 passed**（无污染）。
- **纯 HEAD 对照**：双仓 `git stash` 至开工基线（Atlas `54f75b13` / MemoryOS `f7fe1b7`），仅运行「capture_lifecycle + legacy_migration」组合，**同样复现 `assert 9 == 8`**。→ 铁证：该失败与 F1-A 改动无关。
- 归属：按 `F1-dispatch.md`，Atlas 既有统一记忆测试的隔离缺陷属 **F1-C** 治理范畴，不列入 F1-A 阻塞项。

## 5. 环境硬事实（复跑须知）

- MemoryOS 服务解释器：`D:/Temp/F1-A-cuda-20261008-174500/venv/Scripts/python.exe`（torch 2.14.0+cu130，CUDA 可用）；共享/生产 `service/.venv` 仍 CPU-only，临时 CUDA 环境不等于部署已变更。
- **MSYS 路径陷阱**：Hermes `terminal` 走 git-bash，`--basetemp /d/Temp/...` 会被改写为 `D:/d/Temp/...` 导致 297 setup errors。必须用原生 `D:/Temp/...` 正斜杠路径。
- Atlas 默认 `addopts = -m unit`（`core/pyproject.toml:102`）会静默 deselect 64 个非 unit 用例；核对全集须显式 `-m ""`。
- 模型：`Qwen/Qwen3-Embedding-0.6B`（本地缓存），索引 10000 条耗时 176.8s。

## 6. 结论

F1-A 全部完成判据已由**官方冒烟 + 双仓全量门禁**闭环验证。唯一遗留 Atlas 失败经纯 HEAD 对照证实为既有隔离缺陷（F1-C 范畴）。

- **F1-A：DONE_PENDING_REVIEW**（ACCEPTED 由审查方写）。
- 可流转：F1-C 门禁可基于本报告 + 稳定源启动连续三连；F1-B/F1-D 不受阻。
