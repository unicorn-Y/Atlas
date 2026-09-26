# CODEX-ATLAS-P15B-SKILL-DISCOVERY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15A-SKILL-REGISTRY
CODE_BASE_HEAD: fc6451a8053734c528d219c16a4bde19a66f65b2

## Objective

把 P15A 的 Skill Registry 变成真正可用的「技能检索入口」：用户或 Agent 给出自然语言任务后，可以快速、稳定地从本地已注册技能中找到候选技能、查看为什么匹配、筛选能力与工具，并直接进入现有 Skill 使用/激活路径。

本阶段重点是 **发现与检索**，不是安装或远程市场。

## Scope

### 1. Discovery Query Contract

建立独立的 Discovery 查询层，基于 P15A Registry，不绕过 Registry 直接扫描数据库。

至少支持：

- free-text query
- exact skill name
- capability filter
- tool filter
- status filter（默认 active）
- source/provenance filter
- limit / pagination

查询必须返回稳定结构，至少包含：

- name
- version
- description
- capabilities
- tools
- requirements
- source
- status
- deterministic relevance score
- match reasons / matched fields

### 2. Deterministic Relevance Ranking

实现无需 LLM 的确定性检索排序，至少区分：

1. 完全匹配 skill name
2. name / alias / keyword 命中
3. capability / tool 命中
4. description / examples 命中
5. requirements 等辅助字段命中

要求：

- 同一 Registry + 同一 query 得到相同顺序。
- 分数相同时使用稳定 tie-break（name、version 等）。
- disabled / invalid 技能默认不进入可用候选。
- 不允许因为排序而改变 Skill 的权限或执行能力。

可以使用轻量 tokenization / normalization / BM25-like lexical scoring；不要在本阶段引入必须联网的向量服务。

### 3. Discovery Metadata Extension

如果 P15A 现有 metadata 不足以支持高质量检索，可以向后兼容地增加可选字段，例如：

- aliases
- tags
- category
- keywords
- use_cases

要求：

- 老 Registry 数据可以正常读取。
- 新旧 Skill metadata 不得破坏 P15A API。
- metadata 扩展仍受 secret validation 约束。

### 4. Discovery API

提供面向 Agent/UI 的独立检索接口，例如：

- `GET /api/skills/discover`
- `GET /api/skills/discover/{name}` 或等价的详情接口

具体路由可根据现有 API 结构调整，但不得破坏：

- `/api/skills`
- `/api/skills/search/{query}`
- `/api/skill-registry/*`

Discovery API 必须支持结构化 JSON 输出，方便后续 Planner/Agent 调用。

### 5. Frontend Skill Center

在现有 Atlas 前端增加一个真正可用的 Skill Discovery 入口：

- 搜索框
- 结果列表
- 能力/工具/来源等筛选
- 匹配原因或命中字段展示
- Skill 详情
- 明确显示版本、状态、依赖/requirements
- 对已经存在的本地 Skill 提供进入现有 activate/use 路径的入口

要求：

- 不自动安装远程 Skill。
- 不因为搜索结果自动执行工具。
- 不改变现有审批边界。
- 搜索失败不能阻塞正常聊天。

### 6. Agent-Facing Discovery Primitive

提供一个可被 Agent/Planner 显式调用的 discovery primitive，使 Agent 可以：

> 根据“我要完成什么任务”检索候选 Skill → 得到结构化候选 → 再决定是否使用。

本阶段只负责返回候选，不自动把候选注入执行上下文，也不自动激活。

### 7. Provenance / Explainability

每个 Discovery 结果必须能够解释：

- 为什么命中
- 命中了哪些字段
- 来自哪个 Registry source
- 当前版本与状态

不得伪造“适合度”或生成无法追溯的推荐理由。

## Non-Goals

本任务明确不实现：

- Skill 自动安装、更新、卸载。
- 远程 Skill Marketplace / Catalog Federation。
- GitHub / skills.sh 等外部来源的实际下载。
- 自动 Skill 选择或 Planner 强制注入。
- 内置 MCP runtime。
- Bundled Node。
- 一键依赖修复/安装。
- 语音、视觉、摄像头、手机端进一步开发。
- 远程设备配对或 LAN 认证。

这些能力由后续 P15C/P15D/P15E/P15F 等阶段处理。

## Compatibility / Safety Rules

- P15A Registry 是本阶段的事实来源，不创建第二套 Registry。
- Discovery 只读 Registry；搜索不得改变 Registry 状态。
- Discovery 不授予工具权限。
- disabled/rejected/invalid 技能不得作为默认可用候选。
- 不存储 API key、token、密码等秘密。
- 不绕过现有 approval / capability / tool execution gate。
- 不修改 MemoryOS 事实生命周期。
- 不要求联网才能搜索本地 Registry。
- 外部 catalog 缺失或不可用时，本地 Discovery 仍必须可用。

## Acceptance Criteria

必须验证：

1. 自然语言 query 可以返回相关本地 Skill 候选。
2. exact name、capability、tool、description 等查询路径均可用。
3. 排序确定性：相同数据 + 相同 query → 相同结果顺序。
4. score 相同情况下 tie-break 稳定。
5. disabled/invalid Skill 默认不会出现在 active Discovery 结果中。
6. 结果包含 match reasons / matched fields 和 provenance。
7. 旧 P15A Registry 数据可以无迁移错误地被 Discovery 读取。
8. 现有 `/api/skills`、`/api/skill-registry/*` 保持兼容。
9. Agent-facing discovery primitive 可以被显式调用，但不会自动执行或自动激活 Skill。
10. 前端可以搜索、筛选、查看详情，并进入已有 Skill 使用路径。
11. 搜索失败、空结果、Registry 不可用时 UI 有明确状态且正常聊天仍可用。
12. 新增测试覆盖 ranking、filters、determinism、disabled exclusion、provenance、API contract 和 frontend discovery flow。
13. `git diff --check` 通过。
14. 新增/修改代码范围通过 Ruff；前端测试和 production build 通过。
15. 不引入必须联网才能工作的本地 Discovery 依赖。

## Delivery

- Read `LUNA_WORKER.md` first.
- Pull `origin/main` before implementation.
- Execute only this taskbook.
- Record implementation and validation in:
  `tasks/results/CODEX-ATLAS-P15B-SKILL-DISCOVERY.result.md`
- Commit intended code and result according to repository workflow.
- Push to `origin main`.
- Verify local HEAD equals `origin/main`.
- Stop after P15B; do not start P15C.

## Queue Intent

P15B 完成后，下一阶段应进入 **P15C Skill Catalog Federation / Acquisition**：把本地 Registry 与可验证的外部 Skill 来源连接起来，形成“搜索到 → 检查 → 明确授权后安装”的完整生态入口。

安装必须与 Discovery 分离，不能因为搜索结果自动下载或执行。
