# TASKBOOK-M3：来源分级的增量提炼

状态：待后续授权施工。本文件为施工合同，不表示已实现。

## 来源与目标

参考 `mem0ai/mem0@0724291bd864cf807e88ee8981c8226644e8fb42:mem0/memory/main.py:_add_to_vector_store` 的同 scope 有限上下文 + 新消息 ADD-only 与 `configs/prompts.py:ADDITIVE_EXTRACTION_PROMPT`；结构化抽取、previous extraction 和 transient retry 参考本轮核验的 `mastra-ai/mastra@a15924e709dd5d9439a6c102901c326ab0ec77fb:packages/memory/src/observational-memory` Observer。Mem0 hash 仅覆盖 top-10 召回结果和当前 batch，不是全局幂等。Basic Memory core `a72751c5d626380dedeed30f55f7a80ba3dc710d` 为 AGPL-3.0-or-later，只作行为参考。M3 必补 memU 等未核候选证据，不将缺项写成胜者。

Atlas 目标 `core/atlas/memory/library/extract.py:SYSTEM_PROMPT/build_messages/apply`、`__init__.py:_extract_full/_apply`。替换“只接受用户原话”的过滤和提炼时直接写 canonical pages；保留 secret scrub、临时状态及可用队列。

## 契约与数据迁移

等级 `user_assertion > tool_observation > model_inference`，三类皆可记录并附证据；推断不得伪装成观察。提炼只生成候选，不覆盖旧事实。幂等键 `(source_event_id, extractor_version)`。解析失败、空候选、部分写入都不得标 committed。旧结果无等级标 `legacy_unknown`；有原文补 M2 引用，无原文不造。

## 最小真实使用验收

真实隔离会话含用户事实、工具返回、模型推断与重复 hook：核对等级和精确引用；同 event/version 重跑不新增重复；失败可重试且不静默消费 pending；已有事实只生成候选不覆盖。记录模型与 prompt 版本、抽取及持久化日志。

## 依赖与并行

依赖 M2。可与 M1、M7 并行，但只改 extract/candidate adapter。M4 等候选契约冻结；M8 消费已验证经验。
