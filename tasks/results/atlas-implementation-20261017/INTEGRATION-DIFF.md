# Integration diff — 2026-10-17

Target: `integration/atlas-fixes-20261017`, based on `ui-redesign` at `0b1ba4114e25643369c95bfac85d37563788444`.

All implementation batches were cherry-picked from isolated worker branches and pushed incrementally. The current branch combines:

- R1–R4 model-router, route mock, verifier, and terminal content-filter corrections.
- Kernel Stop cancellation and verification nudge.
- Memory backend source provenance, Dream checkpointing, timeline/search pagination, queue recovery, and startup drain.
- Memory Library failed-queue controls.
- Candidate-worktree update activation and rollback/relaunch handling.
- Late microphone stream cleanup and explicit context handoff.

GPT-6 rework commits add Dream latest-owner concurrency behavior, transactional update rollback/no-op handling, streamed SQLite-backed complete browse pagination and explicit SourceRef UID handling, plus the isolated Atlas API Stop path test. FIND-5 normal-run UID propagation is partial because no UID-bearing user append result is exposed at the current scheduler entry point; absent UIDs now stay missing instead of being guessed.

No whole-branch merges were used. The canonical `tasks/CURRENT.md` was left unchanged. Windows power-loss/process-termination timing was not simulated; ATL-017 stayed unchanged under its high-authority workflow boundary.
