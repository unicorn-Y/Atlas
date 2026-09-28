# CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1 Result

## Delivery

- Base branch: `main`
- Pulled base HEAD: `1af49e5852646d42a0e6baf626d4fe3d062763c7`
- Dependencies or licenses changed: none

## Capability matrix

| Capability | Atlas implementation and evidence | Upstream inspiration |
|---|---|---|
| Normalized hooks | Optional ordered `HookBus` has all eleven required points. Hook exceptions are logged and surfaced as `hook_error` events while an Agent graph is active, without blocking model/tool work. `test_agent_turn_runs_hooks_around_real_tool_call` verifies a model turn, MCP tool call, and ordered hooks. | [Gemini CLI hook lifecycle and event reference](https://geminicli.com/docs/hooks/reference/) |
| Disposable delegation | `delegate_task(goal, context?, tool_profile?)` uses the existing `AgentBackendHost`, starts a fresh bounded session, collects events/evidence, fires subagent hooks, and closes the session. The deterministic smoke delegates through a backend fake that calls `local_file` using the shared Atlas bridge. | [Hermes delegation patterns](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/delegation-patterns.md) |
| CodeAct | `execute_code` launches a time-bounded Python child process. Its loopback RPC bridge dispatches to the existing P18A, P18B, and MCP runtimes. The smoke calls real P18A `local_file` three times and returns one compact result. | [Hermes code execution guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/code-execution.md) |
| Context maintenance | Structured snapshots preserve goal, session summary, project state, unresolved work, user constraints, process/tool references, and memory references. `should_compact` supplies a count/size trigger; snapshots mount through `before_compact` and `after_compact`. | [OpenCode compaction](https://opencode.ai/v2/docs/compaction) |
| System reminders | Per-run cadence policy injects concise goal, FULL_ACCESS, and verification guidance; each configured slot fires once. | [Pydantic AI Harness System Reminders](https://pydantic.dev/docs/ai/harness/system-reminders/) |
| Optional trajectory reviewer | Callback injection permits a separate reviewer/backend/model; default is disabled. Corrective guidance is returned to the parent, failures continue the task, and review evidence is stored through MemoryOS reflection records. | [Pydantic AI Harness Trajectory Judge](https://pydantic.dev/docs/ai/harness/trajectory-judge/) |
| Shadow Git checkpoints | Atlas-owned storage contains a separate shadow Git repository and scoped snapshots. Local file mutations checkpoint before execution; restore changes only the selected scope. A temp-workspace smoke verifies exact restore and preserves an unrelated file. | [Gemini CLI checkpointing](https://geminicli.com/docs/cli/checkpointing/) |
| Memory reflection | Successful Agent turns automatically emit structured proposals covering fact, project state, decision, preference, and reusable experience. They remain advisory; the bridge calls MemoryOS's existing candidate extraction/governance path and does not promote facts. A real SQLite smoke verifies a pending candidate and no active fact. | [Letta structured memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks) |
| Plugin bundle groundwork | Read-only `atlas-plugin.json` manifest parsing and normalized discovery cover skills, commands, MCP servers, hooks, agents, and optional UI metadata. Declarations are discovery-only and disabled for execution; plain Skills remain discoverable. | [ZCode plugin manifest/components](https://github.com/zai-org/zcode-plugins/blob/main/docs/PLUGIN_DEVELOPMENT.md), [Gemini extension manifest](https://geminicli.com/docs/extensions/reference/) |

## Changed files

- `core/atlas/agent/__init__.py` — lifecycle integration, model-facing tools, checkpoint-before-file-write, and reviewer evidence.
- `core/atlas/agent/enrichment.py` — hook bus, context maintenance, reminders, reviewer, shared tool bridge, CodeAct, delegation, and MemoryOS bridge.
- `core/atlas/agent/checkpoints.py` — scoped shadow Git snapshot/list/restore store.
- `core/atlas/server.py` — capability registry entries for the enrichment surfaces and checkpoint operations.
- `core/atlas/skills/bundles.py` — plugin bundle schema parsing and normalized discovery.
- `core/tests/test_agent_enrichment.py` — deterministic lifecycle and integration regressions.
- `tasks/results/CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1.result.md` — this result record.

## Verification

- New enrichment regression file: `12 passed`.
- Relevant regression collection (Agent, P18X/P18A, MemoryOS, Skills/P15, server, packaged smoke gate): `354 passed, 1 failed, 2 skipped`.
- The failure is `tests/test_memory.py::TestMessages::test_message_with_metadata`: it expects a `metadata` key from `MemoryStore.get_conversation_messages`, which is absent in the current implementation. The failing test and MemoryStore implementation were not changed in this wave.
- Packaged backend smoke cases were skipped because `ATLAS_P16A_RESOURCES_DIR`, `ATLAS_P16A_NODE_RUNTIME_DIR`, and the opt-in packaged-smoke flags are unavailable in this environment.
- Ruff on changed Python files: passed.
- `pip check`: passed (`No broken requirements found`).
- `git diff --check`: passed.

## Remaining degraded integrations

- Codex CLI: `codex login status` reports unauthenticated.
- Browser Use: `ATLAS_API_KEY` is absent, so the prior gateway rejection remains unresolved.
- ZCode: installed CLI is present, but the checked local provider settings are absent.
- DBOS: no system database URL is configured.
- Claude: the Atlas venv contains `claude-agent-sdk` and the Anthropic key variable is present. A direct minimal SDK prompt was attempted, but the SDK refused the installed Windows `claude.CMD` shim; no native `claude.exe` was found in PATH or the checked install paths. The Claude integration remains degraded; no CLI shim bypass or dependency install was added.

## Scope and runtime notes

- The shared P18X integration runtime, P18A/P18B runtimes, MemoryOS governance, and P15 registry/lifecycle were retained.
- FULL_ACCESS remains the default; CodeAct and ordinary local file operations use Atlas's existing full-access runtimes without introducing approval prompts.
- Voice, camera, mobile, marketplace UI, and feature-specific follow-up taskbooks were not added.
