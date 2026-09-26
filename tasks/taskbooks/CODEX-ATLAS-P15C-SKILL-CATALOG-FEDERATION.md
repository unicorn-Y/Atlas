# CODEX-ATLAS-P15C-SKILL-CATALOG-FEDERATION

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15B-SKILL-DISCOVERY
CODE_BASE_HEAD: b596aa1fb578f9810bbab5c4784cdcceb9f20d78

## Objective

把 Atlas 的本地 Skill Discovery 扩展成一个真正可用的 **Skill Catalog Federation + Acquisition** 能力：

> 本地技能搜索 → 外部目录搜索 → 查看来源/内容/审计/哈希 → 安全预检 → 用户明确授权 → 原子安装 → 写入 P15A Registry → 本地 Discovery 可立即发现。

本阶段第一次允许 Atlas 获取第三方 Skill，但必须把“发现”和“安装”彻底分开。

核心原则：

**搜索可以自动；预览可以自动；安装必须明确授权；安装前不执行第三方 Skill；安装后也不得绕过现有 capability / approval 边界。**

## Scope

### 1. Catalog Provider Abstraction

建立统一的只读外部 Catalog Provider 接口，不让 UI 或 Agent 直接耦合某一个网站。

Provider 至少支持：

- search(query, filters, pagination)
- get_detail(external_id)
- get_files/extract_payload(external_id)
- optional get_audit(external_id)
- provider health / unavailable 状态

统一返回结构至少包含：

- provider
- external_id
- name
- description
- source
- source_type
- version（若来源提供）
- source_url / install_url
- remote_hash（若来源提供）
- audit summary（若来源提供）
- provenance
- pagination information

Provider 失败不得破坏本地 Registry / Discovery。

### 2. First External Provider: skills.sh

实现一个 skills.sh Provider，优先使用其公开 HTTPS API，而不是依赖 `npx skills` CLI。

至少覆盖：

- Catalog search
- Skill detail
- Skill file payload
- remote hash（若提供）
- security audit information（若提供）
- pagination / rate-limit / 404 / 429 / 5xx handling

要求：

- 网络失败时给出明确的 external-catalog-unavailable 状态。
- 不把第三方目录结果直接写入本地 Skill Registry。
- 外部搜索结果必须明确标记为 remote / uninstalled。
- Provider 数据只能作为候选与预览来源。

### 3. Optional Direct GitHub Acquisition

为没有可用 Catalog 条目的公开 GitHub Skill 提供直接来源解析能力。

至少支持用户明确提供：

- public GitHub repository
- repository + skill path

解析后必须定位一个合法 `SKILL.md`，并构造与 Catalog Provider 相同的 normalized acquisition record。

本阶段不要求 private GitHub。

不得接受：

- 任意本地路径作为远程来源
- `file://`
- 未验证的压缩包 URL
- 任意 HTTP 下载后直接解包执行

### 4. Unified Catalog Search

扩展 Skill Center，使用户能够切换：

- Local
- External Catalog
- All

要求：

- Local 搜索继续完全离线可用。
- External 搜索明确显示网络状态。
- All 模式不得把 remote 候选伪装成 installed/local Skill。
- 已安装的外部 Skill 可以显示“已安装”以及当前本地版本/来源。
- 相同外部 skill identity 必须可稳定去重。

### 5. Skill Preview / Review Gate

在任何安装动作之前，展示一个完整 Review 页面/面板，至少包含：

- name / version
- description
- source / provider
- repository / source URL
- file list
- `SKILL.md` 内容预览
- supporting files
- remote hash
- computed local payload hash
- security audit result（如有）
- validation result
- detected risks / warnings
- declared dependencies
- whether the skill already exists locally
- exact install target

第三方内容必须被视为 **untrusted input**。

Preview 本身不得：

- 激活 Skill
- 注册 Agent capability
- 执行 Skill 内脚本
- 安装 Python/npm/system dependencies
- 修改 Registry active 状态

### 6. Acquisition Security Gate

建立确定性的安装前安全检查。

至少检查：

#### Manifest

