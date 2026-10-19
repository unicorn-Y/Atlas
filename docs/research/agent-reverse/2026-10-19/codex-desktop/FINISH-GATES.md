# Codex Desktop completion gates

The lane is **not accepted**. This is a gate status snapshot against the shared dispatch taskbook. G0–G5 use PASS/PARTIAL/BLOCKED only with citations; G7 remains OPEN while locally analyzable work remains.

| Gate | Status | Evidence / remaining work |
|---|---|---|
| G0 asset identity/version/source↔binary | PARTIAL | Prior exact MSIX hash and extraction record in EVIDENCE-INDEX; installed app.asar reopened and digest matched; continuation download stopped at 35,675,540 bytes, so no fresh full-MSIX hash. Need finish exact asset verification and relation of packaged binaries to sources. |
| G1 measured code coverage and code/route/IPC/event/flag inventory | PARTIAL | COVERAGE.md reports full literal scan over 15,110 ordinary JS leaves / 414,632,995 bytes and selected REA AST results. No exhaustive semantic or route/IPC/event/flag inventory; non-JS assets and skipped parsing listed explicitly. |
| G2 bidirectional UI↔IPC/RPC↔handler/runtime↔events/persistence | PARTIAL | END-TO-END-TRACES.md contains only mutation vocabulary, preload bridge and host method anchors; exact action handler and reverse maps remain unknown. |
| G3 ordered Agent semantics, child lifecycle, state and failure/recovery | PARTIAL | Existing IMPLEMENTATION-TRACE §3–5 covers open-source server version only. Windows package child lifecycle and persistence/re-execution boundaries remain unknown. |
| G4 synthetic real UI+Agent→model→tool/subagent and pause/close/reopen | BLOCKED | No safe end-to-end action was recorded. REA isolated scenario returned `Transport closed`; user's existing session was not touched. Need retry isolated controlled launch or record exact additional failure/unlock. |
| G5 fresh Atlas main SHA and source-level mechanism comparison/backlog | PARTIAL | `origin/main` fetched and remained `aa6196f550098cc46081dc6db2c376cb87ddffa5`; backlog documents current source anchors but Codex side is not closed and Atlas live behavior was not tested. |
| G6 all required deliverables and citations | PARTIAL | COVERAGE.md, SURFACE-MAP.tsv, END-TO-END-TRACES.md, ATLAS-IMPLEMENTATION-BACKLOG.md and this file now exist; citations and completeness still need review after G0–G5 work. |
| G7 continue while local analysis/tests remain | OPEN | JS modules still have analyzer resource/parser failures; module slicing and alternative analysis remain feasible. No lane completion claim is permitted. |
