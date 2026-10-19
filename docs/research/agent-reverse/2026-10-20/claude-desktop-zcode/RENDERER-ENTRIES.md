# RENDERER-ENTRIES.md — Claude Desktop Windows 2.42304.0

Analysis of `D:\Atlas\_research\claude-desktop\2026-10-20\extract\_asar\.vite\renderer\`
plus the main-process bundles that create these surfaces.

**Evidence convention** (used in every TSV in this directory)
- **S** = the code constructs it (I located the constructor / `buildFromTemplate` /
  `globalShortcut.register` / `dispatchNavigate` / literal `loadFile` path).
- **I** = inferred from a string existing near a plausible site; not proven by construction.
- **U** = unresolved (anchor not found; the anchor text is written into the evidence cell).

Every offset in the TSVs was produced by searching for a verbatim anchor string in the
cited file, so each offset can be re-verified by `file[offset:offset+N]`. The generator is
`PARSERS/gen_outputs.py`. Rows that failed to resolve are marked `U(nofind)` — there are
currently **zero** such rows.

---

## 0. Bottom line: how much UI is local vs remote

The header comment in `main_window/index.html` line 1 is accurate and load-bearing:

> `<!-- this is the html for app title bar and error UI. everything else gets loaded from claude.ai -->`

### Structural split of the main window

`W-MAIN` is a `BrowserWindow` whose own webContentses only ever render a **local shell**.
The chat UI is NOT in that webContents at all — it is a **second, separate
`WebContentsView`** (`W-MAINVIEW`, tagged `Di.CLAUDE_AI_WEB`) added as a child view of the
same window, and that view loads `https://claude.ai`, `https://claude.com`,
`https://preview.claude.*`, or the bundled `app://localhost` SPA.

| Layer | Local or remote | What it is | Scale |
|---|---|---|---|
| Window chrome | **NATIVE-CHROME** | `titleBarStyle:"hidden"` + `titleBarOverlay:true`; OS draws the buttons. No HTML. | 0 HTML |
| Boot placeholder | **LOCAL-UI** | `#boot-placeholder-sidebar` skeleton + a 48 px drag strip. Paint only, no text, removed on load. | ~2.5 KB inline JS + ~3.5 KB CSS |
| Error / offline UI | **LOCAL-UI** | `MainWindowPage-BM1J3SeB.js` — `A()` → `T()`: "Couldn't connect to Claude", "Check your network connection", "Retrying automatically…", Reload, Restart Claude, plus an offline game (`clawdQuestEngine`, 1.2 MB, lazily imported). | 11.7 KB component code + 1.23 MB game |
| Title bar | **NATIVE-CHROME** | The local React tree explicitly renders **nothing** for the main window: `function E({isMainWindow:e,...}){if(e)return null; ...}`. The only local chrome affordance is a ghost "Menu" button shown **only when the error overlay is up**. | 1 button |
| Chat / sidebar / settings / projects | **REMOTE-UI** | Everything rendered by claude.ai inside `W-MAINVIEW`. | — |

### Measured local payload for the main window

```
     9,198  renderer/main_window/index.html
    85,469  assets/main-9C0encc1.js               (entry: Sentry init, theme, lazy mount)
    11,683  assets/MainWindowPage-BM1J3SeB.js     (error overlay + offline-game host)
   251,089  assets/MainWindowPage-DTxMhyWF.css    (Tailwind v4 + CDS tokens)
    56,287  assets/react-intl-CW2bLHOS.js
   183,023  assets/attachReactWithSelector-Bf7MO2XB.js   (React + ReactDOM)
 1,232,059  assets/clawdQuestEngine-CdvdlRdl.js  (offline game, lazy chunk)
    10,425  assets/clawdQuestEngine-C2Z1JudX.css
 ---------
 1,839,233  total shell bundle (of which ~1.24 MB is the optional offline game)
```

Font faces (4 × woff2, 576,684 B) are shared with the other local windows and only load
with the lazy `MainWindowPage` chunk.

**So: of the main window, the local renderer contributes a boot skeleton, one error
card with two buttons, one hidden "Menu" button, and an Easter-egg game. Every product
surface (chat, sidebar, projects, settings, connectors, cowork, code) is remote.**

### The one nuance: `app://localhost`

`ql = "app://localhost"` is a privileged scheme registered in the main process
(`protocol.handle("app", ...)`) that serves a **bundled** SPA. Two local routes use it:
`app://localhost/device-code-verify` and `app://localhost/setup-desktop-3p`. Both are still
served by `mainView.js` (the same remote-oriented preload) and are marked LOCAL-UI in
`UI-ROUTES.tsv` because the HTML is served from the app bundle, not the network.

### Everything else that is local

All remaining local UI is *auxiliary*: quick entry, about, hardware buddy, find-in-page,
local-exec consent, and a family of offscreen/HUD overlays that render **inline HTML
written to tmpdir at runtime** (no `.vite/renderer` entry at all).

---

## 1. The six `.vite/renderer` entries

