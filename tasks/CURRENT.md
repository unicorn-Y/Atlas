# Atlas Current Task

CURRENT: ATLAS-MEGA-LATEST-DAILY-READY
STATUS: READY_FOR_EXECUTION
CONTROLLER: ZCodex
TASKBOOK: tasks/taskbooks/ATLAS-MEGA-LATEST-DAILY-READY.md
RESULT: tasks/results/ATLAS-MEGA-LATEST-DAILY-READY.result.md
REVIEW: tasks/reviews/ATLAS-MEGA-LATEST-DAILY-READY.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C6R-FINISH
PREVIOUS_REVIEW: PASS — C1-C6 closed

## Goal

One continuous execution from current Atlas to daily-ready:

1. freeze current latest upstream/product sources;
2. sync latest Hermes upstream into the Atlas fork;
3. re-audit and upgrade already-finished C1-C6 against current best implementations;
4. finish latest-best X2 Computer/Browser;
5. finish latest-best X4 Skill Market;
6. finish X5 Self-Evolution / continuous upstream tracking;
7. integrate everything;
8. run K1 parity/tests/fake daily paths and fix discovered problems;
9. deliver a version ready for the user's own daily real-world use.

Do not stop between these internal phases for external review.

## SUBAGENT EXECUTION POLICY — HARD REQUIREMENT

- Use subagents aggressively for research, source comparison, conflict resolution, implementation, tests, and review.
- **Target the maximum subagent concurrency the current runtime actually allows.**
- **Do not hard-code a worker count.**
- Whenever independent file/module ownership exists, keep spawning workers until the runtime refuses additional concurrent workers.
- If a spawn is rejected because of concurrency/quota, automatically shrink that batch and continue with available workers; when slots free up, spawn the remaining work.
- A concurrency rejection is NOT a reason to disable subagents or fall back to one worker.
- Same hot files must have one owner or be integrated serially.
- Controller reviews/integrates; workers do the bulk of coding and focused tests.
- Commit/push at internal checkpoints and continue immediately.

## Boundaries

- Speed first; mature upstream code first.
- Do not build duplicate runtimes/registries/schedulers/session systems.
- Keep Memory frozen.
- No video.
- No real paid model calls required.
- Do not weaken OriginGuard.
- User handles security review.
- Do not start X1/X3/X6/X7/full-T1/R1.

## Completion

Write the unified mega result, set CURRENT to AWAITING_REVIEW, push both repositories, verify local/remote heads, and stop.
