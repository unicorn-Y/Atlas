# CODEX-ATLAS-P15A-SKILL-REGISTRY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P14-AGENT-ECOSYSTEM-AND-MULTIMODAL
CODE_BASE_HEAD: a71032a62dd7371e01ddfbb4364259d3cd7168fe

## Objective

建立 Atlas 的 Skill Registry 基础层，使技能成为可描述、可持久化、可查询的独立能力单元，为后续 Skill Discovery、Skill Lifecycle、MCP Runtime 和依赖管理提供稳定基础。

本任务只建立 Registry，不提前实现后续阶段的自动选择、安装分发或 MCP runtime。

## Scope

### 1. Skill Metadata Contract

定义稳定的 Skill 元数据结构，至少包含：

- name
- version
- description
- capabilities
- tools
- requirements
- examples

要求：

- 明确必填与可选字段。
- name + version 具备确定性身份。
- 无效或缺失关键字段的 Skill 不得进入 active registry。
- 不得把凭据、API key、token 等秘密写入 registry。

### 2. Persistent Registry

建立持久化 Registry，支持：

- register
- get
- list
- disable/remove

要求：

- 重启后数据保持。
- 重复注册同一身份必须具有确定性行为。
- list 结果稳定排序。
- 无效记录不能污染 active registry。
- 与现有 Skill/Agent capability 数据兼容；不得破坏既有接口。

### 3. Registry API

提供最小可用 API：

- 注册 Skill
- 获取单个 Skill
- 列出 Skill
- 查询 Skill 状态

API 返回结构应稳定、可供前端和后续 Agent Discovery 使用。

### 4. Deterministic Search Primitive

在 Registry 层提供基础查询能力：

- name
- description
- capability
- tool

要求返回确定性排序结果。

本阶段只提供查询原语，不把查询结果自动注入 Planner/Executor。

### 5. Provenance and Validation

Registry 记录应能够追溯：

- Skill identity
- version
- registration source
- registration/update time
- validation status

验证失败的 Skill 必须明确处于非 active 状态。

## Non-Goals

本任务明确不实现：

- 自动 Skill 选择或 Planner 自动编排。
- Skill marketplace / remote marketplace。
- Skill 自动安装、更新、卸载工作流。
- 内置 MCP runtime。
- Bundled Node。
- 一键依赖修复/安装。
- 语音、视觉、摄像头、手机端的进一步开发。
- 远程设备配对或 LAN 认证。

这些能力由后续 P15B/P15C/P15D/P15E 或后续产品阶段处理。

## Compatibility Rules

- 不修改 MemoryOS 的事实生命周期规则。
- 不绕过现有审批/权限边界。
- Skill Registry 本身不授予工具执行权限。
- Registry 数据只能描述能力；工具执行仍走现有审批和 capability 边界。
- 不把 pending/rejected 内容当作 active Skill。
- 不引入新的秘密存储机制。

## Acceptance Criteria

必须验证：

1. 有效 Skill 可以注册并持久化。
2. 无效 Skill 被拒绝或保持非 active。
3. 重启后 Registry 内容保持一致。
4. 重复注册行为确定且不会产生重复 active identity。
5. list/search 顺序稳定。
6. get/list/search API 返回结构稳定。
7. Registry 与现有 Agent capability/Skill 接口兼容。
8. Registry 操作不会改变事实、审批状态或工具权限。
9. 新增测试覆盖注册、校验、持久化、重复注册和查询。
10. `git diff --check` 通过；新增/修改代码范围通过 Ruff 检查。

## Delivery

- Read `LUNA_WORKER.md` first.
- Pull `origin/main` before implementation.
- Execute only this taskbook.
- Record implementation and validation in the result file:
  `tasks/results/CODEX-ATLAS-P15A-SKILL-REGISTRY.result.md`
- Commit intended code and result according to repository workflow.
- Push to `origin main`.
- Verify local HEAD equals `origin/main`.
- Stop after P15A; do not start P15B.