All six share the same HTML skeleton convention (CDS token scope stamp on `<html>`,
`data-mode="system"`, `data-density="comfortable"`, `data-platform="desktop"`).
**None of them declares a `<title>` element** — window titles come from the
`BrowserWindow` options (`title:` in the main-process constructor).

### 1.1 `main_window/index.html` → W-MAIN

| Property | Value |
|---|---|
| Title element | none (window title from `title:mqa()`, i.e. app name) |
| Script entries | inline boot-placeholder script (head), `<script type="module" src="./assets/main-9C0encc1.js">`, inline boot-placeholder script (body) |
| CSS | **No `<link rel=stylesheet>`.** Two inline `<style>` blocks (first-frame colors + drag regions; boot-placeholder rules). Tailwind/CDS arrives with the lazy `MainWindowPage-DTxMhyWF.css`. |
| Mounts | `#root` — but only via a lazily imported chunk; `ec()` dynamically imports `MainWindowPage-BM1J3SeB.js` then `attachReactWithSelector-Bf7MO2XB.js` and calls `t(document.getElementById("root"), e)` on `load` |
| Preload | `.vite/build/mainWindow.js` (`webPreferences.preload` at the `qSe({...})` call) |
| eipc namespace(s) | `claude.internal.ui_$_` + `claude.hybrid_$_` |
| World keys | dynamic eipc keys (`claude.internal.ui.MainWindowTitleBar`), plus literal `process`, `desktopEssentialTelemetryDisabled`, `desktopBootPlaceholder` |
| Callable eipc methods | 13 (AboutWindow 5, QuickWindow 2, MainWindowTitleBar 4, DesktopIntl 2) |
| Renders | boot placeholder skeleton; on failure, the error card; renders **nothing** during normal operation |

Component tree (from `PARSERS/components.js` on `MainWindowPage-BM1J3SeB.js`):

```
default export A()                       hooks: useEffect ×4, useState ×2
├─ E({windowTitle, isMainWindow:true})   -> returns null for the main window
├─ (if errorDetails) div.nc-no-drag > button aria-label="Menu" (Menu icon)
└─ (if errorDetails) T({details,onRefresh,onRestart})   hooks: useRef,useState
   ├─ Warning icon (or Spinner when compact/offline-game)
   ├─ h1   details.errorTitle || "Couldn't connect to Claude"
   ├─ p    details.errorDescription || "Check your network connection"
   ├─ p[role=status] Spinner + "Retrying automatically…"   (when details.retrying)
   ├─ Button "Reload"        (when !details.hideReload)
   ├─ Button "Restart Claude"(when details.offerRestart)
   └─ w({onPlayingChange,clearRef})   offline game host  hooks: useEffect, useEffectEvent, useRef, useState
      └─ lazy chunk clawdQuestEngine -> createClawdQuest(el, {theme,sounds,topInset,reducedMotion,storage,onModeChange})
```

i18n message ids present in this window:

| id | defaultMessage |
|---|---|
| `Nmvo1ufAY5` | Couldn't connect to Claude |
| `6yv8ytK4El` | Check your network connection |
| `OYG7nX5yAG` | Retrying automatically… |
| `tjzoYuBJHm` | Reload |
| `azhLfkYAGK` | Restart Claude |
| `E0ebputFjt` | Press {key} to play |
| `G7z34vBsCO` | Space |

Literal (non-i18n) labels: `aria-label:"Menu"`, `id:"titleBar"` (unused for main window).

### 1.2 `quick_window/quick-window.html` → W-QUICK

| Property | Value |
|---|---|
| Title | none (window has `titleBarStyle:"hidden"`, `frame:false`) |
| Script | `<script type="module" crossorigin src="./assets/main-DFyKxPTW.js">` |
| CSS | `<link rel="stylesheet" href="./assets/main-CiwjW8Wn.css">` (2,226 B) |
| Mounts | **not React** — this is a hand-written DOM page. Elements exist statically in the HTML: `#prompt-input` (textarea, `maxlength=16384`, `placeholder="What can I help you with today?"`), `.container`, `.input-box`, `.app-logo` (inline Clawd SVG, `fill="#D97757"`). The bundle only wires events. |
| Preload | `.vite/build/quickWindow.js` |
| eipc namespace(s) | `claude.internal.ui_$_` + `claude.hybrid_$_` |
| World keys | dynamic (`claude.internal.ui.QuickWindow`), + `process`, `desktopEssentialTelemetryDisabled` |
| Callable methods | 13 (4 used: `QuickWindow.requestDismiss`, `QuickWindow.requestSkooch`, `DesktopIntl.getInitialLocale`, `DesktopIntl.onLocaleChanged`) |
| Note | HTML is 250 KB, but 245 KB of that is inline `<style>`; the visible markup is ~40 lines. Bundles React 19 + RxJS (342 KB) even though only RxJS `fromEvent`/`debounceTime` is used. |

Behaviour (all in the `load` handler at the tail of `main-DFyKxPTW.js`):
- `input` → debounced 750 ms → `QuickWindow.requestSkooch(container.scrollWidth, container.scrollHeight)`
- click outside `.container` → `requestDismiss(null)` and refocus input
- `Enter` (no shift/alt) → `requestDismiss(input.value)` then clear
- `Escape` (keyup) → `requestDismiss(null)`
- drag events are swallowed; wheel scrolls the textarea
- locale: `DesktopIntl.getInitialLocale()` then `onLocaleChanged` re-formats the placeholder

