# M2 施工结果

分支：`mem-m2`；基线：`origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。施工隔离在 `D:\atlas-mem-m2`，未改 `D:\Atlas`。

## 已完成

- 冻结 `SourceRef`、Markdown provenance 字段、`open_ref` / `memory_open` 签名与下游视图要求，见 `CONTRACT-M2.md`。`SourceRef` URI 决定为版本化 `atlas://source/v1` 查询格式；来源等级取 `user_assertion`、`tool_observation`、`model_inference`、`legacy_unknown`。S3 开工信号已推送至 `origin/mem-m2`。
- 新增 `source_ref.py` 值对象与严格 URI 编解码；没有 transcript 正文字段。
- `open_ref` 支持按 `(conversation_id, message_uid)` 精确打开并返回精度，支持工具调用 ID；无法精确还原 span 时返回整条消息并标 `span_applied=false`。旧 `conversation@ISO-time` 仍可打开并标 `precision=approximate`。
- `search_raw` 改为输出精确 UID 引用。`memory_open` 提供只读 Python 入口，现有 `memory_search(open=...)` 路径保持兼容。
- `Entry` 增加七个规范 metadata 字段；旧 `src/at/until/expires` 可映射到来源等级、记录时间和有效截止时间；未知 JSON metadata 保留 round-trip。手写条目按用户陈述，不能确认的旧来源等级为 `legacy_unknown`。
- 基线 `session_sync.py` 已含 message UID 映射、按会话和 UID 查询来源证据及原文读取能力；审计确认符合 M2 精确身份要求，因此未重复改写该文件。

## 验证

- `core/tests/test_memory_library_w2.py`：8 passed。
- 临时 SessionDB smoke：两个 conversation 使用相同时间戳、不同 message UID；精确引用分别返回对应消息。Markdown provenance 的旧字段映射和未知 metadata round-trip 通过。此为临时 SessionDB 验证，不是两条真实 Atlas 会话的模型端到端验收。
- 新增/修改代码的 Ruff 检查通过（`store.py` 忽略基线既有 E501）；`compileall` 与 `git diff --check` 通过。

## 未完成的集成验收

- 当前 W2 `schedule_turn` 只给记忆写入队列传入会话与时间戳，不能由 M2 安全推导新 Entry 的精确 UID。按文件所有权，M2 未改 M3 所有的 `library/__init__.py` / `extract.py`。S3 消费本合同后需让写入器传入精确 `SourceRef` 并把七个字段加入 `/api/memlib` 视图；在该集成前，新写入 Entry 的 `source_ref` 不会自动出现。
- 未运行真实 Atlas 模型生成两条会话并完整打开/改写/重建索引验收；此项保留给后续集成和 S4 验收，不宣称通过。

## 提交

- 契约开工信号：`6b64ded7`（已推送）。
- 最终实现提交见本结果文件所在分支远端 tip。

M2 DONE
