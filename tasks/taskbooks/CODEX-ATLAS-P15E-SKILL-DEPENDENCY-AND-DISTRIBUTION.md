# CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT
CODE_BASE_HEAD: ba1e56de6d627bbbee428143d369536824a28e9d

## Objective

在已经通过 P15A Registry、P15B Discovery、P15C Catalog/Integrity、P15D Lifecycle/Trust 的基础上，把 Skill 的 dependency 与 distribution 做成可真实使用的最小闭环。

目标不是做大型包管理器。

目标是：

搜索/获取 Skill
-> 安全预检
-> 明确看到依赖
-> 依赖可验证
-> 缺失依赖不会被偷偷执行
-> 用户明确批准后才能执行需要安装/变更环境的动作
-> Skill package 可导入/分发
-> provenance/version/hash/lifecycle 保持完整

## Existing baseline

优先复用当前已有实现：

- SkillRegistry
- SkillManager
- skills/acquisition.py
- skills/lifecycle.py
- MCPClient
- 当前 Skill Center
- 当前 source/version/hash/trust/provenance 记录

当前 SkillManager 已能检查三类依赖：

- MCP servers
- Python packages
- system commands

当前 P15D lifecycle 已提供：

- audited install/update/downgrade/rollback/remove
- trust/pin
- drift detection
- dependency state
- server-side approval

不要另造第二套 Skill Registry、第二套 lifecycle、第二套 approval。

## Scope

### A. First-class dependency model

把 Skill dependency 从“检查结果”提升为稳定的结构化 dependency contract。

最少支持：

- mcp_servers
- python_packages
- commands

每项依赖至少能表达：

- name
- kind
- requested/version constraint when declared
- detected
- state
- source
- blocking reason

状态至少保持：

- satisfied
- missing
- incompatible
- unknown

禁止把 unknown 当 satisfied。

禁止通过自动猜测安装来源来绕过检查。

### B. Dependency preflight

在 Skill inspect / Skill Center 中提供明确的 dependency preflight。

必须能够回答：

1. 当前 Skill 需要什么；
2. 哪些已经满足；
3. 哪些缺失；
4. 哪些版本不兼容；
5. 哪些状态无法确定；
6. 哪些依赖会阻止 Skill 使用。

预检不得修改环境。

Agent 可以读取 dependency 状态，但不能自行批准依赖安装或环境修改。

### C. Explicit dependency acquisition

为缺失依赖建立最小“准备依赖”路径，但必须保持显式用户批准边界。

规则：

- MCP server：只允许从已登记/受信任的 server configuration 准备；
- Python package：必须明确 package 名称与来源；安装动作进入现有 Policy/Approval 边界；
- system command：不得因为 Skill 声明缺失就自动下载并执行任意安装脚本；
- 不允许 Skill 内容自己决定提权、执行 shell 安装、下载未知二进制；
- 任何安装失败都留下结构化结果，不伪装成 satisfied。

第一版可以只实现“生成依赖准备计划 + 用户确认后执行已支持的安全 adapter”，不要为了覆盖所有生态而做通用包管理器。

### D. Distribution / package import

增加最小 Skill package distribution 能力。

支持从受控本地 package/bundle 导入 Skill。

Package 至少包含：

- Skill identity
- version
- manifest
- payload
- dependency declaration
- source/provenance
- content hash

导入必须复用 P15C/P15D 已有安全检查：

- UTF-8 text validation
- file count/size limits
- path traversal protection
- symlink/junction protection
- manifest validation
- deterministic content hash
- secret detection
- security scan
- lifecycle approval

不得直接把 zip/bundle 解压到 production skills 目录后绕过 Registry。

### E. Distribution provenance

导入/分发后的 Registry 必须保留：

- original source
- package source
- provider
- external ID when available
- version
- computed hash
- fetched/imported timestamp
- user approval reference
- lifecycle state

同 name+version 冲突继续遵守 P15D-FIX1：

- 不覆盖已有不同 identity/hash/provenance；
- deterministic conflict；
- filesystem 与 Registry 原子保持。

### F. Dependency-aware activation

Skill Center / activation 前必须能明确发现 blocking dependencies。

规则：

- satisfied -> 可以继续现有 activation path；
- missing/incompatible -> 阻止直接 activation，并给出具体 dependency；
- unknown -> 不得假装满足；根据 dependency kind 进入安全的 blocked/needs-review 状态；
- trust revoked/blocked、lifecycle drift、quarantine 等 P15D 规则继续优先生效。

不得通过前端隐藏 dependency blocker 来“强行打开”。

### G. Minimal UI

只补 Skill Center 必需入口：

- dependency summary
- preflight result
- missing/incompatible blocker
- package import entry
- explicit “prepare/install dependency” flow where supported
- result/error state

不要做完整 package marketplace UI。

不要做复杂 dependency graph 可视化。

## Required tests

至少覆盖：

1. all three dependency kinds are parsed;
2. satisfied dependency;
3. missing dependency;
4. incompatible dependency;
5. unknown dependency;
6. dependency preflight is read-only;
7. Agent can inspect dependency state;
8. Agent cannot approve/install dependencies;
9. missing dependency blocks activation;
10. unknown dependency does not become satisfied;
11. explicit dependency installation requires Policy/Approval;
12. arbitrary shell install from Skill content is rejected;
13. package manifest validation;
14. package path traversal rejected;
15. package symlink/junction rejected;
16. package secret detection;
17. package deterministic hash;
18. package source/provenance persisted;
19. package import uses existing lifecycle approval;
20. same name+version conflict does not overwrite;
21. failed package import leaves filesystem and Registry unchanged;
22. existing trust/pin/drift rules remain effective;
23. existing P15A-P15D regression remains passing;
24. Windows-specific dependency/path behavior is covered where applicable.

## Validation

必须执行：

- P15A/P15B/P15C/P15D full regression；
- new P15E dependency tests；
- package import/distribution tests；
- frontend tests；
- production build；
- Ruff；
- git diff --check；
- isolated HTTP smoke；
- dependency blocker smoke；
- package conflict smoke；
- LOCAL_HEAD == origin/main；
- git status clean。

External provider live update is not required unless the implementation actually changes provider code. Do not weaken P15C verification.

## Forbidden

不得：

- 开始 P16；
- 开始 E01 Workflow Distillation / Skill Learning；
- 开始 E02 Generated Tool；
- 新增 remote provider；
- 重做 P15C hash verification；
- 重做 P15D lifecycle/approval authority；
- 新造第二 Registry；
- 新造第二 Approval/Policy system；
- 自动信任外部 Skill；
- 自动安装未知依赖；
- 自动执行 Skill 声明的 shell install command；
- 绕过 lifecycle approval 直接写 production skills；
- 修改已有 lifecycle history；
- 做无关 UI 重构；
- 为了测试向 production skills 目录写临时文件。

## Delivery

1. Read LUNA_WORKER.md first.
2. Pull origin/main.
3. Record actual BASE_HEAD.
4. Read PLAN.md.
5. Inspect the existing SkillRegistry, SkillManager, acquisition, lifecycle, MCP runtime and Skill Center before changing code.
6. Execute only this taskbook.
7. Write:
   tasks/results/CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION.result.md
8. Commit implementation + result.
9. Push origin/main.
10. Verify LOCAL_HEAD == origin/main.
11. Stop.
12. Do not start P16 or E01/E02/E03/E04.

## Queue Guard

P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION is the only READY task.

P16 and E01-E04 remain BLOCKED until this task receives a separate review.

No task may be started automatically after P15E completion.
