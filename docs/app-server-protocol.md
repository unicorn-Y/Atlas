# Atlas app-server JSON-RPC protocol

`atlas app-server --workspace <absolute-or-relative-directory>` runs a local process that speaks newline-delimited JSON-RPC 2.0 over stdin/stdout. Each input and output line is one UTF-8 JSON object. stdout is reserved for protocol messages; diagnostics are written to stderr. The process serves one client and keeps sessions in memory until `session/close` or process exit. It is a local stdio protocol and does not open a network listener.

## Versioning

The protocol version is the integer `1`. Clients must call `initialize` first with `{"protocolVersion":1}`. A successful result includes `protocolVersion`, `serverInfo`, and `capabilities`. Unknown methods return `-32601`; unsupported versions return `-32002`. Incompatible changes require a new protocol version. Additive optional result fields and new notification event types are compatible; clients should ignore fields and events they do not use. Protocol version and Atlas application version are separate.

## Methods

| Method | Params | Result |
| --- | --- | --- |
| `initialize` | `protocolVersion: 1` | `{protocolVersion, serverInfo, capabilities}` |
| `tools/list` | `{}` | `{tools: [{type:"function", function:{name,description,parameters}}]}` |
| `session/start` | `{workspace?: string, conversation_id?: string}` | `{session_id, conversation_id, workspace}` |
| `session/prompt` | `{session_id: string, prompt: non-empty string}` | `{session_id, text, status}`; `status` is `completed`, `failed`, or `cancelled` |
| `session/cancel` | `{session_id: string}` | `{cancelled: boolean}`; may also be sent as a notification |
| `session/close` | `{session_id: string}` | `{closed: true}` |
| `approval/response` | `{event_id: string, choice: "allow"|"deny"}` | `{accepted: true}` |
| `input/response` | `{call_id: string, value: string}` | `{accepted: true}` |

`session/prompt` is a request whose completion response arrives after the run. While it is pending, the server may send `session/event`, `approval/request`, and `input/request` notifications. A client must continue reading until the matching prompt response, and answer approval/input requests with the corresponding methods. Approval defaults to deny when a client disconnects. `session/close` cancels an active run before removing the session.

## Notifications and event payloads

`session/event` has params `{session_id, event}`. `event` is the same typed event object emitted by Atlas runs (for example `chunk`, `tool_call`, `tool_result`, `plan_updated`, `error`, and terminal events); event-specific keys are extensible. `approval/request` includes `{session_id, event_id, tool_name, arguments}`. `input/request` includes `{session_id, call_id, prompt, options}`. Clients should display the request and answer promptly; stale IDs return `-32602`.

## Errors

Errors use JSON-RPC's `{code, message, data?}` shape. Standard parse/invalid-request/method/params codes are `-32700`, `-32600`, `-32601`, and `-32602`. Atlas uses `-32002` for version mismatch, `-32010` for a run failure, and `-32011` when a session already has an active run. Failure to start a process or loss of stdio is a transport error, not a JSON-RPC error. Error messages are diagnostic and may change; clients should branch on numeric codes, not message text.

## ACP boundary

`atlas acp` is a separate adapter for the Agent Client Protocol (ACP) v1. It uses ACP method names and payloads (`session/new`, camelCase fields, `session/update`, and ACP stop reasons), and only exposes the subset implemented by that adapter. ACP clients must follow the upstream ACP protocol and must not send the Atlas app-server snake_case requests. ACP currently requires an absolute `cwd`, accepts text prompt blocks only, does not accept per-session MCP server injection, and reports free-text elicitation as unsupported. These limitations do not alter app-server v1.

## Python SDK

Install `sdk/python` and use `atlas_sdk.AppServer`. `AppServer.start()` negotiates version 1; `new_session()` creates a session; `prompt()` streams event notifications to an optional callback and can answer approvals/inputs; `close_session()` ends the session. See [`sdk/python/examples/app_server.py`](../sdk/python/examples/app_server.py). The SDK uses the same `atlas` executable and local config as the CLI; credentials are never returned in protocol results.
