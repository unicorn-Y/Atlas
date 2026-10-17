# ATL-001–ATL-025 final status

This is a closeout ledger, not a second project-wide audit. Statuses retain the earlier integration evidence and add this task's Windows results. `PRIOR-ISOLATED` refers to the focused evidence summarized in `tasks/results/atlas-implementation-20261017/TEST-EVIDENCE.md`; it does not mean Windows or live-model acceptance.

| ID | Issue | Final state | Evidence / boundary |
|---|---|---|---|
| ATL-001 | Model failure retry / keep selected model | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | R1 focused retry checks: 9 passed; no live provider request. |
| ATL-002 | Run cancellation / long tools | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Isolated Stop path observed `run.cancelled` without tool completion; no side effect claim beyond that scenario. |
| ATL-003 | Truthful completion / post-edit verification | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior focused kernel checks; no blanket full-suite acceptance. |
| ATL-004 | Duplicate tool stream / candidate integration risk | `INTEGRATION_RISK_AVOIDED; NOT_DEPLOYED` | Deduped integration tip retained; not an entity vulnerability. |
| ATL-005 | Session queue / run state | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior queue and runtime-focused evidence only. |
| ATL-006 | Model failure detail UI | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior UI/kernel regression checks; no claim of all error states. |
| ATL-007 | SSH workspace / LSP | `PARTIAL; CODE_FIXED; NOT_DEPLOYED` | User-facing notice added and focused worker checks passed. Remote LSP transport is still absent. Windows file: 2 passed, 1 test import failed (`No module named 'tools'`). |
| ATL-008 | Dream checkpoint / recovery | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior isolated Dream checkpoint/restart cases passed. |
| ATL-009 | Dream manual edit / concurrent write | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Three focused concurrent addition/deletion/replacement cases passed. |
| ATL-010 | Failed queue recovery | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior isolated failure detail and explicit retry coverage. |
| ATL-011 | Queue process restart | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Bounded startup drain after model readiness covered in prior focused tests. |
| ATL-012 | Memory search pagination / filters | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior >100k candidate and filtered-page checks. |
| ATL-013 | Timeline cursor pagination | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Stable `(at,id)` cursor checks passed previously. |
| ATL-014 | Provenance / source authenticity | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Exact SessionDB UID chain and no-guess boundary verified in temporary data. |
| ATL-015 | Forget / source propagation | `CODE_FIXED; TESTED_ISOLATED; VERIFIED_WINDOWS; NOT_DEPLOYED` | Exact-source tombstones; Windows focused file 7 passed. Derived memory stays excluded; raw session source is retained and can be opened. |
| ATL-016 | Memory-root multi-writer / Git history rewrite | `NOT_APPLICABLE_CURRENT_DEPLOYMENT; NOT_DEPLOYED` | Current observed Atlas API uses one server-owned store; no second writer was observed. Detached Hub remains a conditional risk, not a tested success. |
| ATL-017 | Startup / debugging surface | `CODE_FIXED; VERIFIED_WINDOWS; NOT_DEPLOYED` | Local no-Origin CDP/CUA preserved; foreign Origin rejected with 403; loopback bind verified. |
| ATL-018 | Update / rollback | `CODE_FIXED; TESTED_ISOLATED; VERIFIED_WINDOWS; NOT_DEPLOYED` | Windows updater transaction tests 3 passed; lock/build cold start completed. No live replacement of the user's tree. |
| ATL-019 | Dependency pin / Python startup | `CODE_FIXED; VERIFIED_WINDOWS; NOT_DEPLOYED` | Windows startup used `requirements.lock`; build stamp records locked install. No claim for other Python environments. |
| ATL-020 | Source / build artifact consistency | `CODE_FIXED; VERIFIED_WINDOWS; NOT_DEPLOYED` | Cold-start build stamp matches source commit and frontend build completed. No installer/package acceptance. |
| ATL-021 | Voice/resource lifecycle | `CODE_FIXED; PRIOR-ISOLATED; NOT_VERIFIED_WINDOWS; NOT_DEPLOYED` | Prior focused lifecycle checks; no microphone or device test on this Windows run. |
| ATL-022 | content_filter must be terminal | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior terminal-failure regression passed; no rewriting/resend workaround retained in integration. |
| ATL-023 | Bounded runtime retry | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Prior bounded retry and delay checks; no live network outage run. |
| ATL-024 | Auxiliary model fallback | `CODE_FIXED; PRIOR-ISOLATED; NOT_DEPLOYED` | Integration keeps same-model retry/no hard-coded DeepSeek fallback; live provider behavior not tested. |
| ATL-025 | W1 / runtime merge conflict | `PARTIAL; READY_FOR_CUTOVER; NOT_DEPLOYED` | Candidate patch applied cleanly except `core/atlas/kernel/model_call.py`: local content-filter guidance/reissue conflicts with terminal content-filter policy. Exact local version and research/config backup are preserved. Requires human semantic selection before cutover. |

`VERIFIED_WINDOWS` only marks Windows evidence described in [WINDOWS-SMOKE.md](WINDOWS-SMOKE.md). No row means all 25 bugs passed live end-to-end. Overall status: `AWAITING_GPT6_WINDOWS_REVIEW` for code and evidence; deployment is not performed.
