# CODEX-ATLAS-P15C-FIX2-PROVIDER-HASH-INTEROP

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P15C-FIX-INTEGRITY-APPROVAL-VERSION
CODE_BASE_HEAD: 5379dd3195ac06f0aeb93ddd23471c42cd0b1b37

## Objective

完成 P15C 最后一项真实运行时验收：正确处理 skills.sh provider 的 hash/snapshot 不一致。

**核心原则：绝不因为 provider 自己给出了 hash 就放宽 Atlas 的完整性闸门。**

当前已观察到：

- skills.sh 真实多文件下载：76 files
- provider hash: `ca7b0c0c6e5f2750043f7f0cd72d16ac4e2abc48f9b5500d047a4b77a2506212`
- Atlas 对下载 payload 的计算：`3219a1944e404ffc14d1d9d6aef6dd2e3855b81387ee0a044ccbfe14d34c2357`
- Atlas 正确 BLOCK

公开证据还显示 skills.sh 存在长期 stale snapshot/reindex 问题。不要把这个问题修成“忽略 mismatch”。

## Scope

只做 provider hash interoperability / safe fallback。

禁止：

- P15D 生命周期功能；
- 自动更新；
- trust/version pinning 生命周期；
- MemoryOS 写入；
- dependency 自动安装；
- agent 绕过 Skill Center；
- 修改既有 approval 安全边界。

## A. 建立可复现的 provider mismatch 诊断

对至少一个真实多文件 skills.sh Skill 做实网测试：

1. GET `/api/download/<owner>/<repo>/<slug>`
2. 保存：
   - provider hash
   - file count
   - relative file paths
   - Atlas local content hash
3. 使用当前 skills CLI 的公开参考实现核对：
   https://github.com/vercel-labs/skills/blob/main/src/blob.ts
4. 记录完整诊断，不上传/提交 Skill 正文中的秘密。

必须区分：

- provider hash 与 payload 不一致；
- payload 与 GitHub 当前 source 不一致；
- Atlas hash 算法本身不兼容。

## B. 独立 GitHub source comparison

对于 skills.sh external_id：

`owner/repo/skill-slug`

从 GitHub source 获取同一 Skill：

- recursive tree；
- 处理 `truncated=true`；
- 获取选定 Skill 的全部文本文件；
- 保持相对路径；
- 不允许 symlink / unsafe path / oversized / non-text；
- 使用已有安全扫描与 manifest 校验。

比较 provider payload 与 GitHub payload：

### Case 1 — payload 完全一致，provider hash 错

这是允许的“provider integrity metadata stale”情况。

处理：

- provider hash 继续标记为 mismatch；
- **不得**把 provider hash 当成通过；
- 改用已独立验证的 GitHub payload 作为待安装 Acquisition；
- GitHub payload 通过自身验证后才能进入 Skill Center approval；
- provenance 必须记录：
  - provider hash
  - provider computed hash
  - provider mismatch
  - GitHub source
  - GitHub source revision/tree SHA（能取得则记录）
  - installed computed hash
  - fallback reason
- 安装内容必须来自 GitHub payload，不得继续使用 mismatch 的 provider snapshot。

### Case 2 — provider payload 与 GitHub source 不一致

必须：

- BLOCK；
- 不安装；
- 不允许 approval；
- Preview 明确显示 catalog snapshot 与 source 不一致；
- 记录可审计原因。

### Case 3 — GitHub source 无法验证

必须：

- BLOCK；
- 不安装；
- 不允许 approval；
- 不提供“忽略 hash mismatch”按钮。

## C. Exact hash compatibility

当前 skills CLI 的参考代码为：

`sha256(sorted(path.localeCompare) + path + contents)`

参考：

https://github.com/vercel-labs/skills/blob/main/src/blob.ts

Atlas 当前实现使用：

`(path.casefold(), path)`

这不能继续标成“exact upstream algorithm”。

要求：

