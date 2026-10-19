# DSH Desktop G0–G7 coverage ledger (checkpoint)

**Status: WORK IN PROGRESS.** This continues the pinned A/B investigation. Evidence IDs are retained; no Atlas product files changed.

## G0 — artifact identity: PARTIAL

The original ZIPs were rehashed read-only in the external scratch worktree during this continuation:

| Asset | Bytes | Recomputed SHA-256 | Pinned source |
|---|---:|---|---|
| `dsh-desktop-anywhere-labs-03d18d13bb.zip` | 222,488,979 | `03d18d13bb4a5bbfe79e3cd340d465d415a24f69968828c045efb5ea234b0a31` | `anywhere-labs/dsh-desktop` `6a63b9730b82cf4e858b9a11ac9783da9a5a0c3a`; Next `2.0.19-next` |
| `dsh-desktop-dongdong-agent-1dd3b7ded3.zip` | 5,400,611 | `1dd3b7ded3646abf5245f46b76e214d33908ac563d1c796d1a9baf592a9f5dc6` | `dongdong-agent/DSH-Desktop` `0aea85f01acd4583bb3fcebaa8c51586b08833a1`; `0.1.15` |

They are source archives, not compiled desktop payloads. A contains the Next host source and 343 versioned DSH runtime tarballs whose hashes matched A's embedded manifest in the earlier extraction pass; B contains its Tauri/React wrapper source. Neither ZIP establishes the compiled executable that would run these sources. The locally installed `DeepSeek Harness.exe` is the official product, not either community wrapper, and is not A/B execution evidence. See `extracted/ASSET-VERIFICATION.md` and package tree indexes.

## G1 — executable source coverage: PARTIAL

Counts come from complete extracted ZIP member inventories (`*-package-tree.tsv`); source and runtime tarballs are distinct coverage units.

| Scope | Files | JS/TS/HTML family files | Bytes in family | Full executable-symbol pass |
|---|---:|---:|---:|---|
| A source ZIP | 4,559 | 1,121 | 9,729,392 | No: 230 `A-code-sha256.tsv` entries and focused symbol indexes; 343 vendor tarballs individually manifest-matched; 15 selected runtime packages extracted to `selected-runtime` (454 files / 5,572,860 bytes). Remaining packages are not fully enumerated for registrations/actions. |
| B source ZIP | 133 | 40 | 380,970 | No: 47 `B-code-sha256.tsv` entries (includes non-code); focused `B-symbol-index.md`; no dynamic UI action traversal. |

Path grouping:

- **A community host**: `dsh-desktop-next/src/**`, `dsh-desktop-next/scripts/**`, root scripts, Cordis patches/profile config. Host lifecycle, controller, profile, desktop IPC, recovery and HTTP/WS policy were statically traced in `IMPLEMENTATION-TRACE.md`.
- **A official runtime**: `vendor/dsh-runtime/0.2.1-rc.2/*.tgz`; 343 archive members in A. Fifteen selected packages were unpacked for focused traces (loop, persistence, session controller, chat, subagent, trajectory, host runner, jobs). This is not semantic coverage of all 343 packages.
- **B wrapper**: `src/**`, `src-tauri/src/**`, `src-tauri/capabilities/**`, `tools/**` and configs; 40 JS/TS/HTML-family files inventoried.
- Images, fonts, locales, docs, licenses, lockfiles and repeated assets are inventoried, not semantically decoded.

## Focused search and parser accounting

No whole-archive REA analysis was repeated. The full pinned A source archive `dsh-desktop-next/src` has 106 files. A Next pins `@deepseek-ai/dsh-web-frontend@0.2.1-rc.2` (`package.json:209`), embedded at `vendor/dsh-runtime/0.2.1-rc.2/deepseek-ai-dsh-web-frontend-0.2.1-rc.2.tgz` (SHA-256 `c797fa5fce3375c78b2afe7458864bb5b23814eef80013e510ad9a1f8bfbfbda`). Its 61 JS assets (4,798,411 bytes) plus all 106 app source files were searched for `session/updateQueue`, `next-step`, `next-turn`, `QueueAction`, and `steer`: no UI mutation caller. `updateQueue` occurs 55 times only in `index-CN7NIWNw.js` (921,071 bytes; SHA-256 `4bc914bfbb6addd63953a29f63835eb7127defd2a973149d64cdab489f1a9a5`) as React Fiber internal queue machinery. The API method exists in the server controller and SessionReference package. Thus queue edit/remove/steer controls and caller are absent in this exact pinned A frontend build; other versions, external installs and plugins remain outside this claim.

