# T1-TERMINAL-TOOL-ENTRY-SOURCE-064

Status: DONE_SCOPED (the DSH tool entry file is mapped; no Atlas model-terminal implementation is claimed)

## Files and dependencies

- tasks/dsh-parity/atomic/semantic-decisions.jsonl
- tasks/dsh-parity/atomic/atomic-capabilities.jsonl
- tasks/dsh-parity/atomic/interaction-edges.jsonl
- tasks/dsh-parity/atomic/batch-queue.jsonl
- tasks/dsh-parity/atomic/source-index.json and completion.json (updated from a digest-verified, pinned index)
- This report and tasks/dsh-parity/BEYOND-DSH-PROGRESS.md
- Dependency: DSH HEAD=d743267388641bc76f17c45ce8b4c231aed1d32c; exact file packages/experimental/tool-terminal/src/index.ts.

## Coverage result

The 78 units in the exact file are: 13 imports, 7 exports, 9 configuration defaults, 13 method candidates, 3 state transitions, 32 TypeScript function contracts and one file-review unit. Every unit is bound by exact unit_id and digest to a PARTIAL Task 1 source capability and an OPEN Atlas integration edge.

Source review covered all six tools (terminal_open, terminal_send, terminal_read, terminal_signal, terminal_close, terminal_list), owner/session identity checks, default cwd from workingDirectory.ensure, byte caps/finalization, foreground and background job behavior, and presentation contracts. Atlas has an interactive terminal WebSocket/renderer, but current model-catalog/API search found no matching persistent six-tool terminal surface. The edge remains OPEN pending production implementation. This source map does not imply terminal parity.

## Verification

Before applying decisions, the source repository head matched the pinned head and SHA256 of the indexed tool-terminal/src/index.ts matched the current source file. Applying the existing semantic overlay then validated all decision head/digest/reference constraints and persisted the resolution counts.

Actual verification output:

{"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","source_file_digest_match":true,"target_file_units":78,"decisions_added":78,"global_total":413747,"global_unresolved":413579,"overlay_validation":"PASS"}

Post-write index count: INDEXED_FILE_UNITS 78 MAPPED 78 GLOBAL_UNRESOLVED 413579. Completion remains INCOMPLETE.

## Limits and next work

This atom maps one runtime file only. Tests, renderer, background source, README/config, terminal service, lifecycle, and all cross-package consumers remain open. Next: implement and test one owner-scoped terminal_open/send/read/close vertical slice using an existing Atlas process/PTY seam or the smallest runnable provider, then continue mapping terminal package files and consumers.

