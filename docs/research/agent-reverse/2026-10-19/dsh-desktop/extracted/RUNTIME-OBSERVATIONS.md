# Runtime observations

**NOT-RUN. R=0.** Both supplied release assets are source archives (A: 4,559 extracted files; B: 133), not compiled Windows desktop installers. This lane did not install dependencies, build either product, configure an external DSH profile/model, launch Electron/Tauri, or capture process/window/HTTP/WebSocket behavior. No claim is made about actual runtime plugin activation, UI controls, remote model calls, event ordering, or restart restoration.

Static package/source observations are recorded separately in `ASSET-VERIFICATION.md`, `A-runtime-symbol-index.md`, and lane `IMPLEMENTATION-TRACE.md`. Do not treat checksums, source-level code paths, README claims, or bundled tarball presence as live behavior evidence.
