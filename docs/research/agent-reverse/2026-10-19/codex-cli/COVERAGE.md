# Codex CLI / Code Mode Host coverage ledger

**Scope:** Windows x64 release `0.163.0`, release/source identities in `extractions/ARCHIVE-HASHES.json`; source is `openai/codex@83086188ae0614bd882818ff1aa23f3194962012`. This is a package inventory plus scoped static analysis, not a claim that every Rust module was semantically audited.

## Release composition and identity (G0)

The pinned release manifest in `docs/research/agent-clients/2026-10-19/manifest.json` resolves to three archives already collected and independently re-hashed in the staging area: CLI ZIP 167,080,091 bytes / `dabdb4d16aaf10fea40b74811c96efddcd9138f122163b69ed604fcb3eb704c3`; standalone Host ZIP 28,217,604 bytes / `bc82fa6d8f449c818292eac35bd7400c4f7dae08908fc9bc67bfbad8c4a3de68`; source ZIP 22,647,697 bytes / `36fda4e61c251d805c2d68203c3a34b0f6881a88846e12776ca02fb13d6e67c7`. CLI archive expands to 47 files / 491,608,073 bytes; standalone Host to one EXE / 74,921,264 bytes; source to 9,176 files / 90,861,742 bytes. The CLI-bundled Host and standalone Host are byte-identical: SHA-256 `07f3869f0849cd54b31cec1f86ec796f004501bd3a215135c1facc883a2b9988`. CLI entry is `codex-x86_64-pc-windows-msvc.exe` (341,270,320 bytes, SHA `2692c8c7bb2cf8b0aefe638741fc90236f4b824c59578ce84994f9de58200993`); helpers include command-runner, Windows sandbox setup, `rg.exe`, voice host, GStreamer runtime/DLLs and manifests/licenses. Exact per-file inventory and hashes are `extractions/EXTRACTED-TREE.txt` and `extractions/BINARIES.json`.

The voice resource manifest reports app `0.163.0` and build commit matching the fixed source. This is attribution, not reproducible-build equivalence. Package signature and bounded PE import/string evidence remain in extraction files; no binary function mapping is claimed.

## Executable source groups

Counts below are all `.rs`, `.toml`, `.json` files under each listed crate from the complete pinned source tree. They are **inventory counts**, not counts of files fully interpreted. Source-snapshot path outside this research branch: `D:\agent-client-staging\codex-cli-deep\source\codex-rust-v0.163.0\codex-rs`.

| Group | Inventory files / bytes | Analysis in this lane | Unscanned / reason |
|---|---:|---|---|
| `cli` | 105 / 1,461,372 | `src/main.rs` command/daemon/remote wiring; shipped help; release app-server protocol smoke | Other CLI command internals only followed where linked; complete command-by-command effect review remains open |
| `app-server` | 355 / 7,116,704 | request admission, serialization scope, daemon thread recovery, thread/turn and streaming event paths | Most processors and event families are not exhaustively enumerated |
| `app-server-protocol` | 387 / 4,934,346 | typed JSON-RPC request/event definitions; initialize/thread/turn schemas and scoping macros | Schema field inventory beyond mapped flows remains open |
| `app-server-daemon` | 35 / 405,703 | local daemon control is indexed in `IMPLEMENTATION-TRACE.md` | Full platform-specific lifetime/transport failure audit open |
| `core` | 868 / 16,965,535 | turn loop, tool registry/runtime, Code Mode delegate, agent control/spawn/residency/mailbox/completion, retained context and MCP refresh | Full crate is not covered; targeted file/function anchors are in `DISCOVERY-LEDGER.md` and `IMPLEMENTATION-TRACE.md` |
| `code-mode-host` | 35 / 338,716 | legacy stdio and gRPC transports, handshake, session lease, cell/callback routing, quotas and recovery tests | Every request type and failure test has not been independently replayed against release binary |
| `code-mode-runtime` | 28 / 292,694 | V8 module evaluation, async cell lifecycle and pending frontier | Full runtime implementation review open |
| `code-mode-protocol` |  (included in source) | length-prefixed JSON frame and handshake schema; real Host handshake below | Complete message catalog not mapped |
| `agent-graph-store` | 6 / 17,380 | SQLite interface, parent/child edge writes and descendant queries | Exhaustive query/error case review open |
| `agent-message-board-client` | 6 / 35,739 | remote board protocol/client/subscription hooks | Release activation and real remote service remain unknown |
| `hooks` | 59 / 583,513 | Registration/turn lifecycle surfaces indexed as independent extension path | Hook inventory and end-to-end invocation coverage incomplete |
| `realtime-webrtc` + `voice-host` | 49 / 298,692 | packaged helper identity, IPC handshake and source lifecycle map | Authenticated backend/audio capture intentionally not attempted |

## Registration and extension inventory

The registry is layered, not a single plugin list: trusted core tools and externally supplied tools enter `CoreToolRuntime`/`ToolRegistry`; `ToolOrchestrator` applies policy/hooks; MCP server refresh builds external definitions; Skills/Plugins and dynamic tools are introduced through prompt/context and typed app-server configuration; Code Mode tool definitions are lazily searched and brokered; MultiAgent V2 handler registration is feature/config gated; graph-store and message-board are injected dependencies. Evidence IDs `CODEX_CLI-004,019,027–033` and implementation anchors enumerate the confirmed paths. Independent crates are not proof of enabled product behavior. No complete mechanically extracted registration table exists yet.

## Coverage conclusion

G1 **PARTIAL**. Release composition is exact and the critical packages/modules named above are inventoried; there are still hundreds of executable-source files and registration sites not audited. The earlier 341 MB CLI PE REA overview timeout remains explicitly non-evidence; source is available and being sliced by crate and chain. No same-size recursive package scan is repeated.
