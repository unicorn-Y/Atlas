# Codex CLI package extraction status

- Captured: 2026-10-19, Asia/Hong_Kong; Windows 11 Pro 10.0.26200 x64.
- Source archive cache: `D:\agent-client-staging\release-assets`. No repeat download was needed; the exact three bytes matched the manifest size and SHA-256 (see `ARCHIVE-HASHES.json`).
- Commands run: `Get-FileHash -Algorithm SHA256`; `Expand-Archive`; `codex-x86_64-pc-windows-msvc.exe --version`; `codex-x86_64-pc-windows-msvc.exe --help`; `codex-code-mode-host-x86_64-pc-windows-msvc.exe --help`; `Get-AuthenticodeSignature`; bounded read-only PE header/import/string parser.
- All three archives opened: CLI contains 47 regular files; host archive contains one EXE; source snapshot contains 9,176 regular files under `codex-rust-v0.163.0/`.
- Observed CLI version: 0.163.0 (exit 0, 150 ms). CLI and Host help both returned exit 0 (99 ms and 88 ms); stdout and empty stderr are committed in their respective files.
- CLI, Code Mode Host (both copies), command runner, Windows sandbox setup, and voice host signatures reported `Valid`, signer `OpenAI OpCo, LLC`. PE version resources were absent. `rg.exe` was not included in the OpenAI signer statement.
- `dumpbin`, `llvm-readobj`, `strings64.exe` were not available. `PE-IMPORTS.txt` records import descriptors/symbols recovered by a bounded PE32+ parser and states that import presence alone does not show runtime use. `SYMBOL-STRINGS.txt` records a small set of exact file-offset strings; these are not function addresses.
- The CLI ZIP contains the same Code Mode Host bytes as the separately published Host ZIP (SHA-256 `07f3869f...b9988`).
- The bundled voice manifest declares app version `0.163.0`, x64 targets, and build commit `83086188ae0614bd882818ff1aa23f3194962012`, matching the pinned source ZIP/tag. This is build attribution, not a reproducible build comparison.
- No authenticated prompt/task was executed. No account data, config, token, rollout, or private session material was read or committed.

## Remaining boundary

The package and matching source snapshot are verified and unpacked. Dynamic turn execution, event ordering in an actual session, gRPC/stdio frames, audio capture/playback, cancellation, daemon recovery and server-side services remain unobserved. No PE disassembly or function-level binary/source equivalence claim is made.

- REA `binary_overview` against the 341 MB CLI PE did not complete within the bounded analysis window and was terminated. No result from that operation is used. PE header/import/string observations come from the separate bounded read-only parser documented in `PE-IMPORTS.txt` and `SYMBOL-STRINGS.txt`; no disassembly/function mapping is claimed.

## Later isolated protocol observation (2026-10-19)

The shipped CLI was run with a fresh `CODEX_HOME`, synthetic workspace, and key/base-URL environment variables removed. App-server JSON-RPC initialize, thread/start and turn/start were accepted, and user-message start/completion events plus a rollout file were observed. No assistant/model/tool completion event was observed before closing the bounded process. The shipped Code Mode Host was separately sent legacy framed stdio hello, session/open, session/execute, and one synthetic tool delegate request/response; a V8 cell returned the synthetic callback result and exited cleanly. These are limited runtime observations; see sibling `END-TO-END-TRACES.md`. No account/session data was read or used. Authenticated agent execution, Core's gRPC+stdio transaction, cancellation, child agent, and restart recovery remain unobserved.
