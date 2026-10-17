# Atlas 知识库（骨架，2026-10-17）

## 目的

把强模型（Claude Code / Codex / Atlas 接的强模型）的会话经验存下来、提炼出来，换成任何模型（本地 Qwen、DeepSeek 等）都能读着干活。
原则：**模型可换，资产在外面**。微调权重换模型就作废，这里的东西不会。

和记忆库（`data/memory`，`core/atlas/memory/library`）的分工：记忆库记「用户是谁、在做什么」；知识库记「活怎么干」。两者独立，以后召回时一起拼进上下文。

## 三层

| 层 | 位置 | 内容 | 给模型看吗 |
|---|---|---|---|
| 原始档案 | `data/knowledge/raw/<source>/` | 会话日志原样存档 | 否，只当原材料 |
| 提炼层 | `data/knowledge/curated/{事实,技能,决策,案例}/*.md` | 一条一个文件，frontmatter 带 source/model/tags | 是，检索后注入 |
| 评测集 | `data/knowledge/evals/*.jsonl` | 真实活的题目 + 判分标准 | 换模型时跑 |

索引 `.kb.sqlite`（FTS5 trigram）是派生物，随时 `POST /api/knowledge/reindex` 重建。

## 已做（骨架）

- `core/atlas/knowledge/`：`KnowledgeBase`、`KnowledgeStore`（写条目、全文检索、计数）、`importers.py`（claude-code / codex 原样镜像，可重复跑，按大小+mtime 跳过）。
- `core/atlas/api/knowledge_router.py`：`/api/knowledge/{stats,search,import,item,reindex}`，已在 `application.py` 注册。
- 配置：`[knowledge] enabled = true`、`root = ""`（默认 `DATA_ROOT/data/knowledge`）。

## 下周要做（按顺序）

1. **提炼器 `distill.py`**：raw → curated。拿来主义——照 Codex 记忆管线（主机 `D:\_deliverables\官方拆解汇总\Codex-Official\03-SOURCE\codex-rs\memories`：phase1 每会话出 raw_memory + rollout_summary，phase2 整合 Agent 合并成文件）和 ExpeL / Agent Workflow Memory 的「从成功/失败轨迹提炼规则和工作流」。先解析 Claude Code jsonl（user/assistant/tool_use/tool_result）和 Codex rollout。用强模型提炼，去掉试错噪音，只留结论、流程、决策、好案例。
2. **内核工具 `knowledge_search`** + 召回：照记忆库 `memory_search` 的接法，在 `run_phases` 里按任务检索若干条注入；技能类可以接到现有 skills 体系。
3. **Atlas 自己的会话导出**：从 state.db 导出到 raw/atlas，形成闭环（Atlas 接强模型时的好轨迹自动沉淀）。
4. **向量检索**：复用记忆库 W2 的 fastembed（bge-small-zh）+ hybrid，别另造。
5. **评测集 + 跑分**：几十道真实任务，换模型时自动对比。
6. **界面**：记忆页旁边加「知识库」页，看各层数量、浏览/编辑条目、手动触发导入和提炼。

## 注意

- Claude / OpenAI 条款禁止用输出训练竞品模型；这里只做检索参考，不拿去微调。以后真要微调，老师选许可宽松的（DeepSeek MIT、Qwen）。
- 原始档案里有隐私和密钥，导入后提炼时要过滤；raw 目录别同步到别处。
