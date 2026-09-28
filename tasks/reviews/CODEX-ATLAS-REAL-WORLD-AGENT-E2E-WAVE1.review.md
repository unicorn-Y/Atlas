# CODEX-ATLAS-REAL-WORLD-AGENT-E2E-WAVE1 Review

REVIEW_RESULT: REWORK
DISPOSITION: DIAGNOSTIC_ACCEPTED_ADVANCE_TO_ONE_PRODUCT_GAPS_CLOSEOUT_WAVE
IMPLEMENTATION_HEAD: eb6a659180e044cde381c98d5e709870e5756a48

## Independent review

This wave did the right thing as a real-world diagnostic run, but it does not satisfy the product acceptance success criterion.

No product source was changed; the commit only records the observed results. That is acceptable for an acceptance wave, but the failures now need to be fixed in one concentrated closeout wave.

## What passed

- Normal Atlas Agent coding flow with a deterministic provider.
- P18A local file/shell/git.
- Repo-map use in a real coding scenario.
- Automatic checkpoint-before-mutation.
- Test failure -> source fix -> passing test -> git diff/status.
- CodeAct in the normal Agent path.
- Browser form automation on a deterministic local page.
- MemoryOS pending proposals survived restart and no active fact was silently promoted.
- Shadow checkpoint restore.
- Hermes minimal prompt returned PONG.
- Codex CLI minimal read-only prompt returned PONG.
- Windows package build completed.

These are real product-level positives and must be preserved.

## Product blockers

### 1. Normal Atlas Agent desktop control is still using the native foreground-oriented path instead of the mature Cua window-targeted path

The current normal Agent receives `ComputerUseRuntime` native tools.

Cua Driver is installed and registered as a capability, but it is not the normal Agent's primary `computer_*` execution path.

The real Notepad scenario therefore relied on global foreground focus + SendInput.

That failed in two related ways:

- modern Notepad reused an existing process/tab surface;
- save/readback remained the placeholder;
- the native focus regression hit Windows foreground activation restrictions.

This is a product integration gap, not evidence that SendInput itself is broken.

The next wave must make the existing `computer_*` surface hybrid:

- window-targeted Cua/UIA first where supported;
- native SendInput fallback;
- explicit foreground escalation only when a background action is unavailable.

Do not expose 56 raw Cua tools to the model and do not build a second Computer Use API.

### 2. Programmatic SetForegroundWindow must not be a single point of failure for product Computer Use

The isolated native test currently treats exact foreground activation as mandatory before testing the rest of the input path.

Windows may legally deny foreground activation.

Product correctness should instead rely on target-addressed Cua/UIA actions when possible.

Keep native focus behavior honest:

- do not report success if foreground activation was denied;
- preserve a structured failure/degraded result;
- prove product-level input can still succeed through the hybrid target-addressed path.

Do not delete native SendInput regression coverage.

### 3. Packaged API timeout has a likely event-loop blocking root cause

Independent source review found:

- `GET /api/integrations` is an async FastAPI endpoint;
- it calls synchronous `capability_bus.status()` directly;
- `CapabilityBus.status()/discover()` runs synchronous external CLI probes with `subprocess.run(... timeout=8)`;
- the first-run UI automatically opens Settings when no API key is configured;
- Settings mounts `IntegrationPanel`, which immediately requests `/api/integrations`.

Therefore a slow CLI probe can block the FastAPI event loop and make unrelated follow-up HTTP requests time out even after `/api/health` succeeded.

This strongly matches the packaged acceptance symptom and must be fixed/verified.

Minimum fix:
- never run CLI/version/auth subprocess probes on the event loop;
- run registry probing in a worker thread;
- add a small result cache so repeated Settings renders do not repeatedly launch all probes.

Do not create a new health service.

### 4. Browser acceptance did not prove the normal Atlas Agent browser tool path

The local browser form passed through the installed `agent-browser` CLI, not through a normal `AgentOrchestrator.run()` selecting Atlas MCP/browser tools.

The next wave must run one deterministic normal-Agent browser task using the already connected Playwright MCP or equivalent Atlas-exposed browser tools.

No new browser framework is needed.

### 5. The long-standing MemoryStore metadata failure is a trivial real bug

`save_message()` persists `metadata`, but `get_conversation_messages()` selects only:

- id
- role
- content
- created_at

It omits the stored metadata column.

This is why `test_message_with_metadata` has remained the only known red test across multiple waves.

Fix this in closeout:
- select metadata;
- decode JSON to a dict;
- preserve backward-safe empty metadata.

This is small enough to remove the permanent regression exception.

## Environment-only items that remain non-blocking

Do not block product closeout on:

- configured Atlas Gemini gateway invalid token;
- Claude local launch/access issue;
- ZCode provider config;
- DBOS database URL;
- Pi CLI availability.

Codex/Hermes minimal prompts already work and should remain working.

## Decision

REWORK for product acceptance.

Do not repeat the entire E2E wave.

Advance immediately to one PRODUCT-GAPS-CLOSEOUT-WAVE1 that fixes the concrete product blockers and reruns the failed acceptance scenarios.