- `SKILL.md` 存在
- frontmatter 可解析
- name / version / description 合法
- name 与目标目录 identity 一致
- metadata 不包含 API key/token/password/credential 等秘密

#### Filesystem

拒绝：

- 绝对路径
- `..` path traversal
- 解包后逃逸目标目录的路径
- symlink / junction 等可能逃逸安装根目录的对象
- 超出文件数量限制
- 超出单文件 / 总 payload 大小限制

#### Content

扫描并报告：

- credential / secret patterns
- suspicious shell / PowerShell / cmd execution instructions
- install-time commands
- network download commands
- attempts to alter Atlas config / approval / memory / capability state
- obvious prompt-injection instructions aimed at overriding Atlas system rules

这里的扫描结果是 **risk evidence**，不能声称“绝对安全”。

至少形成：

- PASS
- WARN
- BLOCK

三态结果。

**BLOCK 不允许继续安装。**

WARN 必须进入显式确认页面，由用户再次确认后才能安装。

### 7. Hash / Provenance Binding

安装必须形成可追溯的 provenance record。

至少保存：

- provider
- external_id
- source URL
- fetched_at
- remote_hash（若有）
- computed_sha256
- installed_at
- installed_path
- manifest name/version
- security gate result
- user approval event id / timestamp

如果来源提供 hash：

- 必须计算本地 payload hash。
- hash 不一致时直接 BLOCK。
- 不得用“内容看起来一样”替代 hash 校验。

### 8. Staged + Atomic Install

禁止直接把网络返回内容写进正式 `skills/` 目录。

安装流程必须是：

1. fetch
2. stage 到隔离临时目录
3. validate
4. security scan
5. hash
6. 用户明确 approve
7. atomic move/rename 到正式 Skill 目录
8. 注册到 P15A Registry
9. refresh SkillManager
10. 重新运行本地 Discovery

任何中间步骤失败：

- 正式 Skill 目录不得留下半成品。
- Registry 不得留下 active 半成品记录。
- 临时目录必须清理。

### 9. Registry Integration

P15A Registry 继续是本地安装状态的事实来源。

安装成功后注册 metadata 至少包含：

- name
- version
- description
- capabilities
- tools
- requirements
- examples
- aliases / tags / category / keywords / use_cases
- source = 外部 provider + stable external identity
- provenance / hash metadata

不得创建第二套“installed registry”。

如果同一 `name + version` 已存在：

- 不得静默覆盖。
- 必须展示 existing vs incoming provenance/hash。
- 由明确的 install/replace action 决定。
- 默认选择保持现有版本不变。

### 10. No Auto-Activation / No Auto-Execution

安装完成后：

- Skill 可以被 SkillManager 扫描到。
- Skill 可以进入 Registry / Discovery。
- 不得自动执行其内容。
- 不得自动调用其 tools。
- 不得自动安装其 declared dependencies。
- 不得自动把远程 Skill 转换成新的高权限 capability。

用户后续主动使用 Skill 时，仍必须走现有 Atlas capability / approval / tool execution boundary。

### 11. Agent-Facing Acquisition Primitive

提供一个显式的 Agent-facing primitive，例如：

`skill.catalog.search`
`skill.catalog.inspect`
`skill.catalog.install`

但权限边界必须严格：

- `search`: 可自动调用，返回候选。
- `inspect`: 可自动调用，返回 preview + risk evidence。
- `install`: **必须要求显式用户 approval**，不能由普通 Agent invocation 自动完成。

Agent 不得通过修改输入参数绕过 approval。

### 12. Frontend Acquisition UX

Skill Center 增加：

- Local / External / All tabs
- external search state
- provider/source labels
- remote / installed badges
- detail preview
- security/audit section
- file tree
- hash/provenance section
- Install button
- explicit confirmation modal
- BLOCK / WARN / PASS visual state
- install progress
- success/failure state
- already-installed / version-conflict state

正常聊天必须与 Catalog 网络故障隔离。

### 13. Catalog Cache

允许建立轻量本地 Catalog cache，但必须明确区分：

- external cache
- canonical local Registry

缓存：

