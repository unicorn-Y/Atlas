# Atlas Current Task

CURRENT: ATLAS-C1-HERMES-CORE
STATUS: PARTIAL; NOT ACCEPTED; CURRENT FULL SUITE HAS 7 BASELINE FAILURES; C1 PARITY GAPS REMAIN
TASKBOOK: tasks/taskbooks/ATLAS-C1-HERMES-CORE.md
RESULT: tasks/results/ATLAS-C1-HERMES-CORE.result.md

BASE_BRANCH: main
PROTOCOL: 1.10
SCOPE: C1 Hermes core replacement, including backend and frontend. `core/atlas/origin_guard.py` was not relaxed; `core/atlas/safety/` remains disabled and unchanged for this work.

DELIVERY:
- §§1–4 and §9 were already committed before this continuation. This continuation pushed §5 `35cd874`, §6 `b93076b`, §7 `4d975de`, §8 `fe31ba1`, §10 focused coverage `4357a86`, and the protocol 1.10 follow-up `fafb7c8`.
- Frontend checks passed: renderer TypeScript, Electron TypeScript, Vitest (36 tests), Vite build. Edge screenshots were captured for the conversation, changes, terminal, and settings views.
- Baseline at `805110c` (`0d48720^`): `9 failed, 955 passed, 9 skipped, 2 warnings in 223.86s`; current full run: `7 failed, 975 passed, 9 skipped, 1 warning in 235.47s`. Every current failure reproduces at baseline. No new full-suite failure remains.
- Not accepted: CORE-PARITY C1 rows A5 (MoA), L9 (budget reminders), T11 (interactive terminal stdin/PTY actions), and T19 per-action verification, plus §10 #10 full event-sequence comparison, remain incomplete or uncovered. Hermes source regression selection also has Windows-specific failures.
- No real model or live remote MCP/SSH scenario was run. Local voice remains deferred. Safety review remains user-owned and was not performed.
