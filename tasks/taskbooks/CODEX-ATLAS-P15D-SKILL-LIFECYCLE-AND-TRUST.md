# CODEX-ATLAS-P15D-SKILL-LIFECYCLE-AND-TRUST

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15C-FIX2-PROVIDER-HASH-INTEROP
CODE_BASE_HEAD: 11a3345ef2d1b84b6ffae5b9e48bfb469772c14e

## Objective

把 P15C 已经安全安装的 Skill 从“只能安装/发现”推进到一个完整、可审计、可回退的生命周期：

- update
- remove
- rollback / safe downgrade
- trust state
- version pinning
- provenance history
- dependency state
- lifecycle audit trail

核心原则：

生命周期操作不能绕过 P15C 的完整性验证、明确授权和 Skill Center 安全边界。

P15C 解决的是：
external source → verify → preview → explicit approval → install

P15D 解决的是：
installed skill → inspect state → explicit lifecycle action → verify new state → atomic transition → audit

## Scope

### 1. Lifecycle state model

建立明确、持久化的 Skill lifecycle metadata。

至少能够区分：

- installed / active
- disabled
- update-available
- pinned
- quarantined / blocked
- removed
- rollback-available

要求：

- lifecycle state 不等于 execution permission；
- trust state 不得直接授予新的 capability/tool 权限；
- 不能通过修改 metadata 就把 BLOCK/QUARANTINED Skill 变成可执行 Skill；
- P15A Registry 继续是 installed metadata 的事实来源，不创建第二套 installed registry。

如果需要扩展 Registry schema，必须向后兼容已有 skill_registry 数据。

### 2. Trust state

建立最小可审计 trust model。

至少支持：

- unreviewed
- trusted
- revoked
- blocked

要求：

- 新安装 Skill 默认不能因为“来自 skills.sh/GitHub”自动成为 trusted；
- trusted 必须对应明确的用户操作和可追溯事件；
- revoked/blocked Skill 不得通过普通 lifecycle 操作恢复为 trusted；
- trust state 变化必须记录 actor、timestamp、reason、skill identity、version/hash；
- trust state 不是 capability grant；
- 不允许 Agent 自己提升 trust。

### 3. Version pinning

支持对已安装 Skill 设置版本策略：

- unpinned
- pinned exact version
- pinned content hash

要求：

- pin 是 lifecycle policy，不是安装授权；
- pinned Skill 不得被普通 update 覆盖；
- 用户可以明确解除 pin；
- hash pin 必须绑定到实际已安装 content hash；
- source/version/hash 不一致时 update 必须进入 review，而不是静默替换。

### 4. Update flow

实现安全更新：

1. 读取当前 installed provenance；
2. 检查 source/external_id/source_url；
3. 查询来源是否有新版本/新内容；
4. 获取候选 payload；
5. 重新执行 P15C 的完整 acquisition verification；
6. 重新执行 manifest/path/content/security/hash checks；
7. 展示 current vs incoming：
   - version
   - source
   - provider
   - hash
   - file changes
   - risks
   - dependencies
   - trust/pin state
8. 用户明确批准 update；
9. staged install；
10. atomic replacement；
11. Registry transition；
12. SkillManager rescan；
13. 写 lifecycle audit；
14. 保留 rollback snapshot。

禁止 background auto-update、silent update、same-source hash bypass、Agent 自动 update、pinned Skill 自动更新。

### 5. Safe downgrade / rollback

实现安全回滚。

每次成功 update 前必须形成可验证的 rollback record：

- previous version
- previous content hash
- previous source/provenance
- previous installed files
- created_at
- originating lifecycle event

Rollback 必须：

1. 检查 rollback record 完整性；
2. 检查目标 snapshot；
3. 不使用不可信 provider payload；
4. staged restore；
5. atomic replace；
6. Registry 更新；
7. SkillManager rescan；
8. lifecycle audit。

如果 rollback snapshot 损坏、缺失或 hash 不一致：

- BLOCK；
- 不删除当前正常版本；
- 不尝试“修复后继续”。

Rollback 也必须保留当前版本的历史记录，不能把历史抹掉。

### 6. Remove / uninstall

实现明确的用户主动 remove。

要求：

