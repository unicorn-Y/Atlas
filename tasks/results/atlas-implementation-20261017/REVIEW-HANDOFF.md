# GPT-6 review handoff — 2026-10-17

Review branch: `integration/atlas-fixes-20261017`

Review starting tip before this handoff update: `688d57e4c82fae86379bc9d9bc40dc1f5122b3b6`

Read `IMPLEMENTATION-STATUS.md`, `TEST-EVIDENCE.md`, and `INTEGRATION-DIFF.md`. Please independently review the integrated source and evidence, with particular attention to R1 same-model retry/budget behavior, R2 resolved route wire assertions, R3 propagated process exit status, R4 terminal content-filter handling, memory exact-source and queue recovery behavior, and startup activation rollback.

Known review limits: no live provider calls, D:\Atlas changes, real-memory writes, or Electron microphone smoke tests were performed. The focused Stop test required disabling WebSocket ping in the test client because isolated server skills startup can exceed its default ping interval; business timeout remains 90 seconds.

FIND-5 is now wired on the normal path (this supersedes the earlier "UID not exposed" limit). `KernelRequest.message_uid` is populated from the durable user-row insert's UID reported on `hermes.result`, with a trailing-row recovery branch for callers that persist the user message before the run; the finalizer passes it to `schedule_turn`. Two turns of identical text were verified against a real temp SessionDB to produce two distinct SourceRefs, and an absent UID still records `missing` rather than a guess. Please check that the dedup/recovery branch in `core/atlas/kernel/loop.py` cannot adopt a stale UID for a repeated message, since that is the specific regression this finding was about.

Status: `AWAITING_GPT6_REVIEW`
