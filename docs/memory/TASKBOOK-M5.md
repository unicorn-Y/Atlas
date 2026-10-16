# TASKBOOK-M5：分层召回、引用与使用反馈

状态：待后续授权施工。本文件是合同，不表示已实现。

## 目标与来源

为 Atlas 提供短总览、检索和按需下钻。参考 `mem0ai/mem0@0724291bd864cf807e88ee8981c8226644e8fb42:mem0/memory/main.py:Memory.search/_search_vector_store` 的语义 overfetch + lexical/BM25 + entity/lemma boost + rerank fallback；`mnemostack/mnemostack@1d8dc160c06276b49c598e29cef3efbaf17d2559:src/mnemostack/recall/flow.py:recall_flow` 与 `retry.py:retry_weak_recall` 的统一流水线/有界 query reformulation（retry 默认关闭）；Claude-Mem 的三级按需检索行为；Codex `citations.rs` 与 usage stats（官方拆解）作为精确引用/采用统计参照。Supermemory pinned `ccf048586919b7a555c117c439ec327386237b35` 的 MCP 是远端 API façade，不可作为后端实现来源。OpenViking `119eba57db8a2fe7d5c8b7bb400d2e2b032a6825` 根 AGPL，仅观察层级读取思路，不复制代码。

## Atlas 目标与替换

目标 `core/atlas/memory/library/index.py:MemoryIndex.search/sync`、`hybrid.py` 与 `run_phases.py` 现有 recall 接线；新增/收敛到 `recall.py:RecallRouter` 和 `citations.py`。保持 Atlas UI/API 兼容，统一原本分散的关键词/向量检索排序及引用格式。

## 契约

输入包含 query、scope、当前任务状态和 token budget；结果按摘要/claim/原文三层返回，带 claim ID、rank reason、source refs、temporal state。排序合并 lexical + semantic + exact entity/time filters；rerank 失败回原排序。记录曝光、引用打开、实际采用、显式 helpful/unhelpful 与 task outcome；未采用不删除事实。低命中时仅在配置启用后做最多两次受约束改写，不放宽 tenant/权限/validity filters。无候选安全返回空并解释。

## 数据迁移

从现有 SQLite FTS/vector 重建索引，不迁移搜索缓存作为事实。对旧 memory 无 source ref 标低可信/legacy，并允许读但不宣称可回溯。使用统计新增独立 event 表或 JSONL，不改变事实正文。

## 最小真实使用验收

真实任务中检查关键词、语义、实体/时间过滤各一个例子；每条结果可打开准确原文；reranker/embedding 失效时可退回；权限过滤不会被 query retry 放宽；日志能区分曝光、引用、使用和反馈。检查重复使用统计不重复累计同一事件。

## 依赖与并行

依赖 M2 SourceRef；M9 可提供可选关联候选。与 M4 文件提交实现并行，独占 recall/index adapter 文件，不修改 store/dream。