- 默认 remove 不自动删除历史 provenance；
- remove 前显示 name/version、installed hash、source、trust state、pinned state、dependency state；
- 用户明确确认后才执行；
- 文件删除与 Registry 状态变更必须保持一致；
- 失败时不得留下 Registry 已删除但文件还在或反向半状态；
- 已 removed 的历史记录仍可审计；
- remove 不得被普通 Agent capability 自动触发。

对于有 dependency relationship 的 Skill，只阻止或警告当前操作；不得自动级联删除其他 Skill，除非用户在明确的同一操作中确认。

### 7. Dependency state

P15C 只保存 declared dependencies；P15D 不允许自动安装依赖。

增加可审计 dependency state：

- declared
- detected/missing
- satisfied
- incompatible
- unknown

要求：

- 依赖状态不等于依赖已安装；
- 检测失败不能伪造 satisfied；
- P15D 不自动执行 pip/npm/system package installation；
- lifecycle update 如果引入新的 dependency requirement，必须在 Review 中明确显示；
- dependency mismatch 可以阻止 update，也可以要求用户明确继续，具体取决于安全级别，但不得静默忽略。

### 8. Provenance history

当前 P15A Registry 保存当前 provenance；P15D 增加不可覆盖的 lifecycle history。

每条 history 至少：

- event_id
- timestamp
- action
- skill name/version
- previous version/hash
- resulting version/hash
- source/provider
- trust state before/after
- pin state before/after
- approval event id（需要用户批准的操作）
- actor = user / system
- reason
- result
- error code（失败时）

历史记录不得保存 API key、password、bearer token、arbitrary skill body、raw credentials。

建议使用 SQLite append-only lifecycle table，并通过 DB 约束/代码路径防止普通 registry update 覆盖历史。

### 9. Atomic lifecycle transition

Update/remove/rollback/trust/pin 的状态转换必须有明确的失败边界。

至少保证：

- staged filesystem mutation；
- registry transaction；
- rollback on failure；
- no half-installed target；
- no orphan registry record；
- no lost rollback record。

同一 name 的 lifecycle 操作必须串行化，沿用 P15C 的安装锁思路。

并发场景至少覆盖：

- update + update
- update + remove
- rollback + update
- remove + restore

不能让最后一个请求无条件覆盖前一个请求。

### 10. Approval boundary

P15C 的 server-side approval contract 必须继续有效。

以下操作必须明确用户批准：

- update
- downgrade
- rollback
- remove
- trust promotion
- unpin
- force lifecycle transition

以下不能由普通 Agent capability 自动执行：

- approve
- trust promotion
- remove
- update
- rollback
- unpin

Agent 可以 inspect lifecycle state、inspect update availability、inspect provenance/history、inspect dependency state。

Agent 不能自己制造 approval artifact、自己消费用户尚未确认的 lifecycle action、自己把 Skill 标成 trusted。

### 11. Version/content identity

生命周期判断不能只比较 version。

必须至少比较：

- name
- version
- content hash
- source identity
- provenance

处理：

- same version + different hash → review/block；
- newer version + same hash → no-op；
- older version + different hash → downgrade review；
- same source + changed hash → content change review；
- different source + same name/version → conflict；
- pinned hash + changed content → block normal update。

### 12. Frontend lifecycle UX

Skill Center 在已安装 Skill 详情中增加：

- current version/hash
- source/provenance
- trust state
- pin state
- dependency state
- update available
- update review
- file/content diff summary
- rollback history
- remove action
- trust/revoke action
- pin/unpin action
- lifecycle history

危险操作必须使用明确的 confirmation dialog。

WARN/BLOCK 继续沿用 P15C 的语义：

- BLOCK：不能继续；
- WARN：必须二次确认；
- PASS：进入正常 approval。

不要把 trust badge 做成“绿色=可执行”的权限开关。

### 13. Direct filesystem drift detection

增加一个轻量 drift check：

- Registry recorded hash
- actual installed payload hash

如果不一致：

- 标记 drifted；
- 不自动修复；
- 不自动重新信任；
- Update/rollback/remove 前必须先处理 drift；
- UI 显示实际 hash 与记录 hash。

检测到 drift 时不得把当前目录内容直接当作可信 rollback source。

### 14. Compatibility

必须保持：

