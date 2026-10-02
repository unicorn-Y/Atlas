# ATLAS-C4-EXTENSIONS Review

Verdict: **PARTIAL — one minimal repair wave required before integration/C6.**

Reviewed main head:
- `57696c2577b7aae676d5acc3d51d249ab3acbefc`

## Accepted

The main C4 implementation direction is accepted and should not be reopened:

- **E2** one SkillManager with Atlas / Claude user+project / plugin / optional Hermes sources and stable priority.
- **E4** Claude plugin + marketplace discovery/install/enable/disable/uninstall/update and shared contribution discovery for commands/agents/skills/hooks/MCP.
- **E6** scan→select→import flow for Claude Code/Codex with source directories read-only.
- fake Claude-format plugin E2E crosses the real Atlas runtime path.
- focused C4 suites and frontend four checks passed.
- backend full suite's single failure is the stale C3R `legacy_goal` test drift and is not caused by C4.

## Repair 1 — PermissionRequest `ask` must enter Atlas approval flow

Claude hook output that requests `ask` is currently treated the same as deny/block.

Required:
- `deny` still blocks;
- `allow` bypasses/permits according to current approval policy;
- `ask` must continue into the existing Atlas approval card/callback, not synthesize a denied tool result.

No second approval system.

## Repair 2 — SubagentStop blocking/continue semantics

The SubagentStop hook is fired, but its blocking result is ignored.

Required:
- when hook semantics request the child to continue, do not finalize/delete that child session yet;
- feed the hook's reason/additional context back into the child and let it continue;
- normal non-blocking SubagentStop keeps current completion path.

Use the existing child runtime; no second worker loop.

## Repair 3 — close existing lifecycle hook gaps

Where Atlas already has a concrete lifecycle point, route it through the same HookStore instead of declaration-only support.

At minimum close:
- manual and automatic compact around `PreCompact/PostCompact` where the Atlas/Hermes bridge exposes the point;
- `SessionEnd` at real conversation/session teardown;
- preserve existing UserPromptSubmit / tool / permission / subagent / notification behavior.

Do not invent fake events for lifecycle points Atlas genuinely does not have.

## Repair 4 — command model/tool metadata must affect the next run

`RenderedCommand` already returns:
- `model`
- `tool_allow`
- `tool_deny`
- `mode`

Current frontend only consumes prompt/mode.

Required:
- executing a custom command applies its model and tool allow/deny to **that run only**;
- reuse the existing `run.start` / AgentRunContext fields (`model`, `tool_allow`, `tool_deny`);
- do not persist these as conversation-global settings unless the source format explicitly requires it;
- Recipe behavior stays unchanged.

## Scope

Everything else in C4 is closed. Do not rebuild plugin/skills/import/commands discovery.

After the four focused repairs pass, C4 can be marked PASS. Then do a separate integration wave for accepted C5 + C6A before the remaining C6 work.
