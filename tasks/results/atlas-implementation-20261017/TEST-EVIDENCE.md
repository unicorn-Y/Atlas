# Test evidence — 2026-10-17

All results below are focused checks reported from the isolated implementation worktrees; broad unrelated suites were not run.

| Area | Result | Boundary |
|---|---|---|
| R1 auxiliary retry | `9 passed, 65 deselected`; diff check clean | No live provider/API request |
| R2 route mock | `1 passed`; verifier `9/9`, exit 0 | Corrected route/model/wire assertions |
| R3 verifier exit | Injected failing assertion in a temporary copy; process exit 1 | Temporary copy only |
| R4 content filter | `1 passed` | Confirms terminal failure; no prompt rewrite/resend |
| Kernel cancel + verification | `3 passed`; content-filter regression in combined focused run contributed to `4 passed` total; existing deprecation warnings | Direct AtlasKernel end-to-end Stop not exercised |
| Memory backend | Nine isolated targeted cases passed individually: Dream late/checkpoint/restart and owner edit; equal-timestamp cursor; failed queue detail/retry; 1,205 search candidates; exact UID open and missing-UID no-guess; exact source text; diary idempotency; startup drain after model ready; pending retained without a ready model | Each used temporary `ATLAS_DATA_DIR` or monkeypatch. Ruff on `source_ref.py` passed; broad Ruff scan found 46 mostly pre-existing style findings, not changed |
| Memory queue UI | `2 files, 6 tests passed`; renderer TypeScript check exit 0; diff check clean | Exercises user-triggered single/all retry and refresh |
| Startup/update | `node --check scripts/atlas-update.mjs` and diff check passed; isolated candidate dependency failure kept active HEAD, main/renderer/preload, stamp, and dependency fingerprint unchanged; old Electron actually relaunched and wrote its marker | Candidate frontend build-stage failure was not reached because locked dependency installation exceeded the probe time limit |
| Voice lifecycle | Five focused static checks and diff check passed | `tsc` unavailable in that worktree; Electron/microphone smoke not run |
| Context handoff | `2 passed`; frontend build passed; modified-file Ruff and diff checks passed | No automatic sending |

The broad `core/tests/test_kernel_tool_error_regressions.py` attempt with system Python first lacked the declared `json_repair` dependency. The relevant regression passed under the project interpreter. A later full-file attempt stalled and was stopped; it is not counted as passing.