- P15A Registry API compatibility；
- P15B Discovery compatibility；
- P15C catalog/search/inspect/install compatibility；
- existing SkillManager activation behavior；
- existing Agent capability boundaries；
- existing local skills untouched.

P15D 不得改变 P15C provider hash verification algorithm 或 fallback safety rules。

## Non-Goals

本任务不实现：

- automatic update scheduler；
- background trust automation；
- dependency auto-install;
- automatic rollback on every update failure；
- MemoryOS lifecycle writes；
- remote execution；
- MCP runtime；
- private GitHub auth；
- new remote catalog provider；
- voice/video/camera；
- automatic Skill selection by Planner。

## Acceptance Criteria

### Backend

1. Lifecycle state persists across restart.
2. Existing P15A records remain readable.
3. Update requires explicit approval.
4. Update re-runs P15C integrity/security verification.
5. Same-version/different-hash is detected and not silently overwritten.
6. Pinned Skill blocks ordinary update.
7. Unpin requires explicit approval.
8. Rollback restores the exact recorded previous payload.
9. Rollback verifies hash before replacing files.
10. Corrupt/missing rollback snapshot blocks without damaging the current version.
11. Remove preserves provenance history.
12. Remove does not cascade-delete dependencies without explicit confirmation.
13. Trust promotion/revocation is auditable.
14. Agent cannot promote trust or mint lifecycle approval.
15. Dependency state distinguishes declared/missing/satisfied/incompatible/unknown.
16. Filesystem drift is detected and exposed.
17. Lifecycle events are append-only/auditable.
18. Concurrent lifecycle operations are serialized and cannot silently overwrite one another.
19. Failed transitions leave no half-installed Registry/filesystem state.

### Frontend

20. Installed Skill detail shows lifecycle/trust/pin/dependency state.
21. Update review shows current vs incoming version/hash/source and risk changes.
22. Rollback UI shows target version/hash and confirmation.
23. Remove UI shows provenance/trust/dependency warnings.
24. Trust/pin actions have explicit confirmation.
25. Drifted state is visible and blocks unsafe automatic repair.
26. Lifecycle history is viewable.

### Security

27. No lifecycle action bypasses server approval.
28. No Agent capability can mint or consume user approval.
29. No provider hash mismatch is accepted.
30. No trust state grants capability/tool permission.
31. No lifecycle operation executes Skill contents.
32. No lifecycle operation installs dependencies automatically.
33. Secrets are excluded from audit history and metadata.
34. P15C fallback provenance remains intact.

### Regression / validation

35. P15A/P15B/P15C regression tests pass.
36. New backend tests cover update/remove/rollback/trust/pin/dependency/drift/concurrency/failure recovery.
37. Frontend lifecycle tests pass.
38. Production build passes.
39. Modified Python files pass Ruff.
40. git diff --check passes.
41. Live smoke uses only a temporary/test Skill and does not mutate production skills.
42. Worker verifies LOCAL_HEAD == origin/main.
43. Result file records exact state transitions and hashes.
44. No P15E/P16 or unrelated feature work is started.

## Required test matrix

At minimum:

- install v1.0.0 → update v1.1.0 → rollback v1.0.0;
- v1.1.0 same version but different content hash;
- pinned v1.0.0 with available v1.1.0;
- unpin then update;
- remove clean install;
- remove with declared dependency;
- trust promote → revoke;
- revoked Skill update attempt;
- missing/corrupt rollback snapshot;
- filesystem drift before update;
- filesystem drift before rollback;
- concurrent update/update;
- concurrent update/remove;
- failed registry transaction;
- failed filesystem replacement;
- approval replay;
- approval for another acquisition/lifecycle action;
- Agent attempted lifecycle approval bypass.

## Delivery

- Read LUNA_WORKER.md first.
- Pull origin/main.
- Record actual BASE_HEAD.
- Execute only this taskbook.
- Write:
  tasks/results/CODEX-ATLAS-P15D-SKILL-LIFECYCLE-AND-TRUST.result.md
- Commit implementation + result.
- Push origin/main.
- Verify local HEAD == origin/main.
- Stop.
- Do not start another task.

## Queue Guard

P15D is the only READY task after this review.

Do not start P15E/P16 or unrelated work until P15D has its own review and acceptance.
