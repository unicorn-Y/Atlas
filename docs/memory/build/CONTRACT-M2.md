# M2 接口冻结合同

状态：冻结（S3 可依此开始）。基线：`origin/memory-w2-api@aa14c3173392d0fc60ec3e401e4495a2d3357cb7`。

## 数据约束

- `SourceRef` 是 SessionDB 原文的指针，不存储、不缓存 transcript 正文。其身份键严格为 `(conversation_id, message_uid)`。
- URI 格式：`atlas://source/v1?conversation_id=<urlencoded>&message_uid=<urlencoded>[&tool_call_id=...&span_start=...&span_end=...&content_hash=...&observed_role=...&observed_at=...]`。必填身份字段各恰好一次；未知字段、重复字段或无效 span 拒绝解析。可选字段为 `tool_call_id: str`、成对的 `span_start/span_end: int`、`content_hash: str`、`observed_role: str`、`observed_at: ISO-8601 str`。
- Markdown 行内 JSON 元数据在现有 `Entry.line()` 的 HTML 注释中保存并 round-trip 下列键：
  - `source_level: Literal["user_assertion", "tool_observation", "model_inference", "legacy_unknown"]`
  - `recorded_at: ISO-8601 str`
  - `valid_from: ISO-8601 str | None`、`valid_to: ISO-8601 str | None`
  - `supersedes: list[str]`、`retracts: list[str]`
  - `source_ref: SourceRef JSON object | None`（不存正文；旧 `ref` 保持可读兼容）
- `Entry` 必须同时保留未识别的 JSON 元数据键；手工编辑的规范字段从 Markdown 回读生效。`legacy_unknown` 是缺少可信来源证据时的唯一默认，不推断等级或有效起始时间。
- `session_sync.session_message_evidence(home, conversation_id, message_id)` 保持原签名；给定 conversation 时按会话与 UID 精确定位，返回 UID、role、timestamp 元数据，不以时间近似匹配。

## 打开接口

```python
def open_ref(
    ref: SourceRef | str,
    window: int = 1,
    *,
    engine_root: str | Path | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]: ...

def memory_open(
    ref: SourceRef | str,
    window: int = 1,
    *,
    engine_root: str | Path | None = None,
) -> dict[str, Any]: ...
```

`open_ref` 与 `memory_open` 同步、只读。新 URI 必须只读指定 conversation/message UID 及有限邻近上下文；工具消息用 `tool_call_id` 关联。若 span 无法保真定位则返回整条消息，不得捏造字符范围。旧 `conversation@ISO-time` 仅兼容打开并在返回值标为 `precision="approximate"`；不得静默升级 UID。未找到会话/消息如实报告来源不可用。现有 `memory_search(open=...)` 调用兼容入口；不增加独立来源账本。

## 下游消费约定（S3）

- 新建记忆条目的 `source_ref` 存 `SourceRef.to_dict()` 结果；对模型/用户暴露的 `ref` 值用 `SourceRef.to_ref()` URI。只有没有精确 UID 的历史条目才继续暴露旧 `conversation@ISO-time`。
- 记忆页与 `/api/memlib` 条目视图需返回上述七个规范 metadata 字段（含 `source_ref`），手工编辑并重建索引后读回 Markdown 中的值；不要从 SQLite 等派生索引补写权威字段。
- `memory_search(open=<ref>)` 保持兼容。`memory_open(ref, window=1, *, engine_root=None)` 是可直接调用的只读 Python 入口，位于 `atlas.memory.library.sources`；本次不另注册重复的模型工具。

## 初始 Python 类型

`core/atlas/memory/library/source_ref.py` 已提供冻结的 `SourceRef` 值类型、字典序列化和 URI 编解码。S3 可立即依此消费。此合同先冻结；若后续确需变更，只能在文末追加「变更」并同步 S3。

## 变更

（暂无）
