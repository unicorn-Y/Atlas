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
- 只读 pull 预检：`D:\Atlas` 当前有 40 个本地变更/未跟踪路径；相对当前 HEAD，`origin/ui-redesign` 有 26 个变更路径，路径交集为 0。该项只说明当前路径清单未见重叠，不替代最终 `git pull --ff-only` 结果；尚未执行 pull。

## M2 — 集成版复验通过

- 验收对象：`origin/mem-integrate@07ae2b1a827303e2f749e7d4bad9054a147977fe`（包含 M2、M3、M5 接线/修正）。
- 真实模型：隔离临时数据根 `D:\atlas-memory-e2e-data`，沿用主机模型配置与凭据读取机制，未改写主机配置或 `D:\Atlas\data`。使用 `gemini-3.8-flash` 通过临时后端真实 `/ws/chat` 生成用户断言和工具观察条目。
- 精确来源：用户断言条目通过 conversation + message UID 的 `open_ref` 精确打开；工具观察条目通过 conversation + tool message UID + tool_call_id 精确打开。成功结果均带回对应消息 UID。
- metadata/index：对真实模型产生的 `model_inference` 条目手工改为 `user_assertion` 并设置 `valid_from=2026-10-16`、`valid_to=2026-11-16`；删除临时库 `.index.sqlite` 后重建，搜索和 page API 返回修改后的级别、日期及来源引用，exact open 成功。另验证旧时间引用返回 approximate、伪造的失效来源返回 `ok=false`。
- 原文搜索/API：`/api/memlib/search`、`page`、`open` 均返回预期状态/来源信息；原文搜索结果只含有界匹配摘要（`text == snippet`，长度 136），没有把完整 SessionDB 消息正文放入结果。
- 日志正文边界：在隔离临时运行日志中检索本轮用户断言、工具观察和唯一测试标记，均为 0 命中；不把无正文日志之外的其他敏感信息范围扩大推断。
- 判定：M2 任务书所列的精确引用、tool 引用、人工 metadata 修订与派生索引恢复、旧引用精度、失效引用、受限原文摘要门通过。临时环境缺少 `fastembed`，因此不把向量嵌入可用性列为已验证。该判定仅针对 M2 验收门，不代表整套系统可上线；M1 另有下节记录的真实运行阻断。

## M1 — 打回（真实工具失败路径崩溃）

- 验收对象：`origin/mem-integrate@07ae2b1a827303e2f749e7d4bad9054a147977fe`。
- 证据：真实 `gemini-3.8-flash` 工具会话中，`local_file` 与 `tool_search` 成功后 `project_note` 失败；后端随后在 `core/atlas/kernel/loop.py:1488` 抛出 `UnboundLocalError: cannot access local variable 'consecutive_tool_failures' where it is not associated with a value`，该会话未正常完成。另有日志写入错误：`record()` 将 hook payload 内的 `run_id` 与位置参数重复传给 `append_run_event`，产生 `TypeError: append_run_event() got multiple values for argument 'run_id'`，事件写入被丢弃。
- 处理要求：修正嵌套工具结果消费函数对失败计数的闭包赋值，并在追加 run event 前剔除或显式处理 payload 的 `run_id`；推送后重跑真实模型工具失败/重试路径，确认会话正确收敛且运行事件链完整，再提交 M1 DONE 供验收。
- 判定：拒绝 M1 DONE / 总体验收；这是集成版的真实运行缺陷，不以静态检查、单个成功工具会话或单元测试替代修复证据。

## M8 — 契约一致性退回预警（等待正式 DONE）

- 对照依据：`VERDICT.md` 顶部「Claude 定稿」要求 gate pass 后自动晋升候选，并在每日变更后重跑 heldout、失败时回滚；`M8-RESULT.md` 与 S3 集成结果写明不自动晋升、需要显式用户审阅。
- 判定：当前没有把 M8 记作正式 DONE 验收；但实现/集成说明与定稿合同冲突，必须先统一为更强的 Claude 定稿要求并补齐真实 heldout/回滚证据，才能提交 M8 DONE。若保留人工确认或缺少自动晋升/回滚，M8 将打回。

## 上线门状态（2026-10-16）

- A0：`origin/ui-redesign` 的结果仍为部分完成，主机 pull、`AtlasDev` 重启、8765 与无 mock 的真实工作流证据待执行；不拉取到含用户未提交改动的主机工作树。
- S3：`origin/mem-integrate@07ae2b1a827303e2f749e7d4bad9054a147977fe` 的集成结果明确写明真实运行验收待执行且 M1–M8 均未 DONE。该提交不足以触发最终 rebase/push/主机 pull。
- 其他任务：M3、M4、M5、M6、M7、M8、M9 的远端结果仍标记真实使用或集成门待验收；没有把实现完成误记为验收通过。
- 总体判定：当前不可上线。阻断项至少包括 A0 主机验收未完成、M1 真实工具失败路径崩溃、多个任务的真实运行门未过，以及 M8 与 Claude 定稿合同的冲突。待 S3 和任务所有者修正/补齐并更新共享结果后继续 S4。
