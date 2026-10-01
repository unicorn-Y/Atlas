# ATLAS-W11-EFFICIENCY-SKILLS-CODING（第十一波：效率、技能、编程）

> **冻结 / 拆分（2026-10-01）**：主体优先。第 1、2 节（按需加载、压缩）随 Hermes 内核在 C1 带进来；第 4 节插件 → C4；第 5 节服务商 → C5；第 6 节编程 → C6；第 3 节技能市场冻结。见 `docs/plan/00-MASTER-PLAN.md` 第五节。

STATUS: READY（W08 交付后）
PROTOCOL: +1
先读：`docs/plan/SOURCE-MAP.md` A、D、G 节；`docs/research/2026-09-30-landscape/07-context-and-cost.md`、`09-coding.md`
主要来源：H（Hermes）

## 本波目标

- **工具多了也不浪费**：工具按需加载（MCP 和连接器接多了以后必需）。
- **长对话更省更稳**：H 的上下文压缩。
- **技能和插件生态**：一条命令装 skills.sh / ClawHub / GitHub 上的技能，装之前自动安全扫描；兼容 Claude Code 插件。
- **模型接入更全**：国内服务商全套 + 多密钥轮换。
- **编程**：LSP、PR 审查、扫描配方。

---

## 1. 工具按需加载（后端，从 H 搬）

**来源**：H `tools/tool_search.py`（583 行）、`tool_search_catalog.py`、`tool_search_validation.py`。H 的做法：MCP / 插件工具和一部分不常用的核心工具，在发给模型的工具列表里换成三个桥接工具 `tool_search / tool_describe / tool_call`；核心工具永远不延迟；目录每次从当前工具定义重建（不按会话缓存，避免漏工具）；桥接调用走正常的工具分发（照常过审批）。

**做法**：搬到 `core/atlas/tools/tool_search.py`；配置 `tools.defer: "auto"|"off"`、`tools.defer_threshold`（工具定义总 token 超过多少才启用，默认 8000）；Atlas 的核心工具清单写在配置里；**注意不要破坏 W06 的提示缓存**（工具列表在一个 run 内保持不变）。

**测试**：搬 H 对应测试。

## 2. 上下文压缩（后端，从 H 搬）

**来源**：H `agent/context_engine.py`（250 行，可插拔的压缩引擎接口）、`agent/context_compressor.py`（5673 行：用便宜的辅助模型总结中间轮次，保护开头和结尾，**先剪工具输出**，按 token 预算保留结尾，迭代总结）、`context_compressor_summary.py`、`conversation_compression_archive.py`（压缩前的原文归档）、`conversation_compression_reply_anchor.py`、`compression_marker.py`；`micro_compaction.py`（H 默认关闭，因为每次都会破坏提示缓存——Atlas 也默认关闭）。

**做法**：
1. 用 H 的 `ContextEngine` 接口替换 Atlas 现有的压缩（`agent/enrichment.py` 的 `should_compact / compact`、`agent/__init__.py` 的 `compact_context`）。
2. 只搬需要的部分（5673 行的门面不要整个拷）：规则优先（先剪旧工具输出）、保护头尾、辅助模型总结、原文归档（压缩掉的内容存档，需要时可以查）。
3. 压缩用 `agents.fast_model`。
4. 手动压缩（Atlas 已有）走同一个引擎。

**测试**：搬 H 的压缩测试；长对话压缩前后关键信息仍在。

## 3. 技能市场 + 安全扫描（后端，从 H 搬）

**来源**：H `tools/skills_hub.py`（417 行，门面：路径、受保护的 HTTP、索引缓存、锁文件、审计日志）+ `skills_hub_search.py`、`_install.py`、`_skillssh.py`（380 行，skills.sh）、`_clawhub.py`（577 行，ClawHub）、`_github.py`、`_official.py`、`_sources.py`、`_models.py`；`tools/skills_guard.py`（849 行：外部技能的正则静态扫描 + 按信任分级的安装策略：内置不扫、可信来源允许「需注意」、社区来源有任何发现就拦，除非强制）；`skills_ast_audit.py`、`skill_linter.py`、`skill_provenance.py`、`skillevaluator_scan.py`。

**做法**：
1. Atlas 已有技能注册、发现、联邦、信任、回滚。把 H 的市场适配器（skills.sh、ClawHub、GitHub、官方）接进 Atlas 的技能发现；搜索结果标来源和信任级别。
2. 安装前的安全扫描（H `skills_guard`）不做（安全审查由用户亲自负责，本计划不做）；安装前把技能的文件清单和脚本原文给用户看。
3. 记录每个技能的来源（`skill_provenance`）。
4. 技能页「市场」标签：搜索、安装、更新、卸载。

## 4. 插件（兼容 Claude Code 格式）（后端，从 H 搬）

**来源**：H `hermes_cli/plugins_discovery.py`（已能识别 `.claude-plugin`）、`hermes_cli/plugins*.py`、`plugins/AGENTS.md`（插件种类和兼容约定）、`tools/plugin_guard.py`；Claude Code 插件市场格式（仓库里的 `.claude-plugin/marketplace.json`，每个插件的 `.claude-plugin/plugin.json`，含 skills / agents / commands / hooks / MCP 配置）——动手前查 Claude Code 官方文档确认字段。

