# DSH Parity Coverage — consolidated 135-row status

This table covers all 135 ledger rows. Statuses are derived from the current
ledger and batch RESULT files; each row links to its source evidence. CLOSED
means the parity requirement is closed, PARTIAL preserves the ledger's weaker
or incomplete behavior, NOT-DONE preserves absent work, and ATLAS-STRONGER
records an existing advantage that must not be reduced.

## Batch A — engine (E1–E36)

| Row | Status | Reason / evidence |
|---|---|---|
| E1 | NOT-DONE (mutable messages and redacted run journal are not an append-only source of truth) | [Ledger E1](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E2 | PARTIAL (typed terminal reason exists; complete turn/step lifecycle is missing) | [Ledger E2](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E3 | PARTIAL (hooks and finalizers exist; unified typed waterfall/result observer is incomplete) | [Ledger E3](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E4 | NOT-DONE (mandatory output schema/render/presentationMeta validation is absent) | [Ledger E4](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E5 | CLOSED (durable ordered inbox behavior implemented) | [Ledger E5](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E6 | CLOSED (request envelope and tool-change notice behavior implemented) | [Ledger E6](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E7 | CLOSED (argument-aware concurrency check and dispatch recheck implemented) | [Ledger E7](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E8 | CLOSED (step-boundary compaction and overflow retry generation implemented) | [Ledger E8](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E9 | CLOSED (durable plan mode and rejection feedback implemented) | [Ledger E9](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E10 | CLOSED (todo state persists as durable events) | [Ledger E10](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E11 | CLOSED (goal revision CAS and default round budget implemented) | [Ledger E11](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E12 | CLOSED (approval close values fail closed) | [Ledger E12](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E13 | CLOSED (permission preset binds sandbox and approval policy) | [Ledger E13](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E14 | PARTIAL (Docker per-call modes and enforcement reporting have focused tests; Docker Engine was unavailable and Windows host has no general per-call OS executor) | [Ledger E14](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT2-V7](waves/RESULT2-V7.md). |
| E15 | CLOSED (persistent PTY ownership, wait reasons, and bounded replay implemented) | [Ledger E15](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E16 | CLOSED (unified background job registry implemented) | [Ledger E16](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E17 | PARTIAL (delegate support lacks full inherited fork prefix and persona behavior) | [Ledger E17](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E18 | PARTIAL (real DeepSeek run reached one-call approval; accepted host call failed closed because no per-call executor is available) | [Ledger E18](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT2-V7](waves/RESULT2-V7.md). |
| E19 | NOT-DONE (tool result cannot yet conclude its enclosing turn) | [Ledger E19](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E20 | CLOSED (repeated identical tool calls produce non-blocking reminders) | [Ledger E20](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E21 | NOT-DONE (per-session durable working directory is absent) | [Ledger E21](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E22 | NOT-DONE (Agent Teams task roster and DAG behavior remains in-loop/unimplemented) | [Ledger E22](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E23 | PARTIAL (workflow orchestration is not model-authored script execution) | [Ledger E23](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E24 | NOT-DONE (serial Ralph context-reset loop is absent) | [Ledger E24](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E25 | PARTIAL (maintenance scheduling does not meet idle-only runMaintenance semantics) | [Ledger E25](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E26 | PARTIAL (tool restriction is not complete registration-scope validation) | [Ledger E26](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E27 | PARTIAL (PTC execution does not enforce the single run_code transport contract) | [Ledger E27](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E28 | CLOSED (compression preserves tool call/result spans) | [Ledger E28](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E29 | PARTIAL (surface-node token accounting lacks full request-usage anchoring) | [Ledger E29](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E30 | CLOSED (LSP operation union and provider registry are present) | [Ledger E30](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E31 | PARTIAL (session query tools do not yet provide full five-tool event/trace/lineage surface) | [Ledger E31](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E32 | PARTIAL (worktree support lacks full fixed-revision enter-session workflow) | [Ledger E32](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E33 | ATLAS-STRONGER (Atlas has write-path incremental diagnostics) | [Ledger E33](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E34 | CLOSED (cancellation emits synthetic results for skipped calls) | [Ledger E34](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E35 | CLOSED (compression lock bracket is persisted and orphan-detectable) | [Ledger E35](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| E36 | PARTIAL (background job completion followup behavior is incomplete) | [Ledger E36](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |

## Batch B — session/state (S1–S33)

| Row | Status | Reason / evidence |
|---|---|---|
| S1 | NOT-DONE (message rows and run journal are not an immutable sequenced event source) | [Ledger S1](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S2 | NOT-DONE (surface replacement does not durably shadow earlier event sequence ranges) | [Ledger S2](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S3 | CLOSED (session format migrations and forward-version refusal implemented) | [Ledger S3](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S4 | PARTIAL (reader-side crash repair closer is not fully wired) | [Ledger S4](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S5 | PARTIAL (persistent handle/lease guarantees are incomplete) | [Ledger S5](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S6 | CLOSED (checkpoint barriers fail closed) | [Ledger S6](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S7 | PARTIAL (summary metadata cannot yet fully reconstruct compressed event history) | [Ledger S7](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S8 | CLOSED (compression threshold/retention policy has parity) | [Ledger S8](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S9 | PARTIAL (pruned tool results are not durable masking replacement nodes across resume) | [Ledger S9](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S10 | NOT-DONE (image offload and model projection are blocked by durable attachment support) | [Ledger S10](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S11 | CLOSED (projection registry is pure, versioned, and snapshot-aware) | [Ledger S11](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S12 | NOT-DONE (persistent projection cache is absent) | [Ledger S12](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S13 | CLOSED (incremental session query corpus and invalidation implemented) | [Ledger S13](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S14 | PARTIAL (model-visible session query surface is incomplete) | [Ledger S14](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S15 | PARTIAL (sessionStats lacks complete timing metrics) | [Ledger S15](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S16 | NOT-DONE (turnOutline projection is unavailable) | [Ledger S16](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S17 | PARTIAL (ZIP export does not yet cover flushed live roots, child sessions, and attachment bytes) | [Ledger S17](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S18 | PARTIAL (spill failure preservation and locator semantics are incomplete) | [Ledger S18](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S19 | PARTIAL (durable content-addressed attachments and read-time integrity are incomplete) | [Ledger S19](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S20 | NOT-DONE (present deliverables and per-turn workspace changes are absent) | [Ledger S20](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S21 | PARTIAL (session-scoped filesystem observation and provider tokens are incomplete) | [Ledger S21](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S22 | PARTIAL (checkpoint span exists; independent event and session-log queues are incomplete) | [Ledger S22](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S23 | NOT-DONE (deduplicated session telemetry ledger is absent) | [Ledger S23](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S24 | NOT-DONE (opt-in OTLP/HTTP product telemetry is absent) | [Ledger S24](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S25 | PARTIAL (measurement helpers exist without route-aware production image pricing) | [Ledger S25](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S26 | NOT-DONE (DeepSeek API incremental session-log upload is absent) | [Ledger S26](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S27 | PARTIAL (skill provider freshness and incomplete-observation behavior is incomplete) | [Ledger S27](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| S28 | CLOSED (session title source precedence and user pinning implemented) | [Ledger S28](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S29 | PARTIAL (`@session` snapshot admission and untrusted wrapping are incomplete) | [Ledger S29](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S30 | ATLAS-STRONGER (Atlas long-term memory/library has no DSH equivalent) | [Ledger S30](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S31 | ATLAS-STRONGER (Atlas has three-mode rewind and file restoration) | [Ledger S31](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S32 | CLOSED (fork boundary guard and inherited end seed implemented) | [Ledger S32](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |
| S33 | CLOSED (attempt-level durable observability has parity) | [Ledger S33](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-B](RESULT-B.md). |

## Batch C — policy/sandbox/tools (X1–X33)

| Row | Status | Reason / evidence |
|---|---|---|
| X1 | NOT-DONE (service graph and fully unprivileged plugin core are absent) | [Ledger X1](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X2 | PARTIAL (registration disposal does not cover every extension lifecycle) | [Ledger X2](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X3 | PARTIAL (disabled-layer update is not idempotent on reload) | [Ledger X3](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X4 | PARTIAL (profile/bundle/patch ordered row-level composition is incomplete) | [Ledger X4](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X5 | NOT-DONE (dependency-resolving bundle install/remove and rollback are absent) | [Ledger X5](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X6 | NOT-DONE (peer compatibility and precise risk waiver flow are absent) | [Ledger X6](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X7 | NOT-DONE (persistent per-package build approval is absent) | [Ledger X7](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X8 | PARTIAL (agent preset isolation and revision guarantees are incomplete) | [Ledger X8](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X9 | PARTIAL (preset capabilities apply to runs; ACP entry is not wired) | [Ledger X9](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| X10 | PARTIAL (model plugin management lacks complete eight-action approval contract) | [Ledger X10](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X11 | PARTIAL (bundle source/availability/coverage manifest is incomplete) | [Ledger X11](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X12 | CLOSED (Claude Code hook bridge parity present) | [Ledger X12](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X13 | PARTIAL (Codex hook bridge coverage remains incomplete) | [Ledger X13](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X14 | ATLAS-STRONGER (Atlas has per-hook trust and approval gates) | [Ledger X14](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X15 | CLOSED (skill discovery root precedence has parity) | [Ledger X15](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X16 | PARTIAL (durable available-skills disclosure and inline injection are incomplete) | [Ledger X16](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X17 | CLOSED (skill invocation flags are normalized) | [Ledger X17](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-A](RESULT-A.md). |
| X18 | PARTIAL (skill provider protocol and per-scope layering are incomplete) | [Ledger X18](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X19 | PARTIAL (skill freshness invalidation is not immediate across all paths) | [Ledger X19](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X20 | ATLAS-STRONGER (Atlas enforces skill dependency and lifecycle gates) | [Ledger X20](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X21 | PARTIAL (MCP server instructions are not yet an independent prompt segment) | [Ledger X21](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X22 | CLOSED (MCP liveness budget, terminal removal, and recovery reset implemented) | [Ledger X22](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X23 | CLOSED (MCP resources and scope isolation implemented) | [Ledger X23](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X24 | PARTIAL (ACP session lifecycle remains incomplete) | [Ledger X24](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X25 | PARTIAL (SDK JSON-RPC lifecycle and wait protocol are incomplete) | [Ledger X25](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X26 | NOT-DONE (typed client/host remote gateway generation is absent) | [Ledger X26](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X27 | NOT-DONE (client extension slots and remote node definitions are absent) | [Ledger X27](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X28 | CLOSED (human slash commands register and run without model execution) | [Ledger X28](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-D](RESULT-D.md). |
| X29 | CLOSED (webhook provider adapter and trusted session request implemented) | [Ledger X29](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X30 | PARTIAL (SSH does not relocate the complete execution world) | [Ledger X30](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X31 | PARTIAL (scheduled execution is not bound to the original session) | [Ledger X31](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X32 | PARTIAL (configuration introspection lacks complete per-layer source composition) | [Ledger X32](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |
| X33 | CLOSED (agent/subagent provider seam has parity) | [Ledger X33](../../docs/parity/DSH-GAP-LEDGER.md); [RESULT-C](RESULT-C.md). |

## Batch D — desktop/UX (D1–D33)

## Batch E rows (D1–D33)

| Row | Status | Reason / evidence |
|---|---|---|
| D1 | PARTIAL (OS-assigned port/startup injection remains incomplete) | See ledger row D1 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D2 | PARTIAL (typed host IPC lifecycle is incomplete) | See ledger row D2 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D3 | PARTIAL (the event cap is removed; incremental timeline projection remains incomplete) | See ledger row D3 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D4 | NOT-DONE (central built-in renderer switch has not been removed) | See ledger row D4 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D5 | PARTIAL (durable attachment staging is incomplete) | See ledger row D5 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D6 | PARTIAL (structured composer draft behavior is incomplete) | See ledger row D6 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D7 | PARTIAL (reconnect baseline and sequence-gap repair are incomplete) | See ledger row D7 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D8 | PARTIAL (dock/float behavior is incomplete) | See ledger row D8 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D9 | CLOSED (retry affordance and restart confirmation are implemented and tested) | See ledger row D9 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D10 | PARTIAL (automatic update scheduling is incomplete) | See ledger row D10 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D11 | PARTIAL (the data is present, but presentation is weaker) | See ledger row D11 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D12 | PARTIAL (the available options exceed DSH, but placement is weaker) | See ledger row D12 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D13 | NOT-DONE (`present` deliverable tool is absent) | See ledger row D13 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D14 | CLOSED (`plan-review` routes to plan review controls; focused tests pass) | See ledger row D14 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D15 | PARTIAL (action coverage is stronger, reading coverage is weaker) | See ledger row D15 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D16 | CLOSED (ledger records parity) | See ledger row D16 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D17 | PARTIAL (namespaced i18n is incomplete) | See ledger row D17 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D18 | PARTIAL (see the Atlas-state limitation in the ledger) | See ledger row D18 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D19 | PARTIAL (see the Atlas-state limitation in the ledger) | See ledger row D19 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D20 | CLOSED (ledger records parity) | See ledger row D20 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D21 | ATLAS-STRONGER (preserve the existing advantage) | See ledger row D21 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D22 | CLOSED (ledger records parity) | See ledger row D22 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D23 | PARTIAL (see the Atlas-state limitation in the ledger) | See ledger row D23 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D24 | ATLAS-STRONGER (preserve the existing advantage) | See ledger row D24 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D25 | ATLAS-STRONGER (preserve the existing rewind advantage) | See ledger row D25 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D26 | CLOSED (ledger records parity) | See ledger row D26 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D27 | CLOSED (ledger records parity) | See ledger row D27 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D28 | ATLAS-STRONGER (preserve the existing advantage) | See ledger row D28 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D29 | PARTIAL (see the Atlas-state limitation in the ledger) | See ledger row D29 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D30 | PARTIAL (readable trajectory/raw event toggle exists; unified Chat/Trajectory mode is incomplete) | See ledger row D30 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D31 | ATLAS-STRONGER (preserve multi-window, split panes, and floating composer) | See ledger row D31 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D32 | ATLAS-STRONGER (preserve message-level edit/fork/rewind actions) | See ledger row D32 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |
| D33 | CLOSED (ledger records parity) | See ledger row D33 in [DSH-GAP-LEDGER.md](../../docs/parity/DSH-GAP-LEDGER.md). |

## Added section 6 requests

| Item | Status | Reason / owner |
|---|---|---|
| Causal message explain endpoint | PARTIAL (endpoint answers turn/step ordinal, tool links, current compaction projection, and rewinds logged after this change) | Historical rewinds have no durable per-message rewind ID, and message rows do not carry a first-class step ID; old rows therefore return `specific_rewind: not_recorded` and infer the step ordinal from transcript order. |
| `capabilities.usage` | NOT-DONE (outside Batch E directories) | Coordinator / introspection owner should add registry-source and usage accounting under `core/atlas/introspect/`. |
| Effect receipt | NOT-DONE (outside Batch E directories) | Batch A/C should capture post-tool effects; Batch B should persist receipts to the event stream. |
| Eight Atlas-stronger regression cases | NOT-DONE (requested aggregate file is outside Batch E) | Core test owner should add `core/tests/test_atlas_advantages.py`; feature evidence belongs to Batch A (LSP), Batch D (trust/skills), Batch E (rewind/UI/document preview), plus the memory/library owner. |
| Cross-system parity benchmark | NOT-DONE (outside Batch E `core/atlas/api/` and `frontend/src/`) | Coordinator/core-scripts owner should implement `core/scripts/dsh_parity_bench.py` and record measurements in `BENCH.md`. |
