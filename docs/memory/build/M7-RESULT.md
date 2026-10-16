# M7 施工结果（未完成真实使用验收）

分支：`mem-m7`，基线 `origin/mem-m2`（含冻结的 `docs/memory/build/CONTRACT-M2.md`）。工作树：`D:\atlas-mem-m7`。

## 变更范围

- `core/atlas/memory/library/claim_resolution.py`（新建）：无状态 `is_current_claim(entry, now) -> bool` 和 `resolve_claim_conflict(existing, proposed) -> dict`。输入为 M3 冻结候选字段 `key,value,source_level,recorded_at,valid_from,valid_to,supersedes,retracts,source_ref` 与现有 Entry metadata；不写 Markdown、不访问数据库或 SessionDB。优先级为明确用户纠正、来源等级 `user_assertion > tool_observation > model_inference > legacy_unknown`、同等级较新的有效 `recorded_at`。相同时间或缺少可信时间时保留既有项。输出含胜者、待标 superseded/retracted 的 ID、原因和给 M4 的元数据建议。
- `core/atlas/memory/library/store.py`：仅改 `Entry` 元数据段。新增冻结字段序列化；保留未知 JSON 键；对已有 `src/at/until/ref` 只做有证据的兼容映射。不能从旧时间引用伪造 UID，无法解析的旧 `ref` 标为 `source_ref_status=legacy_unresolved`。Markdown 手改条目映射为 `user_assertion`；其余缺证条目默认 `legacy_unknown`。不改 Page/MemoryStore 写入协议。
- `core/atlas/memory/library/forget.py`：新增 `propagate_forget(store, entry_refs, derived_manifest)`。可按当前 Entry、历史 Entry ID 或显式文本找遗忘内容；仅删除记忆库根目录内调用方列出的派生路径；收集文本派生行并调用既有 `purge_history`。W0 哈希墓碑仍由 M4 的写入方维护，函数明确返回未写墓碑状态。

## 协作接口与风险

- M5 可传 `Entry` 或 metadata mapping 调用 `is_current_claim`。M4 写入被替代的历史项时应保存 `superseded_by`/`retracted_by`（或 `superseded`/`retracted` 标记），当前性判断同时检查这些标记和 ISO `valid_from/valid_to`。M4 消费 resolver 的 `suggested_metadata` 与 `winner_metadata`；M7 不接线。
- `store.py` 是交接风险点：M2 同时拥有文件级工作，而本分支只实现 TASKBOOK-M7 划定的 `Entry` 元数据段；M4 后续拥有写入事务。集成时按 `M2 → M7 → M4` 保留 M2 的 SourceRef / Markdown 权威实现、M7 的 Entry 字段兼容逻辑、M4 的原子写入协议，不覆盖彼此代码。
- `propagate_forget` 的调用方需在同一写入流程提供完整 Markdown lineage（Entry/ID/原文文本）与记忆库内派生文件清单。函数会提交记忆库工作树变更后改写历史；应由 M4 在目标条目及哈希墓碑写入流程协调调用。当前尚无 M4 call-site。
- M7 只消费已解析的 ISO `valid_from/valid_to`，不实现通用时间表达解析；不确定表达不得转换成猜测日期。M3 原始经历和 SessionDB 指针仍是追溯依据。

## 已执行验证

- 临时 Markdown+Git 根目录：验证用户来源胜过更新的工具来源、同级较新主张胜出、未来/过期时间边界、旧 metadata 和未知键 round-trip、旧 ref 标为 `legacy_unresolved`，并验证通过 Entry ID 遗忘后派生摘要及正文不再出现在可达 Git 历史。通过。
- `python -m pytest core/tests/test_memory_library_w0.py core/tests/test_memory_library_w1.py --basetemp D:\Temp\atlas-m7-pytest -p no:cacheprovider -q`：`16 passed, 5 warnings`。
- `python -m ruff check ... --ignore E501` 与 `python -m compileall -q ...`：通过。未忽略的 E501 均位于本次未改动的既有行。
- `git diff --check`：通过。

## 未验收项

- 未在真实 Atlas 对话中演练用户更正、工具/模型冲突、事实召回、重启及忘记后不复活；临时 Markdown+Git 结果不等于真实运行时验收。
- M4 尚未接线，M5 尚未在该分支消费 predicate；未验证全量索引重建后的真实查询行为。
- 未来计划与不确定自然语言时间的真实提炼路径未验证。M7 不猜测日期。

当前状态：代码自检完成；真实使用验收待 S3/M4/M5 集成后执行。本结果不标记 `M7 DONE`。
