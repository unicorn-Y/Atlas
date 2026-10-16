# M9 实施结果

基线：`origin/mem-m2`，冻结接口提交 `6b64ded7f0186de89248c7c5fdbcb786d4af2b4fb`。

## 实现

- 新增 `core/atlas/memory/library/association.py`，唯一源码文件。
- 导出 `parse_wikilinks(text)`, `build_link_index(store)`, `expand_one_hop(seeds, link_index, limit)`, `rank_associations(seeds, candidates)`；一跳候选结构与 M5 对齐：`page_path`, `via_page`, `link_text`, `seed_id`, `seed_source_ref`, `reason`, `rank_reasons`。
- `[[Page]]` 与 `[[Page#section|alias]]` 解析保留原始 link 文本；代码、注释中的伪链接不作为导航。目标以页面标题、文件名、路径及别名解析；归一化忽略大小写和空白。不存在或歧义目标记录为 orphan，不创建目标页。
- 索引每次从 `MemoryStore.pages()/read()` 与可用时的 `diary_pages()`、当前 Markdown 原文重建；历史区不生成边。链接来源 Entry 存在 `source_ref` 时透传，没有来源时保持为空。索引不落盘、不写 Markdown、不持有 transcript。
- 仅扩展直接链接目标；已在 seeds 中的页面与重复目标排除。关联排序维持 M5 seed 顺序，不改写 M5 分数。`association_ppr_enabled = False`；本轮未实现 PPR 算法。

## 验证与边界

- `python -m py_compile core/atlas/memory/library/association.py`：通过。
- `git diff --check`：通过。
- 未运行单元测试或独立模拟对话。
- 真实 Atlas 查询、日志、人工编辑后重建、孤立/断链、forget 后清理、PPR-off 路径及删除 `.index.sqlite` 后一致性，须在 M5 接线后的真实使用验收中完成；本结果不将这些集成 gate 记为通过。

M9 DONE
