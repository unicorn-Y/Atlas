# DSH Core coverage ledger

**WORK IN PROGRESS.** Counts below are measurable coverage boundaries, not a claim that every code path has been semantically understood. The exact G0–G7 taskbook was read from origin/research/agent-reverse-dispatch-20261019 because that file is not in this lane checkout.

## G0 — PASS for artifact identity

SHA-256, byte size, URLs and package identity are in extracted/manifest-verified.json. Source commit 687f282e8625c6b8d11ff58211a90524be2e4317 was checked out in a separate system temporary directory and rev-parse matched. extracted/version-diff.md separates versions and marks file/build correspondence unknown where no proof exists.

| Object | Inventory | Exact identity | Inspection |
|---|---|---|---|
| npm CLI | 20 rows in cli-tree.txt; executable bundles include lib/bin.js, plugin and profile bootstrap | @deepseek-ai/dsh 0.2.0-rc.2; 24,265 bytes; bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859 | Launcher code inspected and --version/--help executed. Manifest has 82 dependencies; 9 key runtime packages have registry integrity + entry SHA records and were statically examined. |
| Web npm | 91 indexed rows, 86 package assets; dist HTML, 25 JS chunks, 2 CSS; no maps | @deepseek-ai/dsh-web-frontend 0.0.1-rc.5; 1,428,754 bytes; ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516 | All paths indexed/hash-listed; bounded JS symbol contexts retained. Main bundle analyzer exceeded heap; no old-source mapping is established. |
| Upstream source | 9,485 rows in source-tree.txt; upstream Git tree reports 18,758 paths (tree records included, truncated=false) | Root 0.2.1-rc.2; commit 687f282e8625c6b8d11ff58211a90524be2e4317; ZIP 44,386,184 bytes; dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f | Fixed snapshot present in an isolated temporary checkout. Targeted source paths read; not every file. |

CLI, Web and source versions are 0.2.0-rc.2, 0.0.1-rc.5 and 0.2.1-rc.2 respectively. Package name and API role similarity are correlation only, not proof that a bundle was built from the inspected source.

## G1 — PARTIAL executable coverage

| Surface | Coverage | Unresolved |
|---|---|---|
| Fixed repository | git ls-files: 16,297 paths; 6,089 code paths with TS/TSX/JS/JSX/MJS/CJS/HTML extensions | Not every code file received AST or semantic review; executable byte sum not yet archived. |
| Existing source registration scan | command-endpoints.txt: 1,039 path/line/symbol rows for command, Remote, tool, event and slot patterns | Search patterns do not prove all aliases, generated registrations, menus, routes or feature flags are captured. |
| Client packages | 66 direct packages; 1,816 tracked code paths under packages/client | Main Web mount, conversation composer/queue, child navigation/chat are traced; all slots, menu actions, lazy components and commands remain unenumerated. |
| API and host transport | 217 tracked code paths under packages/api | Session prompt/updateQueue/child route/follow/control and remote mux are mapped; full Remote registry and activation gates remain open. |
| CLI | 101 tracked code paths under apps/cli; exact shipped CLI has 20 indexed rows | Launcher and source layering inspected; published profile composition/default mount and actual boot remain unobserved. |
| Web JS | 25 published chunks scanned for bounded strings/contexts | Need split AST/de-minify pass over each chunk and route/action extraction. Literal search cannot prove feature presence or absence. |

The initial whole-Web analyzer heap failure was replaced by per-asset inventory and bounded chunk symbol scanning. It remains a partial analysis, not a blocked target. Images, fonts and locales are inventoried/classified rather than semantically interpreted.

See SURFACE-MAP.tsv and END-TO-END-TRACES.md for call paths and their observation level.
