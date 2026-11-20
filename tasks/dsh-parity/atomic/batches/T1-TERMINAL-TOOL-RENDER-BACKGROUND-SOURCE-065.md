# T1-TERMINAL-TOOL-RENDER-BACKGROUND-SOURCE-065

Status: DONE_SCOPED (two source files mapped; Atlas model-terminal rendering and background PTY behavior remain open)

## Files and dependencies

- tasks/dsh-parity/atomic/semantic-decisions.jsonl
- tasks/dsh-parity/atomic/atomic-capabilities.jsonl
- tasks/dsh-parity/atomic/interaction-edges.jsonl
- tasks/dsh-parity/atomic/batch-queue.jsonl
- tasks/dsh-parity/atomic/source-index.json and completion.json
- This report and tasks/dsh-parity/BEYOND-DSH-PROGRESS.md
- Dependency: pinned source head d743267388641bc76f17c45ce8b4c231aed1d32c.

## Coverage result

Mapped 35 exact units across:

- packages/experimental/tool-terminal/src/render.ts: 28 units covering UTF-8 byte length, head/tail retention, suffix/prefix truncation, spawn/send/read/list renderers and state markers.
- packages/experimental/tool-terminal/src/background.ts: 7 units covering the consuming terminal-send output source and monotonic byte cursor.

Each decision is linked to the still-open model-terminal integration capability. Both current source-file SHA256 values matched the existing pinned source index before overlay application. The tool-terminal entry file plus these files now has 113/113 source units mapped; the rest of the DSH package remains unresolved.

## Verification

Actual overlay validation output:

{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","files":["packages/experimental/tool-terminal/src/render.ts","packages/experimental/tool-terminal/src/background.ts"],"units":35,"digest_bound":35,"global_total":413747,"global_unresolved":413544,"overlay_validation":"PASS"}

Completion remains INCOMPLETE. No Atlas runtime equivalence is implied.

## Limits and next work

This map does not implement terminal result rendering, persistent PTY lifecycle or background job integration in Atlas. The package tests, docs/defaults, terminal backend package and consumer call sites remain open.

