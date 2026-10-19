# Entrypoints and packaged renderer map (partial)

| Layer | Observed target | Evidence | Status |
|---|---|---|---|
| MSIX app | `app\\Claude.exe`, `Windows.FullTrustApplication` | `identity.json`; `msix-tree.tsv` | S |
| Electron main | `app/resources/app.asar` package metadata: `main=index.pre.js` | `asar-tree.txt`, package metadata static analysis | S |
| Main bundle | `.vite/build/index.chunk-lzaSYO3Q.js` | SHA256 `66a2071baf285aaa3d88aeace7344e7941c3df93c1ef3b21bc6cf64205c58d0d` | S, partial graph |
| Main window preload | `.vite/build/mainView.js` | main bundle binds preload; preload SHA256 `9fb003faa3e791af2e42870b695c7b137d6ca37576df8714f18fcc55966d728d` | S |
| Other preload bridges | `quickWindow.js`, `aboutWindow.js`, `designWindow.js` | ASAR path inventory + BrowserWindow/preload observations | S, dynamic settings |
| Renderer bundles | `.vite/renderer/main_window`, `quick_window`, `about_window`, `buddy_window`, `find_in_page`, `local_exec_consent` | ASAR tree | S; route/action joins incomplete |
| Artifact bridge | `.vite/build/coworkArtifact.js` | SHA256 `21f4dfed39f8290444e31a153fe8d68596b10d6d3b44af6e94b4d472c9c14e45` | S; narrow bridge |
| Remote URLs/webviews | Not exhaustively resolved | Analyzer has partial graph; dynamic loads | U |
| Source maps | None identified in ASAR path listing | `asar-tree.txt` | S within listed paths |

The static analyzer reported 15 BrowserWindow constructions, 41 explicit webPreferences objects and three utility process constructors. This does not establish all windows created at runtime or resolve dynamic utility entrypoints.
