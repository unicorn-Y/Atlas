# Evidence checkpoint 1 — Claude Desktop 2.42304.0

Authority labels: **S** shipped-package static evidence; **R** controlled runtime; **D** official docs; **I** inference; **U** unresolved. This checkpoint is S-only unless explicitly stated. No user profile, login, credentials, or account data were accessed. No app or service was launched.

## Exact artifacts

- MSIX `claude-desktop-x64-2bf309665f.msix`: 297,191,037 bytes, SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee` — matches fixed release manifest.
- `app/resources/app.asar`: 49,338,428 bytes, SHA256 `8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db2`.
- `app/resources/cowork-svc.exe`: 13,761,360 bytes, SHA256 `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f`.
- MSIX tree: 4,443 extracted files. Identity: Claude, x64, version 2.42304.0.0, entry executable `app\\Claude.exe`, `Windows.FullTrustApplication`. See `identity.json`, `msix-tree.tsv`.
- ASAR path listing contains 548 lines. See `asar-tree.txt`.

## Package and renderer observations

`app.asar` analysis observed 437 parsed JS files (40,616,215 text bytes), 0 parse failures, 15 BrowserWindow constructions, 52 contextBridge exposures, and 1,535 IPC operations (1,301 renderer transmissions, 231 renderer listeners, 3 main handlers; dynamic channel construction dominates, so this is not a complete literal channel inventory). Three utility-process constructions were found; entrypoints were unresolved by static analysis. These are static analyzer counts, not runtime call counts.

The package metadata declares `index.pre.js` as main. Main bundle `.vite/build/index.chunk-lzaSYO3Q.js` (7,081,117 bytes; SHA256 `66a2071baf285aaa3d88aeace7344e7941c3df93c1ef3b21bc6cf64205c58d0d`) creates the main and auxiliary windows; its main-window configuration binds preload `.vite/build/mainView.js`. That preload bundle (171,276 bytes; SHA256 `9fb003faa3e791af2e42870b695c7b137d6ca37576df8714f18fcc55966d728d`) exposes generated APIs backed by IPC invoke/send wrappers. Observed families include MCP server config/probe, import history, scheduler status/settings and window controls. Exact examples and bounded source coordinates are in `ipc-map.tsv` and `trace-snippets/renderer-ipc.md`.

`coworkArtifact.js` (2,687 bytes, SHA256 `21f4dfed39f8290444e31a153fe8d68596b10d6d3b44af6e94b4d472c9c14e45`) exposes a `window.cowork` bridge for MCP tool call, ask Claude, scheduled task, host navigation and external URL operations. The main bundle registers `CoworkArtifactBridge`; the observed validation checks the sender frame origin against `cowork-artifact:`. This is a narrow artifact bridge, not evidence that all Cowork execution is local.

ASAR analyzer found 15 BrowserWindows across main/quick/about/design and other views; explicit preferences include context isolation true and Node integration false. Some preferences are dynamic. Renderer assets include main, quick, buddy, about, find-in-page and local-exec-consent views. Routes/actions are not yet exhaustively paired to callback and state persistence; see partial structured maps.

## Cowork Windows service observations

The PE is x86_64 and has a valid Authenticode signature from Anthropic PBC (DigiCert Trusted G4). Static analysis identifies Go, 9 PE segments, 12,769 procedures and 38,491 strings. Only `kernel32.dll` appears as a static imported DLL (46 imported functions); dynamic API loading means this does not bound runtime API use. Help text describes a Hyper-V VM management service and install/uninstall/start/stop/status operations. Strings include HCS/HCN compute-system and network APIs, Plan 9 shares, Hyper-V sockets and gvisor tap-vsock components. These strings and symbols alone do not establish reachable call flow.

Bounded scan of packaged `.vite/build/*.js` did not find a literal `cowork-svc` or `@ant/cowork-win32-service` reference or direct service process spawn. However, the main bundle does implement the Windows VM service client at `\\.\pipe\cowork-vm-service`, including configure/start/stop/process methods and event subscription; this closes the app-side named-pipe RPC path. The service installation/launch parent and full Go handler call graph remain U. In packaged main code, the pipe client requires native `connectNamedPipeSystemOwned` and refuses an insecure fallback if absent; plain `net.createConnection` is only allowed in a dev/unpackaged build. This is a source-level identity-verification requirement, not a runtime test of the native binding. The service evidence concerns the legacy local Hyper-V VM lane and does not establish that current `remote || cloudRun` execution uses that service.

## Integrity and extraction limitations

The ASAR integrity metadata declares SHA256 `e83669e99a699d6bea4de15a3914b3279c19449744dc3cf10c22734ae98935f5` for `app.asar.unpacked/node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node`; extracted bytes at that declared relative path hash to `576c180668dde332b051ce673fccadd82646faae4987c091502ba186dc20ea5b`. This is an observed declared/observed mismatch only; cause is unproven. A separate extraction attempt also encountered an escaped `%40ant` path mismatch for a native binding. No package bytes were altered to resolve either condition.

## Boundaries

- Static shipped-artifact authority only; no controlled runtime evidence (R=0).
- Cloud/server internals and account rollout configuration remain U.
- The exact consumer package was not available; enterprise/consumer equivalence remains U.
- App-level service lifecycle, complete dynamic IPC channel names, exhaustive route-action-state joins, and durable state/recovery behavior remain incomplete.
- Atlas comparison baseline: `origin/main` `aa6196f550098cc46081dc6db2c376cb87ddffa5`. Existing Atlas source-backed conclusions remain limited to cited main source paths; this checkpoint does not modify Atlas code.


## Additional module evidence (second static pass)

`module-traces.md` adds exact file hashes and character offsets for extension signature/capability checks, MCPB same-fd archive identity recheck, built-in Node self-spawn refusal, PTY scrollback redaction plumbing, file-index worker initialization, remote/cloud local-command bypass and migration timestamps, and Computer Use preview bridge. The Cowork artifact scheduled-task path is now traced from renderer method through guarded main IPC to schedule `runNow`; the MCP tool bridge is traced through per-tool managed policy/destructive approval. The artifact call chain is S/static and does not establish cloud server internals or generic task ownership.

**Atlas main source SHA at comparison:** `aa6196f550098cc46081dc6db2c376cb87ddffa5`. Atlas comparison findings are narrow and cite the matching files/lines in `ATLAS-GAP.md`.


The second static pass found a concrete app→VM service protocol. See `module-traces.md` for exact channels, framing, method/event names and offsets.

Packaged pipe-server identity requirement and the explicit development-only fallback are recorded in `module-traces.md`.
