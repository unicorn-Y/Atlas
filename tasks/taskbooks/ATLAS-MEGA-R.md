# ATLAS-MEGA-R：Latest + Daily-Ready 三项最小收口

> Do not redo the Mega wave.
> Fix only the three blockers in `tasks/reviews/ATLAS-MEGA-LATEST-DAILY-READY.review.md`.
> Use maximum available subagent concurrency for independent work; no fixed worker count.

## Parallel execution

Immediately split at least into independent ownership groups:
1. X5 watcher backfill/pagination + tests;
2. K1 fake Computer driver seam + tests;
3. Hermes upstream delta reconnaissance since the prior frozen head.

Use the maximum concurrency the runtime allows. If spawn is rejected, shrink the current batch and continue; when slots free, dispatch remaining work. Do not disable subagents.

The Hermes actual merge waits until watcher fix is reviewed, but reconnaissance can run in parallel.

## R1 — Fix X5 watcher gap handling

Current bug:
- `FETCH_LIMIT=30`;
- checkpoint can jump across unseen history when upstream is >30 commits ahead.

Required behavior:

### Local git
- page/walk history until old checkpoint is found;
- use deterministic commit order;
- collect all unseen commits up to a sane configurable backfill ceiling;
- no duplicate entries;
- do not overwrite checkpoint if the previous checkpoint was not reached because the ceiling was exhausted.

### GitHub REST
- paginate `page=1..N` with `per_page` batches until:
  - old checkpoint found, or
  - response exhausted, or
  - configured backfill ceiling hit.
- release/tag mode must retain equivalent seen-id safety.

### State
Add explicit status fields sufficient to distinguish:
- current/complete;
- offline/cache;
- backfill_incomplete.

Never silently report current if older unseen commits may exist.

### Tests
At minimum:
- local git previous checkpoint 100+ commits behind → all unseen commits surfaced once;
- GitHub fake pagination 100+ commits behind → all surfaced once;
- second check emits zero duplicates;
- ceiling reached → `backfill_incomplete`, checkpoint not jumped beyond unseen gap;
- offline behavior unchanged.

## R2 — Final Hermes tail sync

After R1 is in place, fetch current upstream and record a final checkpoint:
- upstream HEAD/date;
- current fork HEAD;
- merge-base/ahead/behind.

Semantic merge current:
`NousResearch/hermes-agent:main`
into:
`unicorn-Y/hermes-agent:atlas`

Rules:
- preserve Atlas-specific fork patches;
- no blind ours/theirs;
- inspect only capability/code areas changed since prior frozen `a6e75acb0dc68c99d33fe8ba421a186b6b781b7c`;
- if upstream now provides a stronger duplicate, use upstream and keep Atlas as thin adapter only;
- do not rerun the whole U1 audit.

After merge:
- push fork;
- update Atlas `core/pyproject.toml` Hermes pin;
- focused tests for conflict/touched areas + Atlas fork patches;
- record final upstream and fork HEADs.

**Moving-target rule:** latest means the upstream HEAD fetched at this final tail-sync checkpoint. Do not restart the sync merely because newer commits appear while tests are running.

## R3 — K1 fake Computer path must be a real pass

Remove the xfail in:
`core/tests/test_k1_daily_paths_x2x4x5.py::test_daily_computer_use_with_fake_driver`

Wire a deterministic fake backend through the same production X2 Computer bridge.

Required:
- `computer_observe` actually executes;
- tool.completed exists;
- non-error;
- carries screenshot/image evidence;
- no real mouse/keyboard/desktop side effects;
- no user machine dependency.

Run the full K1 daily fake matrix and require:
- **15/15 passed**
- zero xfail.

## Validation

Workers run focused tests.

Controller final:
- watcher focused suite;
- K1 daily path suites;
- Hermes fork touched/conflict focused suites;
- frontend need not rerun unless production frontend files change;
- backend full pytest does not need another full run unless fixes spread unexpectedly.

## Delivery

Append `Mega-R closeout` to:
`tasks/results/ATLAS-MEGA-LATEST-DAILY-READY.result.md`

Include:
- watcher backfill design + tests;
- final Hermes upstream/fork heads;
- final ahead/behind at the checkpoint;
- K1 15/15 fake path result;
- focused test summary.

Then:
- `tasks/CURRENT.md` → `AWAITING_REVIEW`
- push Hermes fork
- push Atlas main
- verify both local HEAD == remote HEAD
- stop

Do not start X1/X3/X6/X7/full T1/R1.