### 1.3 `buddy_window/buddy.html` → W-BUDDY

| Property | Value |
|---|---|
| Title | none; window `title:"Hardware Buddy & Maker Devices"` (msgid `2x2ParVoQo`) |
| Script | `<script type="module" crossorigin src="./assets/main-DeOnnb9G.js">` |
| CSS | `<link rel="stylesheet" href="./assets/main-a4mzyXdA.css">` (4,185 B) |
| Mounts | empty `<body>`; bundle dynamically imports `BuddyWindow-_Jgif_qX.js` (`export{O as default}`) |
| Preload | `.vite/build/buddy.js` (only 4.5 KB) |
| eipc namespace(s) | `claude.buddy_$_` + `claude.hybrid_$_` |
| World keys | `claude.buddy.Buddy`, `claude.hybrid.DesktopIntl`, `process`, `desktopEssentialTelemetryDisabled`, `buddy` (`{getPathForFile}` via `webUtils`) |
| Callable methods | 14 (Buddy 12, DesktopIntl 2) |
| Note | `main-DeOnnb9G.js` is 323 KB but only 18.6 KB is the actual app code; the rest is React + CDS. |

Component tree (14 detected components; named ones shown):

```
default export O()
├─ S({conn,device,name,setName,onSetName,onConnect,onChange,onForget})   status + telemetry card
│   "Connected · Encrypted" / "Connected" / "Disconnected" / "No buddy paired"
│   "This device requested an unencrypted connection…"  (title, when !device.sec)
│   "Change…"  "Forget"  "Name"  "Save"
│   "Battery" "Charging" "USB" "{mA}mA" "{pct}%" "Progress" "Level" "Approved"
│   "Velocity" "{s}s" "System" "Uptime" "Heap" "{kb}KB" "No response" "Connect"
├─ C({onClose,onPick})   scan/pair flow
│   "Choose your Buddy"  "Scanning for 5s…"  "Tap to pair:"  "None found. Make sure yours is on and nearby."
│   "Pair with {name}"   "Enter the 6-digit code shown on the device's screen to connect."
│   "Pairing code"       "Pair"  "Cancel"  "Close"
├─ w({...})   on-device preview pane ("preview")
└─ T({...})   maker docs / install
    "Connect maker devices to Claude"  "Reference implementation"  "Build your own device"
    "Availability"  "What is this?"  "Drop a data folder here / or click to choose"
    "Send to Device"  "Uploading…"  "Can't read folder, or it's empty or too large"
```

i18n: 43 `defaultMessage` strings (see `PARSERS/i18n_raw.tsv` for the 8 collected as
`formatMessage` descriptors; the rest are `<FormattedMessage>`-style `defaultMessage`
attributes on element children). Notable ids: `U4…` (Connection is unencrypted),
`GvZR+GimJM` (Close), `lPkYPQQtQp` (Pairing code), `rzOlorSGCr` (Send to Device),
`EZtqZABDTT` (Name saved), `b32kW1tdoX` (Device did not respond), `TZvMyB3+VV` (Uploading…).

### 1.4 `about_window/about.html` → W-ABOUT

| Property | Value |
|---|---|
| Title | none; window `title:"About Claude"` (msgid `tBeSdR33YY`) |
| Script | `<script type="module" crossorigin src="./assets/main-tJY2FsYJ.js">` |
| CSS | `<link rel="stylesheet" href="./assets/main-CiwjW8Wn.css">` |
| Mounts | empty `<body>`; dynamic import of `AboutWindow-DtKZougt.js` (`export{S as default}`) |
| Assets | `icon-BhGhQuZm.png` (196,590 B) — the 64×64 app icon in the dialog |
| Preload | `.vite/build/aboutWindow.js` |
| eipc namespace(s) | `claude.internal.ui_$_` + `claude.hybrid_$_` |
| World keys | dynamic (`claude.internal.ui.AboutWindow`), + `process`, `desktopEssentialTelemetryDisabled` |
| Callable methods | 13 (5 used: `AboutWindow.openHelp`, `getSupport`, `getAppName`, `getBuildProps`, `ancientJournal`) |

Component tree:

```
default export S() -> x()
├─ img  (app icon, 64×64, draggable=false)
├─ h (wordmark)
├─ h3 > button
│      aria-label = "Copy version {version} to clipboard" (Xo3uc2GpYB)
│      text        = "Version {version}" (S3k5yXss2r)  |  on click: "Copied version to clipboard" (mCXNyEdJat)
│      onClick -> navigator.clipboard.writeText(`${appName} ${version} ${commitTimestamp}`)
├─ p > time (commitTimestamp, dateStyle:"medium", timeStyle:"short")
├─ div[role=status].sr-only  ("Copied version to clipboard")
├─ Button[variant=secondary] "Help"        (zAYm/Z684h)  -> AboutWindow.openHelp
└─ Button[variant=secondary] "Get support" (XfMPtFNO8C)  -> AboutWindow.getSupport
```

