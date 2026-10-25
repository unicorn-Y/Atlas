# Atlas CLI JSONL event protocol, version 1

`atlas exec --output-format jsonl` (or `--json`) writes one UTF-8 JSON object and one newline for every event to stdout. Diagnostics and notifications go to stderr. Every protocol event includes:

| Field | Type | Meaning |
| --- | --- | --- |
| `protocol` | string | Always `atlas.exec.events`. |
| `version` | integer | Schema major version; currently `1`. |
| `event_id` | string | Unique within a turn. |
| `sequence` | integer | Starts at 1 and increases for every line in the turn. |
| `timestamp` | string | UTC ISO 8601 timestamp. |
| `type` | string | Event name. |
| `session_id` | string | Atlas conversation ID. |
| `turn_id` | string | Unique ID for this `exec` invocation. |

## Event sequence

- `start` begins the stream for compatibility with early Atlas JSONL consumers.
- `turn.started` begins the agent turn.
- `item.started` / `item.completed` bracket each user message, assistant message, and tool call. The two events share `item_id`; `item` contains a typed payload. An unfinished item is completed with `status: "interrupted"` if the turn stops before a tool result.
- `input`, `text_delta`, `tool_call`, `tool_result`, and `usage` retain the original Atlas event names and payload fields. They now also carry the versioned envelope; streamed text deltas include their `item_id`.
- `error` describes input, runtime, schema, or agent failure. Runtime/agent error text is intentionally generic in JSONL; local diagnostics remain on stderr.
- Exactly one terminal event follows: `turn.completed`, `turn.failed`, or `turn.cancelled`; `end` follows with the matching status. Existing `final` is retained before the terminal event.

## Payloads

```jsonl
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:3","sequence":3,"timestamp":"2026-10-25T22:00:00+00:00","type":"item.started","session_id":"conversation-id","turn_id":"turn-uuid","item_id":"item_0","item":{"type":"user_message","text":"Summarize the file"}}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:4","sequence":4,"timestamp":"2026-10-25T22:00:01+00:00","type":"item.completed","session_id":"conversation-id","turn_id":"turn-uuid","item_id":"item_0","item":{"type":"user_message","text":"Summarize the file"}}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:5","sequence":5,"timestamp":"2026-10-25T22:00:02+00:00","type":"item.started","session_id":"conversation-id","turn_id":"turn-uuid","item_id":"item_1","item":{"type":"tool_call","call_id":"call-1","name":"local_file","arguments":{"path":"README.md"}}}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:6","sequence":6,"timestamp":"2026-10-25T22:00:03+00:00","type":"item.completed","session_id":"conversation-id","turn_id":"turn-uuid","item_id":"item_1","item":{"type":"tool_call","call_id":"call-1","name":"local_file","arguments":{"path":"README.md"},"result":"...","status":"completed"}}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:7","sequence":7,"timestamp":"2026-10-25T22:00:04+00:00","type":"usage","session_id":"conversation-id","turn_id":"turn-uuid","input_tokens":120,"output_tokens":48}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:8","sequence":8,"timestamp":"2026-10-25T22:00:05+00:00","type":"turn.completed","session_id":"conversation-id","turn_id":"turn-uuid","status":"completed"}
{"protocol":"atlas.exec.events","version":1,"event_id":"turn-uuid:9","sequence":9,"timestamp":"2026-10-25T22:00:05+00:00","type":"end","session_id":"conversation-id","turn_id":"turn-uuid","status":"completed"}
```

Callers must ignore unknown event types while validating `protocol` and `version`, and use `item_id` rather than line order to pair item lifecycle events. New optional fields may be added in a minor-compatible version; incompatible field or semantic changes require a new major `version`.
