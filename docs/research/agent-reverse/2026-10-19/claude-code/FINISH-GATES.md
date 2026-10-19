# Claude Code lane finish gates

Status: **WORK IN PROGRESS**. Last updated 2026-10-19 HKT. No completion declaration.

| Gate | Status | Evidence / remaining work |
|---|---|---|
| G0 exact shipped identity | PASS | Two pinned archives, full archive/member hashes and exact executable SHA/version are recorded in `evidence/01-archive-manifest.json`, `evidence/03-native-file-tree.txt`, `evidence/04-package-metadata.md`; exact PE reopened in REA and matched. |
| G1 all executable code/registrations coverage | PARTIAL | Complete package member inventory, bounded PE header, registrations and three source regions. Bun embedded module inventory, all command handlers and hook/plugin/MCP/TUI surfaces remain unenumerated. See `COVERAGE.md`. |
| G2 UI/CLI → runtime → events/persistence chain | PARTIAL | New static CLI Agent tool → permission/target resolution → inbox writer → inbox reader/ack chain is closed in `END-TO-END-TRACES.md`; worker recovery is statically traced. Full argument dispatch, TUI action, actual scheduler→model→tool and parent notification are unknown. |
| G3 Agent semantics | PARTIAL | Worker retry/resume selection, v5 state fields, SendMessage routing, mailbox append/read/prune and task/event schemas are source grounded. Model attempt/tool ordering, cancellation races, error recovery and actual parent-child lifecycle are open. |
| G4 limited real execution | BLOCKED | Exact binary starts in isolated synthetic repo and emits `system/init`; model request returns repeated HTTP 401 `authentication_failed`, so no model/tool/subagent turn. REA Windows PTY capture unavailable (descendant-cleanup verification limitation). See exact attempt and unlock condition in `END-TO-END-TRACES.md`. |
| G5 Atlas main comparison | PARTIAL | Pinned SHA `aa6196f550098cc46081dc6db2c376cb87ddffa5`; path-specific comparisons and backlog in `ATLAS-IMPLEMENTATION-BACKLOG.md`. Further general runtime/UI cross-check remains. |
| G6 auditable bundle | PARTIAL | Required files now exist, this gate file links evidence, and original provenance/index/unknowns are retained. Need independent evidence spot-check and fuller inventory before pass. |
| G7 stop rule | WORK IN PROGRESS | Local analysable executable source and the synthetic runtime remain investigable. G4 blocker is specifically credentials for an isolated synthetic run; it does not excuse unfinished G1–G3. Continue on available source before any completion status. |

Evidence categories: **S** exact-package bytes/source and static control logic; **R** isolated process init plus explicit 401 response; **D** existing official-document references only where separately cited; **I** bounded comparison judgment; **U** live model/tool/subagent behavior, daemon registry transaction/IPC and full UI/TUI.