`b()` component reads `AboutWindow.ancientJournal()` on mount and on window focus.

### 1.5 `find_in_page/find-in-page.html` → V-FINDINPAGE (a `WebContentsView`, not a window)

| Property | Value |
|---|---|
| Title | none (it is a child view, never titled) |
| Script | `<script type="module" crossorigin src="./assets/main-hLSpBHWq.js">` |
| CSS | `<link rel="stylesheet" href="./assets/main-CiwjW8Wn.css">` + lazily `FindInPage-BLyCri-A.css` (159 B) |
| Mounts | `body` (note: `rd(document.querySelector("body"), ...)`, **not** `#root`) with the default export `qi` |
| Preload | `.vite/build/findInPage.js` |
| eipc namespace(s) | `claude.internal.findInPage_$_` + `claude.hybrid_$_` |
| World keys | dynamic (`claude.internal.findInPage.FindInPage`), + `process`, `desktopEssentialTelemetryDisabled` |
| Callable methods | 5 (`FindInPage.findInPage`, `stopFindInPage`, `endFindSession`, `DesktopIntl` ×2) |
| Chunks | `asHTMLElement`, `CdsPortal`, `Tooltip`, `impl` — this is the **only** local renderer with a real CDS component vocabulary (Tooltip, Portal, IconButton, Input). |

Component tree (26 detected components; app-level ones):

```
qi()  default
└─ v({density: "ready"|{total,activeIndex}|"comfortable", platform:"desktop"})   CDS provider
   └─ Ji()   hooks: useCallback ×3, useEffect ×7, useMemo, useRef, useState ×4
      ├─ Input (ref, auto-focus/select on visibilitychange/focus, 100 ms debounce)
      │    onChange -> Wi(debounced ">=2 chars") -> FindInPage.findInPage(q,{findNext:true})
      │    empty/1-char -> FindInPage.stopFindInPage()
      ├─ span  "{activeIndex}/{total}"   (memoized)
      ├─ IconButton ArrowUp    aria-label="Previous match" (dxTrXnjtp0)  title="{label} (Shift+Enter)"
      ├─ IconButton ArrowDown  aria-label="Next match"     (lu0ZPQSzrk)  title="{label} (Enter)"
      └─ IconButton X          aria-label="Close find bar" (t0wMcoAvaD)  title="{label} (Esc)"
      ids 4            "Find in page" (sNnRQsIEYz)  — aria-label on the search field
      id  pU6Pzn7NcO   "{label} ({shortcut})"
```

Streams: `onClearQuery`, `onStepToMatch(forward)`, `onFocusInput`, `onBlurInput` come from the preload's event surface.

### 1.6 `local_exec_consent/localExecConsent.html` → W-LOCALEXEC-CONSENT

| Property | Value |
|---|---|
| Title | none; window title is a dynamic `select` message: `"{action, select, connect {Connect connector} disconnect {Disconnect connector} apply {Review configuration} other {Confirm}}"` (`ZGBRnVVCUF`) |
| Script | `<script type="module" crossorigin src="./assets/main-Ddc-H8_l.js">` (5,061 B, no framework) |
| CSS | **all inline** in `<style>` (~5 KB, CDS-pinned token values) |
| Mounts | static DOM: `#dialog[role=dialog][aria-modal=true]`, `#title`, `#desc`, `#warn` (disconnect credential warning), `#targets` (`<ul>` of `<details>` rows for `apply`), `#trust-note`, `#cancel`, `#allow` (initially `disabled`) |
| Preload | `.vite/build/localExecConsent.js` (1,366 B) |
| eipc namespace(s) | `claude.internal.localExecConsent_$_` only |
| Callable methods | **1** (`LocalExecConsent.choose(decision)`) — the smallest eipc surface in the app |
| Trust boundary | header comment: *"Deliberately dependency-free (no windowBase / React): the consent surface must not run any stack the web-origin renderer could influence. Content arrives via query; the page renders it with textContent only."* |

Rendered content by `kind` (resolved from `window.location.search`):

| kind | title | desc | primary | secondary | extra |
|---|---|---|---|---|---|
| `connect` | `Connect to {connector}?` | "Your organization set up this connector. You may be asked to sign in." | Connect | Cancel | — |
| `disconnect` | `Disconnect from {connector}?` | "Claude will stop using this connector until you connect again." | Disconnect | Cancel | `#warn` visible |
| `chat-grant` | `Let this app use {connector}?` | "Actions your organization allows will run when requested in chat…" | Allow | Cancel | — |
| `apply` | "Apply settings from your organization?" | "Your organization's configuration server delivered {N} setting(s)…" | Allow | **Quit** | `#targets` list + `#trust-note` |

Guards: `Escape` → cancel; `Tab`/`Shift+Tab` are hand-cycled inside `#dialog`; the
primary button is disabled for 500 ms after focus (anti-accidental-confirm); `apply`
keeps Cancel disabled until the same 500 ms elapses.

---

## 2. Per-window IPC surface

