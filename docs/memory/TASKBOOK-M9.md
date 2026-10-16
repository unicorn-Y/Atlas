# TASKBOOK-M9：页面联想与轻量图排序

状态：待后续授权施工。本文件是合同，不表示已实现。

## 目标与来源

在显式 Markdown `[[links]]` 上提供实体/证据联想，不改变事实真源。参考 A-MEM pinned `ceffb860f0712bbae97b184d440df62bc910ca8d:agentic_memory/memory_system.py:add_note/find_related_memories/process_memory` 的邻居建议，但其更新可能错索引且 consolidation 前仅在内存，故只用提案范式。参考 HippoRAG 2 pinned `d5c8329422e0a0b834a15874545cb6a74b4f9b26:src/hipporag/HippoRAG.py:graph_search_with_fact_entities/run_ppr` 的 seed-weighted PPR；本线审查已更正：仓库函数名 `run_ppr` 调 graph library 方法 `personalized_pagerank`，不是项目自定义同名方法。Cognee/Graphiti 只提供邻接/hybrid 对照。

## Atlas 目标与替换

目标 `core/atlas/memory/library/index.py:MemoryIndex.sync/search` 与 `hybrid.py`；新增轻量 link index / `association.py`。替换仅靠单一向量相似度扩展上下文的路径；不接 Neo4j，不从关联分数改写事实或时间状态。

## 契约

链接来自显式 Markdown ref、共同 source/claim entity 或用户认可关联；模型新增链接为待审 proposal。查询 seed 经 M5 权限/时间过滤后做限深关联扩展；PPR 为可选排序器，记录 seed/权重/算法版本，空 seed、无边或超预算安全退回 M5 原排序。返回原因、连接路径和来源引用，不无限遍历。

## 数据迁移

从已有 `[[Page]]` 解析可构建只读 link index；失效目标保留原文字并列 repair，不自动重命名/改写用户页面。关联权重/访问计数均可重建或单独迁移，不作为事实。

## 最小真实使用验收

真实查询中各选一个显式链接、共同来源和无关联 seed：前两者可解释地扩展，后者稳定回退；删除/改名目标后不生成虚假路径；限制预算后响应可结束；关联候选不改变原 claim 内容、来源等级或有效时间。

## 依赖与并行

依赖 M2 与 M5 query/filter contract；可与 M4 并行，独占 link/association 文件与读取排序 adapter，不修改 Markdown 写协议。
