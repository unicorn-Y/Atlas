# CODEX-ATLAS-P12-END-TO-END-USABILITY Result

STATUS: COMPLETED

## Delivery

- Starting HEAD after `git fetch origin` and `git pull --ff-only origin main`: `06af3aacd981d31193eb88240dd3bb342e12256e`.
- Enabled filesystem, git, and brave-search in the ignored local `config/atlas.toml`. The git server needed `uvx mcp-server-git` because `mcp-server-git` was not directly available on PATH. Live startup exposed 14 filesystem tools and 12 git tools.
- The orchestrator already streamed model chunks through a per-run event queue at the starting HEAD. Live WebSocket runs emitted 33 and 44 deltas; the largest measured inter-delta gaps were 0.121s and 0.121s.
- Replaced plain-text assistant rendering with `react-markdown`, GFM, and syntax highlighting. Lists, safe clickable links, fenced code, and highlighted code were verified in component tests and the live UI.
- Added live runtime plan-event handling and a plan strip that derives total/completed steps from `run.plan.updated` data. A real three-step plan rendered as `3 步 · 0/3 完成`.
- Added a settings username preference stored at `atlas.preference.username`; message avatars use the first character. Playwright verified saving `测试用户` and rendering `测`.
- Confirmed empty backend conversation history remains empty in a store test; removed the visible Mock mode labels.

## Validation

- `uv run pytest tests/test_agent.py tests/test_mcp_client.py -q`: 42 passed.
- `npm test`: 8 passed.
- `npm run build`: passed. Vite reported a 537.59 kB minified JavaScript bundle size advisory.
- `npm install` reported 2 high-severity audit findings; no dependency audit or broad upgrade was included in this task.
- Isolated live E2E: filesystem query called `filesystem__search_files`, returned `message.delta` events and completed; Python JSON function response included a persisted code fence; missing-key Brave search returned a user-facing response and completed without disrupting later runs.
- Stopped and restarted the isolated backend, then reloaded its conversation: 6 messages remained available (3 user, 3 assistant).
- Started the desktop development workflow with `npm run dev`; UI reported the backend connected, created a conversation with an automatic title, rendered syntax-highlighted assistant code, showed the saved username avatar, and displayed real plan progress.
- The taskbook command `uv run pytest tests/test_mcp_integration.py -v -k "filesystem or git"` could not collect tests because `core/tests/test_mcp_integration.py` is absent. Its live acceptance was checked directly: filesystem and git servers started and exposed 14 and 12 tools respectively.
- The repository's existing backend on port 8765 and its database were left untouched. Live E2E used a temporary isolated data directory, removed after verification.

## Environment Notes

- Brave Search is defined and enabled, but startup is expected to fail until `BRAVE_API_KEY` is configured. No key was available during validation.
- `config/atlas.toml` is gitignored and was not committed, per `LUNA_WORKER.md`; the sample configuration remains the tracked source template.