Machine-generated into `IPC-SURFACE-BY-WINDOW.tsv` and `IPC-NAMESPACE-ROLLUP.tsv`.
Authoritative totals: **1170 indexed eipc methods across 92 services** (from
`EIPC-METHODS.tsv`, read positionally — the file has variable-width rows).

| surface | preload | eipc namespaces | services wired | methods reachable |
|---|---|---|---|---|
| W-MAIN | mainWindow.js | 2 | 4 | 13 |
| W-QUICK | quickWindow.js | 2 | 4 | 13 |
| W-ABOUT | aboutWindow.js | 2 | 4 | 13 |
| W-BUDDY | buddy.js | 2 | 2 | 14 |
| V-FINDINPAGE | findInPage.js | 2 | 2 | 5 |
| W-LOCALEXEC-CONSENT | localExecConsent.js | 1 | 1 | 1 (`LocalExecConsent.choose`) |
| **W-MAINVIEW** | **mainView.js** | **10** | **82** (81 indexed + `electron_window`) | **1127 indexed / 1133 total** |
| W-SETUP3P | mainView.js | 10 | 82 | 1127 indexed |
| W-DEVICECODE | mainView.js | 10 | 82 | 1127 indexed |
| W-CODEPOPUP | mainView.js | 10 | 82 | 1127 indexed |
| W-DESIGN | designWindow.js | 1 | 1 | 1 (`DesignPdf.printFrameToPdf`) |
| W-SABLEOTTER-HUD | computerUseTeach.js | 2 | 4 | 21 |
| W-CU-TEACH | computerUseTeach.js | 2 | 4 | 21 |
| W-WATCH-CHOOSER | watchRecordChooser.js | 1 | 3 | 12 |
| W-WATCH-PILL | computerUseWatchRecord.js | 1 | 3 | 12 |
| W-CU-GLOW | none | 0 | 0 | 0 |
| W-ARTIFACTPOPUP | none (adopted guest) | 0 | 0 | 0 |
| V-PREVIEW-TABS | claudePagePreview.js when `isClaudePage` | 0 | 0 | 0 (MessagePort only) |
| V-COWORK-ARTIFACT / V-COWORK-FILEPREVIEW / V-SILENT-AUTH / V-CHROME-IMPORT | none | 0 | 0 | 0 |

`mainView.js` wires **82** services: 81 of the app's 92 indexed services (= 1127 of 1170
indexed methods) **plus one external service not in the index** —
`electron_window_$_WindowManager` (namespace `$eipc_message$_fcb91d11-972d-4fd6-b90b-72739699bff5_$_electron_window_$_`,
6 methods + 1 event) exposed as world key `electron_window.WindowManager`:
`RegisterWindow`, `UnregisterWindow`, `UpdateWindow`, `DestroyWindow`, `WindowAction`,
`GetWindowState`, event `WindowEvent`. So the true RPC ceiling is 1133 methods.

The 11 indexed services (43 methods) `mainView.js` does **not** wire are exactly the other
local windows' private services:
`AboutWindow`(5), `MainWindowTitleBar`(4), `QuickWindow`(2), `FindInPage`(3),
`LocalExecConsent`(1), `DesignPdf`(1), `CoworkArtifactBridge`(6), `CuTeach`(4),
`CuWatchRecordPill`(4), `CuWatchRecordChooser`(4), `SableOtterHud`(9).

### Why the 1127/1170 number is larger than the remote UI's real reach

`mainView.js` is origin-gated. Every one of its 81 service blocks is wrapped in a
predicate that requires **all** of:
1. `webFrame.top === webFrame` (must be the top frame), and
2. origin ∈ {`https://claude.ai`, `https://preview.claude.ai`, `https://claude.com`,
   `https://preview.claude.com`, `localhost`, `*.ant.dev`, `app://localhost`} —
   `claude.buddy` and `claude.officeAddin` use the shorter list ending at `app://localhost`.

So the 1127 methods are the *maximum* any of those four windows could call. The
`claude.web` namespace alone is 900 of them (LocalSessions 329, LocalAgentModeSessions 115,
Launch 88, and so on).

### World keys exposed by mainView.js (12 literal + dynamic eipc keys)

`buddyBle`, `claudeAppBindings`, `claudeAppSettings`, `process`, `desktopBootFeatures`,
`desktopManagedConfig`, `desktopEnterpriseConfig`, `desktopTelemetryConfig`,
`desktopDeviceClass`, `desktopPreferredLanguages`, `electronWindowControl`,
`electronIntl`, plus the dynamic eipc keys published via
`for(let[t,n]of Object.entries(M))e.contextBridge.exposeInMainWorld(t,n)`:
`claude.web` (60 services), `claude.settings` (17), `claude.simulator`, `claude.skills`,
`claude.officeAddin`, `claude.engineSurface`, `claude.hybrid`, `claude.buddy`
(9 app namespaces), plus the external `electron_window` namespace published separately as
`electron_window.WindowManager` (with its own origin gate `$n()` requiring
`__ELECTRON_WINDOW_ALLOWED_ORIGINS__` when defined).

