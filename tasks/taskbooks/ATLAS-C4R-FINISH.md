# ATLAS-C4R-FINISH：C4 四项最小收口

> Only close the four blockers in `tasks/reviews/ATLAS-C4-EXTENSIONS.review.md`.
> Do not reopen accepted C4 implementation and do not start C6.

## 1. PermissionRequest ask → existing approval card

Current bug: Claude hook decision `ask` is treated as blocked/denied.

Fix semantics:
- deny → block;
- allow → allow according to current Atlas permission flow;
- ask → invoke the existing approval callback/card.

Cover both ask_writes and the normal sensitive-tool approval path.

## 2. SubagentStop continue

Consume the SubagentStop hook result.

If the hook blocks final stop / requests continuation:
- keep the existing child session alive;
- inject the reason/additional context;
- continue the same child runtime;
- only finalize/delete after a later non-blocking stop.

Do not create a second child-agent runtime.

## 3. Existing compact/session lifecycle hook points

Wire the same HookStore into lifecycle points Atlas actually has:
- PreCompact/PostCompact for manual compact and the existing automatic compact bridge where available;
- SessionEnd at real conversation/session teardown.

Do not manufacture unsupported lifecycle events just to tick names.

## 4. Custom command model/tools apply to one run

The command renderer already returns `model/tool_allow/tool_deny/mode`.

Make the slash-command execution path pass these into the next run:
- model override
- allowed tools
- denied tools
- mode

Reuse current run-start / AgentRunContext fields. One-run scope only.

## Minimal tests

Focused only:

- PermissionRequest: allow / deny / ask, with ask proving the existing approval callback is invoked.
- SubagentStop: one continue case then a later successful stop.
- Compact/session lifecycle: one manual compact pair + one SessionEnd case; automatic compact only if the existing bridge is directly testable without broad setup.
- Custom command: render metadata → next run receives model/tool_allow/tool_deny/mode; following normal run does not inherit it.
- relevant frontend Vitest if frontend state/send path changes.
- renderer tsc + Vitest once if frontend touched.

Do **not** rerun backend full pytest unless the repair unexpectedly expands.

## Hard boundaries

- do not touch C5 model implementation except existing generic run model field;
- do not merge `zcode/c5-models-parallel`;
- do not merge `zcode/c6a-lsp-parallel`;
- do not start C6;
- do not weaken OriginGuard;
- no real models/services.

## Delivery

- append repair evidence to `tasks/results/ATLAS-C4-EXTENSIONS.result.md`;
- update `docs/plan/CORE-PARITY.md` only if wording needs correction;
- write/leave review target at `tasks/reviews/ATLAS-C4-EXTENSIONS.review.md`;
- `tasks/CURRENT.md` → `AWAITING_REVIEW`;
- pull --rebase, push main, verify local == origin/main;
- stop.
