# ATLAS-C3-SESSION-INTERACTION Review

Verdict: **PARTIAL — requires one minimal repair wave (C3R) before C4.**

Reviewed implementation:
- Atlas implementation: `94de9c547f3ac747e8a82e6f892558307737e316`
- Result: `a7216132503bcd034344f0c48c11737f1f9d481c`
- Hermes: unchanged at `e287231d7906bcce5bc373d20fb2e3e1e6427220`

## Accepted C3 items

The implementation/result and current code are sufficient to accept these C3 rows without reopening them:

- **L6** immediate redirect / queued steer
- **S2** real SessionDB branch tree + branch summaries
- **S3** bounded checkpoint chain / pruning
- **I1** permission modes and child privilege cap
- **I2** plan-mode read-only execution path
- **I5** daily slash-command coverage
- **I6 / X7** status bar + context breakdown
- **I7** background-process list/output/stop/notifications using the existing registry
- **A2** worker acceptance requires real completion + verifier acceptance; failure can redispatch

The required fake WebSocket flows passed (**2 passed**), focused backend selection passed (**134 passed**), adapter tests passed (**10 passed**), renderer/electron TypeScript passed, Vitest passed (**41 passed**), and Vite build passed.

The single permitted full backend pytest run reported **1038 passed, 9 skipped, 2 failed**. Both failures were subsequently reproduced/fixed with focused checks. Per the taskbook, the full suite was intentionally not rerun; this is not itself a C3 blocker.

## Blocking gaps

### 1. I3 is not complete

The taskbook required the Automation page's persistent goals to use the **same Hermes GoalManager backend** as chat `/goal`, with no second goal state machine.

The submitted result explicitly says Automation still uses the Atlas Scheduler goal store/loop. Current `GoalsPanel.tsx` still talks to the existing `/api/goals` scheduler-oriented API and `CORE-PARITY.md` records I3 as partial.

**Required repair:** make Automation goals a scheduling/front-end layer over the same Hermes GoalManager lifecycle/state used by chat goals. Scheduling may remain in Scheduler, but goal state/progress/evaluation/continuation must not remain a second independent implementation.

### 2. A4 is not complete

The C3 taskbook explicitly required the sub-Agent settings UI:
- enable / disable
- default model

The result explicitly reports this UI is absent. Current Settings UI contains status/model-provider controls but no sub-Agent enable/default-model controls.

**Required repair:** add the two settings and wire them to the existing child-Agent configuration/data path. Do not create a second child-Agent settings store if one already exists.

## Scope decision

Do **not** reopen the completed C3 work and do **not** start C4 yet.

Next task is `ATLAS-C3R-FINISH`, limited to the two gaps above. Once those pass focused verification, C3 can be marked PASS and C4 can start immediately.