`claudeAppBindings` is notable: `registerBinding`, `unregisterBinding`, `listMcpServers`,
`connectToMcpServer`, `openMcpSettings`. `electronWindowControl` maps to the external
`electron_window` namespace (`WindowManager.RegisterWindow/UnregisterWindow/UpdateWindow/DestroyWindow`).

---

## 3. Offscreen / HUD surfaces built from inline HTML

These have **no** `.vite/renderer` entry. Each one writes a complete HTML document into a
temp directory at runtime and `loadFile`s it.

| surface | tmpdir pattern | size | preload | renderer wiring |
|---|---|---|---|---|
| W-SABLEOTTER-HUD | `so-hud-*` | 460×72, grows | computerUseTeach.js | `SableOtterHud.button/submit/fieldChanged/paste/escape/tab/removePill/settings/resize` (9) |
| W-CU-GLOW | `cu-glow.html` | full display bounds | none | `webContents.executeJavaScript` only (sets `#badge-label` textContent, toggles `#overlay` opacity) |
| W-CU-TEACH | `cu-teach-<ts>.html` | work-area | computerUseTeach.js | `CuTeach.next/exit/mouseEnter/mouseLeave` + `onShow/onWorking/onHide/onReassertHover` |
| W-WATCH-CHOOSER | `wr-chooser-*` | 500×280, grows on shortfall | watchRecordChooser.js | `CuWatchRecordChooser.choose/setMicPreview/stopMicPreview/reportContentShortfall` + `onMicState/onInputDevices` |
| W-WATCH-PILL | `cu-watch-record-pill-*` | small pill, centred bottom | computerUseWatchRecord.js | `CuWatchRecordPill.done/discard/toggleMic/reportProcessingWidth` + `onMicState/onProcessing/onTimeWarning/onMicError` |

Security posture of these: all are `sandbox:true, nodeIntegration:false,
contextIsolation:true`, all `setWindowOpenHandler(()=>({action:"deny"}))`, all reject
`will-navigate`. W-CU-GLOW and W-CU-TEACH are `focusable:false` + `setIgnoreMouseEvents(true)`;
W-CU-TEACH re-enables mouse input only while the cursor is over its card (with an
explicit 3 s re-arm because of a click-through race documented in the source).

---

## 4. Router surface

`UI-ROUTES.tsv` has 64 rows: **62 remote, 2 local** (`/device-code-verify`,
`/setup-desktop-3p`), all evidence S.

Route constants come from the `Dl` enum (offset 838512 in the main bundle):

```
MagicLink, New, SSOCallback, McpAuthCallback, OpenConversation, OpenProject,
Settings, AdminSettings, Customize, Directory, Create, Tasks, Task, Space,
ClaudeCodeDesktop, Code, Epitaxy, Design, Resume, Cowork, LocalSessions
```

plus host enum `El` (`hotkey`, `login`, `claude.ai`, `preview`, `cowork`, `code`,
`debug-handoff`, `sable-otter`), and three route *guard* lists:

- `uLt` — navigate-forbidden paths (`/login`, `/logout`, `/oauth`, `/magic-link`,
  `/sso-callback`, `/partner-*`, `/cai`, `/redirect`, `/health`, `/lti`, `/api/lti`,
  `/edge-api/preview-redirect`, `/onboarding`, `/connect`)
- `dLt` — "sensitive" paths allowed only on explicit navigation (`/upgrade`, `/invites`,
  `/join`, `/setup-2fa`, `/age-verification`, `/create/team/*`, `/labs-verification/email`,
  `/settings/billing`, `/admin-settings/billing`, `/settings/connectors`, `/customize`,
  `/plugins`, `/settings/mcp/auth_mismatch`)
- `kqe` — anti-spoof route table (`join/org/*`, `join/*`, `enterprise/order/*`,
  `user-profiles/enrollment/*`, `offers/*`, `referral/*`, `team-promo/*`, `provision/*`,
  `claude-code/onboard/*`, `artifacts/invite/*`)

### Deep links (`claude:` and variants)

`wl="claude:"`, `Zze="claude-dev:"`, `Qze="claude-nest:"`, `$ze="claude-nest-dev:"`,
`eBe="claude-nest-prod:"`. The strict validator `xe()` at offset ~3180 accepts only:

| host | pathname | allowed query keys |
|---|---|---|
| `claude.ai` | `/new` | `q` |
| `cowork` | `/new` | `q` |
| `claude.ai` | `/chat/<uuid>` or `/project/<uuid>` (UUID regex) | none |

Everything else is rejected (`return!1`) — including any hash. The desktop actions registry
(`Zxr()`, offset ~3805468) emits the wider set used for jump lists / tray actions:
`claude://claude.ai/new?surface=chat&source=desktop_action`,
`claude://code/new?source=desktop_action`,
`claude://code/continue?session=last&source=desktop_action`,
`claude://code/needs-input?source=desktop_action`.

