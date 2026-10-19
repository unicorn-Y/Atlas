# Codex Desktop completion-lane coverage

Status: **PARTIAL; all runtime and action-chain gates remain open.** This supplement records new corpus coverage and the continuing limits. It does not supersede older evidence or imply G0–G7 completion.

## Artifact identity

The installed Windows package reports version `26.1013.4894.0`; REA opened its `app/resources/app.asar` at `D:\WindowsApps\OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0\app\resources\app.asar`, SHA-256 `bbec1d64e135b718a154b31655bb8ad9a39472bac1b2cabba991a9d97a339dd8`. This matches the prior lane ASAR hash. The release MSIX download was not completed in this continuation, so its previously recorded size/hash is not re-attested here.

## Exhaustive lexical corpus pass

The local ASAR header traversal counted 21,073 file leaves (593,720,176 declared bytes). It then read every ordinary `.js` file (`unpacked` entries excluded): 15,110 files and 414,632,995 bytes. This is complete literal-anchor coverage of those `.js` leaf files for the selected terms below; it is not AST or control-flow coverage.

| Literal anchor | Files containing literal (count capped at 18 for candidate path collection) |
|---|---:|
| `electronBridge` | 16 |
| `sendMessageFromView` | 9 |
| `thread/start` | 8 |
| `thread/resume` | 4 |
| `thread/queue/` | 7 |
| `turn/start` | 10 |
| `turn/steer` | 4 |
| `mcpAppUi` | 2 |
| `computerUse` | at least 18 |

Useful candidate paths confirmed in the scan: `.vite/build/main-C4DYk222.js`, `.vite/build/preload.js`, `.vite/build/application-network-startup-DB1VeU3v.js`, `webview/assets/app-initial-5851df3f6cb1.js`, `webview/assets/app-primary-fe8a450b3b04.js`, `webview/assets/app-shared-bbfeca5e5737.js`, and `webview/assets/tasks-e5a6331c5cca.js`.

The visible `app-initial` mutation classifier names `thread/start`, `thread/startAeon`, `thread/fork`, `thread/inject_items`, `thread/queue/add`, `turn/addUserMessage`, `turn/start`, and `turn/steer`. Main-process code includes `thread/start` and queue-list/resume paths. Preload exposes an `electronBridge` object and implements `sendMessageFromView` with `ipcRenderer.invoke`. The actual UI handler that reaches a particular JSON-RPC request has not yet been followed across modules; approval, MCP widget and computer-use actions also remain unclosed end-to-end.

REA module-sliced analysis attempt details: a 7-file subset (27,196,163 text bytes; 6,334,393 AST nodes; 1 parse failure) exceeded the parent evidence/worker budget for app-initial, app-shared and main bundle semantic analysis, leaving 25,799 semantic unknowns. Running main alone parsed its 4,049,746 bytes / 1,024,577 nodes without syntax errors but still exhausted the semantic worker heap. Running preload alone parsed cleanly (6,909 bytes / 1,815 nodes), retaining 31 call-flow, 79 closure, 827 data-flow, 6 event, 113 object-flow and 3 promise-ownership relations; 385 unknowns remain. app-primary failed parsing (2,435,976 bytes, 0 AST nodes). This is a more specific failure map than the former whole-ASAR timeout, not a complete semantic pass. Evidence IDs: 7-file analysis `ev_00e2667d0a40a8b5643303444d49b94f3502f2aef966c64d408f4b4f1ad01d1c`; main-only `ev_f24090b39747e4368328833f268c4f15e3a39edb64220823819ab8bfbd5f07b3`; preload-only `ev_185166f15d0b940aec301dc7dd3153550ecf0547058e8432317f5c8e10a5ee06`.

## Runtime attempts and limits

- The installed build was already running in the user's session. Process names included ChatGPT.exe, codex.exe, codex-code-mode-host, codex-computer-use-swift and codex-windows-sandbox-service. The observation did not recover parent-child links, process arguments in a retained evidence record, IPC or task/session persistence behavior.
- No CDP listening port was found for ChatGPT. A REA-owned isolated launch-and-wait scenario failed with `Transport closed`; no user UI was clicked, and the existing session was left untouched.
- A broad REA analysis against the whole ASAR stalled and was cancelled. Future semantic work must be split by exact files/modules rather than repeated as one aggregate analysis.
- The release asset download was interrupted at 35,675,540 bytes; no local full-package size or SHA-256 was generated in this continuation.

## Remaining coverage required

1. Chunk by chunk AST/semantic analysis of the UI/action registration modules and direct trace from one real UI action through `electronBridge`, main handler and JSON-RPC method.
2. Separate proof for subagent lifecycle, task/session persistence, restart recovery and failure handling; package presence and protocol strings do not prove activation.
3. Safe isolated UI capture or other controlled replay that produces a real UI action observation without touching the user's running session.
4. Completed acquisition and SHA/size verification of the exact release MSIX in this continuation, or explicit gate disposition based on the previously recorded extraction evidence.
5. Refresh the Atlas comparison against `origin/main@aa6196f550098cc46081dc6db2c376cb87ddffa5`; the fetched main tip still equals that SHA.

REA-sliced JS semantic completion is still locally analyzable work. G7 therefore remains OPEN.

The exact `CODEX-REVERSE-COMPLETION-GATES.md` taskbook was not present in this lane checkout. The parent coordinator reported it on `origin` dispatch; no unobserved gate language is quoted here.
