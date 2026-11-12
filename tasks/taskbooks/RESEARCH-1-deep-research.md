# RESEARCH-1 深度调研（deep_research 工具）

日期：2026-10-15　分支：ui-redesign（主机 D:\Atlas）

## 目标

遇到需要查资料的复杂问题（对比、价格、现状、「最新」），Atlas 自动拆子问题 → 多轮 web_search →
挑可信来源 web_fetch 读原文 → 交叉核实 → 给出带编号出处链接的结论。不依赖 Hermes，底层只用
`core/atlas/websearch/`（经 `atlas.tools.web.WebRuntime`）。

## 移植清单（拿来主义，不从零设计）

| 部件 | 来源仓库 / 文件 | 拿了什么 | Atlas 位置 |
|---|---|---|---|
| 递归调研循环 | dzhng/deep-research（MIT）`src/deep-research.ts` 的 `deepResearch` / `generateSerpQueries` / `processSerpResult` | breadth×depth 递归、下一层 breadth 减半、`researchGoal` + `followUpQuestions` 拼下一轮问题、learnings 去重、并发上限 | `core/atlas/research/deep.py` `DeepResearcher._dive` / `_queries` / `_learn` |
| 搜索词规则 | assafelovic/gpt-researcher（Apache-2.0）`gpt_researcher/prompts.py` `generate_search_queries_prompt` | 不用 site:/OR 等运算符、注入当前日期 | `_queries` 提示词 |
| 选源标准 | 同上 `curate_sources` | 相关性 / 可信度 / 时效 / 有数字优先 的评判口径 | `_learn` 提示词 + `_pick_sources` 排序 |
| 来源分级 + 核实结构 | nicobailon/pi-web-access（MIT）`source-check.ts` 的 `classifySource`、`ClaimStatus`、`ClaimAssessment` | official_docs / vendor_docs / repo_issue / news / forum / blog 分级规则（补了中文站点）；supported / contradicted / unclear / missing-evidence 四态 | `classify_source`、`_verify` |
| 交叉核实 | Pi 的 `assessClaim` 只是占位（永远 unclear），这里换成：按「引用了几个不同域名」机器判定 + 模型找冲突 + 对冲突/单一来源的关键结论补一轮定向搜索 | | `_verify` + `_recheck` |
| 最终报告 + 引用规则 | langchain-ai/open_deep_research（MIT）`src/open_deep_research/prompts.py` `final_report_generation_prompt` 的 Citation Rules；GPT Researcher `generate_report_prompt` 的「每个数字都要带引用、只引给定来源、自己下结论」 | | `_report` 提示词 |
| 末尾来源列表 | dzhng `writeFinalReport` 追加 `## Sources` | 由代码按编号生成，模型不能编造链接 | `_render_sources` |

## 接线

- 工具 schema：`agent/tool_catalog.py` 在 web 工具旁加 `deep_research`（question / breadth / depth）。
- 分发：`agent/tool_node.py` 在 web_search 分支旁加 `deep_research`，模型调用走 `agent._model_router.complete_for`
  （模型 = 用户设置 `research_model`，没有就当前模型），进度经 `report_process_output` 流到界面。
- 只读工具名单：`kernel/tools.py`、`kernel/plan.py` 的 `READ_ONLY_TOOLS` 加 `deep_research`。

## 完成标准

真实 Atlas 里问「对比 2026 年主流搜索 API 的价格和质量」→ 调用 deep_research，多轮搜索、读原文，
回答带来源链接。只写少量单测（`core/tests/test_deep_research.py`，假模型 + 假搜索）。
