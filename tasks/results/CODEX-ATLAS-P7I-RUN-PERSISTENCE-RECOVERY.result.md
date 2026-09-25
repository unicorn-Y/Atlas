# CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY

STATUS: PASS WITH EXISTING TEST FAILURES

BASE_HEAD: fe708b9eec25f00a956a6abfa0502e4323c46d42

## Changes

- Added SQLite-backed run lifecycle metadata in the existing Atlas database.
- Persist run identity, conversation, model, status, sequence, and the interruption event.
- On service startup, convert persisted `running`, `paused`, or `waiting` runs to a terminal `run.failed` event with `category: interrupted` and `recoverable: true`.
- Preserve the existing no-replay behavior: a recovered run ID cannot start model or tool execution again.

## Verification

- New persistence and idempotent recovery tests: **2 passed**.
- Full backend suite: **not green**. It reported two existing failures before stopping at 50 passed:
  - `tests/test_config.py::TestAtlasConfigFromData::test_db_path_absolute` expects POSIX path semantics on Windows.
  - `tests/test_memory.py::TestMessages::test_message_with_metadata` expects a `metadata` key absent from the returned message.
- A separate `tests/test_server.py` run was interrupted after it stopped producing progress; no pass result is claimed for that run.
- Ruff still reports existing findings outside the new code, including a pre-existing unused local, timestamp style, and long lines/import ordering in existing code.

## Delivery

Changes and this result file are committed and pushed to `origin/main`. Remote HEAD verification is recorded in the worker closeout.
