# Runtime observations

**R=host lifecycle only; GUI and Agent R=0.** Both supplied assets are source archives, not compiled desktop installers. In disposable scratch outside Atlas checkouts, A Next `npm run build` passed. `npm run verify:host:electron` failed before window creation: Electron fetch returned `TypeError: fetch failed`, followed by “Electron failed to install correctly”. No Electron window was created.

A separate `npm run verify:host` did spawn the Node host against a synthetic temporary profile, observed `process.ready`, and observed graceful `shutdown.complete`. The verifier then failed its assertion at `scripts/verify-host.mjs:118`: expected `dsh-community-market` bundle record was `true`, actual was `false`. This supports only host boot/readiness/shutdown, not the verifier's full pass, GUI behavior, Agent turns, model/tool use, subagents, inbox actions, or restart recovery.

The installed `DeepSeek Harness.exe` is the official DSH product, not A or B; its existing sessions and profile were not touched. No community GUI click, message submission, tool, subagent, interruption, or restoration was observed. B was not built or run.

Static package/source observations remain in `ASSET-VERIFICATION.md`, `A-runtime-symbol-index.md`, and lane `IMPLEMENTATION-TRACE.md`. Checksums and source paths are not runtime proof.