No parser timeout was encountered in this focused search. Full route/event/IPC registration coverage is incomplete; no unsupported “all code parsed” claim is made. Continuation IDs: `DSH_DESKTOP-038` exact A frontend/UI boundary; `DSH_DESKTOP-039` A build/host runtime evidence; `DSH_DESKTOP-040` separate B external UI boundary.

## G2 — UI ↔ IPC/RPC ↔ runtime/state: PARTIAL

`SURFACE-MAP.tsv` enumerates A desktop controls, A's official DSH session/web boundary, and B management/runtime handoff. `END-TO-END-TRACES.md` closes the A Host lifecycle and official inbox API mutation to session events, and the B readiness/navigation chain. The exact A-pinned frontend has no edit/remove/steer queue controls or `session/updateQueue` caller. B navigates to a separately served official Web UI whose build remains **U**.

Official child-session/sidebar UI is attributed to the pinned official `dsh-client-ui-subagent` / `ui-trajectory` source, not invented by A or B. B's top-level navigation replaces the React management page; native Rust tray handlers survive, but React title/status controls are no longer mounted.

## G3 — Agent semantics/recovery: PARTIAL

Static evidence covers the official durable inbox projection, next-turn/next-step split, session queue mutation validation/cold `resolveAgent`, JSONL persistence package identity and official child Session references/sidebar projection. A starts official `runProfile`; B starts or reuses the external official web engine. Neither wrapper owns the Agent loop. Controller cold reconstruction is not proof that an interrupted model/tool step resumes; wrapper restart/engine keep-alive is not proof of turn continuation.

Runtime model routing, actual child lifecycle, retry/interrupt and post-kill recovery, Host/UI event ordering, and each app's loaded Profile/bundle remain U.

## G4 — safe execution: PARTIAL; R=host lifecycle only

Observed prerequisites: Node `v24.18.1`, npm `12.0.2`; assets are source archives, not compiled installers. In disposable scratch, A Next `npm run build` passed. `npm run verify:host:electron` failed before window launch because Electron fetch returned `TypeError: fetch failed`, then “Electron failed to install correctly”. `npm run verify:host` spawned a synthetic-profile Node host, observed `process.ready` and graceful `shutdown.complete`, then failed at `scripts/verify-host.mjs:118` because expected `dsh-community-market` bundle record was false. This proves host lifecycle only, not GUI or Agent behavior. The installed `DeepSeek Harness.exe` is a different official product; its sessions/profile were untouched.

Safe attempts: recomputed both ZIP hashes; built A Next in scratch; attempted Electron verification (failed binary fetch); ran synthetic Node-host verifier; checked process identity; searched exact pinned frontend and A source. G4 remains open for GUI, synthetic Agent/tool, child/queue, B runtime, and cold-reopen evidence. No credentials, account data, or existing sessions were used.

This is an environment boundary, not a claim that source cannot be built. Runtime result: `R=host boot/ready/shutdown`; GUI and Agent `R=0`.

## G5 — Atlas comparison: PASS for static source trace only

`origin/main` was fetched and remains `aa6196f550098cc46081dc6db2c376cb87ddffa5`. Existing delegation, task steering, replay and renderer queue findings use that exact commit. See `ATLAS-IMPLEMENTATION-BACKLOG.md`; no product code changed. Runtime equivalence remains U.

## G6/G7 — checkpoint and stop rule

Five gate artifacts are present and the existing lane documents are updated in this checkpoint. Cross-review remains pending. Overall status is **WORK IN PROGRESS**: full executable action coverage, B runtime, GUI, Agent/tool, subagent, and failure/reopen tests remain open. Queue mutation UI absence is established for exact pinned A frontend. This is an evidence checkpoint, not final acceptance.
