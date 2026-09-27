# CODEX-ATLAS-P17A Review

REVIEW_RESULT: PASS
REVIEWED_HEAD: `c19f09040a35d87e64a4d8da290296e0a58f9d17`
BASE_HEAD: `d4b8241f952667e58b8da4180808064f49d53117`

## Verdict

P17A passes the clean first-run daily-usability acceptance gate.

The delivered implementation demonstrates a real packaged Windows user path rather than isolated backend capability checks.

## Product-path assessment

PASS:

- packaged Electron discovers its dynamically assigned backend URL through the preload bridge;
- a clean install no longer auto-starts example MCP servers;
- provider/model settings can be configured through Atlas and persist;
- API secrets are not echoed in normal read responses;
- streaming chat reaches terminal completion correctly;
- conversations survive restart and remain usable after restart;
- bundled Node remains the MCP runtime when system Node is removed;
- filesystem MCP discovery and real Agent `read_file` execute through the packaged product path;
- Skill selection is sent by name from the client and is re-resolved server-side through Skill Manager/Registry;
- lifecycle and dependency checks run before Skill instructions enter Agent context;
- graceful desktop shutdown requests authenticated backend shutdown and verifies child cleanup;
- release acceptance ran twice with separate clean user directories.

## Skill path review

The Skill implementation does not bypass the canonical system.

The renderer stores selected Skill names only. Each Agent run sends those names, and the server resolves the selected Skill through the canonical manager/registry activation gate, checks lifecycle state and dependency readiness, and only then injects returned Skill content into the Agent context.

This is materially different from a test-only prompt injection and satisfies the P17A acceptance requirement.

## Regression/build evidence

Reviewed result evidence includes:

- clean packaged daily-usability acceptance: pass across two independent clean user roots;
- `test_server.py`: 54 passed;
- P16A/P16B live/package MCP smokes: 2 passed;
- Agent/Skill regressions: 161 passed;
- frontend tests: 18 passed;
- frontend production build: pass;
- packaged backend build: pass;
- Electron Windows x64 NSIS/unpacked build: pass;
- Ruff: pass;
- `git diff --check`: clean.

## Node build-source note

The repository's canonical `frontend/scripts/package-node.mjs` remains pinned to the official Node.js 22.23.3 Windows x64 archive and verifies the exact SHA-256 from `frontend/node-runtime.json`.

During P17A verification, the current machine could not reach the official Node archive endpoint and the worker temporarily staged fixed Node/npm binaries from the npm registry to finish the package build.

This does not invalidate the P17A runtime acceptance because the final packaged runtime was version-checked and then exercised with system Node unavailable.

However, the manual staging step is not a reproducible release procedure and must not become the normal build path. That release-engineering gap is promoted into P17B.

## Decision

P17A: **PASS**.

Atlas has reached the point where the clean packaged application can be called daily-usable for the validated chat + persistence + MCP + Skill path.

Next: make the Windows release itself reproducible and verify the actual NSIS install/uninstall lifecycle from a clean release workflow.
