# CODEX-ATLAS-P7D-CONVERSATION-HISTORY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P7C-ELECTRON-BACKEND-LIFECYCLE
CODE_BASE_HEAD: 5b304516ac71741c31ab6854e1d7e5d9b62d14ba

## Goal

Implement persistent conversation history restore.

After a user closes Atlas and starts it again:

- conversations remain available;
- opening an old conversation loads previous messages;
- current Runtime streaming messages are not duplicated with database history.

Only do this stage.

Do not modify:

- Runtime Protocol 1.2
- true streaming implementation
- Electron backend lifecycle
- MCP configuration
- API keys
- UI redesign
- MemoryOS
- Scheduler

## Required work

### 1. Backend history API

Inspect existing MemoryStore/database implementation.

Expose a backend endpoint for reading messages of a conversation.

Suggested:

GET /api/conversations/{conversation_id}/messages

Return stable message objects:

- id
- role
- content
- created_at if available

Do not redesign database schema unless strictly required.

### 2. Frontend store

Update:

frontend/src/renderer/store/useAtlasStore.ts

Add loading of historical messages when opening a conversation.

Maintain separation:

Database history = completed messages.
Runtime events = current active run.

Do not append completed runs twice.

### 3. Rendering rules

Historical user/assistant messages should render before current active Runtime events.

Avoid:

- duplicate user messages;
- duplicate assistant messages;
- fetching database history repeatedly during an active stream.

### 4. Restart verification

Must prove:

1. Start Atlas.
2. Create a conversation.
3. Send a unique marker:

ATLAS_HISTORY_E2E_TEST

4. Finish the response.
5. Close Atlas.
6. Restart Atlas.
7. Open the same conversation.

The marker and assistant response must still appear.

## Tests

Use mocks for unit tests where appropriate.

Add/extend tests for:

- conversation message retrieval API;
- frontend store loading behavior if test infrastructure exists.

Do not require paid model APIs for automated tests.

## Scope guard

Do not fix unrelated Windows test_config path issue.

Do not touch P7B streaming unless a regression is proven.

## Delivery

Before commit:

- git status
- git diff --check
- inspect diff

Commit:

feat: restore conversation history

Push:

git push origin main

Verify:

local HEAD == origin/main

Create:

tasks/results/CODEX-ATLAS-P7D-CONVERSATION-HISTORY.result.md

Include:

- RESULT
- BASE_HEAD
- FINAL_HEAD
- REMOTE_HEAD
- CHANGED_FILES
- TEST_RESULTS
- RESTART_E2E_RESULT
- KNOWN_ISSUES

PASS requires:

- history API works;
- frontend restores history;
- restart E2E passes;
- no duplicate rendering;
- code and result pushed.