`claudeURLHandler` then dispatches per `Dl` case, e.g.:
- `New` → `lPn(q,{surface,composer})` then `NI(pathname+search)`
- `OpenConversation` → `/chat/<uuid>`, fallback `NI("/recents")`
- `OpenProject` → `/project/<uuid>`, fallback `NI("/projects")`
- `Settings/AdminSettings/Customize/Directory/Create/Tasks/Task/Space/ClaudeCodeDesktop/Cowork/LocalSessions` → `EI(base, url, win, {coldStart})`
- `Epitaxy` → `/epitaxy` (path-checked)
- `Resume` → imports the referenced CLI session

Navigation into the remote UI happens through one event, not methods:
`nv = eo(tv,"Navigation",lv,{events:[["navigate",[["path",F]]]]})` — the main process calls
`NV.getDispatcher(webContents).dispatchNavigate(path)`, and `mainView.js` subscribes to the
`Navigation` event. Related methods: `BrowserNavigation.goBack/goForward/requestMainMenuPopup`,
`WindowState.getFullscreen/getVisibility/getOnScreen/getKeptHidden/getAppFocused/getZoomFactor`,
`SessionPopouts.reportOpenPopouts/takeRestorablePopouts/reportOpenLayout/takeRestorableLayout`,
`MenuEvents.claimEditCommands/releaseEditCommands/reportContextMenuEditor/editCommandUnclaimed`
with events `openFile, openFolder, newWindow, closeWindow, reopenClosedSession, toggleSidebar,
backgroundTasksShortcut, switchSurface, selectArea, cycleSession, openCommandPalette,
openKeyboardShortcuts, toggleSessionPane, closeSessionPane, findInFiles, splitViewCommand, editCommand`.

---

## 5. Menus and hotkeys

- `MENUS.tsv` — 99 rows: 82 application-menu entries (incl. submenu headers and separators), 4 tray, 13 context-menu.
- `HOTKEYS.tsv` — 57 rows: 53 menu accelerators, 4 global.
- `UI-ACTIONS.tsv` — 29 rows: 28 S, 0 I, 0 U.

Application menu is built as
`Menu.buildFromTemplate(aFi([lEi(file), wwi(edit), XIi(view), mEi(go), ...(dev?[pii()]:[]), GPi(help)]))`.
`aFi()` appends a hidden `Alt+<first letter>` mnemonic to every top-level menu.
`X9r()` strips leading/trailing/duplicate separators.
`a.Menu.setApplicationMenu(null)` runs at startup; the real menu is installed later
through `kqa()` (which also calls `setAutoHideMenuBar(false)` + `setMenuBarVisibility(false)`
on every window).

The tray menu is a different template: `mLi()` = Show App / [usage info rows, disabled] / Exit.

Context menu (`HU`) is built per `ContextMenuParams`: spelling suggestions, Add to
dictionary, Open Link in Default Browser, Copy Link/Image Address, Copy Image,
Undo/Redo/Cut/Copy/Paste/Select All, and Inspect Element (only when `allowDevTools`).

Global shortcuts: 4 registrations.
- `globalShortcut.register(t, handler)` — generic path used for `QUICK_ENTRY`,
  `DICTATION`, `HUSHED_HERON`; accelerator comes from preferences at runtime.
- Default `Ctrl+Alt+Space` (`Cze`) for Quick Entry.
- Preference default `double-tap-option` (mac gesture, no Electron accelerator).
- `globalShortcut.register("Escape", yzr)` — only while a computer-use lock is held.

---

## 6. Windows: complete inventory

26 rows in `UI-SURFACES.tsv`:

| construction | count | surfaces |
|---|---|---|
| `new BrowserWindow` | **15** | W-MAIN, W-QUICK, W-ABOUT, W-BUDDY, W-DEVICECODE, W-SETUP3P, W-DESIGN, W-ARTIFACTPOPUP, W-CODEPOPUP, W-SABLEOTTER-HUD, W-CU-GLOW, W-CU-TEACH, W-WATCH-CHOOSER, W-WATCH-PILL, W-LOCALEXEC-CONSENT |
| `new WebContentsView` | **7** | W-MAINVIEW, V-FINDINPAGE, V-COWORK-ARTIFACT, V-COWORK-FILEPREVIEW, V-PREVIEW-TABS, V-SILENT-AUTH, V-CHROME-IMPORT (plus one throwaway blank view `WYn` at 3209321, not listed) |
| `new Tray` | 1 | M-TRAY |
| `new Menu` / `buildFromTemplate` | 3 | M-APP, M-TRAYMENU, M-CTX |

Full scan of all 369 `.js` files in `.vite/build/` (regex over every file) gives the exact
construction totals: **`15 × new *.BrowserWindow`**, **`12 × new *.WebContentsView`**,
**`1 × new *.Tray`**, **`0 × new *.BrowserView`**. The 12 views break down as: 10 in the
main chunk (2 are the singleton main-view/find-view factories, 1 is the throwaway `WYn`
blank view, 1 is the artifact-popup guest adoption, 5 are PreviewContext tab views,
1 is the Cowork artifact view) plus `$ua` file-preview, and 2 in separate chunks
(Chrome-import seed, silent IdP authorize).

### Real `BrowserWindow` constructions (15)

