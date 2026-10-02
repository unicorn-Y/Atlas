# ATLAS-C2-TOOLS-CONTEXT Result

Status: submitted for review (`tasks/CURRENT.md` is `AWAITING_REVIEW`).

## Changes

- Removed the legacy LangGraph loop, engine selection/configuration, and tests that existed only for the old loop. Kept Atlas tool permission, checkpoint, local execution, event, and lifecycle adapters used by Hermes.
- Added same-run, same-file edit counting for `patch` and `write_file`. The default reminder begins on edit six; the integer threshold is configurable, and a new run gets a fresh counter.
- Routed image `read_file` results through Hermes image preparation and native vision when supported, through configured `vision_analyze` otherwise, and to a clear unsupported message when neither route exists. Multimodal results retain their image envelope for the model and show a thumbnail in the timeline.
- Added OpenCode’s distinct variable-length replacement between unique endpoint anchors to Hermes fuzzy matching. Ambiguous matches still fail. Existing Hermes whitespace/indentation matching and CRLF/LF/BOM handling remain in place.
- Added short stable model-family guidance for Claude, GPT/Codex, Gemini, DeepSeek, Kimi, GLM, Qwen, MiniMax, and default models.
- Kept Hermes `ContextCompressor`; its summary template now always includes the next-step section. The `new_context_window` handoff retains the six structured summary fields and current todo for the next model context, preserves Atlas conversation history, and emits the timeline divider.
- Changed Windows shell selection to prefer Git Bash, ignore WSL Bash as Git Bash, fall back to PowerShell, and respect explicit user shell choices.

## Commits

- Atlas code and parity/provenance commit: `5970f176b8bae85f6cb46a53bccb0a03aee6cab5` (`origin/main` verified at this commit).
- Hermes fork commit: `e287231d7906bcce5bc373d20fb2e3e1e6427220` (`origin/atlas` verified at this commit). Atlas pins this commit in `core/pyproject.toml`.
- This result record is committed separately after the code commit.

## Source implementations

- Hermes Agent: reused its image preparation and vision routing, fuzzy matching, stable system prompt builder, and `ContextCompressor`; the fork adds the Atlas handoff summary application, multimodal result hashing, fixed next-step summary heading, and direct `new_context_window` tool exposure.
- OpenCode `packages/opencode/src/tool/edit.ts` at `1ddb0873aee50d209d1a8d7f91b89c5daf692d49`: ported only the unique-anchor, variable-length middle matching strategy. The source and MIT notice are recorded in `docs/plan/VENDORED.md` and `THIRD_PARTY_NOTICES.md`.
- Codex `new_context_window` and Pi’s structured compaction headings informed the Atlas handoff behavior and summary shape; no second session store or copied database was added.

## Verification

- Hermes focused tests: `360 passed` across fuzzy matching, context compression, Atlas context handoff, and tool guardrails.
- Atlas C2 fake-model WebSocket end-to-end: `1 passed`; exercised image read, fuzzy edit, sixth same-file edit reminder, compaction, `new_context_window`, and final response.
- Atlas post-cleanup focused group: `27 passed`; covered Atlas tool adapters, C2 unit cases, Git Bash/PowerShell selection, and the updated Hermes tool-translation contract.
- The parallel child-agent fixture was corrected so the parent returns completion text after the dispatch tool result; its targeted test passed (`1 passed`). No production delegation logic was changed.
- One required backend full pytest run: `1030 passed, 9 skipped, 1 failed` in `718.52s`. The failure was the stale `test_hermes_tool_calls_translate_to_atlas_tools` assertion expecting default PowerShell and omitting existing translation metadata. The assertion was updated for `shell="auto"` and the current metadata, then the single test passed. The full suite was not rerun, as required by the one-run limit.
- Renderer TypeScript check: passed.
- Electron TypeScript check: passed.
- Vitest: `9` files and `40` tests passed.
- Vite production build: passed (`4272` modules transformed; existing large-chunk advisory only).
- Full pytest excluded `tests/test_computer_use.py` per taskbook. Tests used temporary Atlas/Hermes directories and fake model services; no real model or external service was used.

## Remaining gaps

- Real provider vision behavior and live model-family prompt behavior were not exercised; live model/service testing was excluded by the taskbook.
- `tests/test_computer_use.py` remains outside this acceptance run as required.
- The full-suite summary retains one failure from the pre-fix run; the changed failing test passed in a targeted rerun, and no second full run was performed.
