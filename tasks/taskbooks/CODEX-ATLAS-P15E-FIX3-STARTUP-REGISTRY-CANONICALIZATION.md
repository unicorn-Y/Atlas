# CODEX-ATLAS-P15E-FIX3-STARTUP-REGISTRY-CANONICALIZATION

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY
REVIEW: tasks/reviews/CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY.review.md
CODE_BASE_HEAD: 2bb0cbb63cad2e116b012eddd84fb8bdb97eee6a

## Objective

完成 P15E-FIX2 验收剩余的 bounded contract fix：

1. 启动阶段把本地 Skill 注册到 Registry 时，必须使用 canonical dependency contract；
2. SkillInfo 的序列化不得继续产生 raw/canonical 语义分叉；
3. 验证启动注册、Registry preflight、SkillManager preflight 对同一个 Skill 使用完全一致的 dependency set。

不要扩展到 P16、E01-E04 或新的 Skill capability 架构。

## Required fixes

### A. Startup Registry registration

当前 core/atlas/server.py lifespan 的本地 Skill 注册使用：

    "requirements": skill.dependencies

必须改为使用 canonical dependency contract。

目标：

    Registry requirements == skill.dependency_contract

对于同时声明 modern dependencies 和 legacy requirements 的 Skill，两者都必须进入 Registry。

不得：

- 丢掉 modern-only dependency；
- 丢掉 legacy-only dependency；
- 重复保存同一个 canonical dependency；
- 把 unknown 当成 satisfied。

### B. SkillInfo serialization contract

当前 SkillInfo.to_dict() 暴露 raw dependencies。

选择一个最小、明确且一致的契约：

- 推荐 dependencies 字段返回 canonical dependency records；
- 如果确实需要保留 raw declaration，则另用明确字段名保存 raw declaration，不得让 consumers 把 raw dependencies 当 canonical contract。

不要做无关 API 重构。

### C. Regression coverage

必须新增或补强测试：

1. local Skill with dependencies-only declaration registers canonical dependencies;
2. local Skill with requirements-only declaration registers canonical dependencies;
3. local Skill with both declarations registers the merged canonical set;
4. modern-only dependency survives startup registration;
5. legacy-only dependency survives startup registration;
6. duplicate declarations are stored once;
7. Registry requirements exactly equal SkillInfo canonical dependency contract;
8. Registry dependency_preflight and SkillManager preflight return the same dependency set;
9. missing modern-only dependency blocks activation;
10. satisfied modern-only dependency permits activation;
11. SkillInfo.to_dict exposes the documented canonical dependency contract;
12. package import canonical dependency regressions remain green;
13. exact name+version conflict remains green;
14. same-name different-version update/downgrade remains green;
15. approval replay/retarget remains green;
16. frontend canonical dependency formatting remains green.

### D. Full validation

Run to completion:

- P15A-P15E regression modules;
- all P15E-FIX3 tests;
- frontend tests;
- production build;
- Ruff on changed Python files;
- git diff --check;
- isolated startup-registration smoke;
- Registry/preflight/activation consistency smoke;
- package import smoke.

Also run the full core/tests suite to completion and record the exact failing test names if any exist.

If unrelated pre-existing failures remain, do not silently count them as passes. Record them explicitly and demonstrate that the P15E-FIX3 changed paths and required regression suites pass.

Finally verify:

- LOCAL_HEAD == origin/main;
- git status clean.

## Forbidden

不得：

- 开始 P16；
- 开始 E01/E02/E03/E04；
- 新造 Registry；
- 新造 Policy/Approval；
- 绕过 lifecycle approval；
- 修改历史 lifecycle event；
- 自动安装未知依赖；
- 重做 P15C provider hash verification；
- 重做 P15D lifecycle architecture；
- 做无关 UI 重构；
- 用修改测试断言的方式掩盖 raw/canonical mismatch。

## Delivery

1. Read LUNA_WORKER.md.
2. Pull origin/main.
3. Record actual BASE_HEAD.
4. Read PLAN.md.
5. Read the P15E, P15E-FIX1, and P15E-FIX2 reviews plus this taskbook.
6. Fix only the bounded startup Registry and SkillInfo serialization contract.
7. Write:
   tasks/results/CODEX-ATLAS-P15E-FIX3-STARTUP-REGISTRY-CANONICALIZATION.result.md
8. Commit implementation + result.
9. Push origin/main.
10. Verify LOCAL_HEAD == origin/main.
11. Verify git status clean.
12. Stop.
13. Do not start P16 or E01-E04.

## Queue Guard

P15E-FIX3 is the only READY task.
P15E-FIX2 is not accepted until this fix receives a separate review.
P16 and E01-E04 remain BLOCKED.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.
