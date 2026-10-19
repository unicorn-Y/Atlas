# End-to-end traces — source-level checkpoint

All traces marked **S** are static source/package evidence. No static source is treated as observed execution. Product owners remain separated: A is Electron/Node host; B is Tauri manager; Agent loop, durable session state, chat modules, child-session UI and trajectory are official DSH packages.

## Trace A1 — community desktop boot to official runtime

1. Electron main starts `NextDesktopRuntime.start()` in `dsh-desktop-next/src/desktop-runtime.ts:102`.
2. `DesktopBackendController.start()` prepares the selected profile and serializes host creation (`src/backend-controller.ts:33-172`). Startup errors trigger cleanup and failed readiness.
3. `HostProcess` spawns a Node child with IPC and stdout/stderr capture (`src/host-process.ts:228-319`). Host messages include `ready`, `fatal`, permission, notification, desktop action, injection, browser access, and update-tasks (`:251-319`). Main-to-host requests include shutdown and configuration/browser permission messages (`src/host/index.ts:96-125`).
4. Host loads the Next profile/patches (`src/host/index.ts:28-80`, `src/profiles.ts:290`) and invokes official `@deepseek-ai/dsh/profile-boot` `runProfile`. The Agent loop is official, not authored by the desktop wrapper.
5. Host publishes a local webserver URL; renderer loads/injects official Cordis client slots from `src/client/index.ts:31-100`. Desktop main↔renderer channels (`src/ipc.ts:1-17`) differ from official DSH WebSocket/session events.

**Failure/recovery edge:** startup failure, child close, invalid IPC, and nonzero exit flow through BackendController/HostProcess errors. Shutdown requests an ACK then escalates after timeout. Safe Mode uses a minimal profile and temporary home (`desktop-runtime.ts:85-145`); configuration recovery snapshots selected files. This establishes desktop host/config behavior in source, not active Agent turn recovery.

## Trace A2 — official inbox mutation; missing UI edge is explicit

1. A's source ZIP embeds `@deepseek-ai/dsh-agent-loop@0.2.1-rc.2`, `dsh-api-session-controller@0.2.1-rc.2`, `dsh-session-persistence-jsonl@0.2.1-rc.2`, and `dsh-client-ui-chat@0.2.1-rc.2`; ZIP/tarball hashes are in `extracted/ASSET-VERIFICATION.md` and `extracted/A-runtime-symbol-index.md`.
2. `ReactLoopInbox` reads the session `inbox` projection; `mutate()` appends `agent/inbox/spliced`, rejects IDs duplicated across `next-turn`/`next-step`, and dispatches inserted/discarded events (`dsh-agent-loop/lib/index.js:70-204`). `claim()` removes all `next-step` and at most one `next-turn`; followup maps to next-turn and steer to next-step (`:806-813`).
3. JSONL persistence stores session events; queue state is a replayable projection, not renderer-only state.
4. Controller `updateQueue()` resolves a cold Agent if absent, verifies the item is still pending, permits constrained text edit/remove, and allows steer only for a running turn's `next-turn` item (`dsh-api-session-controller/lib/index.js:1004-1054`). It is remotely published (`:2689`); generated schema/transport exposes `session/updateQueue` (`lib/typert.remote-client.js:1912-1938`); SessionReference wrapper calls it (`lib/client.js:2415-2418`).
5. `dsh-client-ui-chat` reads `useProjection("inbox")` (`lib/client.js:2757`), merges next-step steering and pending local submissions (`:2815-2847`), then deduplicates local optimistic echo. Its README says queued submissions remain outside Chat.

**Pinned-build result:** A Next `package.json:209` pins `@deepseek-ai/dsh-web-frontend@0.2.1-rc.2`; embedded at `vendor/dsh-runtime/0.2.1-rc.2/deepseek-ai-dsh-web-frontend-0.2.1-rc.2.tgz` (SHA-256 `c797fa5fce3375c78b2afe7458864bb5b23814eef80013e510ad9a1f8bfbfbda`). Its 61 JS assets were searched: `session/updateQueue`, `next-step`, `next-turn`, `QueueAction`, and `steer` have zero occurrences. `updateQueue` appears 55 times only in `index-CN7NIWNw.js` (921,071 bytes; SHA-256 `4bc914bfbb6addd63953a29f63835eb7127defd2a973149d64cdab489f1a9a5`) as React Fiber internal update queue machinery. The full 106-file A app `src` search likewise found no queue mutation caller. Therefore edit/remove/steer controls and RPC caller are absent in this exact pinned A frontend build; other versions/plugins remain outside the claim.

## Trace B1 — management shell to external DSH engine

1. React `App.tsx` reads boot/restart query, starts or reuses engine through `dshEngine.ts`, and waits for a business session-list probe (`src/App.tsx:140-320`; `src/lib/dshEngine.ts`; `src-tauri/src/lib.rs:229-293`). Health/ownership/port live in `engineStore.ts`.
2. React invokes `open_engine_in_main`; Rust navigates the Webview to `127.0.0.1:<port>`, waits for final origin, then evaluates auth-cookie injection (`src-tauri/src/lib.rs:158-209`; `src/lib/engineAuth.ts`). This replaces the top-level management document; React title/status controls are no longer mounted.
3. Native Rust tray handlers persist across navigation (`lib.rs:295-465`). Restart/complete-exit may terminate a process occupying the selected port; code does not prove ownership in a live user environment or that an active job resumes.
4. After navigation, official external engine/Web UI provides Agent, child, queue and persistence behavior. B has no alternate Agent loop.

**Unknown runtime path:** actual port/version, profile plugin load, visible controls, cookie readiness, and close/restart behavior on a synthetic in-flight task. B source archive is not a runnable app binary.

## Trace B2 — official subagent address/UI ownership

Pinned official `ui-subagent` registers lineage/actions in the conversation header, opens child by full `SessionAddress`, and can open a retained `SessionReference` in the right sidebar. `SubagentHeaderLineage` projects status/token/timing and lazily expands descendants. `ui-trajectory` reads durable Session events. This is an official implementation reference, not A/B community invention. Activation in A's Next profile and behavior in B's external engine remain U until observed in each exact served build.

## Runtime evidence — A synthetic host only

In disposable scratch, A Next `npm run build` succeeded. `npm run verify:host:electron` failed before window creation while fetching Electron (`TypeError: fetch failed`). `npm run verify:host` spawned Node host against a synthetic temporary profile, observed `process.ready`, then `shutdown.complete`; it failed at `scripts/verify-host.mjs:118` because expected `dsh-community-market` bundle record was false. This is `R=host boot/ready/shutdown`, not GUI or Agent execution. No model/tool call, UI interaction, or session recovery was run.
