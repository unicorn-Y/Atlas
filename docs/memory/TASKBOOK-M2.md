# TASKBOOK-M2：来源事件与精确原文指针

状态：待后续授权施工。本文件为施工合同，不表示已实现。

## 来源与目标

Atlas `session_sync.py:message_uid` 作为 canonical identity；参考 Codex pinned `openai/codex@a45b8ccb016fb74f63a6bc29e701568e387cbe38` 的 rollout/citation 与 AMA `tool.py:traj_get/traj_find`。审查发现仅用 turn_id 会在不同 trajectory 重复时歧义，因此不照搬。

目标：`core/atlas/memory/library/session_sync.py`、`models.py` / `store.py` 引用字段及新增 `source_event.py`。替换仅用 session 粗粒度或缺 message_uid 的映射；旧数据兼容但不造指针。

## 契约与数据迁移

`SourceRef={source_kind, conversation_id, message_uid, tool_call_id?, span_start?, span_end?, trajectory_id?, payload_hash}`。唯一身份至少包含 conversation/trajectory 与 message UID；签名覆盖完整身份、内容 hash 与 span。支持精确读取和有界查找，读取前检查权限。旧记录能从 Atlas session/message 索引确认时补真实 UID，否则标 legacy。相同 turn_id 不可用来猜 trajectory。

## 最小真实使用验收

使用两条 turn_id 相同但 trajectory 不同的会话引用，分别打开正确原文；span 精确定位；源正文变化时检测 hash mismatch；无权 delegate 不能经引用接口读取；日志能由 claim ID 追到 message/tool result。

## 依赖与并行

A0 后首个前置，先冻结接口。M1/M3/M4/M5/M6/M7/M9 均依赖；实施时独占 source model/store 文件，其他任务不得并改。