1. 增加独立参考 fixture；
2. 覆盖：
   - lowercase paths
   - uppercase/lowercase variants
   - punctuation
   - nested paths
   - multi-file content
3. 用一个独立 Node reference implementation 产生 expected digest；
4. Python implementation 与 reference fixture 必须一致；
5. 如果决定不在生产运行时依赖 Node：
   - 必须明确写出 Python 端采用的等价排序契约；
   - 必须证明该契约与 reference fixture 一致；
   - 不得用“多算法尝试直到命中”规避问题。

注意：`localeCompare()` 本身受 locale/Intl 行为影响，因此不要声称一个 casefold sort 就等于它。若发现无法稳定跨运行时复刻，宁可把 Atlas local hash 定义为独立 deterministic hash，并将 provider hash 验证隔离成独立 reference-compatible verifier。

## D. Healthy provider path

不能只测试 mismatch。

至少找到一个真实 provider payload：

- provider hash == reference-compatible recomputed hash

验证：

- 正常 PASS/WARN；
- 正常进入 Skill Center approval；
- 正常安装；
- provenance 正确；
- 没有 fallback。

如果当前 skills.sh 没有任何可用的 healthy multi-file payload，记录真实原因并保留 BLOCK；不要伪造通过。

## E. Approval integration

fallback 到 GitHub 后：

- 必须生成新的 acquisition_id / pending acquisition；
- 旧 provider mismatch acquisition 的 approval 不得复用；
- 新 acquisition 必须重新 Preview；
- WARN 必须重新二次确认；
- 旧 authorization 不得消费新 acquisition；
- Agent 仍不能 mint approval。

## F. Tests

新增/更新：

1. provider hash match → normal install path；
2. provider hash mismatch + GitHub payload identical → safe GitHub fallback；
3. provider hash mismatch + GitHub payload different → BLOCK；
4. provider mismatch + GitHub unavailable → BLOCK；
5. provider mismatch never bypasses approval;
6. fallback provenance records both provider mismatch and GitHub source;
7. stale provider approval cannot be reused after fallback;
8. exact hash reference fixtures with mixed-case/punctuation paths;
9. GitHub tree truncated remains BLOCK;
10. existing P15A/P15B/P15C approval/security/registry regressions.

## G. Live smoke

必须实网记录：

- skills.sh search;
- one real multi-file provider snapshot;
- provider hash;
- Atlas/reference recomputed hash;
- GitHub source tree/revision;
- file-set comparison result;
- final decision;
- if a healthy provider case exists, its successful hash verification;
- no production skill directory installation during smoke.

如果 provider 当前持续返回错误 hash，不得为了“让测试通过”修改 expected hash。

## Acceptance Criteria

1. 不会接受错误 provider hash。
2. provider hash mismatch + source identical 时，可安全切换到 GitHub source 并完成正常 Skill Center 审批/安装。
3. provider payload 与 GitHub source 不一致时硬 BLOCK。
4. GitHub source 不可验证时硬 BLOCK。
5. approval 不跨 acquisition/fallback 复用。
6. healthy provider hash match 正常通过（若当前 provider 能提供）。
7. hash reference fixtures 证明 Atlas 不再把 casefold sort 冒充为 exact upstream algorithm。
8. provenance 完整记录 provider mismatch/fallback/source revision。
9. P15A/B/C 回归全过。
10. frontend tests + production build 通过。
11. Ruff + git diff --check 通过。
12. 不引入自动执行、依赖安装、P15D 功能。

## Delivery

- Read `LUNA_WORKER.md`.
- Pull origin/main.
- Record actual BASE_HEAD.
- Execute only this task.
- Write:
  `tasks/results/CODEX-ATLAS-P15C-FIX2-PROVIDER-HASH-INTEROP.result.md`
- Commit implementation + result.
- Push origin/main.
- Verify local HEAD == origin/main.
- Stop.
- Do not start P15D.

## Queue Intent

Only after this fix is accepted may the queue advance to:

**P15D — Skill Lifecycle & Trust Management**
