# 记忆系统验收记录

## M2 — 打回

- 验收对象：`origin/mem-m2@5ffb1a16e7bdf73733198beefe8d2f581e04a3b0`
- 对照依据：`docs/memory/survey/VERDICT.md` 顶部「Claude 定稿」及 `TASKBOOK-M2.md`。
- 文件范围：差异仅涉及 `source_ref.py`、`sources.py`、`store.py` 与 M2 契约/结果文件，符合 M2 文件所有权。
- 静态核对：`SourceRef` 身份包含会话与消息 UID；来源对象不含 transcript 正文；旧时间引用仍按近似精度处理；规范 metadata 字段与未知字段 round-trip 已实现。
- 发现的问题：`core/atlas/memory/library/sources.py:235-236` 的 `search_raw` 返回完整 SessionDB 消息正文到 `text`，并在缺少 snippet 时以完整正文填充 `snippet`。M2 任务书要求原文搜索只返回来源指针和匹配摘要，点开时再从 SessionDB 读取原文。请改为有界匹配摘要，不把完整消息正文放入搜索结果。
- 未通过项：M2 结果文件自身说明，现有 `schedule_turn` 只传会话与时间戳，新提炼条目不会自动得到精确 `source_ref`；真实 Atlas 模型会话、工具调用引用、手改 metadata 后重建索引、删除派生索引后的恢复、旧时间引用和失效来源行为均未完成端到端验收。结果文件报告的 8 个 W2 用例和临时 SessionDB smoke 不替代这些门。
- 处理要求：S3 将精确 `SourceRef` 接入新条目写入与 `/api/memlib` 元数据视图，并修正 `search_raw` 正文输出后，在隔离临时数据目录用当前真实模型完成 M2 任务书的最小真实使用验收。逐项记录 UID 定位、tool 引用、metadata 手改/索引重建、原文删除边界及不含正文的日志证据，再提交新的 M2 验收结果供复验。
- 证据边界：本次完成了差异与任务书静态核对；没有启动 Atlas/M2 集成运行，也没有发起真实模型对话，因此不把实现分支中的临时 SessionDB smoke 或历史测试记为本次通过。

## A0

- 状态：等待 `A0 DONE` 及主机验收所需的部署/运行证据。
- 当前 `origin/ui-redesign` 的 `docs/memory/build/A0-RESULT.md` 将远端推送后 tip、主机 pull、`AtlasDev` 重启、8765 与真实运行观察列为待执行，并以「部分完成」结束；不据此记录 A0 通过。
