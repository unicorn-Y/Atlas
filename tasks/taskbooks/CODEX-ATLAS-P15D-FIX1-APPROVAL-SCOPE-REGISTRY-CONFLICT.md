# CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15D-SKILL-LIFECYCLE-AND-TRUST
CODE_BASE_HEAD: 04eced0a200c0590dbf394af4237ff3f669d352e

## Objective

只修复 P15D 审查发现的生命周期授权范围、Registry 冲突与审计 hash 记录问题。

本任务不是重新实现 P15D，也不是进入 P15E。

核心目标：

1. exact lifecycle approval scope；
2. trusted server/UI approval binding；
3. rollback event binding；
4. no silent name+version overwrite；
5. correct before/after audit hashes。

## Scope

### A. Exact approval scope

扩展现有 server-side lifecycle approval record，使 approval 对完整 transition scope 做不可变绑定。

必须绑定：

- action
- skill name
- current version
- current content hash
- acquisition_id for update/downgrade
- target trust state for trust
- target pin policy for pin/unpin
- rollback event_id for rollback
- rollback snapshot hash for rollback
- reason
- created_at / expires_at
- unique approval_event_id
- one-time consumption

Consume 必须逐字段比较；任何 mismatch 必须 fail closed。

不得用 action 相同代替 exact target scope。

### B. Approval authority boundary

复用现有 Atlas approval/controller/session authority if available。

如果当前 P15D 没有可复用的可信 UI decision/session：

- 增加最小 server-held approval request/decision binding；
- approval issuance 必须引用该 server-side decision/request identity；
- generic direct HTTP lifecycle caller 不得仅凭 action/name/version/reason 取得可执行 approval；
- Agent capability 不得获得 approval mint/consume 能力；
- 不新增第二套长期独立 authority store。

目标是让服务端能够区分 trusted Skill Center decision 与 arbitrary client assertion。

不要为了本任务重做全局 Policy/Approval 系统。

### C. Rollback binding

Rollback approval 必须绑定：

- exact rollback event_id
- snapshot_hash
- current skill identity/version/content hash

执行时 event_id、snapshot hash、current identity/hash 必须全部重新验证。

同一个 token 不得用于另一个 rollback event，即使 snapshot hash 偶然相同。

### D. Registry conflict hardening

修复 SkillRegistry.commit_lifecycle_update 的 silent ON CONFLICT overwrite。

规则：

- target name+version 不存在：正常创建；
- target 是当前正在被 same-version content-change transition 替换的同一记录：只允许在 exact identity/hash transition 已获批准时更新；
- target 已存在且 hash/source/provider/provenance 不同：CONFLICT，不能覆盖；
- target 是 disabled/historical version：不得静默覆盖；
- conflict 必须保留已有 Registry record 与 lifecycle history；
- conflict 发生时 filesystem 与 Registry 都保持原状态。

不要删除历史记录来解决冲突。

### E. Audit before/after hash correctness

在 trust/pin transition 中：

- 先捕获 before_hash；
- 执行 mutation；
- event.previous_hash = before_hash；
- event.resulting_hash = resulting hash。

检查 update/downgrade/rollback/remove 的已有 before/after 字段，若同类问题存在只做最小修正，不扩大范围。

## Required tests

新增或修改测试至少覆盖：

1. trust approval for trusted cannot execute as revoked/blocked/unreviewed;
2. pin approval for exact cannot execute as hash;
3. pin approval for hash cannot execute as exact;
4. rollback approval for event A cannot execute event B even with equal snapshot hash;
5. update approval for acquisition A cannot execute acquisition B;
6. expired approval rejected;
7. consumed approval replay rejected;
8. wrong current hash/version rejected;
9. direct lifecycle execution without valid server approval rejected;
10. approval issuance without trusted UI/server decision binding rejected;
11. Agent cannot mint or consume lifecycle approval;
12. same name+version with different hash conflicts;
13. same name+version with different source/provider conflicts;
14. disabled historical target is not silently overwritten;
15. conflict leaves filesystem and Registry unchanged;
16. identical repeated transition is deterministic;
17. trust event previous_hash equals pre-transition hash;
18. pin event previous_hash equals pre-transition hash;
19. existing P15D lifecycle matrix remains passing.

## Validation

必须执行并记录：

- P15A/P15B/P15C/P15D regression tests；
- new P15D-FIX1 tests；
- frontend tests；
- production build；
- modified Python Ruff；
- git diff --check；
- isolated HTTP smoke using temporary Skill + temporary DB；
- approval replay/mismatch smoke；
- exact rollback event binding smoke；
- Registry conflict smoke；
- LOCAL_HEAD == origin/main。

Live external provider update is not required for this fix because P15C owns provider verification. Do not weaken or rewrite P15C provider-hash verification.

## Forbidden

不得：

- 开始 P15E/P16；
- 重做 P15C provider hash algorithm；
- 新增 remote provider；
- 自动更新/自动信任/自动安装依赖；
- 让 Agent 获得 lifecycle approval authority；
- 删除/清空 lifecycle history；
- 用覆盖已有 Registry 记录的方式绕过 conflict；
- 为了测试向 production skills 目录写入临时 Skill；
- 做无关前端重构或 bundle 优化。

## Delivery

- Read LUNA_WORKER.md first.
- Pull origin/main.
- Record actual BASE_HEAD.
- Execute only this taskbook.
- Write:
  tasks/results/CODEX-ATLAS-P15D-FIX1-APPROVAL-SCOPE-REGISTRY-CONFLICT.result.md
- Commit implementation + result.
- Push origin/main.
- Verify LOCAL_HEAD == origin/main.
- Stop after this fix.
- Do not start P15E/P16.

## Queue Guard

P15D-FIX1 is the only READY task.

P15D remains unaccepted until this fix receives a separate review.

P15E/P16 are BLOCKED.