- 不能授予 execution rights。
- 不能成为本地 installed state 的事实来源。
- 应尊重 provider cache/rate-limit semantics。
- cache stale 时必须标记，不得伪装为实时数据。

### 14. Compatibility / Safety Rules

必须保持：

- P15A Registry API 兼容。
- P15B local Discovery API 兼容。
- existing `/api/skills` 兼容。
- existing SkillManager activation path 兼容。
- existing Agent capability / approval boundary 兼容。

严禁：

- 自动安装。
- 自动激活。
- 自动执行第三方 Skill。
- 自动安装依赖。
- 通过 catalog result 直接授予工具权限。
- 把外部内容写入 MemoryOS 事实层。
- 把 secrets 写入 Registry。
- 为了“方便安装”引入新的长期明文 token/password 存储。

### 15. Non-Goals

本任务不实现：

- Skill 自动更新/升级策略。
- Skill 自动卸载/回滚 UI。
- 全自动 Skill 选择。
- Planner 强制注入外部 Skill。
- MCP Runtime。
- Bundled Node。
- 一键依赖修复。
- 私有 GitHub OAuth 登录。
- 云端账户系统。
- 远程设备配对。
- 语音、视频、摄像头。
- MemoryOS 生命周期修改。

这些进入后续阶段。

## Acceptance Criteria

必须验证：

1. skills.sh Provider 可以搜索并返回 normalized catalog results。
2. Provider detail 可以取得 Skill payload/preview。
3. provider unavailable / 429 / 5xx 时本地 Discovery 与正常聊天仍可用。
4. external result 与 local installed state 可稳定区分。
5. public GitHub source 可以被明确指定并解析到合法 `SKILL.md`。
6. Preview 阶段不修改 Registry、不激活 Skill、不执行第三方内容。
7. Manifest validation 可以拒绝非法 Skill。
8. path traversal / absolute path / symlink / oversized payload 等攻击路径有测试并被拒绝。
9. secret / credential 检测可以阻止写入。
10. security gate 正确产生 PASS/WARN/BLOCK。
11. remote hash 与 computed hash 不一致时安装被阻止。
12. 安装前必须存在可审计的 explicit user approval。
13. 安装使用 stage + atomic move，不产生半成品正式 Skill。
14. 安装成功后 Registry provenance/hash/source 完整可追溯。
15. 安装后本地 Discovery 可以找到 Skill。
16. 安装不会自动激活、执行或安装依赖。
17. 同一 name+version 冲突不会静默覆盖。
18. Agent `search/inspect/install` primitive 权限边界正确，install 无 approval 不可执行。
19. Frontend 可以完成 external search → preview → approval → install → result 状态展示。
20. 本地搜索在无网络情况下继续工作。
21. P15A/P15B API regression tests continue to pass.
22. New backend tests cover provider normalization, failures, security gate, path safety, hashing, approval, atomic install, provenance, conflicts, and Agent gate.
23. Frontend tests cover external/local separation, preview, approval modal, blocked/warn/pass states, install success/failure, and network failure isolation.
24. `git diff --check` 通过。
25. 新增/修改 Python 代码通过 Ruff。
26. Frontend tests and production build pass.
27. No required runtime dependency on `npx skills` or Node for the acquisition backend.
28. No secret/token is persisted in Skill Registry, catalog cache, or acquisition records.

## Delivery

- Read `LUNA_WORKER.md` first.
- Pull `origin/main` before implementation.
- Record the actual starting HEAD as BASE_HEAD.
- Execute only this taskbook.
- Record implementation and validation in:
  `tasks/results/CODEX-ATLAS-P15C-SKILL-CATALOG-FEDERATION.result.md`
- Commit intended code and result according to repository workflow.
- Push to `origin main`.
- Verify local HEAD equals `origin/main`.
- Stop after P15C; do not start P15D.

## Queue Intent

P15C 完成后进入 **P15D Skill Lifecycle & Trust Management**：

- install/update/remove/rollback
- trust state
- version pinning
- provenance history
- dependency state
- safe downgrade/rollback
- lifecycle audit trail

P15C 只负责“外部找到 → 检查 → 明确授权 → 安全安装”，不要把完整生命周期提前塞进本阶段。
