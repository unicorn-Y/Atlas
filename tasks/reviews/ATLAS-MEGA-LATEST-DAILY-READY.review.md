# ATLAS-MEGA-LATEST-DAILY-READY Review

Verdict: **PARTIAL — implementation is substantial, but three closeout blockers remain before “latest + daily-ready” can be accepted.**

Reviewed Atlas head:
- `bc377787d00a8852e8d2f5cea891b67cea351ca4`

Reviewed Hermes fork:
- `unicorn-Y/hermes-agent:atlas @ 27c63095b002b531b07bd6ad31da88bfe821f55f`

Current upstream observed during independent review:
- `NousResearch/hermes-agent:main @ ab86a20aeceeead429f3c3b50dd1d33fc26dfcb4`

## Accepted and must not be reopened

The following are real production implementations and are accepted:

- U1 core refresh work that landed in production;
- X2 Computer/Browser bridge, single model-facing surface, permission classification, browser handoff/vault/recording pipeline;
- X4 Skill Market single-registry integration and source/install/update surface;
- X5 evolution modules: watcher, capability diff, parity mapper, taskbook drafting, isolated branch proposal flow, curator;
- X2/X4/X5 integration into Atlas server/runtime/frontend;
- K1 parity/fake-path harness and the product bugs it already discovered and fixed;
- frontend validation evidence;
- focused regressions after the final skill-source fix.

Do **not** redo the Mega wave.

## Blocker 1 — X5 watcher skips history when upstream advances by more than FETCH_LIMIT

`core/atlas/evolution/watcher.py` currently uses:
- `FETCH_LIMIT = 30`;
- local git: `git log -n30`;
- GitHub REST: `per_page=30`;
- after a successful check, `last_id` is set to the newest fetched entry.

If the previous `last_id` is more than 30 commits behind:
1. the first run sees only the newest 30 and never reaches the old checkpoint;
2. it sets `last_id` directly to the newest commit;
3. the next run stops at that newest commit;
4. the older unseen gap is permanently skipped.

This is not theoretical: during this Mega run Hermes advanced from the frozen `a6e75acb...` to current `ab86a20...`, a **320-commit** delta.

Required:
- fetch/paginate until the previous checkpoint is found, or until a bounded explicit backfill ceiling is reached;
- never advance the checkpoint past unseen history;
- support both local git and GitHub REST sources;
- preserve offline/cache behavior;
- if a configured ceiling is reached before the old checkpoint, report a visible `backfill_incomplete` state instead of silently declaring current;
- add regression: previous checkpoint 100+ commits behind → all commits are eventually surfaced exactly once across the check.

## Blocker 2 — Hermes fork is no longer current at final delivery

The Mega source freeze correctly captured an earlier upstream head and synced to it, but upstream moved during execution.

Independent compare now shows the Atlas fork is:
- ahead by Atlas-specific commits;
- **behind current upstream by 320 commits**;
- merge-base is the frozen `a6e75acb...`.

This does not invalidate the Mega implementation, but it invalidates the final wording “current latest Hermes” under the user's explicit latest-first requirement.

Required:
- after fixing Blocker 1, fetch current upstream again;
- semantic tail-sync current `NousResearch/hermes-agent:main` into `unicorn-Y/hermes-agent:atlas`;
- preserve Atlas fork patches;
- update Atlas `core/pyproject.toml` pin;
- only review conflicts/changed capability areas since the previous freeze; do not rerun U1 from scratch;
- run focused tests for touched upstream conflict areas + Atlas fork patches;
- record the exact final upstream/fork heads.

Because upstream is a moving target, “latest” is defined as the upstream HEAD fetched at the final tail-sync checkpoint. Do not chase commits that appear after that checkpoint during the test run.

## Blocker 3 — K1 fake daily-path matrix is 14/15, not complete

`core/tests/test_k1_daily_paths_x2x4x5.py::test_daily_computer_use_with_fake_driver` is still marked `xfail` because no fake CUA driver is wired into the harness.

The Mega taskbook explicitly required a fake Computer Use daily path. A real-device smoke later is separate and cannot replace this deterministic fake acceptance.

Required:
- wire a minimal fake driver/backend seam into the K1 harness using the same production Computer bridge;
- the test must actually execute `computer_observe`;
- assert tool.completed is non-error and carries screenshot/image evidence;
- remove the xfail;
- K1 daily fake matrix must be **15/15 real pass**.

## Non-blockers

- real X2 desktop/login/CAPTCHA/vault/market-network checks remain `REQUIRES_USER_DAILY_SMOKE`;
- a full backend suite does not need to be rerun merely because focused post-fix coverage was used after the one permitted full-suite run;
- X1/X3/X6/X7/full T1/R1 remain intentionally deferred.

## Closeout

Fix only the three blockers above, append evidence to the existing Mega result, and return for final review.
