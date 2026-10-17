# Atlas implementation status — 2026-10-17

Branch: `integration/atlas-fixes-20261017`

Current source tip before this evidence update: `688d57e4c82fae86379bc9d9bc40dc1f5122b3b6`

Status: `AWAITING_GPT6_REVIEW`

## Delivered

- R1: `complete_for()` retries transient auxiliary requests on the same model, bounds retries, honors numeric and HTTP-date `Retry-After`, rejects waits above 15 seconds, and retains one budget reservation/release. No fallback model is used.
- R2: route-mock expectations now follow candidate resolution and assert resolved model and wire payload; stale candidate-count/model claims were corrected.
- R3: the verifier launcher no longer masks child failures with `os._exit(0)`; success and intentional failure exit statuses were checked.
- R4: terminal content-filter behavior is covered; no prompt rewriting or retry workaround was introduced. R1–R3 harness repairs are integrated on this branch.
- Kernel: Stop cancellation cleans up the optional waiter, and the completion verification nudge is wired without permitting later side effects after cancellation.
- Memory: Dream checkpoints use stable source identity and preserve owner edits; failed queue detail and explicit retry API plus UI; bounded startup drain after model readiness; full candidate pagination; stable `(at,id)` timeline cursor; exact SessionDB message UID source references without guessing; idempotent diary append.
- Startup/update: updates build in a candidate worktree, validate required app bundles, and activate only after candidate preparation; failure relaunches the old app. Initial dependency setup uses the locked requirements file.
- Voice overlay: late microphone permission results release tracks after unmount and skip AudioContext creation.
- Context handoff: creates a linked child session and an editable draft; sending remains a user action.

## GPT-6 rework disposition

- BLOCK-1 fixed: Dream writes from latest locked owner state, retaining concurrent additions while not restoring deleted/replaced stale lines.
- BLOCK-2/BLOCK-3 fixed: per-directory updater backup/activation tracking, rollback after second bundle replacement or post-activation rebuild failure, and no-op update exit before candidate setup.
- FIND-4 fixed: browse scans keyword/vector candidates in bounded batches into temporary SQLite staging, filters/deduplicates and counts all matches, and returns the requested page without a 100k candidate ceiling. Raw transcript search is offset-paged in 50-row batches. Score normalization, keyword rounding, vector clamping, and temporal decay follow the prior hybrid semantics.
- FIND-5 fixed: the normal-path reference is now wired end to end. `KernelRequest` carries `message_uid`; `AtlasKernel.run` keeps the UID returned by the durable user-row insert (`append_session_message` already returned one — it was being discarded), also recovers the trailing durable row's UID when the caller already persisted it, and reports it on `hermes.result`; `run_phases` adopts it into `state.request.message_uid` and passes it to `schedule_turn`. References are still only built from a SessionDB-verified UID, so repeated text cannot select a newer message and an absent UID still yields missing precision (it is never guessed). Two turns of the same text ("继续" twice) now produce two distinct SourceRefs.
- FIND-6 fixed at focused-test level: isolated real API/WebSocket Atlas executor test starts `clock.sleep`, sends `run.cancel`, and observes `run.cancelled` without a `tool.completed`. Test client ping is disabled only for this case because temporary server startup's skills scan can exceed the default websocket ping interval; the business timeout remains 90 seconds.
- FIND-7 fixed: updater returns before candidate worktree/dependency/build setup when no remote commit is pending.

ATL-017 high-authority CDP/Computer Use behavior was preserved because no concrete local usability defect was established for this repair scope. ATL-015/016 were not changed.

No files or real data under `D:\Atlas` were modified. One earlier memory test made a read-only SessionDB lookup for a synthetic nonexistent session ID; no matching session was found and no writes occurred. Subsequent memory checks used isolated data roots or monkeypatches.

The independent web ChatGPT GPT-6 reviewer owns final acceptance. This status is not a PASS.
