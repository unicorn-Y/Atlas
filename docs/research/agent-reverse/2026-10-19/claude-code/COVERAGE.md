# Claude Code 2.1.302 coverage ledger

**Status: PARTIAL / WORK IN PROGRESS.** Captured 2026-10-19 HKT. Baseline executable SHA-256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`; core and Windows archive identities remain those in `evidence/01-archive-manifest.json`. Atlas comparison baseline remains `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`.

## G0: artifact identity — PASS

The exact source archives are Claude Code 2.1.302 core (29,082 bytes, SHA-256 `ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8`) and win32-x64 (132,494,857 bytes, SHA-256 `cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d`). The shipped `package/claude.exe` is 290,211,488 bytes and hashes to `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`; REA reopened this exact local executable and observed PE AMD64. Entry files are the core npm wrapper/install surface and the native `claude.exe`; the archive/member list is complete in `evidence/01-archive-manifest.json`. No version mismatch is being used as primary implementation evidence. The bundled `B:/~BUN/root/chunk-*.js` build paths have no source maps in these packages.

## G1: executable-surface coverage — PARTIAL

| Surface | Inventory evidence | Parsed/covered | Not covered / reason |
|---|---|---|---|
| Core npm package | `evidence/01-archive-manifest.json`, 7 members | Wrapper, installer, package metadata and SDK declaration excerpt in `evidence/core-readable/excerpts.md` | Full 171,863-byte SDK declaration API inventory is not yet enumerated |
| win32-x64 npm package | same manifest, 4 members | `claude.exe` PE header/sections/imports/resources in `evidence/05-native-header.md`; exact source offsets in `evidence/12-14` | Native `.bun` module inventory and all embedded JS routes/commands are not yet enumerated |
| CLI commands/flags | `evidence/07-native-registrations.md`, `11-cli-probes.md` | Existing registration and help evidence retained; no help rerun | Registration-to-handler mapping is incomplete outside the examined teammate and worker paths |
| Embedded application JS | exact PE, `.bun` payload at file offset `0x071e2c00`, 170,783,232 raw bytes | Entire `.bun` range byte-scanned: 2,431 `// @bun @bytecode` markers / 2,431 version headers; 211,512 `B:/~BUN/root/chunk-*.js` references / 2,428 unique IDs enumerated in `evidence/17`; selected source regions traced in `12-16` | Byte-level inventory is complete for the named markers/import references, but semantic parsing is selective; marker-to-chunk identity differs by 3 and remains unexplained. All handlers for CLI commands, hooks/plugins/MCP, TUI rendering and model/tool loop remain unparsed |
| UI renderer / IPC / preload | no separate renderer/preload in either pinned npm archive | CLI init advertises tool, skill, plugin and capability sets in controlled process output summarized in `END-TO-END-TRACES.md` | This is a terminal CLI with no shipped graphical UI layer in the selected packages; native terminal interaction and key handling remain unobserved |

Complete archive member counts are 7 core + 4 platform members. These counts are package inventory only; they are **not** a count of executable modules inside the monolithic Bun executable. The pre-existing scan has a bounded 19-line ASCII feature index over the PE and explicitly does not cover all UTF-16LE strings (`evidence/06-native-string-index.jsonl`, `10-unknowns.md`). New byte-local extraction recovered actual embedded source bodies for the mailbox writer, reader, acknowledger and clearer, but no complete module accounting. We will not convert those samples into an executable-code coverage claim.

## Parse methods and failures

The prior full PE symbol/function inventory exceeded the REA 330-second limit (`evidence/10-unknowns.md`). A focused REA `search_strings("retryWake")` also remained pending beyond five minutes and returned no usable result; analysis continued by reading bounded byte spans from the already pinned local PE at known executable offsets. This produced exact minified function bodies with decimal file offsets around 248,019,409–248,027,467. These offsets bind to the SHA above. This is a bounded static fallback, not a complete parser and not native control-flow recovery.

To improve G1 without repeating the timed-out whole-PE decompilation, the exact `.bun` raw range was scanned locally for every `// @bun @bytecode` marker, version header and chunk import reference. `evidence/17-bun-chunk-import-inventory.txt` lists all 2,428 unique referenced chunk IDs. This establishes structural accounting over the full 170,783,232-byte payload, not semantic review of all 2,431 source-marked units.

## G4 execution boundary

A new synthetic repo containing only `README.txt` was created at `D:\agent-client-staging\claude-code-synthetic-20261019`. The exact executable started under isolated `CLAUDE_CONFIG_DIR` and emitted `system/init` (session `528d4e89-5112-46b9-abe0-986fee4b041d`, version 2.1.302, default permission mode, model field `deepseek-v4-flash`, `apiKeySource=ANTHROPIC_API_KEY`, tools including `Read`, `Task`, `Bash`, `SendMessage`, `TaskStop`, and other CLI tools). A synthetic `--print --output-format stream-json --verbose` request then received repeated HTTP 401 `authentication_failed` responses. Thus process initialization is R evidence; no model response, tool invocation, child spawn, task event, or result was observed. REA's PTY capture adapter separately returned `capability_unavailable` on Windows because it cannot verify descendant cleanup. No user transcript or config content was opened. The exact command and output boundary are recorded in `END-TO-END-TRACES.md`.

## Gate snapshot

See `FINISH-GATES.md`. Active gaps include full embedded-module/registration inventory, model/tool loop, parent/child event trace, actual mailbox read/ack/restart, and a real synthetic model turn. Status remains **WORK IN PROGRESS**.
