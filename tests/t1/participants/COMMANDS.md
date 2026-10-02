# Participant command evidence (verified 2026-10-03 Asia/Hong_Kong)

No model prompt, login, or account configuration was invoked during this check. Local CLI evidence came from `--help` only; URLs are primary vendor/project documentation reviewed on the date above.

| Participant | Command / transport used by adapter | Evidence and limits |
|---|---|---|
| Atlas | `ws://127.0.0.1:8765/ws/chat`, `run.start`; steering `run.steer`; plan approval `run.plan.approve`; tool approval `approval.response` | Read-only local source inspection: `D:\Atlas\core\atlas\server.py` (`ws_chat`, `_handle_run_start`) and `D:\Atlas\backend-adapter\src\client.ts` (`startRun`, `steerRun`, `approvePlan`). OriginGuard permits local-process requests without an Origin header; optional `ATLAS_API_TOKEN` is passed only from that environment variable. Parses `run.usage` and cumulative `run.completed.data.usage`; cache tokens/cost remain null if absent. Checkpoint/rewind remain unsupported by this adapter. |
| Claude Code | `claude -p --output-format stream-json --verbose <prompt>`; scenarios use `--input-format stream-json` and JSONL user messages | [Claude Code CLI usage](https://docs.anthropic.com/en/docs/claude-code/cli-usage) documents print mode, JSON/stream-JSON formats, model, and JSONL input. Local: `claude` not found; no executable help available. Scenario input supports multiple user messages and steering; plan approval is not a stream command. |
| Codex CLI | `codex exec --json --cd <workspace> [--model ID] <prompt>` | [OpenAI Codex exec documentation](https://github.com/openai/codex/blob/main/docs/exec.md) documents JSONL events and turn usage; [Codex configuration reference](https://developers.openai.com/codex/config-reference) documents per-invocation `-c` overrides and model-provider base URLs. Local `codex exec --help` confirmed `--json`, `--cd`, and `--model`. The available FaultProxy implements `/v1/chat/completions`, while Codex's documented Responses provider uses a different wire protocol; task 20 proxy capability stays unsupported for Codex. One prompt per `exec` invocation; no live steering/RPC used. |
| OpenCode | `opencode run --format json [--model ID] <prompt>` | [OpenCode CLI commands](https://opencode.ai/v2/docs/cli/commands/) documents `run` and JSONL output. Availability now uses a bounded `opencode run --help` probe with temporary isolated HOME/APPDATA/XDG directories and no inherited key/token variables. The local launcher reports that its installed binary is incompatible with this Windows version, so it is correctly unavailable here. |
| Pi | `pi --mode rpc --no-session [--model ID]`, JSONL commands `prompt`, `steer`, `follow_up`, `get_session_stats` | [Pi RPC mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md), [RPC commands](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc-commands.md), and [JSON event stream](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md) document the protocol, settled lifecycle, steering/follow-up, compaction, and session stats (`tokens.input/output/cacheRead`, `cost`). Local `pi` not found; no executable help available. The documented RPC lacks plan approval and workspace checkpoint/rewind actions. |
| Hermes | `hermes chat --oneshot --quiet --format stream-json --in <workspace> [--model ID] [--resume SESSION] --query <prompt>` | [Hermes CLI command reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/cli-commands.md) documents the command family; [Hermes environment-variable reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/environment-variables.md) identifies `OPENAI_BASE_URL` as a custom OpenAI-compatible endpoint override. Installed `hermes chat --help` confirmed `--oneshot`, `--quiet`, `--format stream-json`, `--in`, `--model`, `--resume`, and `--query`. Scenario prompt/context rounds are separate resumed CLI invocations when stream output supplies a session ID. A per-run `OPENAI_BASE_URL` binding is opt-in and only applies when the selected Hermes provider/model uses its custom OpenAI-compatible route. Mid-turn live steering is unsupported. |
| ZCode | Manual handoff only | No CLI invocation. Adapter emits a workspace instruction and blank result template; GUI work remains human-operated. |

## Capability boundaries

- Atlas supports native sequential rounds, live steering, explicit plan mode, and replies to actual approval/plan events. Native token aggregates are parsed without also counting the underlying per-call usage; absent cache/cost fields remain null.
- Claude's documented streaming input supports multi-turn prompt and steering messages. No machine approval/checkpoint/rewind action is claimed.
- Pi RPC supports multi-round prompts, live steering, follow-up, and native session usage stats. Plan approval and workspace rewind are unsupported.
- Codex and OpenCode adapters use one non-interactive process per task. Hermes uses resumed non-interactive invocations for sequential prompts; none of these adapters claims live steering. Their unimplemented scenario actions return unsupported.
- The fake participant is the only adapter allowed to read a task's `solution/` overlay. Real adapter contexts and commands never include that path.
- Real task 20 proxy routing defaults to unsupported. It is enabled only for Hermes with an explicit per-participant binding:

  ```toml
  [participants.hermes.fault_proxy_binding]
  kind = "env"
  name = "OPENAI_BASE_URL"
  ```

  The runner injects its loopback `fault_proxy_url` into this variable for that child process only. Other participants remain unsupported until a compatible Chat Completions transport binding is verified. The runner owns proxy lifecycle and provider-fault evidence; adapters never edit participant configuration files.
