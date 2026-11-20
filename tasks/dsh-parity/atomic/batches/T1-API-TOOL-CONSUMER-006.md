# T1-API-TOOL-CONSUMER-006

Status: DONE (API consumer path; model-facing full-file read gap split into next atom)

## Atomic scope

Close the real `/ws/chat` tool contract from an actually offered read-only workspace tool through Atlas dispatch and SessionDB tool-result replay. The isolated API smoke forced `read_file` without asserting it was offered; the model schema contained neither `read_file` nor a matching tool-search candidate, and tool search returned it as unknown. That forced-call fixture was invalid. The absence of a model-facing full-file read alias remains a distinct semantic capability gap and must stay queued, not be counted closed here.

## Files

- Inspect/modify if required by reproduced cause: `core/atlas/engine/tool_registry.py`, `core/atlas/engine/kernel/loop.py`, `core/atlas/agent/tool_node.py`.
- Test: `core/tests/test_c1_websocket_acceptance.py`.
- Evidence: `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`, `tasks/dsh-parity/atomic/interaction-edges.jsonl`, `tasks/dsh-parity/atomic/batch-queue.jsonl`.

## Dependencies

- Implementation dependency: `T2-API-ATTEMPT-PERSISTENCE-005` isolated backend WebSocket and private SessionDB harness.
- Runtime seam: FakeLLMServer OpenAI wire request, trusted temporary workspace, Atlas model-facing schema, tool alias registration/dispatch, SessionDB canonical assistant/tool messages.

## Binary acceptance

1. The first model request actually includes the selected read-only tool before the fake provider returns that tool call.
2. The real isolated WebSocket run emits a successful tool completion whose result includes the fixture bytes, not `Unknown tool`.
3. After the next user turn and SessionDB reload, the model request contains the assistant tool call and a matching tool-role result with those bytes.
4. The existing event assertions for tool start/completion, stream delta, and run completion remain intact.

## Verification

- The original forced direct `read_file` call failed: model schema had no `read_file`, and `tool_search(select:read_file)` returned it under `unknown`. Preserve this red result; it demonstrates the prior fixture violated the offered-tool protocol and exposes the separate missing full-file-read atom.
- The corrected API fixture uses the actually offered `grep` schema to fetch the marker, then a real second user turn confirms the persisted assistant tool call and tool-role result. Command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_multiturn_keeps_tool_transcript --tb=short`; output `1 passed, 5 warnings in 10.00s`, exit 0.
- Run only the focused API test while diagnosing; run the adjacent C1 nodes after the cause is corrected.
- Execute pytest with `-o addopts=` so the actual nodes are collected despite repository default `-m unit`.
- Record exact command, output, exit code, and any preserved failure. No real model or public service is part of this batch.

## Rollback boundary

Revert only this batch's newly added lines/files if its test contract is invalidated. Preserve all pre-existing dirty worktree edits; do not reset, clean, stash, commit, or push.
