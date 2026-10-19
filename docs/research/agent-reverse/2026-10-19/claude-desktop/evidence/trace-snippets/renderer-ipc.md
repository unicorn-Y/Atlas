# Renderer/IPC trace snippets

Short location records only; giant bundled source is not redistributed. Offsets/columns refer to original packaged files; analyzer locations are one-based source line/column.

## Main window and preload

- File: `app.asar/.vite/build/index.chunk-lzaSYO3Q.js`; SHA256 `66a2071baf285aaa3d88aeace7344e7941c3df93c1ef3b21bc6cf64205c58d0d`; size 7,081,117 bytes.
- Analyzer location: line 1, column 5,089,469. Main window options bind preload path `.vite/build/mainView.js`.
- Preload file: `app.asar/.vite/build/mainView.js`; SHA256 `9fb003faa3e791af2e42870b695c7b137d6ca37576df8714f18fcc55966d728d`; size 171,276 bytes. Generated wrappers call `ipcRenderer.invoke/send`; dynamic family generation prevents exhaustive literal-channel enumeration.
- Representative exported wrapper names observed: `AppConfig_$_setIsUsingBuiltInNodeForMcp`, `MCP_$_getMcpServersConfig`, `MCP_$_getMcpServersConfigWithStatus`, `Custom3pSetup_$_probeMcpServer`, `Custom3pSetup_$_authorizeAndProbeMcpServer`, `WakeScheduler_$_getStatus`, `WakeScheduler_$_openSettings`. These wrapper names do not alone establish handler semantics.

## Cowork artifact bridge

- File: `app.asar/.vite/build/coworkArtifact.js`; SHA256 `21f4dfed39f8290444e31a153fe8d68596b10d6d3b44af6e94b4d472c9c14e45`; size 2,687 bytes.
- Exposed methods observed: `callMcpTool`, `askClaude`, `runScheduledTask`, `navigateHost`, `openExternalUrl`, dispatched under `CoworkArtifactBridge`.
- Main registration is in `index.chunk-lzaSYO3Q.js` around line 1, column 5,836,915. Sender-frame origin guard compares against `cowork-artifact:`. Full handler-to-runtime/persistence chain remains incomplete.

## Integrity observation

- Manifest path: `app.asar.unpacked/node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node`.
- Declared SHA256 `e83669e99a699d6bea4de15a3914b3279c19449744dc3cf10c22734ae98935f5`; observed bytes SHA256 `576c180668dde332b051ce673fccadd82646faae4987c091502ba186dc20ea5b` (155,472 bytes).
- Classification: **observed mismatch**. No cause established.
