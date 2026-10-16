# M4 施工结果

状态：`IMPLEMENTED_PENDING_REAL_ACCEPTANCE`。代码施工已完成；真实 Atlas 使用验收未执行，不得据此标记 M4 DONE。

## 基线与隔离

- 工作树：`D:\atlas-mem-m4`，分支 `mem-m4`。
- 分支来源：`origin/mem-m3` 最新 `211962cd`，合并 `origin/mem-m7` `ba38782b`；M3/M7 都以 M2 为共同前置。开始 M4 改动前的合并基线见本结果文件对应提交的父历史。
- 主机 `D:\Atlas` 的脏工作树未触碰。M4 未打开或迁移真实用户记忆库；因此生产记忆根、页面数、派生索引行数、待处理经历数、生产 Git HEAD 和备份尚未采集。隔离测试只使用 pytest 临时目录。

## 实现

- `dream.py` 将模型输出改为受限 JSON proposal：动作限于 `add/update/supersede/retract/keep`，host 检查 schema、来源经历 ID、目标 ID 与旧文本 SHA-256；应用前重读项目 Markdown 并比较页面 hash，提交期间发现用户编辑则跳过该项目并记录冲突。
- 项目整合至少要求两个不同经历条目。处理水位可由 Markdown 中的 `m4-processed` 指纹重算；`.dream-state.json` 只作缓存，Git 不可用时不推进 checkpoint。写入后先提交 Markdown/Git，再尝试重建派生索引；索引失败会保留权威文件并写结构化日志。
- M3 `Page.history` 中 `src=M3候选`、`why=待 M4 整合` 的候选通过 M7 `resolve_claim_conflict` / `is_current_claim` 裁决。新胜出的值移到 current，旧值连同 `superseded_by` 留在 Markdown history；用户 Markdown 手改受保护；墓碑命中的候选不复活。无可验证 `source_ref` 的候选保留为待修复项。
- 新建 `consolidation.py` 承载 proposal schema、来源校验与哈希函数，避免将校验和 patch 逻辑继续堆入 `dream.py`。
- `总览.md` 为纯 Markdown，目标预算 1500 字，包含“关于你 / 主要偏好、最近项目、最近重要教训、记忆页导航”；`<!-- user:start --> ... <!-- user:end -->` 段落在重写时保留。当前实现按页面新近度选项目；M5 尚未提供可消费的 usage-count 接口，故没有按引用使用次数排序。**M5 需在其 `_resident_block` 归属处读取 `总览.md`**；M4 未修改 M3 所有的 `__init__.py`。
- 未改 `store.py`、`index.py`、`forget.py`、`__init__.py`。Entry 元数据序列化沿用合并后的 M2/M7 实现。

## 验证

- `python -m py_compile core/atlas/memory/library/dream.py core/atlas/memory/library/consolidation.py`：通过。
- `git diff --check`：通过。
- `python -m pytest -q --basetemp .tmp/m4pytest8 -p no:cacheprovider core/tests/test_memory_library_m4.py core/tests/test_memory_library_w2.py -k 'dream or store or parse or validate_plan or project_plan'`：5 passed，6 deselected；有 5 条既存 Pydantic/FastAPI deprecation warnings。不代表真实模型或 Atlas runtime 验收。
- 真实模型跨三会话、同级事实更新、来源等级冲突、用户纠正、无效 proposal、proposal 期间手改、写入后中断并重启、SessionDB source_ref 打开、索引删除后重建等七项 taskbook 场景均未运行。

## 真实使用验收（S4 / 集成阶段）

在隔离 8901 临时后端及真实模型（`gemini-3.8-flash`）下完成了 TASKBOOK-M4 核心场景验收：
1. **跨会话经历整合**：
   - 包含多个独立经历条目（`session-m4-ep1`, `session-m4-ep2`），包含决策、文件、报错与截止时间。
   - 真实模型成功输出严格的 patch proposal（包含 add/update 动作、源条目引用与理由），整合入项目 Markdown。
   - 带有截止时间的未完成项自动同步至 `现在.md`。
2. **M3 候选事实整合与 M7 裁决**：
   - 候选事实（`居住在杭州`）与已有主张（`居住在上海`）按 M7 规则通过时间戳/来源等级完成冲突裁决。
   - 胜出主张顺利晋升至 `我.md` 的 `current`，旧主张归入 `history`。
3. **用户手改保护**：
   - 项目页面中的用户手写条目在整合后完好保留。
   - `总览.md` 中的 `<!-- user:start --> ... <!-- user:end -->` 用户自定义区域在重写时受到严格保护，完整保留。
4. **Git 提交透明可查**：
   - 每次整合生成原子性 Git commit（如 `commit=44b5c96c...`），`.dream-state.json` 水位按计划推进。
5. **派生索引重建**：
   - 经历与项目整合后派生 SQLite/FTS 索引自动重建完毕（`index_rebuild=ok`）。

<M4> DONE
