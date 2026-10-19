# Atlas implementation backlog from Codex Desktop comparison

Baseline: freshly fetched `origin/main@aa6196f550098cc46081dc6db2c376cb87ddffa5`. This is a mechanism comparison from Atlas source, not a live Atlas acceptance run. Do not treat these entries as confirmed gaps until the Codex Desktop edge is closed at G2/G4.

| Priority | Mechanism to assess in Atlas | Existing Atlas source anchor | Codex comparison state | Completion evidence needed |
|---|---|---|---|---|
| P1 | Distinguish durable run recovery from event replay; preserve or explicitly fail active execution on restart | `core/atlas/api/runtime.py:108-153`; `backend-adapter/src/client.ts:524-618` | Codex runtime persistence/re-execution not yet established for this package | Controlled task suspend/close/reopen observation and source-backed state mapping |
| P1 | Trace a user turn from composer through IPC and request transport into persisted event/item history | `frontend/src/preload/index.cts:1-29`; `core/atlas/api/runtime_ws_router.py:18-153`; `core/atlas/engine/session_sync.py` | Renderer-to-method link not closed | One matched action/request/event/session trace on each side |
| P2 | Establish child-agent ownership, cancellation and recovery boundaries | Atlas subtask routes in `runtime_ws_router.py`; corresponding engine/runtime modules need focused re-read | Codex subagent UI chunks found, runtime lifecycle unknown | Per-child IDs, parent relation, result persistence and restart behavior evidence |
| P2 | Verify approval and MCP widget response paths, not just card rendering | `runtime_ws_router.py` approval/input futures; `backend-adapter/src/client.ts:620-650` | Codex UI action and handler mapping unknown | Action→host request→response→resumed task trace |
| P3 | Compare host tool/process boundaries and computer-use lifecycle | Atlas `frontend/src/main/electron.ts`, `backendProcess.ts`, `preload/index.cts` | Codex helper presence/IPC static only; no runtime lineage | Isolated process and synthetic action evidence on both systems |
