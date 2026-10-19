# DSH Core end-to-end traces

Status: source-level paths are closed for the later 0.2.1-rc.2 snapshot. Synthetic local execution now exists (R-synthetic), but it does not constitute a real cloud-model call or a single live browser-to-host scenario. The exact npm CLI launcher ran only --version and --help. No real model, interactive Web UI/server session, process-kill recovery, or WebSocket reconnect has been observed.

## 1. Composer message to Agent event projection (static S)

1. The Web app enters through apps/web/src/main.ts and packages/client/web/src/{index,mount,boot}.ts. The application is composed from Cordis client modules and slots.
2. Conversation input submits through packages/client/ui-conversation/src/client/service.ts:250-300 into the selected Session object's prompt method.
3. packages/api/session-controller/src/client/sessions/session.ts:254-313 selects a method from the addressed Session. A root session calls session.prompt; an addressed child with a continuable/interactive address routes through subagents.prompt. One-shot and unknown addresses have different behavior.
4. SessionController @Remote('prompt') in packages/api/session-controller/src/index.ts:461-485 records the message source and delegates to SessionCommands.prompt. The command applies mode (queue/steer/followup/inject), ownership/admission rules and resolves/creates the Agent.
5. Agent turn/step code consumes durable session/inbox input, calls the model, writes attempt/message/tool events, and returns committed events to Session history. Transient stream content is distinct from durable sequence.
6. Session follow/control supplies a history baseline plus later events and a separate live control baseline. Typert maps logical remote streams onto /api/remote.mux.

This is a static source chain. It does not establish that the 0.0.1-rc.5 release Web bundle contains this exact client code or that a local Web server was run.

## 2. Queue edit and child routing (static S; synthetic client/host tests R)

QueueDock delegates edit/remove/steer to the conversation service, then the Session wrapper calls session.updateQueue. The host Remote delegates to SessionCommands.updateQueue. The child ownership fence rejects generic session controls against runtime-owned subagent sessions rather than treating a child as an ordinary root Agent. Child composer prompts and interrupts use separately addressed subagents.prompt / subagents.interruptByParent paths.

Executed tests from fixed upstream source SHA 687f282e8625c6b8d11ff58211a90524be2e4317 on Windows x64, Node 24.18.1, Vitest 4.1.11, pnpm 11.28.5, isolated in %TEMP%/dsh-research-687f282e:
- packages/core/agent-loop/tests/loop.spec.ts, agent.spec.ts; packages/api/session-controller/tests/session-cold.host.spec.ts; packages/subagent/subagent/tests/child-agent.spec.ts: 4 files, 112 tests passed. loop.spec uses deterministic MockAdapter responses and a registered fake content tool; actual AgentLoop code produced/asserted session and tool events. No credentials or network model were used.
- packages/api/session-controller/tests/inbox-projection.client.spec.ts and packages/subagent/subagent/tests/service.spec.ts: 2 files, 56 tests passed. This covers client inbox/updateQueue projection, controller-facing contracts and subagent service lifecycle under deterministic fixtures.
- packages/client/ui-conversation/tests/queue-dock.client.spec.tsx, input-scenarios.client.spec.tsx and input-bar.client.spec.tsx: 3 files, 174 tests passed. React UI interaction tests used test fixtures; they do not establish an actual desktop/Web browser session or production host connection.
- packages/boot/app-boot/tests/profile.spec.ts and profile-resolution.spec.ts: 267 tests passed and one failed. The failing case requires creating a file symlink and Windows returned EPERM at profile-resolution.spec.ts:2047. This OS permission boundary was not bypassed; profile/plugin production boot is still unverified.

Together these focused suites establish synthetic Agent/model-adapter/tool execution plus UI/client and host state sub-paths, but not one correlated E2E run across the actual packaged Web UI, live mux, Host, model and child process.

## 3. Child start, durable address, cold activation and visible tree (static S)

A delegate tool calls SubagentManager.startActivation, which reserves admission, creates a child Session with parent metadata and a durable descriptor, then activates a provider and records lifecycle outcomes. Child identity is the Session ID. Resident Agents and durable child descriptors are separate: process-local occupancy can disappear while the continuable child address remains queryable. On later parent-addressed use the manager can resolve/recover the continuable direct child and deliver new input. The Web subagent catalog projects parent/child lineage; selecting the child addresses that Session for page/follow/control. A child session being recoverable for later input is not evidence that an in-flight model/tool computation survives a host crash.

## 4. Persistence and failure boundary (static S; no crash R)

Session JSONL persistence has append batching, a single-writer lease, versioned event format and damaged-tail recovery. Agent turn/step/tool result bookkeeping writes explicit boundaries and repairs missing tool results for handled failures. These mechanisms do not prove atomic persistence across abrupt process termination or replay of an unfinished external side effect. The gateway client fails active logical streams on carrier loss; the UI must reopen domain history/control. The existing source says stream re-open and compute recovery are separate problems.

## 5. Runtime validation

Passed commands and one Windows-specific failure are recorded above. Remaining runnable work includes a single integrated synthetic SessionController -> AgentLoop -> SubagentManager scenario and an actual packaged UI served in an isolated synthetic profile. No account, credential, or user data was used; no process-kill or reconnect behavior is claimed.
