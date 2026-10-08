# 画像块断点修复记录（S3↔S4 集成缺口收口）

**时间**：2026-10-08
**分支**：`memory-v1`
**提交**：MemoryOS `164920a`、Atlas `5480f379`
**上一棒**：`20261008_044936_a3e1d4`（S8 打假返工，真数 21/30，标出"画像块恒空"待批）

## 1. 断点（四层，逐层验明）

S8 记录只指出"反思者写 SUMMARY/PROFILE 记录、current_profile 只投 PROFILE_FACETS，
两者未接"。实测逐层核到**四层**，缺任一层画像块都恒空：

| # | 层 | 位置 | 病 | 修 |
|---|---|---|---|---|
| ① | 写侧 | `MemoryOS/service/unified/consolidation.py` PROFILE_UPDATE 落地 | 画像记录 `valid_to = now`（零时长区间），`current_profile` 过期判定即丢 | 写 **NULL**（开放区间） |
| ② | 服务读侧 | `MemoryOS/service/unified/profile.py::current_profile` | 只投 4 类 `PROFILE_FACETS`，`facet=SUMMARY` 被 `continue` | 新增 `summary` 分节（`facet=SUMMARY and scope=PROFILE`）；**明确排除** ROLLUP 的 `scope=DAY/WEEK` |
| ③ | Atlas 读侧 | `Atlas/core/atlas/memory/recall_context.py::_format_profile_block` | 只渲染 4 节，不渲染画像正文 | sections 加 `("总览", profile_data.get("summary"))` |
| ④ | 评测 harness | `Atlas/scripts/memory_v1/eval_scenarios.py` | 只拼 `relevant_memory_block`，**漏拼 `profile_block`**；生产 `run_phases._phase_context` 是拼的 → harness 失真 | 补注入（靠前稳定位，与生产一致） |

## 2. 证据（真跑，非推测）

### 2.1 端到端（真服务 + 真 HTTP）
`GET /v1/unified/profile` 实测返回：
```
memories.valid_to = None                              ← ①生效（原 = now）
keys 含 "summary"，profile_summary_records=1
  - memory:mem-profile-40feb3b5c0ee | 用户常住杭州，从事跨境电商工作。女儿叫小满，今年6岁。
ROLLUP_DAY（scope=DAY）未混进画像 ✓
```
### 2.2 生产路径召回（全量评测日志）
```
conversation_id=s21_query profile_refs_count=1 profile_tokens=123
assembled_refs=['memory:mem-profile-9bc946715355']
```
修复前同一场景 `profile_refs_count=0 profile_tokens=0`。

### 2.3 判分（judge）
场景 **#21**（反思者画像提炼与逐句出处溯源）：**FAIL → PASS**，两次全量跑都 PASS。

### 2.4 回归
- MemoryOS `tests/unified_memory`：**408 passed / 0 failed**
- Atlas `core/tests/unified_memory`：**198 passed**；2 failed 在 `test_repair_baseline.py`
  （R00 返工线比 HEAD 与旧基准，已用 `git stash` 证明与本改动无关）
- 新增断言：MemoryOS 3 条（含"ROLLUP 不得混进画像"）、Atlas 1 条

## 3. ⚠️ 全量真数有方差（必须知道，别再误判）

同代码两次全量跑：**17/30**（第一次）与 **19/30**（第二次）；上一棒基线 21/30。
逐场景比对，5 个**非画像**场景出现 PASS→FAIL（#6/#7/#19/#23/#29）。

**根因（已用受控实验证明，非本次改动）**：
- 回归场景全部 `assembled_ref_count: 0`（召回空），但记忆**已正确落库**。
- 真因：**观察者输出语言翻转**。旧跑 `CN 53/EN 7`，新跑 `EN 84/CN 2`。
  `observer_prompt.py` 通篇英文示例（Mastra 移植），temperature 0.3 → 中文会话
  有时输出中文、有时英文。中文 query 匹配不到英文记忆 → 召回空。
- 受控证明：`git stash` 掉本次**全部**改动、纯基线重跑 #6，召回**照样空**。
- 附带：`formation.py`（unified 管线）落库**从不写 `memories_fts`**（只有老管线
  `candidate_ingest.py` 写），FTS 通道恒空，召回实际只靠 `_exact_channel`（**ASCII 词匹配**，
  见 `retrieval.py:427`）——所以中/英语言错配直接致命。

### 3.1 三次跑逐场景方差表（硬证据）

| 场景 | OLD(21/30) | RUN1(17/30) | RUN2(19/30) | 判定 |
|---|---|---|---|---|
| #6 | PASS | FAIL | PASS | 漂移（语言翻转，第二次翻回） |
| #7 | PASS | FAIL | PASS | 漂移（同上） |
| #19 | PASS | FAIL | FAIL | 漂移（同源，两次都没翻回） |
| #21 | FAIL | **PASS** | **PASS** | **修复稳定正向** |
| #23 | PASS | FAIL | FAIL | 漂移（同源） |
| #29 | PASS | FAIL | FAIL | 漂移（同源） |

其余 **24/30 场景三次完全稳定**。#19/#23/#29 两次跑都 `assembled_refs=[]`（召回空），
与 #6/#7 同源，只是采样未翻回。

**结论**：本次修复正确且对画像类场景稳定正向（#21 两次 PASS）；5 个回归是既有采样方差
+ 召回通道脆弱性，属**独立缺口**，未在本任务掩盖或顺手改。

## 4. 遗留待办（独立缺口，建议单独立项）

1. **观察者输出语言不稳**：observer prompt 应加"与输入同语言"指令
   （`observer_prompt.py`），否则中文会话记忆变英文、精确召回全废。
2. **FTS 通道恒空**：`service/unified/formation.py` 落 memories 时未同步
   `memories_fts`，召回只剩 ASCII 精确通道。补齐后可大幅降低语言错配的杀伤。
3. **评测只对有预置历史的场景触发反思者**（`eval_scenarios.py` `_run_reflection`
   仅 #21/#24/#25/#27 走到），其余场景永不生成画像 → 生产有画像、评测无，仍失真。
4. 评测分数方差需在 S8 判定里按"多次取中位"或固定种子处理，否则 21/17/19 波动会误导验收。

## 5. 复现命令

```
# 端到端（真服务 + 真 HTTP）
cd /d/MemoryOS && PYTHONUTF8=1 service/.venv/Scripts/python.exe <e2e脚本>

# 全量评测
cd /d/Atlas
PYTHONPATH="D:/Atlas/core" core/.venv/Scripts/python.exe \
  scripts/memory_v1/eval_scenarios.py --all \
  --isolated-dir <隔离目录> --output <输出.json> --judge
```

证据：`artifacts/memory-v1-s8/scenario_eval_results_profilefix{,2}.json`、
`docs/plan/MEMORY-V1/eval/scenario_judge_report.json`。
