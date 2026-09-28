# CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1 Review

REVIEW_RESULT: PASS
DISPOSITION: ACCEPT_WITH_ENVIRONMENT_DEGRADATIONS
IMPLEMENTATION_HEAD: c4d17f4ce9e48b1692252c4e4bbeec3a7739270b
IMPLEMENTATION_COMMIT: 6b10807ae039decd337f8ede5a5ab2c299d2a4fb
RESULT_COMMIT: c4d17f4ce9e48b1692252c4e4bbeec3a7739270b

## Independent review summary

This concentrated debug wave materially closed the important integration gaps from P18X Wave 1.

The implementation is accepted.

### Confirmed real improvements

1. **ACP FULL_ACCESS is no longer hard-denied.**
   - The previous unconditional `DeniedOutcome` was removed.
   - Atlas now chooses the broadest offered normal ACP allow option, preferring `allow_always`.
   - Regression coverage exists for both allow and no-allow cases.

2. **External ACP Agents now receive a shared Atlas MCP capability bridge.**
   - ACP sessions no longer use `mcp_servers=[]`.
   - A shared `atlas.tools.agent_bridge` stdio MCP server is passed to sessions.
   - The bridge reuses canonical Atlas runtimes rather than reimplementing them.

3. **The shared bridge exposes useful Atlas-owned tools.**
   - P18A local execution tools.
   - P18B native Computer Use tools.
   - ast-grep.
   - Aider repo map.
   - Real regression calls `local_file` through the bridge.

4. **Hermes integration is real rather than guessed.**
   - Backend now uses `hermes acp`.
   - Worker evidence shows a real Hermes prompt completed and called Atlas `local_file` through the bridge.

5. **ZCode integration was corrected to its actual installed CLI behavior.**
   - Version detection is fixed on Windows.
   - Backend now uses the real non-interactive prompt flags with `--mode yolo`.
   - Current failure is provider configuration, not the old fake app-server text protocol.

6. **CUA useful workflow closed.**
   - Observe/type/save/readback exact marker succeeded.
   - Native P18B and pywinauto fallback remain intact.
   - The only open detail is closing only the isolated test tab; preserving the user's existing Notepad process was the correct choice.

7. **Browser Use now has a real Agent task path.**
   - Upstream Browser Use Agent API is wired.
   - Current real Agent task failed because the configured model gateway credential was rejected.
   - This is correctly surfaced rather than reported ready.

8. **Capability status is more honest.**
   - Agent backends are not reported ready solely because a version probe works.
   - connected/configured/authenticated/smoke state is reflected.

9. **Packaged Atlas bridge is real.**
   - Packaged MCP bridge enumerated 12 tools.
   - packaged `local_file`, ast-grep and repo-map calls passed.

10. **Regression evidence is strong enough for this stage.**
    - 106 passed / 2 skipped.
    - changed-file Ruff passed.
    - pip check passed.
    - git diff --check passed.
    - packaged API/MCP checks passed.

## Accepted degraded items

These do NOT block the queue:

- Codex CLI not authenticated.
- Browser Use Agent credential rejected.
- ZCode provider configuration missing.
- DBOS system database not configured.
- Pi/extract-zip npm audit issue where npm only suggests an incompatible downgrade.

These are environment/configuration/upstream dependency conditions, not reasons to redo integration.

## Known unresolved item

### Claude ACP initialization timeout

Claude ACP still did not complete a real prompt.

This remains a known degraded integration.

Do not create a dedicated Claude FIX task now.

When a later wave touches external Agent backends, retry through:
1. official Claude Agent SDK direct path first;
2. validated ACP wrapper second.

If no authenticated local Claude environment exists, keep degraded.

## Non-blocking quality debt

Repository-wide Ruff still has pre-existing findings in untouched files.

Do not interrupt feature delivery to clean them globally.

## Review conclusion

PASS.

The bulk install + concentrated debug strategy worked and should continue.

Do not return to one-component-at-a-time FIX churn.

The next task should be one bulk Capability Enrichment Wave that borrows high-value mature features from first-tier Agent systems and mounts them into the now-shared Atlas runtime.
