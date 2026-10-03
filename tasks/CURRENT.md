# Atlas Current Task

CURRENT: ATLAS-MEGA-PERSISTENT-CLOSEOUT
STATUS: REVIEW_PASSED
CONTROLLER: ZCodex
TASKBOOK: tasks/taskbooks/ATLAS-MEGA-PERSISTENT-CLOSEOUT.md
RESULT: tasks/results/ATLAS-MEGA-PERSISTENT-CLOSEOUT.result.md
REVIEW: tasks/reviews/ATLAS-MEGA-PERSISTENT-CLOSEOUT.review.md

BASE_BRANCH: main
BASE_COMMIT: 631b5f6ad030e283bebe5fc64833ca68a55641fc
PARENT: ATLAS-MEGA-PERSISTENT-ALWAYS-ON
PREVIOUS: ATLAS-MEGA-PERSISTENT-ALWAYS-ON
PREVIOUS_STATUS: PAUSED_AFTER_SYNC

## Goal

Resume directly from the synced integration checkpoint and finish the Persistent / Always-On closeout.

Do not redo W1-W7 and do not restart broad research.

Close only the remaining integration gaps:
1. Group Chat -> real persistent-agent runtime;
2. persistent Agent session restart + real sessions API;
3. desktop/channel same conversation;
4. Automation/Heartbeat -> real channel delivery;
5. Atlas-owned laptop offline/restart durable continuation;
6. Device takeover -> X2 pending/resume bridge;
7. learned skill -> actual next Agent run;
8. current backend wiring failures;
9. P11 16 fake-E2E acceptance with no real MISSING items.

## Known checkpoint

Latest synced implementation checkpoint before this closeout:
- `631b5f6`
- frontend batch: 155/155 green
- backend focused batch: 26/38, wiring errors remain
- P11 map: 9 COVERED / 5 PARTIAL / 2 MISSING

## SUBAGENT POLICY — HARD REQUIREMENT

- Use subagents for the bulk of implementation, focused tests, and review.
- Target the maximum concurrency the runtime actually allows.
- Do not hard-code a worker count.
- If a spawn is rejected, shrink the batch and continue when slots free up.
- Do not fall back to single-threaded work because of one concurrency rejection.
- `core/atlas/server.py` has one integration owner.

## Completion

Write:
- `tasks/results/ATLAS-MEGA-PERSISTENT-CLOSEOUT.result.md`

Then set CURRENT to `AWAITING_REVIEW`, push main, verify local/remote heads, and stop.

Do not start X6 / T1 / R1 / MemoryOS / new UI redesign / new upstream research.
