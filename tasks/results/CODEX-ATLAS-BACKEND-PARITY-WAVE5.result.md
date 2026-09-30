# CODEX-ATLAS-BACKEND-PARITY-WAVE5 Result

STATUS: IMPLEMENTED; REQUIRED FULL TEST SUITE VERIFICATION INCOMPLETE
BASE_BRANCH: main
BASE_HEAD: c83b3a5d5a92efa0884addd96e3745ca7b6e90cf

## Delivery

Implemented all seven feature areas in backend scope. `frontend/`, `backend-adapter/`, and `core/atlas/origin_guard.py` were not modified. New test basetemp directories used the system temporary directory. No live Telegram API, public web request, external Agent, or production data directory was used by the new feature tests.

### 1. Atlas as the default subtask Worker

- `delegate_task` and `delegate_parallel` now use the in-process Atlas worker by default; explicitly selected external executors keep their existing path.
- The child run inherits the parent model, permission mode, allowed paths, sandbox and callbacks, has a 12-turn ceiling, and cannot call either delegation tool.
- Child progress and tool activity are forwarded, cancellation reaches the worker, usage is forwarded, and approval data carries `subtask_id`.
- Added regression coverage for single and three-way parallel delegation, continued results after a worker failure, cancellation, recursion denial, read-only inheritance, and approval metadata.

### 2. Multiple conversation roots

- Conversations persist up to five extra roots and return them in conversation listings; run start inherits saved roots when omitted.
- Extra roots are included in the run's allowed paths and rule-trust gathering. Change summaries keep each root distinguishable.

### 3. Project sources

- Added persistent file, folder, URL, and note sources, text indexing/search, refresh/delete operations, and project instructions injected into project runs.
- Added PDF text extraction dependency alongside the existing DOCX/XLSX/PPTX readers.

### 4. Conversation rewind and redo

- Rewind snapshots conversation messages and relevant files before removing the selected message and later messages; redo restores both.
- Added rewind listing and busy-run checks. File checkpoints are processed in reverse run order.

### 5. Custom script tools

- Added create/list/update/delete/test storage under the Atlas data directory and model-tool exposure for enabled tools.
- Tools receive JSON on stdin, return JSON when parseable, cap output, enforce timeouts, and are treated as writes for `ask_writes` and denied for `read_only`.

### 6. Web and video extraction

- Added `POST /api/web/extract` and the `web_extract` Agent tool. Page extraction checks every redirect, rejects non-public addresses, caps responses at 10 MB and text at 60,000 characters, and has a 20-second fetch deadline.
- YouTube caption lookup uses the declared `youtube-transcript-api` dependency. Bilibili subtitles are read from page metadata or the player subtitle API; every page, API, and caption URL is checked for redirects and non-public addresses. HTML article extraction prefers `trafilatura` and has a standard-library fallback.

### 7. Telegram task channel

- Added settings and token-test routes. Tokens are stored through the Windows/system credential store (`keyring`) and never included in settings responses or ordinary JSON configuration.
- Added authorized-user filtering, outbound long polling, task submission in `ask_writes`, `/list`, `/status`, `/stop`, result notifications and short-lived in-memory approval callbacks.
- Desktop and Hub share the Wave3 scheduler lease check so only its current owner processes updates. Telegram conversations are marked `source: "telegram"` and returned by conversation APIs.

## Deviations and known limits

- The required full command (`python -m pytest -q --ignore=tests/test_computer_use.py ...`) did not complete in this environment. It was interrupted by `KeyboardInterrupt` after 60 passed and 1 skipped while moving into the next test module. Runs with longer test batches were also interrupted by the command runner. The child-process Hub smoke test did not finish within the available run window. No full-suite pass is claimed.
- Existing assertions that encoded protocol 1.6 were updated to 1.7. An existing backend-selection test now tests explicit external selection because Atlas is the new default. The WebSocket authorization test now uses a temporary database and an empty test config rather than the machine's MCP/configuration state.
- Real Telegram setup and Bilibili/YouTube caption availability were not manually verified. No live network was used.

## Verification evidence

- Wave5 focused regressions: 14 passed, including mocked Bilibili subtitle extraction.
- Wave5 OriginGuard regressions: 14 passed, including foreign-origin rejection across the new route groups and token-authorized access.
- Wave2 regressions: 22 passed.
- Wave3 regressions: 25 tests printed as passing across focused batches, including protocol 1.7 assertions. The first batch exceeded the terminal's command window after its pass summary, so it did not return a clean process exit.
- Wave4 regressions: 20 passed and 1 skipped across isolated batches; the real SSH case was skipped because no SSH test endpoint was configured. The previously environment-dependent WebSocket authorization test passed with temporary config isolation.
- Additional independent batches reported: 39 passed/1 skipped (agent modules), 28 passed (configuration/durable/project checks), 22 passed/2 skipped (MCP modules), and 22 passed (local execution modules). One 21-test agent-enrichment batch printed a full pass summary but returned exit 1 at the command boundary. These results do not replace the incomplete full-suite gate.
- `core/atlas/origin_guard.py` is unchanged. Full repository test-suite status remains incomplete.

## Manual verification

1. Start Atlas, configure the Telegram bot token, allowed numeric user IDs, and an absolute local workspace through `PUT /api/channels/telegram`; confirm the response contains only `bot_token_set`, then call `/api/channels/telegram/test` and check the returned bot username.
2. From an allowed Telegram account, send a plain-text task and confirm the conversation appears in Atlas with `source: "telegram"`. Try `/list`, `/status`, and `/stop`. Trigger a write and verify the approval buttons allow and deny it; use an unauthorized account and confirm no task is started.
3. Configure Atlas Hub and desktop against the same data directory, enable the Telegram channel, and confirm only the process holding the scheduler lease handles updates.
4. Call `POST /api/web/extract` with a public article URL and YouTube/Bilibili videos with available captions; verify extracted text and truncation metadata.
5. Exercise section 2 with two temporary roots, section 3 with a note plus an indexed file, section 4 by rewinding and redoing a two-run conversation, and section 5 with a harmless JSON echo script. Keep all sample files in temporary workspaces.
