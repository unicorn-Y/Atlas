# Lane finish gates — Codex CLI / Code Mode Host

State remains **WORK IN PROGRESS**. Gate policy follows the fetched `CODEX-REVERSE-COMPLETION-GATES.md` from dispatch branch `research/agent-reverse-dispatch-20261019`; that file is not present on this lane. Do not call this complete because evidence files are present.

| Gate | State | Evidence / open work |
|---|---|---|
| G0 release identity and composition | PASS (package identity); PARTIAL (binary/source implementation matching) | Exact archive hashes/sizes, expanded file counts and host byte equality: `COVERAGE.md`, `extractions/*`. Source tag attribution confirmed; byte-reproducible build or binary function mapping absent. |
| G1 executable code coverage | PARTIAL | Scoped crate inventories are now counted and selected code paths parsed; many app-server/core/CLI handlers and registrations remain unaudited. See `COVERAGE.md`. |
| G2 UI/command → RPC/Host → state/events | PARTIAL | `SURFACE-MAP.tsv` closes CLI protocol admission/user-message event + explicit cross-process `thread/resume` of persisted history, and Host legacy stdio → V8 cell → synthetic tool callback; static Core gRPC/tool/child links identified. No full assistant/tool/subagent event chain from a completed release CLI turn; all CLI/TUI command actions are not enumerated. |
| G3 Agent semantics | PARTIAL | Turn/tool, cell broker, thread graph, mailbox, residency, daemon snapshot recovery and error boundaries have source anchors. No claim of all handlers/default-enabled features or process-level recovery. |
| G4 actual execution | PARTIAL | Shipped CLI initialize/thread/start/turn-start and subsequent cross-process resume of persisted interrupted history, plus Host legacy stdio cell + synthetic nested tool callback, ran in isolated scratch. CLI emitted no assistant/model/tool result; no child agent. No account credentials were supplied; managed daemon snapshot recovery and Host gRPC+stdio Core transaction remain untested. |
| G5 Atlas main comparison | PARTIAL | Compared with main `990d0ccdeed9604b027e74ef152cb0004c4d9375`; backlog lists specific Atlas anchors. Several Atlas runtime/restart and multi-agent modules still require direct path tracing. |
| G6 reports/evidence | PARTIAL | Required lane artifacts exist and existing ledger/index/trace/UI/gap docs updated in this checkpoint; raw synthetic logs remain outside repo. G1/G2/G3 gaps prevent pass. |
| G7 closeout | NOT MET | Continue while local source, operation paths, host protocol, tool result streaming, model turn or child lifecycle can be safely analyzed. Keep `WORK IN PROGRESS`. |

**Do not collapse:** user-message item completion is not turn completion; graph-store existence is not feature activation; rollout file creation is not active-work cold resume; Host hello is not cell execution; gRPC implementation is not a captured gRPC stream; static tests are not runtime evidence.
