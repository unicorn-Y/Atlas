# T2-ACP-KERNEL-ATTEMPT-STREAM-021

## Scope

Exercise the actual ACP `serve_stdio(protocol="acp")` consumer against a real `AgentOrchestrator`/Kernel stream and a private loopback FakeLLM sequence `DropMidStream("OLD answer")` → `Text("NEW answer")`. Verify ACP notifications and stop result, canonical SessionDB transcript, and discarded-attempt audit together.

Changed files: `core/tests/test_app_server_acp.py`, this batch record, `atomic-capabilities.jsonl`, `interaction-edges.jsonl`, `batch-queue.jsonl`, and `BEYOND-DSH-PROGRESS.md`. Production app-server logic already buffered attempt-tagged chunks and emitted them at `model_attempt_committed`; the new real consumer test found that behavior correct, so no production code was changed in this atom.

## Evidence

The first harness draft used a fixed session ID without controlling ACP's generated ID and received `-32602 session_id and non-empty prompt are required`; that was test wiring, not a product result. Once corrected to send `session/prompt` using the actual `session/new` response, further setup errors exposed the minimum real model/preset interfaces required by `AgentOrchestrator`. Those harness errors were corrected before the passing run.

Exact final command from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_acp.py --tb=short
12 passed, 5 warnings in 9.03s
```

The new node asserted exactly two physical FakeLLM requests, actual ACP `session/update` chunks concatenate to `NEW answer` with no `OLD`, `session/prompt` returns `end_turn`, reopened private SessionDB assistant messages include NEW and exclude OLD, and `model/attempt` audit retains the discarded OLD partial text. The server used its actual stdio JSON-RPC loop and actual `AgentOrchestrator`; only ModelManager credentials/metadata, MemoryStore, preset store, stdio, and model endpoint were isolated fixtures.

## Status and limits

`DONE_SCOPED`. ACP real-kernel streaming is verified at the in-process protocol adapter with a loopback FakeLLM. This is not an external ACP client process, packaged Electron, actual desktop window, real model, or full SDK/app-server restart matrix. No user config/credentials/proxy, `data/memory/**`, or 8765 was used. No commit/push/reset/stash/clean was performed.
