# TASKBOOK-M7：变化事实、纠正与遗忘传播

状态：待后续授权施工。本文件是合同，不表示已实现。

## 目标与来源

表达同一事实的多版本、有效时间和系统获知时间，支持用户纠正、取代和遗忘。参考 Graphiti `graphiti_core/edges.py:EntityEdge`、`utils/maintenance/edge_operations.py:_extract_edge_timestamps/resolve_extracted_edge/_dedupe_extracted_edge` 与 `temporal_edge_utils.py` 的 valid/invalid 与 created/expired 双时间和冲突失效；采用 `Cognee:resolve_temporal_contradictions` 的 supersedes lineage 思路。Graphiti/Cognee 仅借规则，不引入图数据库；Graphiti future normalization 有语言/模式限制，不能当通用时间事实解析。

## Atlas 目标与替换

目标 `core/atlas/memory/library/models.py` Claim/Fact 与 `extract.py` 冲突候选、`dream.py` 整合以及 forget/delete propagation。替换当前无法区分“事实何时有效”和“Atlas 何时知道”的单一时间/简单覆盖语义；规范写入由 M4 提交。

## 契约

每条 claim 有 recorded_at、valid_from/to、source_ref、source_level、confidence、status、supersedes/retracts。来源原文中的时间表达和解析结果同时保留；模糊/非支持语言不钳制成确定日期。高等级证据控制当前显示，但低等级原文和旧 claim 留历史。用户显式纠正生成新 claim 并标记旧项 superseded；forget 产生传播请求，沿 derivation links 删除/重建摘要和索引，并按隐私决策保留最小 tombstone 防再导入。不得以 Mem0 vector UPDATE history 冒充事实双时间。

## 数据迁移

旧记录 valid time 未知则 null/unknown，不回填为创建时间；保留旧正文和引用。先生成只读冲突报告，再以来源可确认的记录渐进补 lineage；不可确认项不自动合并。

## 最小真实使用验收

真实对话中同一偏好先后纠正一次，并记录工具观察与模型推断冲突：当前 recall 显示用户纠正，历史与来源仍可审计；设置将来生效/过去失效事实各一例；删除后查验文件、索引、摘要和技能候选均传播，日志含 tombstone/删除结果且重启后不会复活。

## 依赖与并行

依赖 M2 SourceRef；可与 M1/M3 并行但先冻结 Claim schema。M4 消费本任务 supersedes/retracts contract；M8 需读取撤回事件。