**做法**：
1. 插件市场：`GET/POST/DELETE /api/plugins/marketplaces`（git 仓库地址或 `owner/repo`，只允许 https 和 GitHub 简写），拉取到数据目录 `marketplaces/`，`POST .../{id}/refresh` 更新。
2. `GET /api/plugins/marketplaces/{id}/plugins`：名称、说明、版本、作者、包含的组件。
3. `POST /api/plugins/install {marketplace_id, name, dry_run=true}`：**先返回清单**（每个技能、子 Agent、Hook、MCP 服务器，尤其是 Hook 命令和 MCP 启动命令的原文），用户看过后再 `dry_run: false` 安装。安装后技能、子 Agent（W07 的定义文件）立即可用；**Hooks 和 MCP 服务器默认停用**，要用户单独打开。
4. `plugin_guard`、`skills_guard`、`osv_check` 不做（安全审查由用户亲自负责，本计划不做）。

## 5. 模型服务商全套 + 多密钥轮换（后端，从 H 搬）

**来源**：H `plugins/model-providers/`（每个服务商一个目录：qwen-oauth、alibaba、alibaba-coding-plan、kimi-coding、deepseek、zai、stepfun、minimax、xiaomi、ollama-cloud、openrouter、gemini、vertex、bedrock、azure-foundry、xai、nvidia、huggingface……）、`agent/provider_registry.py`、`provider_base.py`、`models_dev.py`（模型目录）、`model_metadata.py`；`agent/credential_pool.py`（3131 行，多密钥轮换、按模型冷却）+ `credential_pool_*.py`。

**做法**：
1. Atlas 现在通过 litellm + 一个 OpenAI 兼容网关调模型。保留 litellm 作为底层，把 H 的服务商目录搬成 Atlas 的「添加服务商」向导：选服务商 → 填密钥（或 OAuth，例如通义） → 自动列出模型和价格（`models_dev.py`）。
2. 多密钥轮换：同一个服务商可以填多个密钥，限流或额度用完时轮换（只搬 `credential_pool` 的核心轮换和冷却逻辑，不搬 Nous 账户相关）。
3. 密钥存系统凭据库。

## 6. 编程（后端从 H 搬 + 自己写）

1. **LSP**（从 H 搬）：H `agent/lsp/`（client、manager、servers、install、protocol、workspace）。Agent 可以用：跳转定义、查找引用、诊断（改完代码自动看有没有新错误）。语言服务器按需安装（Python：pyright / basedpyright；TS：typescript-language-server），装之前问用户。
2. **PR 审查**（自己写，参考 Codex 的代码审查视图、Copilot 代码审查）：`POST /api/git/pr/review {root, number}` → 摘要、风险点、逐行意见（复用 Atlas 现有的 diff 和逐行评论）；用户编辑后 `POST /api/git/pr/review/submit` 发回 GitHub（用 `gh`）。
3. **扫描配方**（自己写，用 W08 的触发器定时跑）：「依赖漏洞检查」（用 OSV，参考 H `tools/osv_check.py`）、「安全扫描」、「死代码清理」，结果列成待办，一键让 Atlas 修。

## 7. 前端

1. 设置 → 工具：按需加载开关和阈值；时间线里 `tool_search` 显示成「查找可用工具：<关键词>」。
2. 压缩：时间线里显示「整理了前面的对话（保留了 <要点数> 个要点）」，可以展开看归档的原文。
3. 技能页「市场」标签：搜索（来源筛选）、安全扫描报告、安装 / 更新 / 卸载。
4. 插件页：市场列表、插件详情、**安装前的清单确认**（Hook 和 MCP 命令原文高亮）、已装插件的启停。
5. 设置 → 模型与服务：服务商向导（图标、密钥 / OAuth、模型列表、价格）、多密钥。
6. 编程：LSP 诊断在改动面板里标出；PR 页「审查」按钮 → 审查结果和逐行意见，可编辑后提交；自动化页里的扫描配方。

## 8. 验收

| 项 | 最强的是 | Atlas 要做到 |
| --- | --- | --- |
| 按需加载 | Claude Code ToolSearch、Hermes、Cursor | H 的做法全部搬到，不破坏缓存 |
| 压缩 | Hermes、OpenClaw tokenjuice | 规则优先 + 归档可查 |
| 技能市场 | Hermes（四个来源 + 安全扫描）、skills.sh | 四个来源 + 扫描报告可视化 |
| 插件 | Claude Code 插件市场 | 兼容格式 + 安装前清单确认 + Hook / MCP 默认停用 |
| 模型 | Hermes（30+ 服务商）、Perplexity（20 个模型） | 国内服务商全套 + 多密钥 + 价格自动带出 |
| 编程 | Codex 代码审查、Devin 扫描 | LSP + PR 审查 + 扫描配方 |

**真机**：接 30 个以上 MCP 工具后，确认发给模型的工具列表变小、任务照常完成；一个 100 轮以上的长对话压缩后还能回答开头的问题；从 skills.sh 装一个技能（看扫描报告）；装一个 Claude Code 插件（看清单）；添加 DeepSeek 服务商并用两个密钥；审查一个真实 PR。

## 9. 交付

同 W06。
