# CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION
REVIEW: tasks/reviews/CODEX-ATLAS-P15E-SKILL-DEPENDENCY-AND-DISTRIBUTION.review.md
CODE_BASE_HEAD: 1fa1c29783304b5c866b06d8d92b9b63a8c89f03

## Objective

修复 P15E 验收发现的两个阻塞问题，只做 bounded rework：

1. structured Skill dependency 在 package import 后必须仍然是可预检、可激活的 canonical dependency contract；
2. package import 必须按 name + version 区分冲突，并正确处理“同名不同版本”。

不要扩展到 P16、Workflow Learning、Generated Tool 或新的 Capability 系统。

## Required fixes

### A. Canonical dependency normalization

当前问题：

core/atlas/skills/acquisition.py::_parse_manifest() 将 structured dependencies mapping stringify 成：

    python_packages: ['requests']

随后 parse_dependencies() 将其视为未知 legacy string。

修复要求：

- 只有一套 canonical normalization；
- 支持当前规范的：
  - dependencies.mcp_servers
  - dependencies.python_packages
  - dependencies.commands
- 支持 P15E 已加入的 named version constraint 形式，例如：
  - {name: requests, version: '>=2,<4'}
  - {name: requests, constraint: '>=2,<4'}
- legacy requirements 字符串继续兼容；
- package manifest 与 SKILL.md dependency declaration 使用同一 canonical representation 比较；
- 安装后 Registry 中的 requirements 必须可以直接被 dependency_preflight() 正确解释；
- 不得把 unknown 误报为 satisfied；
- 不修改 P15C/P15D hash/lifecycle/approval authority。

### B. Package import semantics

将当前过宽的 same name => conflict 改为明确区分：

1. exact name + version exists:
   - deterministic conflict;
   - 不覆盖 Registry；
   - 不覆盖 filesystem；
   - UI 明确提示已存在同版本。

2. same name, different version:
   - 不能作为 identity conflict；
   - 必须进入现有 lifecycle update/downgrade review/approval path，或返回明确的 update_required 状态并让 Skill Center 发起现有 lifecycle update/downgrade；
   - 不允许直接写 production skills；
   - 不允许静默覆盖旧版本；
   - update/downgrade 必须继续绑定 acquisition hash + current hash + server-held decision + one-time approval。

优先复用现有：
- update_skill_lifecycle
- /api/skills/lifecycle/decision
- /api/skills/lifecycle/approve
- /api/skills/lifecycle/update

不要创建第二套 package-update lifecycle。

### C. Frontend

Skill Center package review 至少能区分：

- new Skill import;
- exact version conflict;
- same-name different-version update candidate.

不同版本必须明确显示“这是更新/降级候选”，并走现有 lifecycle approval。

不要做 marketplace 或大型 UI 重构。

## Required regression tests

必须新增并通过：

1. documented structured dependency mapping with Python package;
2. documented structured dependency mapping with command;
3. documented structured dependency mapping with MCP server;
4. structured named version constraint is parsed correctly;
5. legacy requirements remains compatible;
6. package inspection preserves structured dependency semantics;
7. imported package stores dependency metadata that preflight can consume;
8. imported package with satisfied dependencies can activate;
9. imported package with missing dependency remains blocked;
10. imported package with unknown dependency remains blocked;
11. exact same name+version package is rejected without Registry/file overwrite;
12. same name+different version is not reported as exact identity conflict;
13. same name+different version uses explicit update/downgrade lifecycle path;
14. update/downgrade still requires server-held decision and one-time approval;
15. update/downgrade approval cannot be replayed or retargeted;
16. failed different-version package update leaves old Registry/filesystem unchanged;
17. frontend renders exact conflict and update candidate states;
18. P15A-P15E regression remains green.

## Validation

Run:

- P15A-P15E full regression;
- new P15E-FIX1 tests;
- frontend tests;
- production build;
- Ruff on changed files;
- git diff --check;
- isolated HTTP smoke;
- package activation smoke;
- exact-version conflict smoke;
- same-name/different-version update smoke;
- verify LOCAL_HEAD == origin/main;
- verify git status clean.

## Forbidden

不得：

- 开始 P16；
- 开始 E01/E02/E03/E04；
- 新造 Registry；
- 新造 Policy/Approval；
- 绕过现有 lifecycle approval；
- 修改历史 lifecycle event；
- 自动安装未知依赖；
- 静默覆盖同名旧版本；
- 重做 P15C provider hash verification；
- 做无关 UI 重构。

## Delivery

1. Read LUNA_WORKER.md.
2. Pull origin/main.
3. Record actual BASE_HEAD.
4. Read PLAN.md.
5. Read the P15E review and this taskbook.
6. Fix only the two blockers.
7. Write:
   tasks/results/CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT.result.md
8. Commit implementation + result.
9. Push origin/main.
10. Verify LOCAL_HEAD == origin/main.
11. Stop.
12. Do not start P16 or E01-E04.

## Queue Guard

P15E-FIX1 is the only READY task.

P15E is not accepted until this fix receives a separate review.

P16 and E01-E04 remain BLOCKED.
