# Atlas Desktop Backend Protocol (V1)

This document describes the contract used by `backend-adapter/`. The current Python service exposes these routes from `core/atlas/server.py`. Desktop configuration uses `VITE_API_BASE_URL`; the adapter probes `GET /api/health` and uses the live service when healthy, otherwise it starts in local Mock mode.

## HTTP

Base URL example: `http://127.0.0.1:8765`  
Requests and responses use JSON encoded as UTF-8. Error responses use FastAPI's `{ "detail": "..." }` shape.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `{ "status": "ok", "version": "0.1.0" }` |
| GET | `/api/models` | — | `{ "models": Model[], "current": string }` |
| POST | `/api/models/select` | `{ "model": string }` | `{ "status": "ok", "model": string }` |
| GET | `/api/conversations` | — | `Conversation[]` |
| GET | `/api/conversations/{id}/messages?limit=100` | — | `Message[]` |
| PUT | `/api/conversations/{id}` | `{ "title": string }` | `{ "status": "ok", "conversation_id": string }` |
| DELETE | `/api/conversations/{id}` | — | `{ "status": "ok", "conversation_id": string }` |
| GET | `/api/search?q={query}&limit=20` | — | Matching message array |
| GET | `/api/facts?category={category}` | — | `Fact[]` |
| POST | `/api/facts` | `{ "key": string, "value": string, "category": "general" }` | `{ "status": "ok", "key": string }` |
| DELETE | `/api/facts/{key}` | — | `{ "status": "ok", "key": string }` |
| GET | `/api/tools` | — | `{ "servers": string[], "tool_count": number, "tools": Tool[] }` |
| GET | `/api/runtime/protocol` | — | `{ "version": "1.1" }` when durable Agent Run events and replay are supported |

`Model` entries include a stable `id`; the UI optionally reads `name` and `provider`. `Conversation` entries include `id` and `title`. `Message` entries include `id`, `conversation_id`, `role`, and `content`. `Tool` entries contain `name`, `description`, `server`, and `input_schema`. Additional backend fields are allowed and ignored by the UI.

## Agent Run and event stream (V1.1)

An Agent Run is the durable unit of execution. The desktop creates a client-generated UUID before sending, so the same identifier is available for event correlation and reconnect. The backend must persist the run and append events before publishing them.

```ts
interface AgentRun {
  id: string;
  conversationId: string;
  title: string;
  status: 'idle' | 'planning' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed';
  phase: 'planning' | 'reasoning' | 'execution' | 'verification' | 'final';
  startedAt: string; // ISO 8601 UTC
  updatedAt: string; // ISO 8601 UTC
  events: AgentEvent[];
}

interface AgentEvent {
  id: string;           // unique and stable for this run
  runId: string;
  sequence: number;     // starts at 1, strictly increasing per run
  type: string;
  timestamp: string;   // ISO 8601 UTC
  data: Record<string, unknown>;
}
```

### Start a run

Connect to `ws://127.0.0.1:8765/ws/chat` (use `wss://` when the HTTP base URL is HTTPS), then send:

```json
{
  "type": "run.start",
  "run_id": "client-generated-uuid",
  "content": "Summarize the current project",
  "conversation_id": "conversation-id",
  "model": "optional-model-id"
}
```

The server acknowledges the run by publishing an event envelope. Every envelope has a unique `event_id`, the same `run_id`, a per-run increasing `sequence`, an ISO UTC `timestamp`, an `event` name, and an object `data`:

```json
{
  "type": "agent_event",
  "event_id": "evt_01",
  "run_id": "client-generated-uuid",
  "sequence": 1,
  "timestamp": "2026-09-25T03:00:00.000Z",
  "event": "run.started",
  "data": { "status": "planning", "phase": "planning" }
}
```

The event store deduplicates by event ID and sequence, then applies events in sequence order. Producers must not reuse a sequence for different events. Unknown event names are ignored by V1.1 clients and may be added without breaking the envelope.

### Event names

| Event | Suggested `data` | Effect |
| --- | --- | --- |
| `run.started` | `status`, `phase` | Creates/acknowledges the run |
| `run.status` | `status` | Updates run status |
| `run.phase` | `phase` | Updates current phase |
| `message.delta` | `content`, optional `message_id` | Appends assistant output |
| `message.completed` | `message_id`, optional `content` | Closes an assistant message |
| `tool.started` | `tool_call_id`, `name`, `arguments` | Adds a running tool activity |
| `tool.completed` | `tool_call_id`, `name`, `result` | Completes the tool activity |
| `approval.required` | `approval_id`, `description`, `input` | Sets status to `waiting` |
| `artifact.updated` | `artifact_id`, `path`, `change` | Announces an artifact change |
| `run.paused` / `run.resumed` | — | Updates pause state |
| `run.completed` | optional `message_id`, `result` | Terminal success |
| `run.failed` | `code`, `detail` | Terminal failure |
| `run.cancelled` | optional `detail` | Terminal cancellation |

### Resume after disconnect

Reconnect to `ws://127.0.0.1:8765/ws/runs/{run_id}/events?after_seq={last_sequence}`. The server replays all persisted events with a greater sequence, in order, then continues the live stream. Replay and live delivery may overlap; clients deduplicate. If the run or cursor has expired, close with an appropriate WebSocket error and expose a recoverable error to the user. The client uses bounded exponential backoff (up to five reconnect attempts, 8 seconds between attempts).

The server must retain run and event IDs across process restarts. This stream is the source for LangGraph state updates, MCP/tool execution, MemoryOS context events, scheduler transitions, approvals, and artifacts; those systems should publish the same run-scoped envelope rather than create client-specific protocols.

### Control messages

On the active run socket the client may send `{ "type": "run.cancel", "run_id": "..." }`, `{ "type": "run.pause", "run_id": "..." }`, or `{ "type": "run.resume", "run_id": "..." }`. A successful control request is confirmed by a corresponding `run.cancelled`, `run.paused`, or `run.resumed` event. Closing the socket is not cancellation.

### V1 compatibility

The adapter probes `GET /api/runtime/protocol` before the first live run. If it returns `{ "version": "1.1" }`, it uses the durable run command and replay contract above. If the endpoint is missing or reports another version, it sends the V1 `type: "message"` command and accepts `chunk`, `tool_call`, `tool_result`, `done`, `error`, and `cancelled` responses. Those responses are converted to local run events for display, but they do not provide durable IDs or replay, so an unexpected socket loss is reported instead of being resumed. Full crash recovery requires the V1.1 envelope and resume endpoint above. The current Python service may continue to expose only the V1 chat protocol until its Agent Runtime is implemented.

## Structured planning recovery

For an interrupted run with a persisted structured plan, a client may start a
new run ID and set resume_from to the failed run ID. The server resumes the
saved plan's pending subtasks in the same conversation. The original run remains
terminal and replay-only. Plan changes are emitted as additive
run.plan.updated events with the plan and subtask verification evidence.

## Structured planning recovery

For an interrupted run with a persisted structured plan, a client may start a
new run ID and set resume_from to the failed run ID. The server resumes the
saved plan's pending subtasks in the same conversation. The original run remains
terminal and replay-only. Plan changes are emitted as additive
run.plan.updated events with the plan and subtask verification evidence.

## Local development

Copy `frontend/.env.example` to `frontend/.env.local`, then change only `VITE_API_BASE_URL` if the API uses another address. Run the API before starting the desktop app. If the health probe fails, the UI remains usable with Mock conversations and streamed sample replies. No backend endpoint details are embedded in renderer components.