| # | surface | file | offset | creator |
|---|---|---|---|---|
| 1 | W-MAIN (main window) | index.chunk-lzaSYO3Q.js | 6773292 | `V6a()` → `qSe()` (which is `new a.BrowserWindow` at 538269) |
| 2 | W-ARTIFACTPOPUP | index.chunk-lzaSYO3Q.js | 3212832 | `mXn()` |
| 3 | W-CODEPOPUP | index.chunk-lzaSYO3Q.js | 4026209 | `qLr()` |
| 4 | W-CU-GLOW | index.chunk-lzaSYO3Q.js | 4082566 | `IVr()` |
| 5 | W-QUICK | index.chunk-lzaSYO3Q.js | 4408621 | `V5r()` |
| 6 | W-ABOUT | index.chunk-lzaSYO3Q.js | 4442725 | `J9r()` |
| 7 | W-DESIGN | index.chunk-lzaSYO3Q.js | 4986627 | `NTi()` |
| 8 | W-SETUP3P | index.chunk-lzaSYO3Q.js | 6349391 | `ZMa()` |
| 9 | W-CU-TEACH | index.chunk-lzaSYO3Q.js | 6424514 | `SLa()` |
| 10 | W-WATCH-CHOOSER | index.chunk-lzaSYO3Q.js | 6451210 | `TRa()` |
| 11 | W-WATCH-PILL | index.chunk-lzaSYO3Q.js | 6486417 | `DBa()` |
| 12 | W-SABLEOTTER-HUD | index.chunk-BN7PaJ_P.js | 18742 | `ne.ensureWindow()` |
| 13 | W-BUDDY | index.chunk-CzY1tCPL.js | 11417 | `fe()` |
| 14 | W-DEVICECODE | index.chunk-Crjx4ZVt.js | 974 | `l()` |
| 15 | W-LOCALEXEC-CONSENT | index.chunk-JnLh1fOe.js | 6552 | `z()` |

### Popouts / per-URL windows

Two distinct mechanisms, both `REMOTE-UI`:
- **W-CODEPOPUP** (`qLr`) — dedicated singleton for `claude.ai/code...` URLs from `window.open`.
- **W-ARTIFACTPOPUP** (`mXn`) — generic per-URL popups: the guest `webContents` is adopted
  into a `WebContentsView` inside a fresh `BrowserWindow`; reveal is gated by a click-hit
  verification (`opener_mismatch`, `undecided_backstop` → `destroy`).

Separately, `did-create-window` on the main view registers claude.ai's own child windows
(`W-MAIN` popouts) into the `ro` set — these are Electron-created windows with **no local
`BrowserWindow` call** (created by Chromium from `window.open`), tracked with `Di` = none,
patched `show/showInactive/hide/minimize/destroy` methods, and destroyed when the account changes.

### View-based (3 + 4 more)
`JSe` (main view, 538359), `YSe` (find-in-page, 539102), `WYn` (throwaway blank view, 3209321),
`mXn`'s guest view (3212888), PreviewContext tab view (4796914), `createPopupTab` (4833591),
`createUserTab` (4834874), Cowork artifact `zca` (5840523), file preview `$ua` (5877911).
Plus `index.chunk-BMFhTup2.js` (Chrome import seed) and `index.chunk-CU-hpQBB.js` (silent IdP).

---

## 7. Files in this directory

| file | contents |
|---|---|
| `UI-SURFACES.tsv` | 26 surfaces — kind roll-up: 12 `window`, 6 `offscreen`, 2 `popup`, 2 `dialog`, 2 `tray`, 2 `menu`. Of these, 15 are `new BrowserWindow`; 3 `window` rows are `WebContentsView` panes (W-MAINVIEW, V-FINDINPAGE, V-COWORK-*), 1 is the preview-tab view. All evidence S. |
| `UI-ACTIONS.tsv` | 29 local UI actions with handler + RPC/channel + offset |
| `HOTKEYS.tsv` | 57 accelerators (53 menu, 4 global) |
| `MENUS.tsv` | 99 menu rows (82 application-menu entries, 4 tray, 13 context-menu) |
| `UI-ROUTES.tsv` | 64 routes, 62 remote / 2 local |
| `IPC-SURFACE-BY-WINDOW.tsv` | 22 surfaces × preload × namespaces × services × reachable-method count |
| `IPC-NAMESPACE-ROLLUP.tsv` | 15 eipc namespaces with method counts and consumer windows |
| `PARSERS/` | `extract_windows.py`, `extract_menus.py`, `extract_i18n.py`, `html_structure.py`, `preload_surfaces.py`, `ipc_by_window.py`, `components.js`, `gen_outputs.py`, `ctx.py`, `dump_fn.py` + raw JSON/TSV intermediates |

### Reproduce

```
cd PARSERS
python preload_surfaces.py     # -> preload_surfaces.json
python extract_i18n.py         # -> i18n_raw.tsv
NODE_PATH=<tools/node_modules> node components.js <bundles...> > comps.json
python gen_outputs.py          # -> 5 TSVs (all anchors resolved)
python ipc_by_window.py        # -> 2 TSVs
```
