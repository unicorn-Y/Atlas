# CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT
REVIEW: tasks/reviews/CODEX-ATLAS-P15E-FIX1-DEPENDENCY-CANONICALIZATION-AND-VERSIONED-PACKAGE-IMPORT.review.md
CODE_BASE_HEAD: 35cd5182a0599c725aa5d97b60278c61f372796d

## Objective

完成 P15E-FIX1 验收剩余的 bounded contract fix：

1. modern dependencies 与 legacy requirements 在所有入口必须使用同一 canonical dependency semantics；
2. 前端 review 必须正确展示 canonical dependency records。

不要扩展到 P16、Workflow Learning、Generated Tool 或新的 capability 系统。

## Required fixes

### A. One canonical dependency semantic rule

当前代码存在两个语义：

- core/atlas/skills/acquisition.py::_parse_manifest()：requirements 存在时优先使用 requirements，否则使用 dependencies；
- core/atlas/skills/__init__.py::_frontmatter_to_skill_info()：dependencies + requirements 合并后 canonicalize。

必须消除这个分叉。

推荐采用：

    canonical = normalize(dependencies) + normalize(requirements)

再做 deterministic de-duplication。

这样：

- 新规范 dependencies 单独使用 -> 支持；
- 旧 requirements 单独使用 -> 支持；
- 两者同时存在 -> 两者都生效；
- 相同依赖重复声明 -> canonicalize 后只保留一条；
- dependencies 中存在、requirements 中不存在的依赖 -> 绝不能丢失。

如果 worker 认为必须采用不同语义，必须在代码和测试中统一说明并保证 acquisition / SkillManager / package inspection / Registry / lifecycle 全部遵循同一规则。

### B. Package manifest completeness

inspect_skill_package() 必须比较：

    canonical(SKILL.md dependencies + requirements)

与：

    canonical(package manifest dependencies)

不得只比较 legacy requirements。

如果 SKILL.md 声明：

    dependencies:
      python_packages:
        - requests
        - pydantic

    requirements:
      - python:requests

则 package manifest 至少必须表达 requests + pydantic；缺少 pydantic 必须拒绝。

### C. Registry and activation consistency

确保：

- prepare_acquisition() 保存的 validation.dependencies 是完整 canonical 集合；
- 安装后 Registry requirements 是同一 canonical 集合；
- dependency_preflight() 可以直接消费 Registry requirements；
- SkillManager activation/preflight 与 Registry dependency state 对同一个 Skill 得出一致结果；
- 不得把 unknown 当成 satisfied；
- 不得自动安装 unknown dependency。

### D. Frontend dependency contract

更新：

    frontend/src/renderer/pages/SkillDiscoveryPage.tsx

中的 Review 类型，使 validation.dependencies 使用 canonical dependency record，而不是 string[]。

review UI 中不得直接对 dependency objects 调用 join()。

显示至少：

    kind:name
    requested constraint (when present)

例如：

    python_packages:requests >=2,<4

增加前端回归测试。

## Required regression tests

必须新增并通过：

1. dependencies-only structured mapping still works;
2. requirements-only legacy declaration still works;
3. both dependencies and requirements are merged canonically;
4. dependency present only in modern dependencies is preserved;
5. dependency present only in legacy requirements is preserved;
6. duplicate dependency across both forms is deterministically de-duplicated;
7. package manifest missing a modern-only dependency is rejected;
8. package manifest containing the full canonical dependency set is accepted;
9. Registry requirements exactly equal the canonical dependency set;
10. Registry preflight and SkillManager activation see the same dependency set;
11. modern-only missing dependency blocks activation;
12. modern-only satisfied dependency permits activation;
13. unknown dependency remains blocking;
14. version constraints survive canonicalization;
15. exact same name+version package conflict regression remains green;
16. same-name different-version lifecycle update/downgrade regression remains green;
17. update approval replay/retarget regression remains green;
18. frontend renders canonical dependency records correctly;
19. P15A-P15E full regression remains green.

## Validation

Run:

- P15A-P15E full regression;
- all new P15E-FIX2 tests;
- frontend tests;
- production build;
- Ruff on changed files;
- git diff --check;
- isolated package inspect/import/activation smoke;
- package manifest completeness smoke;
- same-name different-version update smoke;
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
- 静默覆盖旧版本；
- 重做 P15C provider hash verification；
- 重做 P15D lifecycle architecture；
- 做无关 UI 重构。

## Delivery

1. Read LUNA_WORKER.md.
2. Pull origin/main.
3. Record actual BASE_HEAD.
4. Read PLAN.md.
5. Read the P15E and P15E-FIX1 reviews plus this taskbook.
6. Fix only the bounded canonical dependency/frontend contract defects.
7. Write:
   tasks/results/CODEX-ATLAS-P15E-FIX2-CANONICAL-DEPENDENCY-CONSISTENCY.result.md
8. Commit implementation + result.
9. Push origin/main.
10. Verify LOCAL_HEAD == origin/main.
11. Stop.
12. Do not start P16 or E01-E04.

## Queue Guard

P15E-FIX2 is the only READY task.
P15E-FIX1 is not accepted until this fix receives a separate review.
P16 and E01-E04 remain BLOCKED.
