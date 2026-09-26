# Atlas Desktop Backend Protocol V1.2

V1.2 makes the run-scoped `AgentEvent` stream the sole source of runtime state. The renderer stores runs, ordered events, and artifacts; it does not turn backend events into `WorkspaceMessage` records. The legacy `/ws/chat` message protocol is not supported by the V1.2 runtime client.

## Run

```ts
interface AgentRun {
  id: string;
  conversationId: string;
  title: string;
  status: 'idle' | 'planning' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled';
  phase: 'planning' | 'reasoning' | 'execution' | 'verification' | 'final';
  startedAt: string;
  updatedAt: string;
  lastEventSequence: number;
  events: AgentEvent[];
}
```

Start a run on `/ws/chat`. The client creates `run_id` before sending the command:

```json
{
  "type": "run.start",
  "run_id": "run_01",
  "content": "Review the project and produce a report",
  "conversation_id": "conversation_01",
  "model": "gpt-5.6-luna",
  "attachments": ["data:image/png;base64,..."]
}
```

`attachments` is optional and accepts up to four inline PNG, JPEG, or WebP images. Each image is limited to 4 MiB and the combined decoded size to 8 MiB. Image bytes are used only for the current model run and are not stored in conversation history. The selected model provider must support image input.

## Event

Events are persisted and published in strictly increasing per-run sequence order. `event_id` and `sequence` are stable across replay. Duplicate IDs or sequence numbers are ignored.

```ts
interface AgentEvent {
  id: string;
  runId: string;
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}
```

Wire envelope example:

```json
{
  "type": "agent_event",
  "event_id": "evt_01",
  "run_id": "run_01",
  "sequence": 1,
  "timestamp": "2026-09-25T03:00:00.000Z",
  "event": "run.started",
  "data": { "status": "running", "phase": "planning", "content": "Review the project and produce a report" }
}
```

The renderer recognizes `run.started`, `run.status`, `run.phase`, `message.delta`, `message.completed`, `tool.started`, `tool.completed`, `artifact.updated`, `approval.required`, `approval.responded`, `run.paused`, `run.resumed`, `run.completed`, `run.failed`, and `run.cancelled`. Unknown event names may be ignored by older clients. `run.started.data.content` carries the user's submitted run prompt; assistant output is carried by `message.delta` and `message.completed`.

## Artifact

An `artifact.updated` event identifies an artifact owned by that run. The client upserts it by `artifact_id` into the Artifact collection.

```ts
interface Artifact {
  id: string;
  runId: string;
  type: 'file' | 'report' | 'patch' | 'image';
  name: string;
  path?: string;
  summary: string;
  createdAt: string;
}
```

```json
{
  "type": "agent_event",
  "event_id": "evt_04",
  "run_id": "run_01",
  "sequence": 4,
  "timestamp": "2026-09-25T03:00:04.000Z",
  "event": "artifact.updated",
  "data": { "artifact_id": "artifact_01", "artifact_type": "report", "name": "runtime-report.md", "path": "artifacts/runtime-report.md", "summary": "Runtime review report" }
}
```

## Approval

The server publishes `approval.required` with an `approval_id`, description, and optional input. The client responds on the run's WebSocket. `event_id` refers to the `approval.required` envelope's `event_id`.

```json
{
  "type": "approval.response",
  "event_id": "evt_05",
  "choice": "allow"
}
```

`choice` is `allow` or `deny`. The server confirms the decision as an `approval.responded` AgentEvent before continuing or completing the run:

```json
{
  "type": "agent_event",
  "event_id": "evt_06",
  "run_id": "run_01",
  "sequence": 6,
  "timestamp": "2026-09-25T03:00:06.000Z",
  "event": "approval.responded",
  "data": { "approval_id": "approval_01", "event_id": "evt_05", "choice": "allow" }
}
```

## Resume

The client stores the run ID and last accepted sequence under a run-scoped local cursor. After a disconnect it reconnects to `/ws/chat` and sends `resume` instead of `run.start`. The server replays every event after the cursor, then streams new events on the same socket.

```json
{
  "type": "resume",
  "run_id": "run_01",
  "after_sequence": 123
}
```

The client ignores replayed duplicates and updates the cursor for every accepted event. Reconnect uses bounded exponential backoff (up to five attempts, capped at eight seconds). A backend advertises V1.2 using `GET /api/runtime/protocol` with `{ "version": "1.2" }`.

## Mock runtime

Mock mode emits the same `agent_event` envelopes as the backend, including `run.started`, tool start/completion, `artifact.updated`, `approval.required`, `approval.responded`, and `run.completed`. Approval waits for an explicit client response.
