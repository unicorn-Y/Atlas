# Published DSH release artifacts vs fixed source snapshot

## Identity and integrity

All three files were downloaded from Atlas release `agent-client-packages-20261019`, checked against the full manifest SHA-256 values, and unpacked. `manifest-verified.json` records URLs, actual byte counts, expected and actual SHA-256, PowerShell version, and capture time. The preserved inventories are `cli-tree.txt`, `web-tree.txt`, and `source-tree.txt`.

| Artifact | Actual package/root version | SHA-256 | License metadata |
|---|---|---|---|
| `@deepseek-ai/dsh` CLI npm | `0.2.0-rc.2` | `bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859` | MIT |
| source ZIP | commit `687f282e8625c6b8d11ff58211a90524be2e4317`, root / `apps/cli` / `apps/web` `0.2.1-rc.2` | `dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f` | root MIT |
| `@deepseek-ai/dsh-web-frontend` npm | `0.0.1-rc.5` | `ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516` | BSD-3-Clause |

Sizes verified: CLI `24,265` bytes; source ZIP `44,386,184` bytes; Web `1,428,754` bytes. The ZIP expanded to 9,485 files in the captured tree inventory. No hash mismatch occurred.

## CLI 0.2.0-rc.2 vs source apps/cli 0.2.1-rc.2

The published tarball is a 20-file launcher package, not the full runtime source. `lib/bin.js` contains the launcher parser and mode dispatch: profile launch; `plugin` forwarding to pnpm; config dump; default config dump; and schema dump. It preserves the app's remaining arguments, rejects the Electron-owned `desktop` profile, loads layered environment values, and saves startup diagnostics under `$DSH_HOME/logs` after a `StartupError`. The actual Agent/runtime is loaded through external npm dependencies; those package files and profile templates are not embedded in this CLI tarball.

The release package declares 82 direct dependencies; source `apps/cli/package.json` declares 86 workspace dependencies. The exact only-release / only-source dependency names and published-to-source package pairs are retained in `source-versions.json`. Of 82 published CLI dependencies, 73 DSH package names exist in the snapshot but each source package version is `0.2.1-rc.2` while the published CLI pins `0.2.0-rc.2`; the other nine dependencies have no matching package metadata in the selected DSH/Cordis workspace scan. The CLI's generated `profile-boot.js` exports match named launcher responsibilities in the source tree, but neither package-version equality nor source maps establish byte-for-byte/build-level equivalence. Follow-up: the exact verified CLI tarball was installed as npm root; selected old runtime packages were retrieved with registry SHA-512 integrity values and recorded with installed entry SHA-256 hashes in `published-runtime-packages.json`. This supports static findings against actual `0.2.0-rc.2` compiled loop/session/API/subagent/Web glue. Full 82-package review, profile boot, and dynamic execution remain unverified.

## Web 0.0.1-rc.5 vs source apps/web 0.2.1-rc.2

The Web tarball is a static Vite output: `dist/index.html` mounts `#root`, loads `index-DYtepzMn.js`, preloads `vendor-Cjbwl5VI.js`, and loads two CSS files. The complete `dist/assets` inventory has 86 assets (25 JS) and zero `.map` files. Every shipped JS chunk retains a `sourceMappingURL=<chunk>.js.map` marker, but the referenced map files are not in the package. `web-assets-map.json` records the source map URL and whether that file exists, in addition to path, byte size and SHA-256. `web-chunk-symbols.jsonl` records byte offsets and bounded printable context for every match of the requested ten terms across all 25 JS files.

The shipped Web package metadata says `0.0.1-rc.5` and BSD-3-Clause; source `apps/web/package.json` says `0.2.1-rc.2` and MIT. Release dependency `@deepseek-ai/dsh-client-web@^0.0.1-rc.5` maps by name to source package `0.2.1-rc.2`, not the published range; React/React DOM resolve outside the scanned DSH workspace. The newer workspace app places its client shell and UI packages in workspace development dependencies and builds a different tree. The release bundle's main entry contains literal `session` and `prompt` matches; the searched main entry contains no literal `remote.mux`, `subagent`, `interrupt`, `assistant`, `job`, `usage`, `team`, or `trajectory`. Other chunks contain generic parser/editor occurrences of words such as `interrupt`, `job`, and `session`; those are not feature proof. Since referenced maps are missing and versions diverge, current-source subagent, trajectory, job, or Team features cannot be attributed to this old release from string search alone, nor can absence of a string prove the feature is absent.

## What is and is not paired

- **Verified:** asset identity, package metadata, release file trees and hashes, CLI launcher code in the actual npm package, and static contents of the actual Web dist.
- **Correlated only by names / API role:** release CLI entry/profile-boot module names with source `apps/cli/src/bin.ts` and `profile-boot.ts`; this is not exact-source equivalence.
- **Not paired:** any release Web chunk to a specific TypeScript source file; no source map is shipped, and `0.0.1-rc.5` is not the source snapshot's `0.2.1-rc.2`.
- **Partially analyzed as the old runtime:** selected actual transitive CLI npm packages at `0.2.0-rc.2` were statically reviewed; installed profile bundle patches / default mounts were not. The standalone shipped Web asset and runtime's `dsh-web-frontend@0.2.0-rc.2` are not proven to be the same build.
- **Dynamic status:** only the CLI launcher's `--version` and `--help` were run successfully. No profile, Agent, Web server, or browser UI was started. There is no R-level Agent/event/recovery/network observation.
