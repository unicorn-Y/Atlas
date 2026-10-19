# Claude Code evidence bundle

Bounded report bundle for Claude Code CLI 2.1.302. Captured 2026-10-19 HKT. Raw `.tgz` archives, extracted 290 MB executable, full string dumps and CLI output files remain local at `D:\agent-client-staging\release-assets\` or task-local scratch and are not committed.

| File | Contents | Bytes |
|---|---|---:|
| `00-provenance.md` | branch/worktree/baseline and scope | see git |
| `01-archive-manifest.json` | both verified archive hashes/sizes and all 11 member hashes/types/executable flags | see git |
| `02-core-file-tree.txt` | actual seven-member core tree | see git |
| `03-native-file-tree.txt` | actual four-member win32-x64 tree | see git |
| `04-package-metadata.md` | manifest, wrapper installation/run path, SDK surface | see git |
| `05-native-header.md` | PE sections, imports and resources | see git |
| `06-native-string-index.jsonl` | 19 bounded offset hits and SHA binding | see git |
| `07-native-registrations.md` | shipped CLI registrations and behavior descriptions | see git |
| `08-native-call-anchors.md` | module/function-like string anchors and executable boundary | see git |
| `09-native-state-schema.md` | observed native/SDK state fields and explicit unknowns | see git |
| `10-unknowns.md` | unresolved runtime/decompiler coverage and next material | see git |
| `11-cli-probes.md` | isolated command lines, exit codes and output snippets | see git |
| `12-native-supervisor-source.md` | bounded readable JS embedded in exact PE, with offsets for supervisor/respawn/retirement/adoption methods | see git |
| `13-native-message-task-schemas.md` | exact-PE source for CLI message, stream, result, tool-progress and task event schemas, plus Atlas adapter comparison | see git |
| `core-readable/excerpts.md` | short path-and-line excerpts from wrapper, install script, shell stub and package metadata | see git |

Verified input archives: core `29,082` bytes SHA256 `ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8`; win32-x64 `132,494,857` bytes SHA256 `cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d`. Executable SHA256 is separately pinned in `03-native-file-tree.txt`.

Coverage is partial: native package and unauthenticated CLI were analyzed, but authenticated agent execution, daemon persistence, exact model/event protocol, and cloud-service implementation are not observed.

`12-native-supervisor-source.md` upgrades background supervisor findings from symbol-cluster-only to visible application-source logic embedded in the exact Bun PE. This remains static shipped-code evidence, not runtime observation or a recovered complete persistence schema.

`13-native-message-task-schemas.md` upgrades event findings from field-name clusters to embedded wire-schema definitions. It records protocol fields and semantics without claiming a live event trace or a stable public contract.

