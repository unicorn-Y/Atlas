# Atlas implementation backlog from DSH desktop comparison

**Comparison base:** freshly fetched `origin/main` at `aa6196f550098cc46081dc6db2c376cb87ddffa5`. Research/design only; no Atlas product code changed.

| Priority | Mechanism | Atlas main source path | Assessment | Narrow design follow-up / reusable pattern |
|---|---|---|---|---|
| P1 | Addressable child Agent Session with parent/child/mode reference, separate view and continuation policy | `core/atlas/agent/tool_node.py:604-720`; `frontend/src/renderer/components/ConversationActivity.tsx`; `frontend/src/renderer/components/ForkTree.tsx` | Delegation, parallel task and steer exist. ForkTree represents user session forks; subtask activity is parent-run timeline. No proved child `SessionAddress` equivalence. | First establish whether `subtask_id` maps to durable child session ID/events/usage. If not, add only a persistent reference. Reuse Conversation + event replay and gate composer by child mode/parent availability as official DSH does. Official reference: `ui-subagent` / `sidebar-chat`; MIT. |
| P1 | Independent child token/time/tool projection | `frontend/src/renderer/services/runtimeEvents.ts`; `frontend/src/renderer/components/ConversationActivity.tsx`; `core/atlas/agent/tool_node.py` usage events | Parent-level usage and child subtask usage events exist, but an independent child transcript/projection panel is not established. | Trace true per-child event and usage storage before display; borrow projection pattern, not estimates. |
| P1 | Backend durable queue item identity/edit/remove/cold restore | `frontend/src/renderer/store/useAtlasStore.ts:74-78,291,623-635,686-714`; `core/atlas/api/runtime_ws_router.py`; `core/atlas/runtime/hub.py` | Normal chat queue/pause/steer are renderer state initialized empty; runtime steer and Hub durability are separate mechanisms. This does not prove queued user intent restores. | Decide whether queued intent survives renderer/backend restart. If yes, persist per-session items/events, make UI projection authoritative, and test stale IDs, attachment retirement and in-flight steer semantics against DSH. |
| P2 | Resume event history after reconnect | `core/atlas/api/runtime_ws_router.py:11-33`; `frontend/src/renderer/services/runtimeEvents.ts:51-82` | WebSocket sequence replay and client dedupe/reorder exist. Client cache caps at 800, so older history needs durable retrieval to reconstruct. | Compare history pagination before changing transport. |
| P2 | Host lifecycle cleanup/recovery boundary | `frontend/src/main/backendProcess.ts`; `core/atlas/runtime/hub.py`; `core/atlas/runtime/hub_control.py` | Startup health and durable hub/scheduler exist. Process recovery is not proof an in-flight model/tool operation resumes. | Borrow A's explicit ready/fatal/shutdown-ACK/single-host transitions only where race evidence requires. Do not copy B's unqualified kill-by-port behavior. |
| P2 | Plugin/profile activation feedback | `core/atlas/api/plugins_router.py`; `core/atlas/runtime/hooks.py`; `frontend/src/renderer/pages/SkillDiscoveryPage.tsx`, `SkillsMarketPage.tsx` | Different extension architecture; registry-to-invocation behavior was not audited in this lane. | Keep open until a separate source-of-use trace identifies registered-but-unreachable features. |

## Already present; do not track as missing

- `delegate_task` / `delegate_parallel` backend implementation in `tool_node.py`.
- Subtask steer/cancel through runtime WebSocket route, store actions and Activity UI; this is not a browsable child Session.
- WebSocket sequence replay/dedupe and backend readiness probes.

Official DSH source and community A/B report MIT licenses. Reuse requires original notices and dependency-license review. This design backlog is not a dynamic comparison.
